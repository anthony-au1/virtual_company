"""Campaign model validation for the equal-criteria research model."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from virtual_company.api.models import CampaignCreateRequest
from virtual_company.domain.criteria import CompanySizeCriteria, campaign_criteria
from virtual_company.workflows.research.models import CampaignCriteria


def request(**changes: object) -> CampaignCreateRequest:
    return CampaignCreateRequest.model_validate(
        {
            "name": "Australian Fintech Java Research",
            "target_count": 3,
            "status": "DRAFT",
            "target_market": "Australia",
            "industry": "FinTech",
            "technologies": ["Java", "Spring", "Kafka"],
            "company_size": {"min": 100, "max": 500},
            **changes,
        }
    )


def test_campaign_uses_flat_criteria_and_campaign_research_limit() -> None:
    campaign = request()
    assert campaign.max_companies_to_research == 15
    assert campaign.technologies == ["Java", "Spring", "Kafka"]
    assert campaign.company_size is not None
    assert campaign.company_size.min == 100
    assert [(item.criterion, item.subject) for item in campaign_criteria(campaign)] == [
        ("target_market", "Australia"),
        ("industry", "FinTech"),
        ("technology", "Java"),
        ("technology", "Spring"),
        ("technology", "Kafka"),
        ("company_size", "employees >= 100"),
        ("company_size", "employees <= 500"),
    ]


@pytest.mark.parametrize(
    ("company_size", "expected_bounds", "expected_subjects"),
    [
        ({"min": 500}, (500, None), ["employees >= 500"]),
        ({"max": 5000}, (None, 5000), ["employees <= 5000"]),
        (
            {"min": 500, "max": 5000},
            (500, 5000),
            ["employees >= 500", "employees <= 5000"],
        ),
        (
            {"min": 500, "max": 500},
            (500, 500),
            ["employees >= 500", "employees <= 500"],
        ),
    ],
)
def test_company_size_bounds_are_direct_integers_and_generate_same_criteria(
    company_size: dict[str, int],
    expected_bounds: tuple[int | None, int | None],
    expected_subjects: list[str],
) -> None:
    campaign = request(
        target_market=None,
        industry=None,
        technologies=[],
        company_size=company_size,
    )

    assert campaign.company_size is not None
    assert (campaign.company_size.min, campaign.company_size.max) == expected_bounds
    assert [item.subject for item in campaign_criteria(campaign)] == expected_subjects
    assert campaign.model_dump(mode="json")["company_size"] == {
        "min": expected_bounds[0],
        "max": expected_bounds[1],
    }


@pytest.mark.parametrize(
    "company_size",
    [{"min": -1}, {"max": -1}],
)
def test_company_size_rejects_negative_bounds(company_size: dict[str, int]) -> None:
    with pytest.raises(ValidationError):
        request(company_size=company_size)


def test_company_size_rejects_minimum_above_maximum() -> None:
    with pytest.raises(ValidationError, match="company_size.min cannot exceed"):
        request(company_size={"min": 501, "max": 500})


def test_legacy_persisted_company_size_bounds_remain_readable() -> None:
    legacy = CompanySizeCriteria.model_validate(
        {"min": {"value": 500}, "max": {"value": 5000}}
    )

    assert legacy.model_dump(mode="json") == {"min": 500, "max": 5000}


def test_campaign_research_limit_defaults_for_large_target_and_serializes() -> None:
    campaign = request(target_count=20)
    assert campaign.max_companies_to_research == 20
    serialized = campaign.model_dump(mode="json")
    assert serialized["max_companies_to_research"] == 20
    assert "requirement" not in str(serialized)
    explicit = request(target_count=5, max_companies_to_research=10)
    assert explicit.max_companies_to_research == 10


def test_campaign_rejects_research_limit_below_target() -> None:
    with pytest.raises(ValidationError, match="cannot be less than target_count"):
        request(target_count=5, max_companies_to_research=4)


def test_workflow_campaign_dto_keeps_limit_and_size_operator() -> None:
    payload = request().model_dump(mode="json")
    payload["id"] = str(uuid4())
    campaign = CampaignCriteria.model_validate(payload)
    assert campaign.max_companies_to_research == 15
    assert campaign.company_size is not None
    assert campaign.company_size.min == 100
