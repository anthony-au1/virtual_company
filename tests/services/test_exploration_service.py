"""Unit tests for Exploration generation and derived-obligation lifecycle."""

from __future__ import annotations

from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest

from virtual_company.repositories.dtos import ExplorationUpdate
from virtual_company.services.exploration import (
    ExplorationGenerationConflictError,
    ExplorationObligationGenerationError,
    ExplorationService,
)
from virtual_company.services.obligation_generator import (
    GeneratedObligation,
    ObligationGenerationResult,
)


class SessionStub:
    def __init__(self) -> None:
        self.store = {"explorations": {}, "obligations": {}, "runs": set()}
        self.fail_flush = False

    @asynccontextmanager
    async def begin(self):
        snapshot = deepcopy(self.store)
        try:
            yield
        except Exception:
            self.store.clear()
            self.store.update(snapshot)
            raise


class ExplorationRepositoryStub:
    def __init__(self, session: SessionStub) -> None:
        self.store = session.store

    async def create(self, data):
        item = SimpleNamespace(
            id=uuid4(),
            business_context=data.business_context,
            max_obligations=data.max_obligations,
            status=data.status,
        )
        self.store["explorations"][item.id] = item
        return item

    async def get_by_id(self, exploration_id):
        return self.store["explorations"].get(exploration_id)

    async def get_by_id_for_update(self, exploration_id):
        return await self.get_by_id(exploration_id)

    async def update(self, exploration_id, data):
        item = await self.get_by_id(exploration_id)
        if item is None:
            return None
        for field in data.model_fields_set:
            setattr(item, field, getattr(data, field))
        return item

    async def list(self):
        return list(self.store["explorations"].values())

    async def delete(self, exploration):
        del self.store["explorations"][exploration.id]
        if self.store.get("fail_exploration_delete"):
            raise RuntimeError("delete persistence failed")


class ObligationRepositoryStub:
    def __init__(self, session: SessionStub) -> None:
        self.session = session
        self.store = session.store

    async def create_many(self, exploration_id, descriptions):
        if self.session.fail_flush:
            raise RuntimeError("persistence failed")
        created = []
        for description in descriptions:
            item = SimpleNamespace(
                id=uuid4(), exploration_id=exploration_id, description=description
            )
            self.store["obligations"][item.id] = item
            created.append(item)
        return created

    async def replace_for_exploration(self, exploration_id, descriptions):
        self.store["obligations"] = {
            key: value
            for key, value in self.store["obligations"].items()
            if value.exploration_id != exploration_id
        }
        return await self.create_many(exploration_id, descriptions)

    async def delete_for_exploration_id(self, exploration_id):
        self.store["obligations"] = {
            key: value
            for key, value in self.store["obligations"].items()
            if value.exploration_id != exploration_id
        }

    async def list_by_exploration_id(self, exploration_id):
        return [
            item
            for item in self.store["obligations"].values()
            if item.exploration_id == exploration_id
        ]


class RunRepositoryStub:
    def __init__(self, session: SessionStub) -> None:
        self.store = session.store

    async def exists_for_exploration(self, exploration_id):
        return exploration_id in self.store["runs"]


class GeneratorStub:
    def __init__(self, *results) -> None:
        self.results = list(results)
        self.calls = []

    async def generate(self, business_context, max_obligations):
        self.calls.append((business_context, max_obligations))
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def result(*descriptions: str) -> ObligationGenerationResult:
    return ObligationGenerationResult(
        obligations=[GeneratedObligation(description=value) for value in descriptions]
    )


@pytest.fixture
def service_factory(monkeypatch):
    from virtual_company.services import exploration as module

    monkeypatch.setattr(module, "ExplorationRepository", ExplorationRepositoryStub)
    monkeypatch.setattr(
        module, "ExplorationObligationRepository", ObligationRepositoryStub
    )
    monkeypatch.setattr(module, "ExplorationRunRepository", RunRepositoryStub)

    def build(generator):
        session = SessionStub()
        return ExplorationService(session, generator), session

    return build


@pytest.mark.asyncio
async def test_create_generates_with_default_and_persists_all_obligations(
    service_factory,
) -> None:
    generator = GeneratorStub(result("One", "Two"))
    service, _ = service_factory(generator)

    exploration = await service.create("context")

    assert generator.calls == [("context", 10)]
    obligations = await service.list_obligations(exploration.id)
    assert [item.description for item in obligations] == ["One", "Two"]


@pytest.mark.asyncio
async def test_create_uses_explicit_limit_and_empty_result_is_success(service_factory):
    generator = GeneratorStub(result())
    service, _ = service_factory(generator)

    exploration = await service.create("context", 4)

    assert generator.calls == [("context", 4)]
    assert await service.list_obligations(exploration.id) == []


@pytest.mark.asyncio
async def test_create_generation_or_persistence_failure_leaves_no_exploration(
    service_factory,
) -> None:
    generator = GeneratorStub(RuntimeError("provider details"))
    service, session = service_factory(generator)
    with pytest.raises(ExplorationObligationGenerationError):
        await service.create("context")
    assert session.store["explorations"] == {}

    service, session = service_factory(GeneratorStub(result("one")))
    session.fail_flush = True
    with pytest.raises(RuntimeError, match="persistence failed"):
        await service.create("context")
    assert session.store["explorations"] == {}
    assert session.store["obligations"] == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("patch", "expected_inputs"),
    [
        ({"business_context": "new"}, ("new", 10)),
        ({"max_obligations": 15}, ("old", 15)),
        ({"business_context": "new", "max_obligations": 15}, ("new", 15)),
    ],
)
async def test_changed_inputs_regenerate_once_and_replace_obligations(
    service_factory, patch, expected_inputs
) -> None:
    generator = GeneratorStub(result("old requirement"), result("new one", "new two"))
    service, _ = service_factory(generator)
    exploration = await service.create("old", 10)
    old_ids = {item.id for item in await service.list_obligations(exploration.id)}

    await service.update(exploration.id, ExplorationUpdate(**patch))

    assert generator.calls == [("old", 10), expected_inputs]
    obligations = await service.list_obligations(exploration.id)
    assert [item.description for item in obligations] == ["new one", "new two"]
    assert not old_ids.intersection(item.id for item in obligations)


@pytest.mark.asyncio
async def test_noop_patch_does_not_generate_or_replace_obligations(service_factory):
    generator = GeneratorStub(result("first"))
    service, _ = service_factory(generator)
    exploration = await service.create("same", 10)
    before = await service.list_obligations(exploration.id)

    await service.update(exploration.id, ExplorationUpdate(max_obligations=10))
    await service.update(exploration.id, ExplorationUpdate(business_context="same"))

    after = await service.list_obligations(exploration.id)
    assert generator.calls == [("same", 10)]
    assert [item.id for item in after] == [item.id for item in before]


@pytest.mark.asyncio
async def test_update_empty_generation_removes_old_obligations(service_factory):
    generator = GeneratorStub(result("first"), result())
    service, _ = service_factory(generator)
    exploration = await service.create("old")

    await service.update(exploration.id, ExplorationUpdate(business_context="new"))

    assert await service.list_obligations(exploration.id) == []


@pytest.mark.asyncio
async def test_update_generation_or_persistence_failure_rolls_back(service_factory):
    generator = GeneratorStub(
        result("old"), RuntimeError("provider details"), result("replacement")
    )
    service, session = service_factory(generator)
    exploration = await service.create("old")
    old_ids = [item.id for item in await service.list_obligations(exploration.id)]

    with pytest.raises(ExplorationObligationGenerationError):
        await service.update(exploration.id, ExplorationUpdate(business_context="new"))
    current = await service.get_by_id(exploration.id)
    assert current.business_context == "old"
    assert [
        item.id for item in await service.list_obligations(exploration.id)
    ] == old_ids

    session.fail_flush = True
    with pytest.raises(RuntimeError, match="persistence failed"):
        await service.update(exploration.id, ExplorationUpdate(business_context="new"))
    current = await service.get_by_id(exploration.id)
    assert current.business_context == "old"
    assert [
        item.id for item in await service.list_obligations(exploration.id)
    ] == old_ids


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "patch",
    [
        {"business_context": "changed"},
        {"max_obligations": 11},
        {"business_context": "changed", "max_obligations": 11},
    ],
)
async def test_run_makes_changed_inputs_immutable_but_allows_noop(
    service_factory, patch
):
    generator = GeneratorStub(result("first"))
    service, session = service_factory(generator)
    exploration = await service.create("same", 10)
    session.store["runs"].add(exploration.id)
    original_obligations = await service.list_obligations(exploration.id)

    await service.update(exploration.id, ExplorationUpdate(max_obligations=10))
    assert len(generator.calls) == 1
    with pytest.raises(ExplorationGenerationConflictError):
        await service.update(exploration.id, ExplorationUpdate(**patch))
    assert len(generator.calls) == 1
    current = await service.get_by_id(exploration.id)
    assert (current.business_context, current.max_obligations) == ("same", 10)
    assert [item.id for item in await service.list_obligations(exploration.id)] == [
        item.id for item in original_obligations
    ]


@pytest.mark.asyncio
async def test_delete_removes_exploration_and_owned_obligations(service_factory):
    service, session = service_factory(GeneratorStub(result("one", "two")))
    exploration = await service.create("context")

    assert await service.delete(exploration.id) is True
    assert await service.get_by_id(exploration.id) is None
    assert session.store["obligations"] == {}


@pytest.mark.asyncio
async def test_delete_missing_exploration_returns_false(service_factory):
    service, _ = service_factory(GeneratorStub())

    assert await service.delete(uuid4()) is False


@pytest.mark.asyncio
async def test_delete_after_any_run_conflicts_and_preserves_state(service_factory):
    service, session = service_factory(GeneratorStub(result("owned")))
    exploration = await service.create("context")
    obligations = await service.list_obligations(exploration.id)
    session.store["runs"].add(exploration.id)

    with pytest.raises(ExplorationGenerationConflictError, match="already been run"):
        await service.delete(exploration.id)

    current = await service.get_by_id(exploration.id)
    assert (current.business_context, current.max_obligations) == ("context", 10)
    assert [item.id for item in await service.list_obligations(exploration.id)] == [
        item.id for item in obligations
    ]


@pytest.mark.asyncio
async def test_delete_persistence_failure_rolls_back_parent_and_obligations(
    service_factory,
):
    service, session = service_factory(GeneratorStub(result("owned")))
    exploration = await service.create("context")
    obligations = await service.list_obligations(exploration.id)
    session.store["fail_exploration_delete"] = True

    with pytest.raises(RuntimeError, match="delete persistence failed"):
        await service.delete(exploration.id)

    current = await service.get_by_id(exploration.id)
    assert (current.business_context, current.max_obligations) == ("context", 10)
    assert [item.id for item in await service.list_obligations(exploration.id)] == [
        item.id for item in obligations
    ]
