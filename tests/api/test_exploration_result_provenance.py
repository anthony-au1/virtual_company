"""HTTP response contracts for persisted Exploration provenance."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from virtual_company.api.dependencies import get_exploration_service
from virtual_company.main import app

EXPLORATION_ID = UUID(int=10)
COMPANY_LINK_ID = UUID(int=20)
OTHER_COMPANY_LINK_ID = UUID(int=30)
CREATED_AT = datetime(2026, 1, 1, tzinfo=UTC)


class ResultServiceStub:
    def __init__(self) -> None:
        self.facts = [
            SimpleNamespace(
                id=UUID(int=40),
                exploration_company_id=COMPANY_LINK_ID,
                statement="A persisted fact",
                created_at=CREATED_AT,
                evidence=[
                    SimpleNamespace(
                        id=UUID(int=52),
                        exploration_company_id=COMPANY_LINK_ID,
                    ),
                    SimpleNamespace(
                        id=UUID(int=51),
                        exploration_company_id=COMPANY_LINK_ID,
                    ),
                    SimpleNamespace(
                        id=UUID(int=50),
                        exploration_company_id=OTHER_COMPANY_LINK_ID,
                    ),
                ],
            ),
            SimpleNamespace(
                id=UUID(int=41),
                exploration_company_id=COMPANY_LINK_ID,
                statement="A fact without evidence",
                created_at=CREATED_AT,
                evidence=[],
            ),
        ]
        self.hypotheses = [
            SimpleNamespace(
                id=UUID(int=60),
                exploration_company_id=COMPANY_LINK_ID,
                statement="A persisted hypothesis",
                created_at=CREATED_AT,
                facts=[
                    SimpleNamespace(
                        id=UUID(int=72),
                        exploration_company_id=COMPANY_LINK_ID,
                    ),
                    SimpleNamespace(
                        id=UUID(int=71),
                        exploration_company_id=COMPANY_LINK_ID,
                    ),
                    SimpleNamespace(
                        id=UUID(int=70),
                        exploration_company_id=OTHER_COMPANY_LINK_ID,
                    ),
                ],
            ),
            SimpleNamespace(
                id=UUID(int=61),
                exploration_company_id=COMPANY_LINK_ID,
                statement="A hypothesis without facts",
                created_at=CREATED_AT,
                facts=[],
            ),
        ]

    async def list_company_facts(self, exploration_id: UUID, company_link_id: UUID):
        if exploration_id != EXPLORATION_ID or company_link_id != COMPANY_LINK_ID:
            return None
        return self.facts

    async def list_company_hypotheses(
        self, exploration_id: UUID, company_link_id: UUID
    ):
        if exploration_id != EXPLORATION_ID or company_link_id != COMPANY_LINK_ID:
            return None
        return self.hypotheses


@pytest.fixture(autouse=True)
def clear_dependency_overrides():
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


def test_fact_response_projects_company_scoped_evidence_ids_in_uuid_order() -> None:
    service = ResultServiceStub()
    app.dependency_overrides[get_exploration_service] = lambda: service
    client = TestClient(app)

    response = client.get(
        f"/api/v1/explorations/{EXPLORATION_ID}/companies/{COMPANY_LINK_ID}/facts"
    )

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": str(UUID(int=40)),
            "exploration_company_id": str(COMPANY_LINK_ID),
            "statement": "A persisted fact",
            "created_at": CREATED_AT.isoformat().replace("+00:00", "Z"),
            "evidence_ids": [str(UUID(int=51)), str(UUID(int=52))],
        },
        {
            "id": str(UUID(int=41)),
            "exploration_company_id": str(COMPANY_LINK_ID),
            "statement": "A fact without evidence",
            "created_at": CREATED_AT.isoformat().replace("+00:00", "Z"),
            "evidence_ids": [],
        },
    ]


def test_hypothesis_response_projects_company_scoped_fact_ids_in_uuid_order() -> None:
    service = ResultServiceStub()
    app.dependency_overrides[get_exploration_service] = lambda: service
    client = TestClient(app)

    response = client.get(
        f"/api/v1/explorations/{EXPLORATION_ID}/companies/{COMPANY_LINK_ID}/hypotheses"
    )

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": str(UUID(int=60)),
            "exploration_company_id": str(COMPANY_LINK_ID),
            "statement": "A persisted hypothesis",
            "created_at": CREATED_AT.isoformat().replace("+00:00", "Z"),
            "fact_ids": [str(UUID(int=71)), str(UUID(int=72))],
        },
        {
            "id": str(UUID(int=61)),
            "exploration_company_id": str(COMPANY_LINK_ID),
            "statement": "A hypothesis without facts",
            "created_at": CREATED_AT.isoformat().replace("+00:00", "Z"),
            "fact_ids": [],
        },
    ]


@pytest.mark.parametrize("collection", ["facts", "hypotheses"])
def test_result_routes_preserve_company_ownership_validation(collection: str) -> None:
    app.dependency_overrides[get_exploration_service] = lambda: ResultServiceStub()
    client = TestClient(app)

    response = client.get(
        f"/api/v1/explorations/{EXPLORATION_ID}/companies/"
        f"{OTHER_COMPANY_LINK_ID}/{collection}"
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Exploration company not found"
