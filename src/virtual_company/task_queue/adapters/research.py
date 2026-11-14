"""Taskiq adapter for the existing Research LangGraph workflow."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from virtual_company.config import get_settings
from virtual_company.db.models import ResearchRun
from virtual_company.repositories.workflow_execution import (
    ExecutionOwnershipLostError,
    WorkflowExecutionClaimOutcome,
)
from virtual_company.services import CampaignService, ResearchService
from virtual_company.task_queue.lifecycle import (
    ExecutionHeartbeat,
    claim_workflow_run,
    run_with_heartbeat,
    transition_workflow_run,
)
from virtual_company.task_queue.workflow_types import WorkflowType

logger = logging.getLogger(__name__)


class ResearchWorkflowAdapter:
    """Claim a queued Research run and execute it with worker-owned resources."""

    async def execute(
        self,
        run_id: UUID,
        *,
        session_factory: async_sessionmaker[AsyncSession] | None,
        task_id: str | None,
    ) -> None:
        if session_factory is None:
            raise RuntimeError("Worker database session factory is unavailable")
        claim = await claim_workflow_run(session_factory, WorkflowType.RESEARCH, run_id)
        if claim.outcome is not WorkflowExecutionClaimOutcome.CLAIMED:
            return
        execution_id = claim.execution_id
        if execution_id is None:
            raise RuntimeError("Claimed execution is missing its ownership token")

        try:
            async with session_factory() as session:
                campaign_id = await session.scalar(
                    select(ResearchRun.campaign_id).where(ResearchRun.id == run_id)
                )
            if campaign_id is None:
                raise ValueError("Research run or campaign was not found")

            from virtual_company.workflows.research.graph import (
                create_configured_research_workflow,
            )

            async with session_factory() as graph_session:
                workflow = create_configured_research_workflow(
                    campaigns=CampaignService(graph_session),
                    research=ResearchService(graph_session),
                )
                settings = get_settings()
                await run_with_heartbeat(
                    ExecutionHeartbeat(
                        session_factory=session_factory,
                        workflow_type=WorkflowType.RESEARCH,
                        run_id=run_id,
                        execution_id=execution_id,
                        interval_seconds=settings.taskiq_heartbeat_interval_seconds,
                    ),
                    workflow.run(
                        campaign_id,
                        research_run_id=run_id,
                        execution_id=execution_id,
                    ),
                )
            transitioned = await transition_workflow_run(
                session_factory,
                WorkflowType.RESEARCH,
                run_id,
                execution_id,
                "COMPLETED",
            )
            if not transitioned:
                raise ExecutionOwnershipLostError(
                    "Execution ownership was lost before terminal transition"
                )
        except asyncio.CancelledError:
            task = asyncio.create_task(
                transition_workflow_run(
                    session_factory, WorkflowType.RESEARCH, run_id, execution_id,
                    "FAILED",
                )
            )
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                with suppress(asyncio.CancelledError, Exception):
                    await task
                raise
            raise
        except Exception as error:
            try:
                await transition_workflow_run(
                    session_factory,
                    WorkflowType.RESEARCH,
                    run_id,
                    execution_id,
                    "FAILED",
                    error=f"Research workflow failed: {type(error).__name__}",
                )
            except Exception as transition_error:  # noqa: BLE001
                logger.warning(
                    "research_failure_transition_failed",
                    extra={"context": {"error_type": type(transition_error).__name__}},
                )
            logger.error(
                "research_taskiq_workflow_failed",
                extra={"context": {"run_id": str(run_id), "task_id": task_id,
                                   "error_type": type(error).__name__}},
            )
            raise
