"""Research adapter passes worker correlation through to the graph."""

from __future__ import annotations

from uuid import uuid4

import httpx
import pytest

from virtual_company.repositories.workflow_execution import (
    WorkflowExecutionClaimOutcome,
    WorkflowExecutionClaimResult,
)
from virtual_company.task_queue.adapters.research import ResearchWorkflowAdapter
from virtual_company.task_queue.workflow_types import WorkflowType


@pytest.mark.asyncio
async def test_adapter_passes_task_and_execution_ids_to_research_graph(monkeypatch):
    run_id, campaign_id, execution_id = uuid4(), uuid4(), uuid4()
    calls: list[tuple[object, ...]] = []

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def scalar(self, _query):
            return campaign_id

    class Workflow:
        async def run(self, requested_campaign_id, **kwargs):
            calls.append((requested_campaign_id, kwargs))

    async def claim(*_args):
        return WorkflowExecutionClaimResult(
            WorkflowExecutionClaimOutcome.CLAIMED, execution_id
        )

    async def supervise(_heartbeat, operation):
        return await operation

    async def transition(*_args, **_kwargs):
        return True

    monkeypatch.setattr(
        "virtual_company.task_queue.adapters.research.claim_workflow_run", claim
    )
    monkeypatch.setattr(
        "virtual_company.task_queue.adapters.research.run_with_heartbeat", supervise
    )
    monkeypatch.setattr(
        "virtual_company.task_queue.adapters.research.transition_workflow_run",
        transition,
    )
    monkeypatch.setattr(
        "virtual_company.workflows.research.graph.create_configured_research_workflow",
        lambda **_kwargs: Workflow(),
        raising=False,
    )

    await ResearchWorkflowAdapter().execute(
        run_id, session_factory=Session, task_id="research-task-1"
    )

    assert calls == [
        (
            campaign_id,
            {
                "research_run_id": run_id,
                "execution_id": execution_id,
                "task_id": "research-task-1",
            },
        )
    ]


@pytest.mark.asyncio
async def test_adapter_marks_run_failed_when_provider_timeout_propagates(monkeypatch):
    run_id, campaign_id, execution_id = uuid4(), uuid4(), uuid4()
    transitions: list[tuple[tuple[object, ...], dict[str, object]]] = []
    timeout_error = httpx.ReadTimeout("timed out")

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def scalar(self, _query):
            return campaign_id

    class Workflow:
        async def run(self, *_args, **_kwargs):
            raise timeout_error

    async def claim(*_args):
        return WorkflowExecutionClaimResult(
            WorkflowExecutionClaimOutcome.CLAIMED, execution_id
        )

    async def supervise(_heartbeat, operation):
        return await operation

    async def transition(*args, **kwargs):
        transitions.append((args, kwargs))
        return True

    monkeypatch.setattr(
        "virtual_company.task_queue.adapters.research.claim_workflow_run", claim
    )
    monkeypatch.setattr(
        "virtual_company.task_queue.adapters.research.run_with_heartbeat", supervise
    )
    monkeypatch.setattr(
        "virtual_company.task_queue.adapters.research.transition_workflow_run",
        transition,
    )
    monkeypatch.setattr(
        "virtual_company.workflows.research.graph.create_configured_research_workflow",
        lambda **_kwargs: Workflow(),
        raising=False,
    )

    with pytest.raises(httpx.ReadTimeout) as raised:
        await ResearchWorkflowAdapter().execute(
            run_id, session_factory=Session, task_id="research-timeout"
        )

    assert raised.value is timeout_error
    assert len(transitions) == 1
    args, kwargs = transitions[0]
    assert args == (Session, WorkflowType.RESEARCH, run_id, execution_id, "FAILED")
    assert kwargs["error"] == "Research workflow failed: ReadTimeout"
