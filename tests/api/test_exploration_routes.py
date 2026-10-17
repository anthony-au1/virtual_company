"""HTTP contract tests for Exploration and read-only Obligation endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from virtual_company.api.dependencies import get_exploration_service
from virtual_company.db.models import Exploration, ExplorationObligation
from virtual_company.main import app
from virtual_company.repositories.dtos import ExplorationUpdate


class ExplorationServiceStub:
    """Small stateful service double that lets route tests verify stored results."""

    def __init__(self) -> None:
        self.explorations: dict[UUID, Exploration] = {}
        self.obligations: dict[UUID, ExplorationObligation] = {}

    async def create(self, business_context: str) -> Exploration:
        now = datetime.now(UTC)
        item = Exploration(
            id=uuid4(),
            business_context=business_context,
            status="DRAFT",
            created_at=now,
            updated_at=now,
        )
        self.explorations[item.id] = item
        return item

    async def get_by_id(self, exploration_id: UUID) -> Exploration | None:
        return self.explorations.get(exploration_id)

    async def list(self) -> list[Exploration]:
        return list(self.explorations.values())

    async def update(
        self, exploration_id: UUID, data: ExplorationUpdate
    ) -> Exploration | None:
        item = self.explorations.get(exploration_id)
        if item is not None and "business_context" in data.model_fields_set:
            item.business_context = data.business_context  # type: ignore[assignment]
        return item

    async def list_obligations(
        self, exploration_id: UUID
    ) -> list[ExplorationObligation] | None:
        if exploration_id not in self.explorations:
            return None
        return [
            item
            for item in self.obligations.values()
            if item.exploration_id == exploration_id
        ]


@pytest.fixture(autouse=True)
def clear_dependency_overrides():
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


def test_exploration_lifecycle_and_restricted_fields() -> None:
    service = ExplorationServiceStub()
    app.dependency_overrides[get_exploration_service] = lambda: service
    client = TestClient(app)

    created = client.post(
        "/api/v1/explorations",
        json={"business_context": "Assess payment-provider fit"},
    )
    assert created.status_code == 201
    exploration = created.json()
    exploration_id = exploration["id"]
    assert exploration["status"] == "DRAFT"
    assert client.get(f"/api/v1/explorations/{exploration_id}").json() == exploration
    assert [item["id"] for item in client.get("/api/v1/explorations").json()] == [
        exploration_id
    ]

    updated = client.patch(
        f"/api/v1/explorations/{exploration_id}",
        json={"business_context": "Assess regional fit"},
    )
    assert updated.status_code == 200
    assert updated.json()["business_context"] == "Assess regional fit"
    assert (
        service.explorations[UUID(exploration_id)].business_context
        == "Assess regional fit"
    )

    assert (
        client.post("/api/v1/explorations", json={"business_context": None}).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/explorations",
            json={"business_context": "context", "id": str(uuid4())},
        ).status_code
        == 422
    )
    assert (
        client.patch(
            f"/api/v1/explorations/{exploration_id}", json={"business_context": None}
        ).status_code
        == 422
    )
    assert (
        client.patch(
            f"/api/v1/explorations/{exploration_id}", json={"status": "RUNNING"}
        ).status_code
        == 422
    )
    assert client.get(f"/api/v1/explorations/{uuid4()}").status_code == 404


def test_obligations_are_readable_but_not_user_managed() -> None:
    service = ExplorationServiceStub()
    app.dependency_overrides[get_exploration_service] = lambda: service
    client = TestClient(app)
    exploration = client.post(
        "/api/v1/explorations", json={"business_context": "Assess fit"}
    ).json()
    exploration_id = UUID(exploration["id"])
    obligation = ExplorationObligation(
        id=uuid4(),
        exploration_id=exploration_id,
        description="System-derived research question",
        created_at=datetime.now(UTC),
    )
    service.obligations[obligation.id] = obligation

    path = f"/api/v1/explorations/{exploration_id}/obligations"
    listed = client.get(path)
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["id"] == str(obligation.id)
    assert listed.json()[0]["exploration_id"] == str(exploration_id)
    assert listed.json()[0]["description"] == obligation.description
    assert client.get(f"/api/v1/explorations/{uuid4()}/obligations").status_code == 404

    # Collection path remains registered for GET, so unsupported POST is 405.
    assert client.post(path, json={"description": "manual create"}).status_code == 405
    item_path = f"{path}/{obligation.id}"
    assert (
        client.patch(item_path, json={"description": "manual update"}).status_code
        == 404
    )
    assert (
        client.put(item_path, json={"description": "manual replace"}).status_code == 404
    )
    assert client.delete(item_path).status_code == 404


def test_exploration_openapi_excludes_obligation_write_operations() -> None:
    schema = app.openapi()
    paths = schema["paths"]
    assert "/api/v1/explorations" in paths
    assert "/api/v1/explorations/{exploration_id}" in paths
    assert "/api/v1/explorations/{exploration_id}/obligations" in paths
    assert set(paths["/api/v1/explorations/{exploration_id}/obligations"]) == {"get"}
    assert (
        "/api/v1/explorations/{exploration_id}/obligations/{obligation_id}" not in paths
    )
    create_schema = schema["components"]["schemas"]["ExplorationCreateRequest"]
    assert set(create_schema["properties"]) == {"business_context"}
    assert "ExplorationObligationCreateRequest" not in schema["components"]["schemas"]
    assert "ExplorationObligationUpdateRequest" not in schema["components"]["schemas"]
