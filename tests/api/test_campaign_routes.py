"""Route tests for the campaign API."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from virtual_company.api.dependencies import get_campaign_service, get_research_workflow
from virtual_company.db.models import Campaign
from virtual_company.main import app
from virtual_company.repositories.dtos import CampaignCreate, CampaignUpdate
from virtual_company.tools import WebSearchNotConfiguredError
from virtual_company.workflows.research.models import ResearchWorkflowResult
from virtual_company.workflows.research.nodes import CampaignNotFoundError


class CampaignServiceStub:
    """In-memory campaign service substitute for route tests."""

    def __init__(self, campaign: Campaign | None) -> None:
        self.campaign = campaign
        self.create_data: CampaignCreate | None = None
        self.update_data: CampaignUpdate | None = None

    async def create(self, data: CampaignCreate) -> Campaign:
        self.create_data = data
        return self.campaign  # type: ignore[return-value]

    async def get_by_id(self, _campaign_id: object) -> Campaign | None:
        return self.campaign

    async def list(self) -> list[Campaign]:
        return [self.campaign] if self.campaign is not None else []

    async def update(
        self, _campaign_id: object, data: CampaignUpdate
    ) -> Campaign | None:
        self.update_data = data
        return self.campaign

    async def list_companies(self, _campaign_id: object) -> list[object] | None:
        return [] if self.campaign is not None else None


class ResearchWorkflowStub:
    """Research workflow substitute for route tests."""

    def __init__(self, result: ResearchWorkflowResult | Exception) -> None:
        self.result = result

    async def run(self, _campaign_id: object) -> ResearchWorkflowResult:
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.fixture(autouse=True)
def clear_dependency_overrides() -> None:
    """Avoid leaking FastAPI dependency overrides between tests."""
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


def campaign() -> Campaign:
    """Build a fully populated campaign ORM model for response validation."""
    now = datetime.now(UTC)
    return Campaign(
        id=uuid4(),
        name="APAC SaaS",
        target_count=25,
        status="DRAFT",
        created_at=now,
        updated_at=now,
    )


def test_create_campaign_returns_created_response() -> None:
    model = campaign()
    service = CampaignServiceStub(model)
    app.dependency_overrides[get_campaign_service] = lambda: service

    response = TestClient(app).post(
        "/api/v1/campaigns",
        json={"name": "APAC SaaS", "target_count": 25, "status": "DRAFT"},
    )

    assert response.status_code == 201
    assert response.json()["id"] == str(model.id)
    assert isinstance(service.create_data, CampaignCreate)
    assert service.create_data.model_dump() == CampaignCreate(
        name="APAC SaaS", target_count=25, status="DRAFT"
    ).model_dump()


def test_patch_null_clears_nullable_field_and_keeps_omitted_fields_unchanged() -> None:
    service = CampaignServiceStub(campaign())
    app.dependency_overrides[get_campaign_service] = lambda: service

    response = TestClient(app).patch(
        f"/api/v1/campaigns/{uuid4()}", json={"description": None}
    )

    assert response.status_code == 200
    assert service.update_data is not None
    assert service.update_data.description is None
    assert service.update_data.model_fields_set == {"description"}


def test_campaign_status_validation_and_missing_campaign_return_errors() -> None:
    invalid = TestClient(app).post(
        "/api/v1/campaigns",
        json={"name": "APAC SaaS", "target_count": 25, "status": "UNKNOWN"},
    )
    assert invalid.status_code == 422

    app.dependency_overrides[get_campaign_service] = lambda: CampaignServiceStub(None)
    missing = TestClient(app).get(f"/api/v1/campaigns/{uuid4()}")
    assert missing.status_code == 404


def test_research_campaign_returns_workflow_result() -> None:
    run_id = uuid4()
    app.dependency_overrides[get_research_workflow] = lambda: ResearchWorkflowStub(
        ResearchWorkflowResult(
            research_run_id=run_id, status="COMPLETED", companies_found=2
        )
    )

    response = TestClient(app).post(f"/api/v1/campaigns/{uuid4()}/research")

    assert response.status_code == 200
    assert response.json() == {
        "research_run_id": str(run_id),
        "status": "COMPLETED",
        "companies_found": 2,
    }


@pytest.mark.parametrize(
    ("error", "status_code"),
    [
        (CampaignNotFoundError("Campaign not found"), 404),
        (WebSearchNotConfiguredError("Web search is not configured"), 503),
    ],
)
def test_research_campaign_maps_expected_workflow_errors(
    error: Exception, status_code: int
) -> None:
    app.dependency_overrides[get_research_workflow] = lambda: ResearchWorkflowStub(error)

    response = TestClient(app).post(f"/api/v1/campaigns/{uuid4()}/research")

    assert response.status_code == status_code
