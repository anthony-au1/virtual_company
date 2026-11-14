"""Workflow correlation context remains scoped and isolated."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from uuid import uuid4

import pytest

from virtual_company.observability.runtime import Observability
from virtual_company.workflows.exploration.graph import ExplorationWorkflow
from virtual_company.workflows.research.graph import ResearchWorkflow


@pytest.mark.asyncio
async def test_research_graph_scopes_taskiq_context_and_restores_outer_context(
    monkeypatch, caplog: pytest.LogCaptureFixture
) -> None:
    observability = Observability()
    campaign_id, run_id, execution_id = uuid4(), uuid4(), uuid4()
    workflow = object.__new__(ResearchWorkflow)
    monkeypatch.setattr(
        "virtual_company.workflows.research.graph.get_observability",
        lambda: observability,
    )

    async def capture_context(*_args, observability, **_kwargs):
        observability.event("research_context_probe")
        return SimpleNamespace(status="COMPLETED")

    monkeypatch.setattr(workflow, "_run_in_context", capture_context)
    observability.clear_context()
    observability.bind(unrelated_id="outer-value")

    with caplog.at_level(logging.INFO, logger="virtual_company"):
        await workflow.run(
            campaign_id,
            research_run_id=run_id,
            execution_id=execution_id,
            task_id="task-1",
        )
        first = caplog.records[-1].context
        await workflow.run(
            campaign_id,
            research_run_id=uuid4(),
            execution_id=uuid4(),
            task_id="task-2",
        )
        second = caplog.records[-1].context
        observability.event("outer_context_probe")

    assert first == {
        "workflow_type": "research",
        "run_id": str(run_id),
        "execution_id": str(execution_id),
        "task_id": "task-1",
        "campaign_id": str(campaign_id),
        "research_run_id": str(run_id),
        "workflow": "company_research",
    }
    assert second["task_id"] == "task-2"
    assert second["run_id"] != first["run_id"]
    assert "unrelated_id" not in second
    assert caplog.records[-1].context == {"unrelated_id": "outer-value"}
    observability.clear_context()


@pytest.mark.asyncio
async def test_exploration_graph_keeps_existing_correlation_and_scopes_context(
    caplog: pytest.LogCaptureFixture,
) -> None:
    observability = Observability()
    workflow = object.__new__(ExplorationWorkflow)
    workflow._observability = observability
    run_id, execution_id = uuid4(), uuid4()

    async def capture_context(*_args):
        observability.event("exploration_context_probe")
        return SimpleNamespace(status="COMPLETED")

    workflow._run_in_context = capture_context
    observability.clear_context()
    observability.bind(stale_run_id="previous")

    with caplog.at_level(logging.INFO, logger="virtual_company"):
        await workflow.run(run_id, execution_id, task_id="exploration-task")
        event_context = caplog.records[-1].context
        observability.event("after_exploration_probe")

    assert event_context == {
        "exploration_run_id": str(run_id),
        "workflow": "exploration",
        "workflow_type": "exploration",
        "workflow_execution_id": str(execution_id),
        "task_id": "exploration-task",
    }
    assert caplog.records[-1].context == {"stale_run_id": "previous"}
    observability.clear_context()
