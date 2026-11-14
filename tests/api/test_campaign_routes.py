"""Route tests for the campaign API."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from redis.exceptions import ResponseError

from virtual_company.api.dependencies import get_campaign_service, get_research_service
from virtual_company.db.models import Campaign
from virtual_company.main import app
from virtual_company.repositories.dtos import CampaignCreate, CampaignUpdate
from virtual_company.services.campaign import (
    CampaignLifecycleConflictError,
    CampaignSealedError,
)


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

    async def list_research_companies(
        self, _campaign_id: object
    ) -> list[object] | None:
        return [] if self.campaign is not None else None

    async def delete(self, campaign_id: object) -> bool:
        return self.campaign is not None and self.campaign.id == campaign_id


class ResearchServiceStub:
    def __init__(self, run: object = None, error: Exception | None = None) -> None:
        self.run = run or type("Run", (), {"id": uuid4()})()
        self.error = error
        self.failed = False

    async def prepare_queued_run(self, _campaign_id: object) -> object:
        if self.error:
            raise self.error
        return self.run

    async def fail_queued_execution(self, _run_id: object) -> bool:
        self.failed = True
        return True


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
        max_companies_to_research=25,
        status="DRAFT",
        keywords=[],
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
    assert response.json()["max_companies_to_research"] == 25
    assert isinstance(service.create_data, CampaignCreate)
    assert service.create_data.max_companies_to_research == 25
    assert (
        service.create_data.model_dump()
        == CampaignCreate(
            name="APAC SaaS", target_count=25, status="DRAFT"
        ).model_dump()
    )


def test_create_campaign_accepts_flat_criteria() -> None:
    model = campaign()
    model.target_market = "Australia"
    model.industry = "fin tech"
    model.keywords = ["java", "kafka"]
    model.company_size = {
        "min": 100,
        "max": 500,
    }
    service = CampaignServiceStub(model)
    app.dependency_overrides[get_campaign_service] = lambda: service
    response = TestClient(app).post(
        "/api/v1/campaigns",
        json={
            "name": model.name,
            "target_count": model.target_count,
            "status": model.status,
            "target_market": model.target_market,
            "industry": model.industry,
            "keywords": model.keywords,
            "company_size": model.company_size,
        },
    )
    assert response.status_code == 201
    assert response.json()["keywords"] == model.keywords
    assert "technologies" not in response.json()
    assert response.json()["company_size"] == model.company_size
    assert response.json()["company_size"] == {"min": 100, "max": 500}
    assert "value" not in response.text
    assert service.create_data is not None
    assert service.create_data.company_size.min == 100


def test_create_campaign_rejects_legacy_technologies_field() -> None:
    response = TestClient(app).post(
        "/api/v1/campaigns",
        json={
            "name": "APAC SaaS",
            "target_count": 25,
            "status": "DRAFT",
            "technologies": ["Java"],
        },
    )

    assert response.status_code == 422


def test_campaign_response_flattens_legacy_persisted_company_size() -> None:
    model = campaign()
    model.company_size = {"min": {"value": 500}}
    app.dependency_overrides[get_campaign_service] = lambda: CampaignServiceStub(model)

    response = TestClient(app).get(f"/api/v1/campaigns/{model.id}")

    assert response.status_code == 200
    assert response.json()["company_size"] == {"min": 500, "max": None}


def test_campaign_openapi_exposes_company_size_bounds_as_integers() -> None:
    schemas = app.openapi()["components"]["schemas"]
    company_size = schemas["CompanySizeCriteria"]

    for bound_name in ("min", "max"):
        assert company_size["properties"][bound_name]["anyOf"][0]["type"] == "integer"
    assert "CompanySizeBound" not in schemas


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


def test_patch_maps_sealed_definition_to_conflict() -> None:
    class SealedCampaignService(CampaignServiceStub):
        async def update(
            self, _campaign_id: object, _data: CampaignUpdate
        ) -> Campaign | None:
            raise CampaignSealedError("Campaign research definition is sealed")

    app.dependency_overrides[get_campaign_service] = lambda: SealedCampaignService(
        campaign()
    )

    response = TestClient(app).patch(
        f"/api/v1/campaigns/{uuid4()}", json={"keywords": ["Go"]}
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "Campaign research definition is sealed"}


def test_delete_campaign_returns_no_content() -> None:
    model = campaign()
    app.dependency_overrides[get_campaign_service] = lambda: CampaignServiceStub(model)

    response = TestClient(app).delete(f"/api/v1/campaigns/{model.id}")

    assert response.status_code == 204
    assert response.content == b""


def test_delete_campaign_maps_missing_and_lifecycle_conflict() -> None:
    missing_service = CampaignServiceStub(None)
    app.dependency_overrides[get_campaign_service] = lambda: missing_service
    missing_response = TestClient(app).delete(f"/api/v1/campaigns/{uuid4()}")
    assert missing_response.status_code == 404
    assert missing_response.json() == {"detail": "Campaign not found"}

    class UsedCampaignService(CampaignServiceStub):
        async def delete(self, _campaign_id: object) -> bool:
            raise CampaignLifecycleConflictError(
                "This Campaign cannot be deleted because it has already been used "
                "for research."
            )

    app.dependency_overrides[get_campaign_service] = lambda: UsedCampaignService(
        campaign()
    )
    conflict_response = TestClient(app).delete(f"/api/v1/campaigns/{uuid4()}")
    assert conflict_response.status_code == 409
    assert conflict_response.json() == {
        "detail": "This Campaign cannot be deleted because it has already been "
        "used for research."
    }


def test_campaign_delete_openapi_documents_success_not_found_and_conflict() -> None:
    operation = app.openapi()["paths"]["/api/v1/campaigns/{campaign_id}"]["delete"]
    assert "204" in operation["responses"]
    assert "404" in operation["responses"]
    assert "409" in operation["responses"]


def test_campaign_status_validation_and_missing_campaign_return_errors() -> None:
    invalid = TestClient(app).post(
        "/api/v1/campaigns",
        json={"name": "APAC SaaS", "target_count": 25, "status": "UNKNOWN"},
    )
    assert invalid.status_code == 422

    old_size = TestClient(app).post(
        "/api/v1/campaigns",
        json={
            "name": "APAC SaaS",
            "target_count": 25,
            "status": "DRAFT",
            "company_size_min": 100,
        },
    )
    assert old_size.status_code == 422

    app.dependency_overrides[get_campaign_service] = lambda: CampaignServiceStub(None)
    missing = TestClient(app).get(f"/api/v1/campaigns/{uuid4()}")
    assert missing.status_code == 404


def test_research_campaign_enqueues_and_returns_accepted(monkeypatch) -> None:
    import virtual_company.api.campaigns as campaign_routes

    run_id = uuid4()
    service = ResearchServiceStub(type("Run", (), {"id": run_id})())
    app.dependency_overrides[get_research_service] = lambda: service
    published = []

    async def publish(*args):
        published.append(args)

    monkeypatch.setattr(campaign_routes.execute_workflow, "kiq", publish)

    response = TestClient(app).post(f"/api/v1/campaigns/{uuid4()}/research")

    assert response.status_code == 202
    assert response.json() == {
        "research_run_id": str(run_id),
        "status": "QUEUED",
    }
    assert published == [("research", str(run_id))]


def test_research_campaign_maps_missing_campaign() -> None:
    app.dependency_overrides[get_research_service] = lambda: ResearchServiceStub(
        error=ValueError("Campaign was not found")
    )

    response = TestClient(app).post(f"/api/v1/campaigns/{uuid4()}/research")

    assert response.status_code == 404


@pytest.mark.parametrize(
    ("cause", "compensated"),
    [
        (RuntimeError("timeout"), False),
        (ResponseError("NOAUTH"), True),
    ],
)
def test_research_publish_ambiguity_does_not_fail_queued_run(
    monkeypatch, cause: Exception, compensated: bool
) -> None:
    from taskiq import SendTaskError

    import virtual_company.api.campaigns as campaign_routes

    run_id = uuid4()
    service = ResearchServiceStub(type("Run", (), {"id": run_id})())
    app.dependency_overrides[get_research_service] = lambda: service

    async def publish(*_args):
        error = SendTaskError()
        error.__cause__ = cause
        raise error

    monkeypatch.setattr(campaign_routes.execute_workflow, "kiq", publish)
    response = TestClient(app).post(f"/api/v1/campaigns/{uuid4()}/research")

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Execution could not be scheduled"
        if compensated
        else "Execution publish outcome is unknown"
    )
    assert service.failed is compensated


def test_research_enqueue_compensation_error_preserves_503_response(monkeypatch) -> None:
    from taskiq import SendTaskError

    import virtual_company.api.campaigns as campaign_routes

    run_id = uuid4()
    service = ResearchServiceStub(type("Run", (), {"id": run_id})())

    async def fail_compensation(_run_id):
        raise RuntimeError("database unavailable")

    service.fail_queued_execution = fail_compensation
    app.dependency_overrides[get_research_service] = lambda: service

    async def publish(*_args):
        error = SendTaskError()
        error.__cause__ = ResponseError("NOAUTH")
        raise error

    monkeypatch.setattr(campaign_routes.execute_workflow, "kiq", publish)
    response = TestClient(app).post(f"/api/v1/campaigns/{uuid4()}/research")

    assert response.status_code == 503
    assert response.json()["detail"] == "Execution could not be scheduled"
