"""Unit tests for Taskiq Exploration adapter lifecycle coordination."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest

from virtual_company.repositories.workflow_execution import (
    WorkflowExecutionClaimOutcome,
    WorkflowExecutionClaimResult,
)
from virtual_company.task_queue.adapters.exploration import ExplorationWorkflowAdapter


@pytest.mark.asyncio
async def test_adapter_runs_graph_only_after_successful_claim(monkeypatch) -> None:
    run_id, execution_id = uuid4(), uuid4()
    session_factory = object()
    events: list[object] = []
    result = SimpleNamespace(status="COMPLETED")

    async def claim(*_args):
        events.append("claimed")
        return WorkflowExecutionClaimResult(
            WorkflowExecutionClaimOutcome.CLAIMED, execution_id
        )

    async def supervise(_heartbeat, operation):
        return await operation

    async def transition(_sessions, _type, _run_id, _execution_id, target):
        events.append(("terminal", target))
        return True

    class Workflow:
        async def run(self, requested_run_id, requested_execution_id, *, task_id):
            events.append(("run", requested_run_id, requested_execution_id, task_id))
            return result

    monkeypatch.setattr(
        "virtual_company.task_queue.adapters.exploration.claim_workflow_run", claim
    )
    monkeypatch.setattr(
        "virtual_company.task_queue.adapters.exploration.run_with_heartbeat", supervise
    )
    monkeypatch.setattr(
        "virtual_company.task_queue.adapters.exploration.transition_workflow_run",
        transition,
    )
    monkeypatch.setattr(
        "virtual_company.workflows.exploration.graph.create_configured_exploration_workflow",
        lambda **_kwargs: Workflow(),
        raising=False,
    )

    await ExplorationWorkflowAdapter().execute(
        run_id, session_factory=session_factory, task_id="task-a"
    )

    assert events == [
        "claimed",
        ("run", run_id, execution_id, "task-a"),
        ("terminal", "COMPLETED"),
    ]


@pytest.mark.asyncio
async def test_adapter_returns_without_graph_when_claim_is_not_won(monkeypatch) -> None:
    async def claim(*_args):
        return WorkflowExecutionClaimResult(
            WorkflowExecutionClaimOutcome.NOT_CLAIMABLE
        )

    monkeypatch.setattr(
        "virtual_company.task_queue.adapters.exploration.claim_workflow_run", claim
    )

    def unexpected_factory(**_kwargs):
        pytest.fail("duplicate delivery must not create or invoke the graph")

    monkeypatch.setattr(
        "virtual_company.workflows.exploration.graph.create_configured_exploration_workflow",
        unexpected_factory,
        raising=False,
    )
    await ExplorationWorkflowAdapter().execute(
        uuid4(), session_factory=object(), task_id="duplicate"
    )


@pytest.mark.asyncio
async def test_adapter_marks_fatal_graph_error_failed_and_reraises(monkeypatch) -> None:
    run_id, execution_id = uuid4(), uuid4()
    transitions: list[str] = []

    async def claim(*_args):
        return WorkflowExecutionClaimResult(
            WorkflowExecutionClaimOutcome.CLAIMED, execution_id
        )

    async def supervise(_heartbeat, operation):
        return await operation

    async def transition(_sessions, _type, _run_id, _execution_id, target):
        transitions.append(target)
        return True

    class Workflow:
        async def run(self, *_args, **_kwargs):
            raise ValueError("safe class only")

    monkeypatch.setattr(
        "virtual_company.task_queue.adapters.exploration.claim_workflow_run", claim
    )
    monkeypatch.setattr(
        "virtual_company.task_queue.adapters.exploration.run_with_heartbeat", supervise
    )
    monkeypatch.setattr(
        "virtual_company.task_queue.adapters.exploration.transition_workflow_run",
        transition,
    )
    monkeypatch.setattr(
        "virtual_company.workflows.exploration.graph.create_configured_exploration_workflow",
        lambda **_kwargs: Workflow(),
        raising=False,
    )

    with pytest.raises(ValueError):
        await ExplorationWorkflowAdapter().execute(
            run_id, session_factory=object(), task_id=None
        )
    assert transitions == ["FAILED"]


@pytest.mark.asyncio
async def test_adapter_propagates_cancellation_and_attempts_cancel_transition(
    monkeypatch,
) -> None:
    run_id, execution_id = uuid4(), uuid4()
    transitions: list[str] = []

    async def claim(*_args):
        return WorkflowExecutionClaimResult(
            WorkflowExecutionClaimOutcome.CLAIMED, execution_id
        )

    async def supervise(_heartbeat, operation):
        operation.close()
        raise asyncio.CancelledError

    async def transition(_sessions, _type, _run_id, _execution_id, target):
        transitions.append(target)
        return True

    class Workflow:
        async def run(self, *_args, **_kwargs):
            await asyncio.Future()

    monkeypatch.setattr(
        "virtual_company.task_queue.adapters.exploration.claim_workflow_run", claim
    )
    monkeypatch.setattr(
        "virtual_company.task_queue.adapters.exploration.run_with_heartbeat", supervise
    )
    monkeypatch.setattr(
        "virtual_company.task_queue.adapters.exploration.transition_workflow_run",
        transition,
    )
    monkeypatch.setattr(
        "virtual_company.workflows.exploration.graph.create_configured_exploration_workflow",
        lambda **_kwargs: Workflow(),
        raising=False,
    )

    with pytest.raises(asyncio.CancelledError):
        await ExplorationWorkflowAdapter().execute(
            run_id, session_factory=object(), task_id=None
        )
    assert transitions == ["CANCELLED"]
