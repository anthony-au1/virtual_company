"""Deterministic qualification over pre-extracted facts."""

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from virtual_company.domain.criteria import CompanySizeCriteria
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
            min=minimum,
            max=maximum,
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
    assert result.evidence_ids == (
        [evidence_id] if expected is not Status.UNKNOWN else []
    )


def test_minimum_uses_any_observation_that_proves_the_predicate() -> None:
    low_ids = [uuid4(), uuid4()]
    match_id = uuid4()
    result = qualify_company(
        campaign(minimum=500),
        QualificationFacts(
            employee_counts=[
                count(200, low_ids[0]),
                count(300, low_ids[1]),
                count(1000, match_id),
            ]
        ),
    )[-1]
    assert result.status is Status.MATCH
    assert result.evidence_ids == [match_id]


def test_airwallex_minimum_regression_uses_each_fact_independently() -> None:
    over_id, exact_2000_id, exact_2947_id = uuid4(), uuid4(), uuid4()
    result = qualify_company(
        campaign(minimum=500),
        QualificationFacts(
            employee_counts=[
                count(2300, over_id, relation="greater_than", year=2026),
                count(2000, exact_2000_id, year=2026),
                count(2947, exact_2947_id, year=2026),
            ]
        ),
        as_of_year=2026,
    )[-1]
    assert result.status is Status.MATCH
    assert result.evidence_ids == sorted(
        [over_id, exact_2000_id, exact_2947_id], key=str
    )


def test_nonfuture_historical_observations_are_all_considered() -> None:
    ids = [uuid4(), uuid4(), uuid4()]
    result = qualify_company(
        campaign(minimum=500),
        QualificationFacts(
            employee_counts=[
                count(800, ids[0], year=2024),
                count(1200, ids[1], year=2025),
                count(2000, ids[2], year=2026),
            ]
        ),
        as_of_year=2026,
    )[-1]
    assert result.status is Status.MATCH
    assert result.evidence_ids == sorted(ids, key=str)


@pytest.mark.parametrize(
    "value,expected",
    [(700, Status.MATCH), (300, Status.UNKNOWN)],
)
def test_regional_facts_prove_minimum_only_from_lower_bound(
    value: int, expected: Status
) -> None:
    evidence_id = uuid4()
    result = qualify_company(
        campaign(minimum=500),
        QualificationFacts(employee_counts=[count(value, evidence_id, scope="regional")]),
    )[-1]
    assert result.status is expected
    assert result.evidence_ids == ([evidence_id] if expected is Status.MATCH else [])


def test_maximum_mismatch_wins_over_smaller_observations() -> None:
    ids = [uuid4(), uuid4(), uuid4()]
    result = qualify_company(
        campaign(maximum=5000),
        QualificationFacts(
            employee_counts=[
                count(2000, ids[0]),
                count(4000, ids[1]),
                count(7000, ids[2]),
            ]
        ),
    )[-1]
    assert result.status is Status.MISMATCH
    assert result.evidence_ids == [ids[2]]


@pytest.mark.parametrize(
    "value,expected",
    [(700, Status.UNKNOWN), (7000, Status.MISMATCH)],
)
def test_regional_facts_never_prove_maximum_match(
    value: int, expected: Status
) -> None:
    evidence_id = uuid4()
    result = qualify_company(
        campaign(maximum=5000),
        QualificationFacts(employee_counts=[count(value, evidence_id, scope="regional")]),
    )[-1]
    assert result.status is expected
    assert result.evidence_ids == ([evidence_id] if expected is Status.MISMATCH else [])


def test_greater_than_does_not_prove_maximum_pass_unless_over_limit() -> None:
    evidence_id = uuid4()
    unknown = qualify_company(
        campaign(maximum=5000),
        QualificationFacts(
            employee_counts=[count(1000, evidence_id, relation="greater_than")]
        ),
    )[-1]
    violation = qualify_company(
        campaign(maximum=5000),
        QualificationFacts(
            employee_counts=[count(5000, evidence_id, relation="greater_than")]
        ),
    )[-1]
    assert unknown.status is Status.UNKNOWN
    assert unknown.evidence_ids == []
    assert violation.status is Status.MISMATCH
    assert violation.evidence_ids == [evidence_id]


def test_min_and_max_are_evaluated_independently() -> None:
    exact = count(1000, uuid4())
    results = qualify_company(
        campaign(minimum=500, maximum=5000),
        QualificationFacts(employee_counts=[exact]),
    )
    assert [item.status for item in results[-2:]] == [Status.MATCH, Status.MATCH]

    results = qualify_company(
        campaign(minimum=500, maximum=5000),
        QualificationFacts(employee_counts=[count(1000, uuid4()), count(8000, uuid4())]),
    )
    assert [item.status for item in results[-2:]] == [Status.MATCH, Status.MISMATCH]


@pytest.mark.parametrize(
    "minimum,maximum,value,expected",
    [
        (500, None, 500, Status.MATCH),
        (None, 5000, 5000, Status.MATCH),
        (500, None, 499, Status.MISMATCH),
        (None, 5000, 5001, Status.MISMATCH),
    ],
)
def test_exact_threshold_boundaries(
    minimum: int | None,
    maximum: int | None,
    value: int,
    expected: Status,
) -> None:
    result = qualify_company(
        campaign(minimum=minimum, maximum=maximum),
        QualificationFacts(employee_counts=[count(value, uuid4())]),
    )[-1]
    assert result.status is expected


def test_future_facts_are_excluded_without_discarding_nonfuture_facts() -> None:
    old_id, future_id = uuid4(), uuid4()
    result = qualify_company(
        campaign(minimum=500),
        QualificationFacts(
            employee_counts=[
                count(800, old_id, year=2025),
                count(100, future_id, year=2027),
            ]
        ),
        as_of_year=2026,
    )[-1]
    assert result.status is Status.MATCH
    assert result.evidence_ids == [old_id]


def test_none_facts_never_become_positive_matches() -> None:
    criteria = qualify_company(campaign(minimum=100), None)
    assert all(item.status is Status.UNKNOWN for item in criteria)
    assert (
        aggregate_qualification(uuid4(), criteria).status
        is Overall.INSUFFICIENT_EVIDENCE
    )


def test_mismatch_takes_precedence_over_unknown() -> None:
    criteria = qualify_company(
        campaign(minimum=100),
        QualificationFacts(
            employee_counts=[count(40, uuid4())],
        ),
    )
    assert criteria[-1].status is Status.MISMATCH
    assert any(item.status is Status.UNKNOWN for item in criteria[:-1])
    assert aggregate_qualification(uuid4(), criteria).status is Overall.NOT_QUALIFIED
