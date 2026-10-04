"""Research results and human review route tests."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from virtual_company.api.dependencies import get_research_results_service
from virtual_company.main import app
from virtual_company.services import (
    ResearchCompanyNotFoundError,
    ResearchRunNotFoundError,
)


class ResearchResultsServiceStub:
    def __init__(self, *, results: object = None, review: object = None) -> None:
        self.results = results
        self.review = review
        self.review_args: dict[str, object] | None = None

    async def get_results(self, _run_id: object) -> object:
        if isinstance(self.results, Exception):
            raise self.results
        return self.results

    async def update_review(self, **kwargs: object) -> object:
        self.review_args = kwargs
        if isinstance(self.review, Exception):
            raise self.review
        return self.review


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
            criteria=SimpleNamespace(
                target_market=SimpleNamespace(
                    value="Australia", requirement="required"
                ),
                industry=SimpleNamespace(value="fin tech", requirement="required"),
                technologies={"required": ["java"], "preferred": ["kafka"]},
                company_size={
                    "min": {"value": 500, "requirement": "preferred"}
                },
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
                review_status="UNREVIEWED",
                summary=SimpleNamespace(required=counts, preferred=counts),
                criteria=[
                    SimpleNamespace(
                        criterion="technology",
                        subject="java",
                        requirement="required",
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
    assert body["campaign"]["criteria"]["target_market"] == {
        "value": "Australia",
        "requirement": "required",
    }
    assert body["summary"] == {
        "researched": 1,
        "qualified": 1,
        "not_qualified": 0,
        "insufficient_evidence": 0,
    }
    assert body["companies"][0]["review_status"] == "UNREVIEWED"
    assert body["companies"][0]["criteria"][0]["evidence"][0]["claim"] == (
        "Uses Java"
    )


def test_patch_review_returns_updated_run_scoped_decision() -> None:
    run_id, company_id = uuid4(), uuid4()
    service = ResearchResultsServiceStub(
        review=SimpleNamespace(company_id=company_id, review_status="ACCEPTED")
    )
    app.dependency_overrides[get_research_results_service] = lambda: service

    response = TestClient(app).patch(
        f"/api/v1/research-runs/{run_id}/companies/{company_id}/review",
        json={"status": "ACCEPTED"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "company_id": str(company_id),
        "review_status": "ACCEPTED",
    }
    assert service.review_args == {
        "research_run_id": run_id,
        "company_id": company_id,
        "review_status": "ACCEPTED",
    }


def test_get_results_maps_missing_run_to_not_found() -> None:
    app.dependency_overrides[get_research_results_service] = lambda: (
        ResearchResultsServiceStub(
            results=ResearchRunNotFoundError("Research run not found")
        )
    )

    response = TestClient(app).get(
        f"/api/v1/research-runs/{uuid4()}/results"
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Research run not found"}


@pytest.mark.parametrize(
    ("error", "detail"),
    [
        (ResearchRunNotFoundError("Research run not found"), "Research run not found"),
        (
            ResearchCompanyNotFoundError("Company not found in research run"),
            "Company not found in research run",
        ),
    ],
)
def test_patch_review_maps_not_found_errors(error: Exception, detail: str) -> None:
    app.dependency_overrides[get_research_results_service] = lambda: (
        ResearchResultsServiceStub(review=error)
    )
    response = TestClient(app).patch(
        f"/api/v1/research-runs/{uuid4()}/companies/{uuid4()}/review",
        json={"status": "REJECTED"},
    )
    assert response.status_code == 404
    assert response.json() == {"detail": detail}


def test_malformed_ids_and_invalid_review_status_are_rejected() -> None:
    client = TestClient(app)
    assert client.get("/api/v1/research-runs/not-a-uuid/results").status_code == 422
    response = client.patch(
        f"/api/v1/research-runs/{uuid4()}/companies/{uuid4()}/review",
        json={"status": "MAYBE"},
    )
    assert response.status_code == 422
