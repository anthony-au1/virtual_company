"""HTTP contract tests for the compact ExplorationRun list endpoint."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from virtual_company.api.dependencies import get_exploration_service
from virtual_company.main import app


def test_lists_run_summary_with_campaign_and_selected_company_count():
    exploration_id = uuid4()
    run_id, research_run_id = uuid4(), uuid4()
    started_at = datetime.now(UTC)

    class ServiceStub:
        async def list_runs(self, requested_exploration_id):
            assert requested_exploration_id == exploration_id
            return [
                SimpleNamespace(
                    id=run_id,
                    research_run_id=research_run_id,
                    status="RUNNING",
                    started_at=started_at,
                    completed_at=None,
                    campaign_name="Payments research",
                    selected_company_count=3,
                )
            ]

    app.dependency_overrides[get_exploration_service] = ServiceStub
    try:
        response = TestClient(app).get(
            f"/api/v1/explorations/{exploration_id}/runs"
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": str(run_id),
            "research_run_id": str(research_run_id),
            "status": "RUNNING",
            "started_at": started_at.isoformat().replace("+00:00", "Z"),
            "completed_at": None,
            "campaign_name": "Payments research",
            "selected_company_count": 3,
        }
    ]


def test_missing_exploration_returns_404_for_run_list():
    class ServiceStub:
        async def list_runs(self, requested_exploration_id):
            return None

    app.dependency_overrides[get_exploration_service] = ServiceStub
    try:
        response = TestClient(app).get(f"/api/v1/explorations/{uuid4()}/runs")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
