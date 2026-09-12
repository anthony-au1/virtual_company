"""Route tests for company and evidence retrieval."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from virtual_company.api.dependencies import get_company_service, get_evidence_service
from virtual_company.db.models import Company, Evidence
from virtual_company.main import app


class CompanyServiceStub:
    """In-memory company service substitute for route tests."""

    def __init__(self, company: Company | None) -> None:
        self.company = company

    async def get_by_id(self, _company_id: object) -> Company | None:
        return self.company


class EvidenceServiceStub:
    """In-memory evidence service substitute for route tests."""

    def __init__(self, evidence: list[Evidence] | None) -> None:
        self.evidence = evidence

    async def list_for_company(self, _company_id: object) -> list[Evidence] | None:
        return self.evidence


@pytest.fixture(autouse=True)
def clear_dependency_overrides() -> None:
    """Avoid leaking FastAPI dependency overrides between tests."""
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


def test_get_company_and_evidence_responses() -> None:
    now = datetime.now(UTC)
    company = Company(id=uuid4(), name="Example", created_at=now, updated_at=now)
    evidence = Evidence(
        id=uuid4(),
        company_id=company.id,
        claim="Uses Python",
        evidence_text="The engineering page mentions Python.",
        source_url="https://example.com/engineering",
        observed_at=now,
        created_at=now,
    )
    app.dependency_overrides[get_company_service] = lambda: CompanyServiceStub(company)
    app.dependency_overrides[get_evidence_service] = lambda: EvidenceServiceStub([evidence])
    client = TestClient(app)

    company_response = client.get(f"/api/v1/companies/{company.id}")
    evidence_response = client.get(f"/api/v1/companies/{company.id}/evidence")

    assert company_response.status_code == 200
    assert company_response.json()["name"] == "Example"
    assert evidence_response.status_code == 200
    assert evidence_response.json()[0]["claim"] == "Uses Python"


def test_missing_company_returns_not_found() -> None:
    app.dependency_overrides[get_company_service] = lambda: CompanyServiceStub(None)
    app.dependency_overrides[get_evidence_service] = lambda: EvidenceServiceStub(None)
    client = TestClient(app)

    assert client.get(f"/api/v1/companies/{uuid4()}").status_code == 404
    assert client.get(f"/api/v1/companies/{uuid4()}/evidence").status_code == 404
