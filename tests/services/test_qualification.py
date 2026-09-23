"""Qualification is pure: fixtures need neither database nor provider clients."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from virtual_company.domain.qualification import CompanyQualificationStatus as Overall
from virtual_company.domain.qualification import QualificationStatus as Status
from virtual_company.services.qualification import (
    aggregate_qualification,
    qualify_company,
)


def campaign(**changes: object) -> SimpleNamespace:
    return SimpleNamespace(
        **{
            "target_market": "Australia",
            "industry": "fin tech",
            "technologies": ["java", "spring", "spring boot", "kafka"],
            "company_size_min": None,
            "company_size_max": None,
            **changes,
        }
    )


def evidence(
    criterion: str | None,
    subject: str | None,
    text: str = "Explicit validated support.",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(), criterion=criterion, subject=subject, claim=text, evidence_text=text
    )


def test_afterpay_and_sparse_evidence() -> None:
    items = [evidence("target_market", "Australia"), evidence("industry", "fintech")]
    criteria = qualify_company(campaign(), items)
    assert [item.status for item in criteria] == [Status.MATCH] * 2 + [
        Status.UNKNOWN
    ] * 4
    assert (
        aggregate_qualification(uuid4(), criteria).status
        is Overall.INSUFFICIENT_EVIDENCE
    )
    items += [
        evidence("technology", label) for label in ["Java", "Spring Boot", "Kafka"]
    ]
    criteria = qualify_company(campaign(), items)
    assert all(item.status is Status.MATCH for item in criteria)
    assert criteria[3].evidence_ids == [items[3].id]
    assert "implication" in criteria[3].reason
    assert aggregate_qualification(uuid4(), criteria).status is Overall.QUALIFIED
    assert qualify_company(campaign(), list(reversed(items))) == criteria


def test_empty_evidence_and_empty_campaign() -> None:
    criteria = qualify_company(campaign(), [])
    assert all(
        item.status is Status.UNKNOWN and not item.evidence_ids for item in criteria
    )
    assert (
        aggregate_qualification(uuid4(), criteria).status
        is Overall.INSUFFICIENT_EVIDENCE
    )
    assert (
        aggregate_qualification(
            uuid4(),
            qualify_company(
                campaign(target_market=None, industry=None, technologies=[]), []
            ),
        ).status
        is Overall.QUALIFIED
    )


@pytest.mark.parametrize(
    "labels,subjects,expected",
    [
        (["spring", "spring boot"], ["Spring"], [Status.MATCH, Status.UNKNOWN]),
        (["spring", "spring boot"], ["SpringBoot"], [Status.MATCH, Status.MATCH]),
        (
            ["python", "aws", "postgresql"],
            ["PYTHON", "aws", " PostgreSQL "],
            [Status.MATCH] * 3,
        ),
        (["Java", "JAVA", "java"], [" java "], [Status.MATCH]),
        (["C", "C++", "C#"], ["C++"], [Status.UNKNOWN, Status.MATCH, Status.UNKNOWN]),
    ],
)
def test_dynamic_normalized_technologies(
    labels: list[str], subjects: list[str], expected: list[Status]
) -> None:
    criteria = qualify_company(
        campaign(target_market=None, industry=None, technologies=labels),
        [evidence("technology", subject) for subject in subjects],
    )
    assert [item.status for item in criteria] == expected


@pytest.mark.parametrize(
    "criterion,subject,text",
    [
        ("technology", "java", "Acme does not use Java."),
        ("target_market", "Australia", "Acme does not operate in Australia."),
        ("industry", "fin tech", "Acme is not a fintech company."),
    ],
)
def test_explicit_negative_and_conflict(
    criterion: str, subject: str, text: str
) -> None:
    negative = evidence(criterion, subject, text)
    criteria = qualify_company(campaign(), [negative])
    result = next(
        item
        for item in criteria
        if item.criterion == criterion and item.subject == subject
    )
    assert result.status is Status.MISMATCH
    assert aggregate_qualification(uuid4(), criteria).status is Overall.NOT_QUALIFIED
    positive = evidence(criterion, subject)
    criteria = qualify_company(campaign(), [negative, positive])
    result = next(
        item
        for item in criteria
        if item.criterion == criterion and item.subject == subject
    )
    assert result.status is Status.UNKNOWN
    assert set(result.evidence_ids) == {negative.id, positive.id}


@pytest.mark.parametrize(
    "text",
    [
        "Acme may use Java.",
        "No Java evidence was found.",
        "Acme does not use Java exclusively.",
    ],
)
def test_ambiguous_negatives(text: str) -> None:
    assert (
        qualify_company(campaign(), [evidence("technology", "java", text)])[2].status
        is Status.UNKNOWN
    )


def test_negative_does_not_propagate_implication() -> None:
    criteria = qualify_company(
        campaign(),
        [evidence("technology", "spring boot", "Acme does not use Spring Boot.")],
    )
    assert criteria[3].status is Status.UNKNOWN
    assert criteria[4].status is Status.MISMATCH


@pytest.mark.parametrize(
    "subjects,expected",
    [
        (["230"], Status.MATCH),
        (["230 employees"], Status.MATCH),
        (["2,300 employees"], Status.MISMATCH),
        ([], Status.UNKNOWN),
        (["230", "2300"], Status.UNKNOWN),
        (["450", "470"], Status.UNKNOWN),
        (["100"], Status.MATCH),
        (["500"], Status.MATCH),
        (["2300+ employees"], Status.MISMATCH),
        (["more than 300 employees"], Status.UNKNOWN),
        (["100–500 employees"], Status.UNKNOWN),
        (["about 230 employees"], Status.UNKNOWN),
    ],
)
def test_size(subjects: list[str], expected: Status) -> None:
    items = [evidence("company_size", subject, subject) for subject in subjects]
    result = qualify_company(
        campaign(company_size_min=100, company_size_max=500), items
    )[-1]
    assert result.status is expected
    assert set(result.evidence_ids) == {item.id for item in items}


@pytest.mark.parametrize(
    "minimum,maximum,count", [(100, None, "2300"), (None, 500, "230")]
)
def test_one_sided_size(minimum: int | None, maximum: int | None, count: str) -> None:
    assert (
        qualify_company(
            campaign(company_size_min=minimum, company_size_max=maximum),
            [evidence("company_size", count)],
        )[-1].status
        is Status.MATCH
    )


def test_size_source_qualification_and_claim_conflict() -> None:
    item = evidence("company_size", "230", "About 230 employees")
    assert (
        qualify_company(campaign(company_size_min=100), [item])[-1].status
        is Status.UNKNOWN
    )
    item = evidence("company_size", "230", "Acme has 2300 employees.")
    assert (
        qualify_company(campaign(company_size_min=100), [item])[-1].status
        is Status.UNKNOWN
    )


def test_no_geography_or_industry_inference() -> None:
    criteria = qualify_company(
        campaign(),
        [
            evidence("target_market", "Melbourne"),
            evidence("industry", "payments"),
            evidence(None, "Java"),
        ],
    )
    assert all(item.status is Status.UNKNOWN for item in criteria)


def test_unparsed_size_does_not_hide_potential_conflict() -> None:
    items = [
        evidence("company_size", "230"),
        evidence("company_size", "more than 3000 employees"),
    ]
    result = qualify_company(
        campaign(company_size_min=100, company_size_max=500), items
    )[-1]
    assert result.status is Status.UNKNOWN
    assert set(result.evidence_ids) == {item.id for item in items}


def test_claim_excerpt_polarity_conflict() -> None:
    item = evidence("technology", "java", "Acme uses Java.")
    item.evidence_text = "Acme does not use Java."
    assert qualify_company(campaign(), [item])[2].status is Status.UNKNOWN


@pytest.mark.parametrize(
    "text,lower,upper",
    [
        ("1300 employees", 1300, 1300),
        ("1,300 employees", 1300, 1300),
        ("1300 staff", 1300, 1300),
        ("1,300 staff", 1300, 1300),
        ("2300 people", 2300, 2300),
        ("2,300 people", 2300, 2300),
        ("over 2300 employees", 2301, None),
        ("over 2,300 people", 2301, None),
        ("more than 2300 employees", 2301, None),
        ("at least 2300 employees", 2300, None),
        ("2300+ employees", 2300, None),
        ("under 500 employees", None, 499),
        ("fewer than 500 employees", None, 499),
        ("less than 500 employees", None, 499),
        ("up to 500 employees", None, 500),
        ("workforce of 1300", 1300, 1300),
        ("A team of 1300.", 1300, 1300),
        ("more than\n2300 employees", 2301, None),
    ],
)
def test_employee_bounds_parser(
    text: str, lower: int | None, upper: int | None
) -> None:
    from virtual_company.services.qualification import EmployeeCountBounds, _size_bounds

    assert _size_bounds(evidence("company_size", None, text)) == EmployeeCountBounds(
        lower, upper
    )


@pytest.mark.parametrize(
    "text,expected",
    [
        ("1300 employees", (Status.MATCH, Status.MISMATCH, Status.MATCH)),
        ("over 2300 employees", (Status.MATCH, Status.MISMATCH, Status.MISMATCH)),
        ("500 employees", (Status.MATCH, Status.MATCH, Status.MATCH)),
        ("100 employees", (Status.MISMATCH, Status.MATCH, Status.MISMATCH)),
        ("300 employees", (Status.MISMATCH, Status.MATCH, Status.MISMATCH)),
        ("2300 employees", (Status.MATCH, Status.MISMATCH, Status.MISMATCH)),
        ("under 300 employees", (Status.MISMATCH, Status.MATCH, Status.MISMATCH)),
        ("over 100 employees", (Status.UNKNOWN, Status.UNKNOWN, Status.UNKNOWN)),
        ("under 1000 employees", (Status.UNKNOWN, Status.UNKNOWN, Status.UNKNOWN)),
        ("over 1000 employees", (Status.MATCH, Status.MISMATCH, Status.UNKNOWN)),
        ("under 1500 employees", (Status.UNKNOWN, Status.UNKNOWN, Status.UNKNOWN)),
        ("under 500 employees", (Status.MISMATCH, Status.MATCH, Status.MISMATCH)),
        ("up to 500 employees", (Status.UNKNOWN, Status.MATCH, Status.UNKNOWN)),
        ("at least 500 employees", (Status.MATCH, Status.UNKNOWN, Status.UNKNOWN)),
        ("over 500 employees", (Status.MATCH, Status.MISMATCH, Status.UNKNOWN)),
        ("2000 employees", (Status.MATCH, Status.MISMATCH, Status.MATCH)),
    ],
)
def test_size_constraint_matrix(text: str, expected: tuple[Status, ...]) -> None:
    for (minimum, maximum), status in zip(
        [(500, None), (None, 500), (500, 2000)], expected, strict=True
    ):
        result = qualify_company(
            campaign(company_size_min=minimum, company_size_max=maximum),
            [evidence("company_size", None, text)],
        )[-1]
        assert result.status is status


@pytest.mark.parametrize(
    "texts,expected",
    [
        (["over 1000 employees", "1300 employees"], Status.MATCH),
        (
            ["over 2300 employees", "over 2300 people", "2300+ employees"],
            Status.MISMATCH,
        ),
        (["at least 500 employees", "up to 2000 employees"], Status.MATCH),
        (["230 employees", "2300 employees"], Status.UNKNOWN),
        (["1300 employees", "unknown workforce"], Status.UNKNOWN),
    ],
)
def test_size_intersection(texts: list[str], expected: Status) -> None:
    items = [evidence("company_size", None, text) for text in texts]
    config = campaign(company_size_min=500, company_size_max=2000)
    result = qualify_company(config, items)[-1]
    assert result.status is expected
    assert result.evidence_ids == sorted((item.id for item in items), key=str)
    assert qualify_company(config, items[::-1])[-1] == result


@pytest.mark.parametrize(
    "text",
    [
        "Afterpay Australia’s 1300 staff",
        "we have a team of over 2,300 of the brightest and most innovative people in tech",
    ],
)
def test_real_run_size_regression(text: str) -> None:
    size = evidence("company_size", None, text)
    items = [
        evidence("target_market", "Australia"),
        evidence("industry", "fin tech"),
        size,
    ]
    items += [
        evidence("technology", name)
        for name in ["java", "spring", "spring boot", "kafka"]
    ]
    criteria = qualify_company(campaign(company_size_min=500), items)
    assert criteria[-1].status is Status.MATCH
    assert criteria[-1].evidence_ids == [size.id]
    assert aggregate_qualification(uuid4(), criteria).status is Overall.QUALIFIED


@pytest.mark.parametrize(
    "text",
    [
        "Revenue of 1300 dollars",
        "100 to 500 employees",
        "team of 2 million people",
        "team of 1.300 people",
        "Founded in 1300",
        "1.300 employees",
        "100–500 employees",
        "about 1300 employees",
        "around 1300 employees",
        "approximately 1300 employees",
        "not over 2300 employees",
    ],
)
def test_unusable_size_text(text: str) -> None:
    result = qualify_company(
        campaign(company_size_min=500), [evidence("company_size", None, text)]
    )[-1]
    assert result.status is Status.UNKNOWN
    assert (
        result.reason
        == "Available company-size evidence does not establish whether the company satisfies the campaign size constraint."
    )


def test_numeric_subject_does_not_strengthen_bound() -> None:
    item = evidence("company_size", "1000", "over 1000 employees")
    assert (
        qualify_company(campaign(company_size_min=500, company_size_max=2000), [item])[
            -1
        ].status
        is Status.UNKNOWN
    )


def test_size_reasons_and_field_conflict() -> None:
    config = campaign(company_size_min=500)
    assert (
        qualify_company(config, [])[-1].reason
        == "No validated company-size evidence is available."
    )
    item = evidence("company_size", None, "at least 2300 employees")
    assert (
        qualify_company(config, [item])[-1].reason
        == "Validated evidence establishes at least 2300 employees, satisfying the campaign minimum of 500."
    )
    item.claim = "230 employees"
    assert qualify_company(config, [item])[-1].status is Status.UNKNOWN
    item = evidence("company_size", None, "2300 employees")
    assert (
        qualify_company(campaign(company_size_max=500), [item])[-1].reason
        == "Validated evidence establishes 2300 employees, exceeding the campaign maximum of 500."
    )
