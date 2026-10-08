"""Deterministic qualification over pre-extracted facts."""

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from virtual_company.domain.criteria import (
    CompanySizeBound,
    CompanySizeCriteria,
)
from virtual_company.domain.qualification import CompanyQualificationStatus as Overall
from virtual_company.domain.qualification import QualificationStatus as Status
from virtual_company.research.models import (
    CategoricalEvidenceFact,
    EmployeeCountEvidenceFact,
    QualificationFacts,
)
from virtual_company.services.qualification import (
    aggregate_qualification,
    qualify_company,
)


def campaign(
    *, minimum: int | None = None, maximum: int | None = None
) -> SimpleNamespace:
    return SimpleNamespace(
        target_market="Australia",
        industry="fintech",
        technologies=["Kafka"],
        company_size=CompanySizeCriteria(
            min=CompanySizeBound(value=minimum)
            if minimum is not None
            else None,
            max=CompanySizeBound(value=maximum)
            if maximum is not None
            else None,
        )
        if minimum is not None or maximum is not None
        else None,
    )


def supported(index: int, evidence_id: UUID) -> CategoricalEvidenceFact:
    return CategoricalEvidenceFact(
        criterion_id=f"criterion_{index}", state="supported", evidence_ids=[evidence_id]
    )


def count(
    value: int,
    evidence_id: UUID,
    *,
    relation: str = "exact",
    year: int | None = None,
    scope: str = "unknown",
) -> EmployeeCountEvidenceFact:
    return EmployeeCountEvidenceFact.model_validate(
        {
            "value": value,
            "relation": relation,
            "year": year,
            "scope": scope,
            "evidence_ids": [evidence_id],
        }
    )


def test_categorical_facts_and_missing_facts_are_deterministic() -> None:
    ids = [uuid4() for _ in range(3)]
    facts = QualificationFacts(categorical=[supported(i, ids[i]) for i in range(3)])
    first = qualify_company(campaign(), facts)
    second = qualify_company(campaign(), facts)
    assert first == second
    assert [item.status for item in first] == [Status.MATCH] * 3
    assert aggregate_qualification(uuid4(), first).status is Overall.QUALIFIED

    sparse = qualify_company(
        campaign(), QualificationFacts(categorical=[supported(0, ids[0])])
    )
    assert [item.status for item in sparse] == [
        Status.MATCH,
        Status.UNKNOWN,
        Status.UNKNOWN,
    ]
    assert (
        aggregate_qualification(uuid4(), sparse).status is Overall.INSUFFICIENT_EVIDENCE
    )


def test_conflicting_categorical_fact_remains_unknown_with_traceability() -> None:
    evidence_ids = [uuid4(), uuid4()]
    facts = QualificationFacts(
        categorical=[
            CategoricalEvidenceFact(
                criterion_id="criterion_1",
                state="conflicting",
                evidence_ids=evidence_ids,
            )
        ]
    )
    result = qualify_company(campaign(), facts)[1]
    assert result.status is Status.UNKNOWN
    assert result.evidence_ids == sorted(evidence_ids, key=str)


@pytest.mark.parametrize(
    "relation,value,minimum,maximum,expected",
    [
        ("exact", 1500, 500, None, Status.MATCH),
        ("exact", 47, 500, None, Status.MISMATCH),
        ("greater_than", 500, None, 500, Status.MISMATCH),
        ("less_than_or_equal", 500, None, 500, Status.MATCH),
        ("approximately", 1500, 500, None, Status.UNKNOWN),
    ],
)
def test_employee_facts_use_deterministic_bounds(
    relation: str,
    value: int,
    minimum: int | None,
    maximum: int | None,
    expected: Status,
) -> None:
    evidence_id = uuid4()
    facts = QualificationFacts(
        employee_counts=[count(value, evidence_id, relation=relation)]
    )
    result = qualify_company(campaign(minimum=minimum, maximum=maximum), facts)[-1]
    assert result.status is expected
    assert result.evidence_ids == [evidence_id]


def test_dated_and_contradictory_employee_facts_preserve_uncertainty() -> None:
    first_id, second_id = uuid4(), uuid4()
    dated = QualificationFacts(
        employee_counts=[
            count(714, first_id, year=2023),
            count(460, second_id, year=2026),
        ]
    )
    result = qualify_company(campaign(minimum=500), dated, as_of_year=2026)[-1]
    assert result.status is Status.MISMATCH
    assert "2026" in result.reason and "superseded" in result.reason

    conflicting = QualificationFacts(
        employee_counts=[count(230, first_id), count(2300, second_id)]
    )
    result = qualify_company(campaign(minimum=100, maximum=500), conflicting)[-1]
    assert result.status is Status.UNKNOWN
    assert "conflicting" in result.reason


def test_none_facts_never_become_positive_matches() -> None:
    criteria = qualify_company(campaign(minimum=100), None)
    assert all(item.status is Status.UNKNOWN for item in criteria)
    assert (
        aggregate_qualification(uuid4(), criteria).status
        is Overall.INSUFFICIENT_EVIDENCE
    )
