"""Service tests for creating ExplorationRun company snapshots."""

from __future__ import annotations

from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest

from virtual_company.services.exploration import (
    ExplorationCompanySelectionError,
    ExplorationService,
    ExplorationStartConflictError,
    ExplorationStartNotFoundError,
)


class SessionStub:
    def __init__(self) -> None:
        self.store = {"explorations": {}, "runs": {}, "links": []}
        self.events: list[str] = []
        self.fail_company_flush = False

    @asynccontextmanager
    async def begin(self):
        snapshot = deepcopy(self.store)
        try:
            yield
        except Exception:
            self.store.clear()
            self.store.update(snapshot)
            raise


class ExplorationRepoStub:
    def __init__(self, session):
        self.session = session

    async def get_by_id_for_update(self, exploration_id):
        self.session.events.append("lock_exploration")
        return self.session.store["explorations"].get(exploration_id)


class RunRepoStub:
    def __init__(self, session):
        self.session = session

    async def create(self, data):
        self.session.events.append("create_run")
        run = SimpleNamespace(id=uuid4(), **data.model_dump())
        self.session.store["runs"][run.id] = run
        return run


class ResearchRunRepoStub:
    def __init__(self, session):
        self.session = session

    async def get_by_id(self, research_run_id):
        self.session.events.append("validate_research_run")
        if self.session.store.get("research_run_id") != research_run_id:
            return None
        return SimpleNamespace(status=self.session.store.get("research_status", "COMPLETED"))


class QualificationRepoStub:
    def __init__(self, session):
        self.session = session

    async def list_member_company_ids(self, research_run_id, company_ids):
        self.session.events.append("validate_membership")
        return set(company_ids) & self.session.store.get("eligible_company_ids", set())


class CompanyRepoStub:
    def __init__(self, session):
        self.session = session

    async def create_many(self, run_id, company_ids):
        if self.session.fail_company_flush:
            raise RuntimeError("company insert failed")
        links = [(run_id, company_id) for company_id in company_ids]
        self.session.store["links"].extend(links)
        return links


class GeneratorStub:
    async def generate(self, business_context, max_obligations):
        raise AssertionError("run start must not generate obligations")


@pytest.fixture
def service_factory(monkeypatch):
    from virtual_company.services import exploration as module

    monkeypatch.setattr(module, "ExplorationRepository", ExplorationRepoStub)
    monkeypatch.setattr(module, "ExplorationRunRepository", RunRepoStub)
    monkeypatch.setattr(module, "ResearchRunRepository", ResearchRunRepoStub)
    monkeypatch.setattr(
        module, "ResearchCompanyQualificationRepository", QualificationRepoStub
    )
    monkeypatch.setattr(module, "ExplorationCompanyRepository", CompanyRepoStub)

    def build():
        session = SessionStub()
        exploration_id = uuid4()
        research_run_id = uuid4()
        session.store["explorations"][exploration_id] = SimpleNamespace(id=exploration_id)
        session.store["research_run_id"] = research_run_id
        service = ExplorationService(session, GeneratorStub())
        return service, session, exploration_id, research_run_id

    return build


@pytest.mark.asyncio
async def test_start_run_persists_one_run_and_unique_selected_companies(service_factory):
    service, session, exploration_id, research_run_id = service_factory()
    company_ids = [uuid4(), uuid4()]
    session.store["eligible_company_ids"] = set(company_ids)

    result = await service.start_run(
        exploration_id, research_run_id, [company_ids[0], company_ids[0], company_ids[1]]
    )

    assert result.run.exploration_id == exploration_id
    assert result.run.research_run_id == research_run_id
    assert result.run.status == "RUNNING"
    assert result.company_ids == company_ids
    assert len(session.store["runs"]) == 1
    assert len(session.store["links"]) == 2
    assert session.events.index("lock_exploration") < session.events.index("validate_research_run")
    assert session.events.index("validate_membership") < session.events.index("create_run")


@pytest.mark.asyncio
async def test_same_exploration_can_start_multiple_runs_for_same_research_run(
    service_factory,
):
    service, session, exploration_id, research_run_id = service_factory()
    company_ids = [uuid4(), uuid4()]
    session.store["eligible_company_ids"] = set(company_ids)

    first = await service.start_run(exploration_id, research_run_id, [company_ids[0]])
    second = await service.start_run(exploration_id, research_run_id, [company_ids[1]])

    assert first.run.id != second.run.id
    assert first.run.research_run_id == second.run.research_run_id == research_run_id
    assert first.run.exploration_id == second.run.exploration_id == exploration_id
    assert len(session.store["runs"]) == 2
    assert len(session.store["links"]) == 2


@pytest.mark.asyncio
async def test_start_run_missing_exploration_returns_none(service_factory):
    service, session, _, research_run_id = service_factory()
    missing_id = uuid4()
    assert await service.start_run(missing_id, research_run_id, [uuid4()]) is None
    assert session.store["runs"] == {}


@pytest.mark.asyncio
async def test_start_run_requires_existing_completed_research_run(service_factory):
    service, session, exploration_id, _ = service_factory()
    with pytest.raises(ExplorationStartNotFoundError):
        await service.start_run(exploration_id, uuid4(), [uuid4()])

    research_run_id = session.store["research_run_id"]
    session.store["research_status"] = "RUNNING"
    with pytest.raises(ExplorationStartConflictError):
        await service.start_run(exploration_id, research_run_id, [uuid4()])
    assert session.store["runs"] == {}


@pytest.mark.asyncio
async def test_invalid_membership_rolls_back_run_and_company_links(service_factory):
    service, session, exploration_id, research_run_id = service_factory()
    allowed, outside = uuid4(), uuid4()
    session.store["eligible_company_ids"] = {allowed}

    with pytest.raises(ExplorationCompanySelectionError):
        await service.start_run(exploration_id, research_run_id, [allowed, outside])

    assert session.store["runs"] == {}
    assert session.store["links"] == []


@pytest.mark.asyncio
async def test_company_persistence_failure_rolls_back_run_and_links(service_factory):
    service, session, exploration_id, research_run_id = service_factory()
    company_ids = [uuid4(), uuid4()]
    session.store["eligible_company_ids"] = set(company_ids)
    session.fail_company_flush = True

    with pytest.raises(RuntimeError, match="company insert failed"):
        await service.start_run(exploration_id, research_run_id, company_ids)

    assert session.store["runs"] == {}
    assert session.store["links"] == []
