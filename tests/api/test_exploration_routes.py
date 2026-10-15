"""HTTP contract tests for Exploration and Obligation endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from virtual_company.api.dependencies import get_exploration_service
from virtual_company.db.models import Exploration, ExplorationObligation
from virtual_company.main import app
from virtual_company.repositories.dtos import (
    ExplorationObligationUpdate,
    ExplorationUpdate,
)


class ExplorationServiceStub:
    """Small stateful service double that lets route tests verify stored results."""

    def __init__(self) -> None:
        self.explorations: dict[UUID, Exploration] = {}
        self.obligations: dict[UUID, ExplorationObligation] = {}

    async def create(self, business_context: str) -> Exploration:
        now = datetime.now(UTC)
        item = Exploration(
            id=uuid4(), business_context=business_context, status="DRAFT",
            created_at=now, updated_at=now,
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

    async def create_obligation(
        self, exploration_id: UUID, description: str
    ) -> ExplorationObligation | None:
        if exploration_id not in self.explorations:
            return None
        item = ExplorationObligation(
            id=uuid4(), exploration_id=exploration_id, description=description,
            created_at=datetime.now(UTC),
        )
        self.obligations[item.id] = item
        return item

    async def list_obligations(
        self, exploration_id: UUID
    ) -> list[ExplorationObligation] | None:
        if exploration_id not in self.explorations:
            return None
        return [
            item for item in self.obligations.values()
            if item.exploration_id == exploration_id
        ]

    async def update_obligation(
        self,
        exploration_id: UUID,
        obligation_id: UUID,
        data: ExplorationObligationUpdate,
    ) -> ExplorationObligation | None:
        item = self.obligations.get(obligation_id)
        if item is None or item.exploration_id != exploration_id:
            return None
        if "description" in data.model_fields_set:
            item.description = data.description  # type: ignore[assignment]
        return item

    async def delete_obligation(self, exploration_id: UUID, obligation_id: UUID) -> bool:
        item = self.obligations.get(obligation_id)
        if item is None or item.exploration_id != exploration_id:
            return False
        del self.obligations[obligation_id]
        return True


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
    assert service.explorations[UUID(exploration_id)].business_context == "Assess regional fit"

    assert client.post(
        "/api/v1/explorations", json={"business_context": None}
    ).status_code == 422
    assert client.post(
        "/api/v1/explorations",
        json={"business_context": "context", "id": str(uuid4())},
    ).status_code == 422
    assert client.patch(
        f"/api/v1/explorations/{exploration_id}", json={"business_context": None}
    ).status_code == 422
    assert client.patch(
        f"/api/v1/explorations/{exploration_id}", json={"status": "RUNNING"}
    ).status_code == 422
    assert client.get(f"/api/v1/explorations/{uuid4()}").status_code == 404


def test_obligation_lifecycle_parent_scope_and_validation() -> None:
    service = ExplorationServiceStub()
    app.dependency_overrides[get_exploration_service] = lambda: service
    client = TestClient(app)
    first = client.post(
        "/api/v1/explorations", json={"business_context": "First"}
    ).json()
    second = client.post(
        "/api/v1/explorations", json={"business_context": "Second"}
    ).json()
    first_id, second_id = UUID(first["id"]), UUID(second["id"])

    path = f"/api/v1/explorations/{first_id}/obligations"
    one = client.post(path, json={"description": "Find target market"})
    two = client.post(path, json={"description": "Review product fit"})
    other = client.post(
        f"/api/v1/explorations/{second_id}/obligations",
        json={"description": "Other exploration"},
    )
    assert one.status_code == two.status_code == other.status_code == 201
    one_id = UUID(one.json()["id"])

    listed = client.get(path)
    assert {item["id"] for item in listed.json()} == {one.json()["id"], two.json()["id"]}
    assert client.get(f"/api/v1/explorations/{uuid4()}/obligations").status_code == 404
    assert client.post(
        f"/api/v1/explorations/{uuid4()}/obligations",
        json={"description": "Orphan"},
    ).status_code == 404
    assert client.post(path, json={"description": None}).status_code == 422
    assert client.post(path, json={"description": "x", "exploration_id": str(second_id)}).status_code == 422

    update_path = f"/api/v1/explorations/{first_id}/obligations/{one_id}"
    updated = client.patch(update_path, json={"description": "Updated question"})
    assert updated.status_code == 200
    assert service.obligations[one_id].description == "Updated question"
    assert client.patch(update_path, json={"description": None}).status_code == 422
    assert client.patch(
        f"/api/v1/explorations/{second_id}/obligations/{one_id}",
        json={"description": "Tamper"},
    ).status_code == 404
    assert client.patch(
        f"/api/v1/explorations/{first_id}/obligations/{uuid4()}",
        json={"description": "Missing"},
    ).status_code == 404

    assert client.delete(
        f"/api/v1/explorations/{second_id}/obligations/{one_id}"
    ).status_code == 404
    deleted = client.delete(update_path)
    assert deleted.status_code == 204
    assert one_id not in service.obligations
    assert client.delete(update_path).status_code == 404


def test_exploration_openapi_includes_routes_and_restricted_create_fields() -> None:
    schema = app.openapi()
    paths = schema["paths"]
    assert "/api/v1/explorations" in paths
    assert "/api/v1/explorations/{exploration_id}" in paths
    assert "/api/v1/explorations/{exploration_id}/obligations" in paths
    assert (
        "/api/v1/explorations/{exploration_id}/obligations/{obligation_id}"
        in paths
    )
    create_schema = schema["components"]["schemas"]["ExplorationCreateRequest"]
    assert set(create_schema["properties"]) == {"business_context"}
