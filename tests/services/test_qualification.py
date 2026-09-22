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
        (["2300+ employees"], Status.UNKNOWN),
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
