"""Tests for identifier-only shared workflow dispatch."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from virtual_company.observability.runtime import Observability
from virtual_company.task_queue.dispatcher import (
    InvalidWorkflowDispatchError,
    WorkflowType,
    dispatch_workflow,
)
from virtual_company.task_queue.tasks import execute_workflow


@pytest.mark.asyncio
async def test_dispatcher_routes_valid_identifier_to_explicit_adapter() -> None:
    run_id = uuid4()
    adapter = AsyncMock()

    await dispatch_workflow(
        WorkflowType.EXPLORATION.value,
        str(run_id),
        adapters={WorkflowType.EXPLORATION: adapter},
    )

    adapter.execute.assert_awaited_once_with(
        run_id, session_factory=None, task_id=None
    )


@pytest.mark.parametrize(
    ("workflow_type", "run_id"),
    [("unknown", str(uuid4())), ("research", "not-a-uuid")],
)
@pytest.mark.asyncio
async def test_invalid_dispatch_does_not_invoke_adapters(workflow_type, run_id) -> None:
    adapter = AsyncMock()

    with pytest.raises(InvalidWorkflowDispatchError):
        await dispatch_workflow(
            workflow_type,
            run_id,
            adapters={WorkflowType.RESEARCH: adapter},
        )

    adapter.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_business_adapter_failure_propagates() -> None:
    adapter = AsyncMock()
    adapter.execute.side_effect = RuntimeError("business failure")

    with pytest.raises(RuntimeError, match="business failure"):
        await dispatch_workflow(
            WorkflowType.RESEARCH.value,
            str(uuid4()),
            adapters={WorkflowType.RESEARCH: adapter},
        )


@pytest.mark.asyncio
async def test_dispatcher_context_reaches_adapter_and_is_cleared_afterward(
    monkeypatch, caplog: pytest.LogCaptureFixture
) -> None:
    run_id = uuid4()
    observability = Observability()
    monkeypatch.setattr(
        "virtual_company.task_queue.dispatcher.get_observability",
        lambda: observability,
    )

    class Adapter:
        async def execute(self, *_args, **_kwargs):
            observability.event("adapter_context_probe")

    with caplog.at_level(logging.INFO, logger="virtual_company"):
        await dispatch_workflow(
            WorkflowType.RESEARCH.value,
            str(run_id),
            adapters={WorkflowType.RESEARCH: Adapter()},
            task_id="task-dispatch-1",
        )
        adapter_event = next(
            record for record in caplog.records
            if record.getMessage() == "adapter_context_probe"
        )
        observability.event("after_dispatch_probe")

    assert adapter_event.context == {
        "workflow_type": "research",
        "run_id": str(run_id),
        "task_id": "task-dispatch-1",
    }
    assert caplog.records[-1].context == {}


@pytest.mark.asyncio
async def test_research_adapter_rejects_missing_worker_session_factory() -> None:
    with pytest.raises(RuntimeError, match="session factory"):
        await dispatch_workflow(WorkflowType.RESEARCH.value, str(uuid4()))


@pytest.mark.asyncio
async def test_exploration_adapter_rejects_missing_worker_session_factory() -> None:
    with pytest.raises(RuntimeError, match="session factory"):
        await dispatch_workflow(WorkflowType.EXPLORATION.value, str(uuid4()))


def test_shared_task_is_registered_without_retry() -> None:
    assert execute_workflow.labels["ack_type"] == "when_executed"
    assert "retry_on_error" not in execute_workflow.labels

