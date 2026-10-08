"""Campaign model validation for the equal-criteria research model."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from virtual_company.api.models import CampaignCreateRequest
from virtual_company.domain.criteria import campaign_criteria
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
            "company_size": {"min": {"value": 100}, "max": {"value": 500}},
            **changes,
        }
    )


def test_campaign_uses_flat_criteria_and_campaign_research_limit() -> None:
    campaign = request()
    assert campaign.max_companies_to_research == 15
    assert campaign.technologies == ["Java", "Spring", "Kafka"]
    assert campaign.company_size is not None
    assert campaign.company_size.min.value == 100
    assert [(item.criterion, item.subject) for item in campaign_criteria(campaign)] == [
        ("target_market", "Australia"),
        ("industry", "FinTech"),
        ("technology", "Java"),
        ("technology", "Spring"),
        ("technology", "Kafka"),
        ("company_size", "employees >= 100"),
        ("company_size", "employees <= 500"),
    ]


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
    assert campaign.company_size.min.value == 100
