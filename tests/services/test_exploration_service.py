"""Unit tests for Exploration application service propagation."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest

from virtual_company.repositories.dtos import ExplorationCreate, ExplorationUpdate
from virtual_company.services import exploration as exploration_service_module
from virtual_company.services.exploration import ExplorationService


class SessionStub:
    @asynccontextmanager
    async def begin(self):
        yield


class ExplorationRepositoryStub:
    def __init__(self, _session: SessionStub) -> None:
        self.created: ExplorationCreate | None = None
        self.updated: ExplorationUpdate | None = None
        self.exploration = SimpleNamespace(
            id=uuid4(), business_context="context", max_obligations=10, status="DRAFT"
        )

    async def create(self, data: ExplorationCreate):
        self.created = data
        self.exploration.business_context = data.business_context
        self.exploration.max_obligations = data.max_obligations
        return self.exploration

    async def update(self, _exploration_id, data: ExplorationUpdate):
        self.updated = data
        if "max_obligations" in data.model_fields_set:
            self.exploration.max_obligations = data.max_obligations
        return self.exploration


class ObligationRepositoryStub:
    def __init__(self, _session: SessionStub) -> None:
        pass


@pytest.mark.asyncio
async def test_service_propagates_max_obligations_on_create_and_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        exploration_service_module, "ExplorationRepository", ExplorationRepositoryStub
    )
    monkeypatch.setattr(
        exploration_service_module,
        "ExplorationObligationRepository",
        ObligationRepositoryStub,
    )
    service = ExplorationService(SessionStub())  # type: ignore[arg-type]

    created = await service.create("context", 17)
    assert created.max_obligations == 17
    assert service._explorations.created is not None
    assert service._explorations.created.max_obligations == 17

    updated = await service.update(created.id, ExplorationUpdate(max_obligations=8))
    assert updated is not None
    assert updated.max_obligations == 8
    assert service._explorations.updated is not None
    assert service._explorations.updated.max_obligations == 8
