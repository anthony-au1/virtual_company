"""Opt-in, live Luna evaluation for the semantic qualification boundary.

Run with ``uv run python tests/evaluations/luna_semantic_regressions.py``.
The evidence snippets are the findings supplied in the audit of the referenced run.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from types import SimpleNamespace
from uuid import UUID, uuid5

from virtual_company.config import get_settings
from virtual_company.llm import LLMRegistry, LLMRole
from virtual_company.services.qualification_evidence_extractor import (
    EvidenceForExtraction,
    QualificationEvidenceExtractor,
)

RUN_ID = "d59ab00f-fd95-420d-9e73-b17c4c7e7b4b"
_NAMESPACE = UUID(RUN_ID)


@dataclass(frozen=True)
class EvaluationCase:
    company: str
    criterion: str
    subject: str
    evidence: str
    expected: str
    kind: str


CASES = (
    EvaluationCase(
        "Airwallex",
        "industry",
        "fin tech",
        "Airwallex is an Australian fintech company.",
        "MATCH",
        "industry",
    ),
    EvaluationCase(
        "ANZ",
        "industry",
        "fin tech",
        "ANZ is a traditional bank adopting and integrating fintech.",
        "UNKNOWN",
        "industry",
    ),
    EvaluationCase(
        "Westpac",
        "industry",
        "fin tech",
        "Westpac provides banking and financial services.",
        "UNKNOWN",
        "industry",
    ),
    EvaluationCase(
        "NAB",
        "industry",
        "fin tech",
        "NAB is a traditional bank adopting and integrating fintech.",
        "UNKNOWN",
        "industry",
    ),
    EvaluationCase(
        "Afterpay",
        "technology",
        "Java",
        "Android Gradle wrapper: @rem Find java.exe",
        "UNKNOWN",
        "technology",
    ),
    EvaluationCase(
        "Airwallex",
        "technology",
        "Java",
        "Several Airwallex backend engineering roles require strong commercial Java development experience.",
        "MATCH",
        "technology",
    ),
    EvaluationCase(
        "Zip",
        "technology",
        "Spring Boot",
        "Experience with Java and Spring Boot.",
        "MATCH",
        "technology",
    ),
    EvaluationCase(
        "Zip",
        "technology",
        "Spring",
        "Experience with Java and Spring Boot.",
        "UNKNOWN",
        "technology",
    ),
)


def _campaign(case: EvaluationCase) -> SimpleNamespace:
    return SimpleNamespace(
        target_market=None,
        industry=case.subject if case.kind == "industry" else None,
        technologies=(
            ["Spring", "Spring Boot"]
            if case.company == "Zip"
            else [case.subject]
            if case.kind == "technology"
            else []
        ),
        company_size=None,
    )


def _criterion_id(case: EvaluationCase) -> str:
    if case.kind == "industry":
        return "criterion_0"
    return (
        "criterion_1"
        if case.company == "Zip" and case.subject == "Spring Boot"
        else "criterion_0"
    )


def _evidence(case: EvaluationCase) -> EvidenceForExtraction:
    evidence_id = uuid5(_NAMESPACE, f"{case.company}/{case.subject}/{case.evidence}")
    return SimpleNamespace(
        id=evidence_id,
        criterion=case.criterion,
        subject=case.subject,
        claim=case.evidence,
        evidence_text=case.evidence,
    )


async def main() -> None:
    settings = get_settings()
    provider = LLMRegistry(settings).for_role(LLMRole.EXTRACTION)
    extractor = QualificationEvidenceExtractor(provider)
    model = getattr(getattr(provider, "_provider", None), "model", "unknown")
    print(f"Run {RUN_ID}; extraction model: {model}")
    failures = 0
    for case in CASES:
        evidence = _evidence(case)
        result = await extractor.extract(_campaign(case), [evidence])
        fact = next(
            (
                item
                for item in (result.facts.categorical if result.facts else [])
                if item.criterion_id == _criterion_id(case)
            ),
            None,
        )
        actual = (
            "MATCH" if fact is not None and fact.state == "supported" else "UNKNOWN"
        )
        passed = actual == case.expected
        failures += not passed
        print(
            f"{case.company} / {case.subject}: expected {case.expected:<7} "
            f"actual {actual:<7} {'PASS' if passed else 'FAIL'}"
        )
    if failures:
        raise SystemExit(f"{failures} Luna semantic regression case(s) failed")


if __name__ == "__main__":
    asyncio.run(main())
