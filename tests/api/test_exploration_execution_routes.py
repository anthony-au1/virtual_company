"""Execution, status, and Exploration result route tests."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import BackgroundTasks, HTTPException
from fastapi.testclient import TestClient

from virtual_company.api import explorations
from virtual_company.api.dependencies import get_exploration_service
from virtual_company.main import app
from virtual_company.repositories.exploration_run import (
    ExplorationRunClaimOutcome,
    ExplorationRunClaimResult,
)


@pytest.fixture(autouse=True)
def clear_overrides():
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


def test_execute_commits_claim_before_scheduling(monkeypatch):
    exploration_id, run_id = uuid4(), uuid4()
    events: list[str] = []

    class ServiceStub:
        async def claim_run_for_execution(
            self, requested_exploration_id, requested_run_id
        ):
            assert requested_exploration_id == exploration_id
            assert requested_run_id == run_id
            events.append("committed")
            return ExplorationRunClaimResult(ExplorationRunClaimOutcome.CLAIMED)

    async def scheduled(requested_run_id):
        assert requested_run_id == run_id
        assert events == ["committed"]
        events.append("executed")

    monkeypatch.setattr(explorations, "execute_exploration_run", scheduled)
    app.dependency_overrides[get_exploration_service] = ServiceStub

    response = TestClient(app).post(
        f"/api/v1/explorations/{exploration_id}/runs/{run_id}/execute"
    )

    assert response.status_code == 202
    assert response.json() == {
        "exploration_run_id": str(run_id),
        "status": "QUEUED",
    }
    assert events == ["committed", "executed"]


@pytest.mark.asyncio
async def test_execute_endpoint_only_schedules_background_callable():
    exploration_id, run_id = uuid4(), uuid4()
    events: list[str] = []

    class ServiceStub:
        async def claim_run_for_execution(self, *_args):
            events.append("claim_committed")
            return ExplorationRunClaimResult(ExplorationRunClaimOutcome.CLAIMED)

    tasks = BackgroundTasks()
    response = await explorations.execute_run(
        exploration_id, run_id, tasks, ServiceStub()
    )

    assert response.status == "QUEUED"
    assert events == ["claim_committed"]
    assert len(tasks.tasks) == 1
    assert tasks.tasks[0].args == (run_id,)
    assert tasks.tasks[0].func is explorations.execute_exploration_run


@pytest.mark.asyncio
async def test_concurrent_execute_requests_schedule_only_the_successful_claim():
    exploration_id, run_id = uuid4(), uuid4()
    claim_lock = asyncio.Lock()
    already_claimed = False

    class ServiceStub:
        async def claim_run_for_execution(self, *_args):
            nonlocal already_claimed
            async with claim_lock:
                if already_claimed:
                    return ExplorationRunClaimResult(
                        ExplorationRunClaimOutcome.NOT_READY
                    )
                already_claimed = True
                return ExplorationRunClaimResult(ExplorationRunClaimOutcome.CLAIMED)

    tasks = [BackgroundTasks(), BackgroundTasks()]
    outcomes = await asyncio.gather(
        *(
            explorations.execute_run(
                exploration_id, run_id, background_tasks, ServiceStub()
            )
            for background_tasks in tasks
        ),
        return_exceptions=True,
    )

    assert (
        sum(
            isinstance(item, HTTPException) and item.status_code == 409
            for item in outcomes
        )
        == 1
    )
    assert sum(getattr(item, "status", None) == "QUEUED" for item in outcomes) == 1
    assert sum(len(background_tasks.tasks) for background_tasks in tasks) == 1


@pytest.mark.parametrize(
    "outcome,status_code",
    [
        (ExplorationRunClaimOutcome.NOT_FOUND, 404),
        (ExplorationRunClaimOutcome.NOT_READY, 409),
    ],
)
def test_execute_rejects_failed_claim_without_scheduling(
    outcome, status_code, monkeypatch
):
    async def unexpected_task(_run_id):
        raise AssertionError("a failed claim must not schedule execution")

    class ServiceStub:
        async def claim_run_for_execution(self, *_args):
            return ExplorationRunClaimResult(outcome)

    monkeypatch.setattr(explorations, "execute_exploration_run", unexpected_task)
    app.dependency_overrides[get_exploration_service] = ServiceStub

    response = TestClient(app).post(
        f"/api/v1/explorations/{uuid4()}/runs/{uuid4()}/execute"
    )

    assert response.status_code == status_code


def test_execute_returns_generic_500_and_guardedly_fails_after_schedule_error(
    monkeypatch,
):
    run_id = uuid4()
    calls: list[object] = []

    class ServiceStub:
        async def claim_run_for_execution(self, *_args):
            return ExplorationRunClaimResult(ExplorationRunClaimOutcome.CLAIMED)

    async def schedule_failure(_run_id):
        return None

    async def fail(requested_run_id):
        calls.append(requested_run_id)

    monkeypatch.setattr(explorations, "execute_exploration_run", schedule_failure)
    monkeypatch.setattr(explorations, "fail_if_still_queued", fail)
    app.dependency_overrides[get_exploration_service] = ServiceStub
    # Starlette's BackgroundTasks.add_task does not execute until response handling;
    # simulate a synchronously detectable scheduler failure at the route boundary.
    monkeypatch.setattr(
        explorations.BackgroundTasks,
        "add_task",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("sensitive")),
    )

    response = TestClient(app).post(
        f"/api/v1/explorations/{uuid4()}/runs/{run_id}/execute"
    )

    assert response.status_code == 500
    assert response.json() == {"detail": "Execution could not be scheduled"}
    assert calls == [run_id]


def test_run_status_and_ownership():
    exploration_id, run_id = uuid4(), uuid4()
    started_at = datetime.now(UTC)

    class ServiceStub:
        async def get_run(self, requested_exploration_id, requested_run_id):
            if requested_exploration_id != exploration_id or requested_run_id != run_id:
                return None
            return SimpleNamespace(
                id=run_id,
                exploration_id=exploration_id,
                status="RUNNING",
                started_at=started_at,
                completed_at=None,
            )

    app.dependency_overrides[get_exploration_service] = ServiceStub
    client = TestClient(app)

    response = client.get(f"/api/v1/explorations/{exploration_id}/runs/{run_id}")
    missing = client.get(f"/api/v1/explorations/{uuid4()}/runs/{run_id}")

    assert response.status_code == 200
    assert response.json()["status"] == "RUNNING"
    assert response.json()["started_at"] == started_at.isoformat().replace(
        "+00:00", "Z"
    )
    assert response.json()["completed_at"] is None
    assert missing.status_code == 404


def test_company_result_routes_validate_ownership_and_serialize_records():
    exploration_id, company_link_id = uuid4(), uuid4()
    now = datetime.now(UTC)
    evidence_id, obligation_id = uuid4(), uuid4()

    class ServiceStub:
        async def list_company_evidence(
            self, requested_exploration_id, requested_link_id
        ):
            assert requested_exploration_id == exploration_id
            if requested_link_id != company_link_id:
                return None
            return [
                SimpleNamespace(
                    id=evidence_id,
                    exploration_company_id=company_link_id,
                    exploration_obligation_id=obligation_id,
                    claim="claim",
                    supporting_excerpt="excerpt",
                    source_url="https://example.test",
                    requested_url=None,
                    source_title=None,
                    created_at=now,
                )
            ]

    app.dependency_overrides[get_exploration_service] = ServiceStub
    client = TestClient(app)
    response = client.get(
        f"/api/v1/explorations/{exploration_id}/companies/{company_link_id}/evidence"
    )
    missing = client.get(
        f"/api/v1/explorations/{exploration_id}/companies/{uuid4()}/evidence"
    )

    assert response.status_code == 200
    assert response.json()[0]["supporting_excerpt"] == "excerpt"
    assert missing.status_code == 404
