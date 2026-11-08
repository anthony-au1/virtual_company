"""Background adapter tests for Exploration LangGraph execution."""

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest

from virtual_company.api import exploration_execution as execution


@pytest.mark.asyncio
async def test_background_invokes_configured_workflow_with_run_id(monkeypatch):
    run_id = uuid4()
    calls: list[object] = []

    class Workflow:
        async def run(self, requested_run_id):
            calls.append(("run", requested_run_id))
            return SimpleNamespace(status=SimpleNamespace(value="COMPLETED"))

    def factory():
        calls.append("factory")
        return Workflow()

    monkeypatch.setattr(execution, "create_configured_exploration_workflow", factory)

    await execution.execute_exploration_run(run_id)

    assert calls == ["factory", ("run", run_id)]


@pytest.mark.asyncio
async def test_background_logs_fatal_error_without_provider_message(
    monkeypatch, caplog
):
    run_id = uuid4()

    class Workflow:
        async def run(self, _run_id):
            raise RuntimeError("private business content")

    monkeypatch.setattr(
        execution, "create_configured_exploration_workflow", lambda: Workflow()
    )
    transitioned: list[object] = []

    async def fail_if_queued(_run_id):
        transitioned.append(_run_id)

    monkeypatch.setattr(execution, "fail_if_still_queued", fail_if_queued)

    await execution.execute_exploration_run(run_id)

    assert "exploration_background_failed" in caplog.text
    assert "private business content" not in caplog.text
    assert transitioned == [run_id]


@pytest.mark.asyncio
async def test_background_factory_failure_fails_queued_run_safely(monkeypatch, caplog):
    run_id = uuid4()

    def fail_factory():
        raise RuntimeError("secret query text")

    monkeypatch.setattr(
        execution, "create_configured_exploration_workflow", fail_factory
    )
    transitioned: list[object] = []

    async def fail_if_queued(_run_id):
        transitioned.append(_run_id)

    monkeypatch.setattr(execution, "fail_if_still_queued", fail_if_queued)

    await execution.execute_exploration_run(run_id)

    assert "exploration_background_startup_failed" in caplog.text
    assert "secret query text" not in caplog.text
    assert transitioned == [run_id]


@pytest.mark.asyncio
async def test_background_cancellation_is_not_logged_as_success(monkeypatch, caplog):
    caplog.set_level("INFO")
    run_id = uuid4()

    class Workflow:
        async def run(self, _run_id):
            raise asyncio.CancelledError

    monkeypatch.setattr(
        execution, "create_configured_exploration_workflow", lambda: Workflow()
    )
    transitioned: list[object] = []

    async def fail_if_queued(_run_id):
        transitioned.append(_run_id)

    monkeypatch.setattr(execution, "fail_if_still_queued", fail_if_queued)

    with pytest.raises(asyncio.CancelledError):
        await execution.execute_exploration_run(run_id)

    assert "exploration_background_cancelled" in caplog.text
    assert "exploration_background_completed" not in caplog.text
    assert transitioned == [run_id]
