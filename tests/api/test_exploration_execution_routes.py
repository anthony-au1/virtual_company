"""Execution, status, and Exploration result route tests."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import ResponseError
from redis.exceptions import TimeoutError as RedisTimeoutError
from taskiq import SendTaskError

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


def test_execute_commits_claim_before_taskiq_publish(monkeypatch):
    exploration_id, run_id = uuid4(), uuid4()
    events: list[str] = []

    class ServiceStub:
        async def claim_run_for_execution(self, requested_exploration_id, requested_run_id):
            assert requested_exploration_id == exploration_id
            assert requested_run_id == run_id
            events.append("committed")
            return ExplorationRunClaimResult(ExplorationRunClaimOutcome.CLAIMED)

    async def publish(workflow_type, requested_run_id):
        assert events == ["committed"]
        assert workflow_type == "exploration"
        assert requested_run_id == str(run_id)
        events.append("published")
        return SimpleNamespace(task_id="task-123")

    monkeypatch.setattr(explorations.execute_workflow, "kiq", publish)
    app.dependency_overrides[get_exploration_service] = ServiceStub

    response = TestClient(app).post(
        f"/api/v1/explorations/{exploration_id}/runs/{run_id}/execute"
    )

    assert response.status_code == 202
    assert response.json() == {"exploration_run_id": str(run_id), "status": "QUEUED"}
    assert events == ["committed", "published"]


@pytest.mark.asyncio
async def test_execute_endpoint_publishes_without_running_workflow(monkeypatch):
    exploration_id, run_id = uuid4(), uuid4()
    events: list[str] = []

    class ServiceStub:
        async def claim_run_for_execution(self, *_args):
            events.append("claim_committed")
            return ExplorationRunClaimResult(ExplorationRunClaimOutcome.CLAIMED)

    async def publish(*args):
        events.append(("publish", *args))
        return SimpleNamespace(task_id="task-456")

    monkeypatch.setattr(explorations.execute_workflow, "kiq", publish)
    response = await explorations.execute_run(exploration_id, run_id, ServiceStub())

    assert response.status == "QUEUED"
    assert events == ["claim_committed", ("publish", "exploration", str(run_id))]


@pytest.mark.asyncio
async def test_concurrent_execute_requests_publish_only_successful_claim(monkeypatch):
    exploration_id, run_id = uuid4(), uuid4()
    claim_lock = asyncio.Lock()
    already_claimed = False
    published = 0

    class ServiceStub:
        async def claim_run_for_execution(self, *_args):
            nonlocal already_claimed
            async with claim_lock:
                if already_claimed:
                    return ExplorationRunClaimResult(ExplorationRunClaimOutcome.NOT_READY)
                already_claimed = True
                return ExplorationRunClaimResult(ExplorationRunClaimOutcome.CLAIMED)

    async def publish(*_args):
        nonlocal published
        published += 1
        return SimpleNamespace(task_id="task")

    monkeypatch.setattr(explorations.execute_workflow, "kiq", publish)
    outcomes = await asyncio.gather(
        explorations.execute_run(exploration_id, run_id, ServiceStub()),
        explorations.execute_run(exploration_id, run_id, ServiceStub()),
        return_exceptions=True,
    )
    assert sum(isinstance(item, HTTPException) and item.status_code == 409 for item in outcomes) == 1
    assert sum(getattr(item, "status", None) == "QUEUED" for item in outcomes) == 1
    assert published == 1


@pytest.mark.parametrize(
    "outcome,status_code",
    [(ExplorationRunClaimOutcome.NOT_FOUND, 404), (ExplorationRunClaimOutcome.NOT_READY, 409)],
)
def test_execute_rejects_failed_claim_without_publishing(outcome, status_code, monkeypatch):
    async def unexpected_publish(*_args):
        raise AssertionError("a rejected claim must not publish")

    class ServiceStub:
        async def claim_run_for_execution(self, *_args):
            return ExplorationRunClaimResult(outcome)

    monkeypatch.setattr(explorations.execute_workflow, "kiq", unexpected_publish)
    app.dependency_overrides[get_exploration_service] = ServiceStub
    response = TestClient(app).post(
        f"/api/v1/explorations/{uuid4()}/runs/{uuid4()}/execute"
    )
    assert response.status_code == status_code


def test_definitive_redis_rejection_fails_queued_records(monkeypatch):
    run_id = uuid4()
    compensated: list[UUID] = []

    class ServiceStub:
        async def claim_run_for_execution(self, *_args):
            return ExplorationRunClaimResult(ExplorationRunClaimOutcome.CLAIMED)

        async def fail_queued_execution(self, requested_run_id):
            compensated.append(requested_run_id)
            return True

    async def publish(*_args):
        try:
            raise ResponseError("NOGROUP")
        except ResponseError as cause:
            raise SendTaskError from cause

    monkeypatch.setattr(explorations.execute_workflow, "kiq", publish)
    app.dependency_overrides[get_exploration_service] = ServiceStub
    response = TestClient(app).post(
        f"/api/v1/explorations/{uuid4()}/runs/{run_id}/execute"
    )
    assert response.status_code == 503
    assert compensated == [run_id]


@pytest.mark.parametrize(
    "failure",
    [RedisConnectionError("connection lost after write"), RedisTimeoutError("publish timed out")],
)
@pytest.mark.asyncio
async def test_ambiguous_redis_publish_does_not_compensate_or_retry(monkeypatch, failure):
    run_id = uuid4()
    compensated: list[UUID] = []
    publish_calls = 0

    class ServiceStub:
        async def claim_run_for_execution(self, *_args):
            return ExplorationRunClaimResult(ExplorationRunClaimOutcome.CLAIMED)

        async def fail_queued_execution(self, requested_run_id):
            compensated.append(requested_run_id)

    async def publish(*_args):
        nonlocal publish_calls
        publish_calls += 1
        try:
            raise failure
        except (RedisConnectionError, RedisTimeoutError) as cause:
            raise SendTaskError from cause

    monkeypatch.setattr(explorations.execute_workflow, "kiq", publish)
    with pytest.raises(HTTPException) as error:
        await explorations.execute_run(uuid4(), run_id, ServiceStub())
    assert error.value.status_code == 503
    assert not compensated
    assert publish_calls == 1


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
