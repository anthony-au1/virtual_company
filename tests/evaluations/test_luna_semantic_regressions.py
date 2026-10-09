"""Offline checks for evaluation plumbing, not tests of a mocked model's judgment."""

import json

import pytest
from luna_semantic_regressions import (
    CASES,
    EvaluationCase,
    _campaign,
    _criterion_id,
    _evidence,
    actual_result,
)

from virtual_company.research.models import (
    CategoricalEvidenceFact,
    EmployeeCountEvidenceFact,
    QualificationFacts,
    QualificationFactsCacheEntry,
    QualificationFactsCacheStatus,
)
from virtual_company.services.qualification_evidence_extractor import (
    QualificationEvidenceExtractor,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case", CASES, ids=[f"{i}-{c.company}-{c.subject}" for i, c in enumerate(CASES)]
)
async def test_cases_preserve_exact_criteria_excerpts_and_expected_fact_processing(
    case: EvaluationCase,
) -> None:
    item = _evidence(case)
    facts = (
        QualificationFacts(
            employee_counts=[
                EmployeeCountEvidenceFact(
                    value=2300,
                    relation="greater_than",
                    scope="global",
                    evidence_ids=[item.id],
                )
            ]
        )
        if case.criterion == "company_size"
        else QualificationFacts(
            categorical=[
                CategoricalEvidenceFact(
                    criterion_id=_criterion_id(case),
                    state="supported" if case.expected == "MATCH" else "unknown",
                    evidence_ids=[item.id],
                )
            ]
        )
    )

    class Provider:
        async def generate_structured(
            self,
            *,
            system_prompt: str,
            user_prompt: str,
            response_model: type[QualificationFacts],
        ) -> QualificationFacts:
            payload = json.loads(user_prompt)
            assert payload["evidence"][0]["subject"] == case.subject
            assert payload["evidence"][0]["evidence_text"] == case.evidence
            assert payload["evidence"][0]["claim"] == (case.claim or case.evidence)
            assert "Normalize spelling, not meaning" in system_prompt
            return facts

    entry = await QualificationEvidenceExtractor(Provider()).extract(
        _campaign(case), [item]
    )
    assert actual_result(case, entry) == case.expected


@pytest.mark.parametrize(
    "status",
    [
        QualificationFactsCacheStatus.FAILED_RETRYABLE,
        QualificationFactsCacheStatus.FAILED_EXHAUSTED,
    ],
)
def test_extraction_failure_cannot_pass_unknown_case(
    status: QualificationFactsCacheStatus,
) -> None:
    case = next(c for c in CASES if c.expected == "UNKNOWN")
    entry = QualificationFactsCacheEntry(
        evidence_ids=[_evidence(case).id],
        facts=None,
        status=status,
        attempt_count=1
        if status == QualificationFactsCacheStatus.FAILED_RETRYABLE
        else 2,
    )
    assert actual_result(case, entry) == "ERROR"


def test_missing_expected_fact_is_an_error_not_unknown() -> None:
    case = next(c for c in CASES if c.expected == "UNKNOWN")
    entry = QualificationFactsCacheEntry(evidence_ids=[], facts=QualificationFacts())
    assert actual_result(case, entry) == "ERROR"


def test_size_evaluation_reports_mismatch_using_existing_qualification() -> None:
    case = next(c for c in CASES if c.criterion == "company_size")
    facts = QualificationFacts(
        employee_counts=[
            EmployeeCountEvidenceFact(
                value=100,
                relation="exact",
                scope="global",
                evidence_ids=[_evidence(case).id],
            )
        ]
    )
    entry = QualificationFactsCacheEntry(evidence_ids=[_evidence(case).id], facts=facts)
    assert actual_result(case, entry) == "MISMATCH"


def test_conflicting_categorical_fact_preserves_existing_unknown_semantics() -> None:
    case = next(c for c in CASES if c.expected == "UNKNOWN")
    facts = QualificationFacts(
        categorical=[
            CategoricalEvidenceFact(
                criterion_id=_criterion_id(case),
                state="conflicting",
                evidence_ids=[_evidence(case).id],
            )
        ]
    )
    entry = QualificationFactsCacheEntry(evidence_ids=[_evidence(case).id], facts=facts)
    assert actual_result(case, entry) == "UNKNOWN"
