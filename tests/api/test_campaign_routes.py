"""Route tests for the campaign API."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from virtual_company.api.dependencies import get_campaign_service
from virtual_company.db.models import Campaign
from virtual_company.main import app
from virtual_company.repositories.dtos import CampaignCreate, CampaignUpdate


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
