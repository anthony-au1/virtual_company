"""Research result and run management route tests."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from virtual_company.api.dependencies import get_research_results_service
from virtual_company.main import app
from virtual_company.services import (
    ActiveResearchRunError,
    ResearchRunNotFoundError,
)


class ResearchResultsServiceStub:
    def __init__(
        self,
        *,
        results: object = None,
        delete_result: object = True,
        runs: list[object] | None = None,
    ) -> None:
        self.results = results
        self.delete_result = delete_result
        self.runs = runs or []

    async def list_runs(self) -> list[object]:
        return self.runs

    async def get_results(self, _run_id: object) -> object:
        if isinstance(self.results, Exception):
            raise self.results
        return self.results

    async def delete_run(self, _run_id: object) -> object:
        if isinstance(self.delete_result, Exception):
            raise self.delete_result
        return self.delete_result


@pytest.fixture(autouse=True)
def clear_dependency_overrides() -> None:
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


def research_results() -> SimpleNamespace:
    now = datetime.now(UTC)
    run_id, campaign_id, company_id, evidence_id = (uuid4() for _ in range(4))
    counts = SimpleNamespace(matched=1, mismatched=0, unknown=0)
    return SimpleNamespace(
        research_run=SimpleNamespace(
            id=run_id,
            campaign_id=campaign_id,
            status="COMPLETED",
            started_at=now,
            completed_at=now,
            error=None,
            companies_found=1,
            created_at=now,
        ),
        campaign=SimpleNamespace(
            id=campaign_id,
            name="Fintech",
            description="Research Australian fintech",
            target_count=1,
            max_companies_to_research=10,
            criteria=SimpleNamespace(
                target_market="Australia",
                industry="fin tech",
                keywords=["java", "kafka"],
                company_size={"min": 500},
            ),
        ),
        summary=SimpleNamespace(
            researched=1,
            qualified=1,
            not_qualified=0,
            insufficient_evidence=0,
        ),
        companies=[
            SimpleNamespace(
                company_id=company_id,
                name="Example",
                website="https://example.com",
                qualification_status="QUALIFIED",
                summary=counts,
                criteria=[
                    SimpleNamespace(
                        criterion="keyword",
                        subject="java",
                        status="MATCH",
                        reason="Supported",
                        evidence=[
                            SimpleNamespace(
                                id=evidence_id,
                                claim="Uses Java",
                                evidence_text="Java is listed.",
                                source_url="https://example.com/jobs",
                                source_title="Jobs",
                                source_type="careers",
                            )
                        ],
                    )
                ],
            )
        ],
    )


def test_get_results_returns_complete_product_projection() -> None:
    result = research_results()
    app.dependency_overrides[get_research_results_service] = lambda: (
        ResearchResultsServiceStub(results=result)
    )

    response = TestClient(app).get(
        f"/api/v1/research-runs/{result.research_run.id}/results"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["campaign"]["criteria"]["target_market"] == "Australia"
    assert body["campaign"]["max_companies_to_research"] == 10
    assert body["summary"] == {
        "researched": 1,
        "qualified": 1,
        "not_qualified": 0,
        "insufficient_evidence": 0,
    }
    assert body["companies"][0]["qualification_status"] == "QUALIFIED"
    assert body["companies"][0]["criteria"][0]["evidence"][0]["claim"] == ("Uses Java")


def test_list_research_runs_returns_compact_run_summaries() -> None:
    now = datetime.now(UTC)
    run_id, campaign_id = uuid4(), uuid4()
    item = SimpleNamespace(
        run_id=run_id,
        status="COMPLETED",
        created_at=now,
        started_at=now,
        completed_at=now,
        campaign_id=campaign_id,
        campaign_name="Australian Fintech Java Research",
        target_count=5,
        max_companies_to_research=10,
        summary=SimpleNamespace(
            researched=10,
            qualified=4,
            not_qualified=3,
            insufficient_evidence=3,
        ),
    )
    app.dependency_overrides[get_research_results_service] = lambda: (
        ResearchResultsServiceStub(runs=[item])
    )

    response = TestClient(app).get("/api/v1/research-runs")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["run_id"] == str(run_id)
    for field in ("created_at", "started_at", "completed_at"):
        assert datetime.fromisoformat(body[0][field]) == now
    assert body[0]["campaign"] == {
        "id": str(campaign_id),
        "name": "Australian Fintech Java Research",
        "target_count": 5,
        "max_companies_to_research": 10,
    }
    assert body[0]["summary"] == {
        "researched": 10,
        "qualified": 4,
        "not_qualified": 3,
        "insufficient_evidence": 3,
    }


def test_delete_run_returns_no_content() -> None:
    run_id = uuid4()
    service = ResearchResultsServiceStub()
    app.dependency_overrides[get_research_results_service] = lambda: service
    assert TestClient(app).delete(f"/api/v1/research-runs/{run_id}").status_code == 204


def test_get_results_maps_missing_run_to_not_found() -> None:
    app.dependency_overrides[get_research_results_service] = lambda: (
        ResearchResultsServiceStub(
            results=ResearchRunNotFoundError("Research run not found")
        )
    )

    response = TestClient(app).get(f"/api/v1/research-runs/{uuid4()}/results")

    assert response.status_code == 404
    assert response.json() == {"detail": "Research run not found"}


def test_delete_run_maps_missing_and_running_runs() -> None:
    app.dependency_overrides[get_research_results_service] = lambda: (
        ResearchResultsServiceStub(delete_result=False)
    )
    response = TestClient(app).delete(f"/api/v1/research-runs/{uuid4()}")
    assert response.status_code == 404
    app.dependency_overrides[get_research_results_service] = lambda: (
        ResearchResultsServiceStub(delete_result=ActiveResearchRunError("running"))
    )
    response = TestClient(app).delete(f"/api/v1/research-runs/{uuid4()}")
    assert response.status_code == 409
    assert (
        TestClient(app).get("/api/v1/research-runs/not-a-uuid/results").status_code
        == 422
    )


def test_human_review_route_and_fields_are_absent() -> None:
    schema = app.openapi()
    assert not any("/review" in path for path in schema["paths"])
    assert "ReviewUpdateRequest" not in schema["components"]["schemas"]
    assert "ReviewResponse" not in schema["components"]["schemas"]
