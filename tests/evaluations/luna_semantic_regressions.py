"""Opt-in live Luna evaluation; never invokes search, fetch, or a campaign.

Run: uv run python tests/evaluations/luna_semantic_regressions.py --repetitions 3
Cases include audit findings from both referenced runs and synthetic positive controls.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from types import SimpleNamespace
from uuid import UUID, uuid5

from virtual_company.config import get_settings
from virtual_company.domain.criteria import CompanySizeCriteria, campaign_criteria
from virtual_company.llm import LLMRegistry, LLMRole
from virtual_company.research.models import (
    QualificationFactsCacheEntry,
    QualificationFactsCacheStatus,
)
from virtual_company.services.qualification import qualify_company
from virtual_company.services.qualification_evidence_extractor import (
    EvidenceForExtraction,
    QualificationEvidenceExtractor,
)
from virtual_company.workflows.research.prompts import (
    EXTRACT_QUALIFICATION_FACTS_PROMPT,
)

RUN_IDS = (
    "d59ab00f-fd95-420d-9e73-b17c4c7e7b4b",
    "a7fee166-ca56-4bf0-885f-8e96bd97446c",
)
_NAMESPACE = UUID(RUN_IDS[1])


@dataclass(frozen=True)
class EvaluationCase:
    company: str
    criterion: str
    subject: str
    evidence: str
    expected: str
    technologies: tuple[str, ...] = ()
    # An extracted claim must not override the actual source excerpt.
    claim: str | None = None


CASES = (
    EvaluationCase(
        "Airwallex",
        "industry",
        "fin tech",
        "Airwallex is an Australian fintech company.",
        "MATCH",
    ),
    EvaluationCase(
        "ANZ",
        "industry",
        "fin tech",
        "ANZ is a traditional bank adopting and integrating fintech.",
        "UNKNOWN",
    ),
    EvaluationCase(
        "Westpac",
        "industry",
        "fin tech",
        "Westpac provides banking and financial services.",
        "UNKNOWN",
    ),
    EvaluationCase(
        "NAB",
        "industry",
        "fin tech",
        "NAB is a traditional bank adopting and integrating fintech.",
        "UNKNOWN",
    ),
    EvaluationCase(
        "Afterpay",
        "technology",
        "Java",
        "Android Gradle wrapper: @rem Find java.exe",
        "UNKNOWN",
    ),
    EvaluationCase(
        "Airwallex",
        "technology",
        "Java",
        "Several Airwallex backend engineering roles require strong commercial Java development experience.",
        "MATCH",
    ),
    EvaluationCase(
        "Zip",
        "technology",
        "Spring Boot",
        "Experience with Java and Spring Boot.",
        "MATCH",
        ("Spring", "Spring Boot"),
    ),
    EvaluationCase(
        "Zip",
        "technology",
        "Spring",
        "Experience with Java and Spring Boot.",
        "UNKNOWN",
        ("Spring", "Spring Boot"),
    ),
    EvaluationCase(
        "Judo Bank",
        "technology",
        "Kafka",
        "With the help of Apache Kafka® and Confluent Cloud, Judo Bank was able to seamlessly integrate its various systems with its data platform.",
        "UNKNOWN",
        claim="Judo Bank uses Kafka.",
    ),
    EvaluationCase(
        "Acme",
        "technology",
        "Kafka",
        "Acme's production platform uses Kafka for event streaming.",
        "MATCH",
    ),
    EvaluationCase(
        "Acme",
        "technology",
        "Apache Kafka",
        "Acme's platform uses Apache Kafka.",
        "MATCH",
    ),
    EvaluationCase(
        "Acme",
        "technology",
        "Spring",
        "Acme's production services are built using Spring Boot.",
        "UNKNOWN",
    ),
    EvaluationCase(
        "Airwallex",
        "technology",
        "Spring Boot",
        "Airwallex's production software is primarily written in Java and Spring Boot.",
        "MATCH",
    ),
    EvaluationCase(
        "Acme", "technology", "Java", "Acme's application uses Java EE.", "UNKNOWN"
    ),
    EvaluationCase(
        "Airwallex",
        "technology",
        "Java",
        "Airwallex's backend services are primarily written in Java.",
        "MATCH",
    ),
    EvaluationCase(
        "Sandstone Technology",
        "industry",
        "fin tech",
        "Sandstone Technology develops banking platforms specifically for financial institutions.",
        "UNKNOWN",
        claim="Sandstone Technology is in the fintech industry.",
    ),
    EvaluationCase(
        "Acme",
        "industry",
        "fin tech",
        "Acme develops software used by major banks.",
        "UNKNOWN",
    ),
    EvaluationCase(
        "BankCo",
        "industry",
        "fin tech",
        "BankCo partnered with several fintech companies.",
        "UNKNOWN",
    ),
    EvaluationCase(
        "BankCo",
        "industry",
        "fin tech",
        "BankCo is adopting fintech solutions across its retail banking business.",
        "UNKNOWN",
    ),
    EvaluationCase(
        "Acme",
        "industry",
        "fin tech",
        "Acme was named one of Australia's leading fintech companies.",
        "MATCH",
    ),
    EvaluationCase(
        "Acme",
        "technology",
        "Java",
        "Acme's official engineering careers page: Experience building backend services in Java.",
        "MATCH",
    ),
    EvaluationCase(
        "Airwallex",
        "technology",
        "Kafka",
        "Airwallex's payments platform uses Kafka event streams.",
        "MATCH",
    ),
    EvaluationCase(
        "Acme",
        "technology",
        "React",
        "Acme's mobile applications use React Native.",
        "UNKNOWN",
    ),
    EvaluationCase(
        "Acme", "technology", ".NET", "Acme builds services using .NET Core.", "UNKNOWN"
    ),
    EvaluationCase(
        "Acme",
        "target_market",
        "Australia",
        "Acme was founded in Melbourne, Australia.",
        "MATCH",
    ),
    EvaluationCase(
        "Airwallex",
        "company_size",
        "employees >= 500",
        "Airwallex employs more than 2,300 people globally.",
        "MATCH",
    ),
)


def _campaign(case: EvaluationCase) -> SimpleNamespace:
    return SimpleNamespace(
        target_market=case.subject if case.criterion == "target_market" else None,
        industry=case.subject if case.criterion == "industry" else None,
        technologies=list(case.technologies or (case.subject,))
        if case.criterion == "technology"
        else [],
        company_size=CompanySizeCriteria(min=500)
        if case.criterion == "company_size"
        else None,
    )


def _criterion_id(case: EvaluationCase) -> str:
    return next(
        f"criterion_{index}"
        for index, criterion in enumerate(campaign_criteria(_campaign(case)))
        if criterion.criterion == case.criterion and criterion.subject == case.subject
    )


def _evidence(case: EvaluationCase) -> EvidenceForExtraction:
    return SimpleNamespace(
        id=uuid5(_NAMESPACE, f"{case.company}/{case.subject}/{case.evidence}"),
        criterion=case.criterion,
        subject=case.subject,
        claim=case.claim or case.evidence,
        evidence_text=case.evidence,
    )


def actual_result(case: EvaluationCase, entry: QualificationFactsCacheEntry) -> str:
    """Keep extraction errors distinct from a successfully extracted UNKNOWN."""
    if entry.status != QualificationFactsCacheStatus.SUCCESS or entry.facts is None:
        return "ERROR"
    if case.criterion == "company_size":
        if not entry.facts.employee_counts:
            return "ERROR"
    elif not any(
        fact.criterion_id == _criterion_id(case) for fact in entry.facts.categorical
    ):
        return "ERROR"
    index = int(_criterion_id(case).removeprefix("criterion_"))
    return qualify_company(_campaign(case), entry.facts)[index].status.value


async def main(repetitions: int = 1) -> None:
    provider = LLMRegistry(get_settings()).for_role(LLMRole.EXTRACTION)
    model = getattr(provider, "model", "unknown")
    if "luna" not in model.lower():
        raise SystemExit(
            f"This evaluation requires the configured Luna extraction model; got {model}."
        )
    extractor = QualificationEvidenceExtractor(provider)
    print(
        f"Runs {', '.join(RUN_IDS)}; model: {model}; prompt: {EXTRACT_QUALIFICATION_FACTS_PROMPT.version}"
    )
    failures = 0
    for repetition in range(1, repetitions + 1):
        for index, case in enumerate(CASES, start=1):
            # Fresh extraction each time: previous facts must not mask variability.
            result = await extractor.extract(_campaign(case), [_evidence(case)])
            actual = actual_result(case, result)
            passed = actual == case.expected
            failures += not passed
            print(
                f"[{repetition}/{repetitions} case {index}] {case.company} / {case.subject}: "
                f"expected {case.expected:<7} actual {actual:<7} {'PASS' if passed else 'FAIL'}"
            )
    total = repetitions * len(CASES)
    print(
        f"{total - failures}/{total} passed; {failures} failed (including extraction errors)."
    )
    if failures:
        raise SystemExit(f"{failures} Luna semantic regression evaluation(s) failed")


def _positive_integer(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("repetitions must be >= 1")
    return parsed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repetitions", type=_positive_integer, default=1)
    asyncio.run(main(parser.parse_args().repetitions))
