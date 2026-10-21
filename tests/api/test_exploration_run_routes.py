"""HTTP contract tests for starting an ExplorationRun."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from virtual_company.api.dependencies import get_exploration_service
from virtual_company.main import app


def test_start_run_returns_run_and_selected_company_ids():
    exploration_id, research_run_id = uuid4(), uuid4()
    company_ids = [uuid4(), uuid4()]
    now = datetime.now(UTC)

    class ServiceStub:
        async def start_run(self, requested_exploration_id, requested_research_run_id, requested_company_ids):
            assert requested_exploration_id == exploration_id
            assert requested_research_run_id == research_run_id
            assert requested_company_ids == company_ids
            return SimpleNamespace(
                run=SimpleNamespace(
                    id=uuid4(),
                    exploration_id=exploration_id,
                    research_run_id=research_run_id,
                    status="RUNNING",
                    started_at=now,
                    completed_at=None,
                ),
                company_ids=company_ids,
            )

    app.dependency_overrides[get_exploration_service] = ServiceStub
    try:
        response = TestClient(app).post(
            f"/api/v1/explorations/{exploration_id}/runs",
            json={
                "research_run_id": str(research_run_id),
                "company_ids": [str(value) for value in company_ids],
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    assert response.json()["exploration_id"] == str(exploration_id)
    assert response.json()["research_run_id"] == str(research_run_id)
    assert response.json()["company_ids"] == [str(value) for value in company_ids]


def test_start_run_rejects_empty_company_ids_and_client_lifecycle_fields():
    exploration_id = uuid4()
    from virtual_company.api.dependencies import get_exploration_service

    class ServiceStub:
        async def start_run(self, *args):
            raise AssertionError("invalid request must not reach the service")

    app.dependency_overrides[get_exploration_service] = ServiceStub
    client = TestClient(app)
    base = {"research_run_id": str(uuid4())}
    try:
        empty = client.post(
            f"/api/v1/explorations/{exploration_id}/runs",
            json={**base, "company_ids": []},
        )
        extra = client.post(
            f"/api/v1/explorations/{exploration_id}/runs",
            json={**base, "company_ids": [str(uuid4())], "status": "COMPLETED"},
        )
    finally:
        app.dependency_overrides.clear()

    assert empty.status_code == 422
    assert extra.status_code == 422
