"""Taskiq adapter for the existing Exploration LangGraph workflow."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from virtual_company.config import get_settings
from virtual_company.domain.exploration.run import ExplorationRunStatus
from virtual_company.observability import get_observability
from virtual_company.repositories.workflow_execution import (
    ExecutionOwnershipLostError,
    WorkflowExecutionClaimOutcome,
)
from virtual_company.task_queue.lifecycle import (
    ExecutionHeartbeat,
    claim_workflow_run,
    run_with_heartbeat,
    transition_workflow_run,
)
from virtual_company.task_queue.workflow_types import WorkflowType

logger = logging.getLogger(__name__)


class ExplorationWorkflowAdapter:
    """Claim once, run the business graph, then persist one guarded outcome."""

    async def execute(
        self,
        run_id: UUID,
        *,
        session_factory: async_sessionmaker[AsyncSession] | None,
        task_id: str | None,
    ) -> None:
        if session_factory is None:
            raise RuntimeError("Worker database session factory is unavailable")

        claim = await claim_workflow_run(
            session_factory, WorkflowType.EXPLORATION, run_id
        )
        if claim.outcome is not WorkflowExecutionClaimOutcome.CLAIMED:
            return
        execution_id = claim.execution_id
        if execution_id is None:
            raise RuntimeError("Claimed execution is missing its ownership token")

        observability = get_observability()
        try:
            observability.bind(
                workflow_type=WorkflowType.EXPLORATION.value,
                run_id=str(run_id),
                workflow_execution_id=str(execution_id),
                task_id=task_id,
            )
            observability.event("exploration_taskiq_workflow_started")
        except Exception as error:  # noqa: BLE001 - telemetry is best effort
            logger.warning(
                "exploration_worker_observability_failed",
                extra={"context": {"error_type": type(error).__name__}},
            )

        try:
            # Import after Taskiq worker startup so its DB engine is process-owned.
            from virtual_company.workflows.exploration.graph import (
                create_configured_exploration_workflow,
            )

            workflow = create_configured_exploration_workflow(
                database_session_factory=session_factory,
                observability=observability,
            )
            settings = get_settings()
            result = await run_with_heartbeat(
                ExecutionHeartbeat(
                    session_factory=session_factory,
                    workflow_type=WorkflowType.EXPLORATION,
                    run_id=run_id,
                    execution_id=execution_id,
                    interval_seconds=settings.taskiq_heartbeat_interval_seconds,
                ),
                workflow.run(run_id, execution_id, task_id=task_id),
            )
            target = ExplorationRunStatus(result.status).value
            transitioned = await transition_workflow_run(
                session_factory,
                WorkflowType.EXPLORATION,
                run_id,
                execution_id,
                target,
            )
            if not transitioned:
                raise ExecutionOwnershipLostError(
                    "Execution ownership was lost before terminal transition"
                )
            observability.event(
                "exploration_taskiq_workflow_completed", final_status=target
            )
        except asyncio.CancelledError:
            await self._transition_after_cancellation(
                session_factory, run_id, execution_id
            )
            try:
                observability.event(
                    "exploration_taskiq_workflow_cancelled",
                    final_status=ExplorationRunStatus.CANCELLED.value,
                )
            except Exception as error:  # noqa: BLE001 - telemetry is best effort
                logger.warning(
                    "exploration_worker_observability_failed",
                    extra={"context": {"error_type": type(error).__name__}},
                )
            raise
        except Exception as error:
            await self._fail_if_owned(session_factory, run_id, execution_id)
            try:
                observability.event(
                    "exploration_taskiq_workflow_failed",
                    error_type=type(error).__name__,
                )
            except Exception as telemetry_error:  # noqa: BLE001 - telemetry is best effort
                logger.warning(
                    "exploration_worker_observability_failed",
                    extra={"context": {"error_type": type(telemetry_error).__name__}},
                )
            raise

    @staticmethod
    async def _transition_after_cancellation(
        session_factory: async_sessionmaker[AsyncSession],
        run_id: UUID,
        execution_id: UUID,
    ) -> None:
        transition_task = asyncio.create_task(
            transition_workflow_run(
                session_factory,
                WorkflowType.EXPLORATION,
                run_id,
                execution_id,
                ExplorationRunStatus.CANCELLED.value,
            )
        )
        try:
            await asyncio.shield(transition_task)
        except asyncio.CancelledError:
            with suppress(asyncio.CancelledError, Exception):
                await transition_task
            raise
        except Exception as error:  # noqa: BLE001 - cancellation stays primary
            logger.warning(
                "exploration_cancel_transition_failed",
                extra={"context": {"error_type": type(error).__name__}},
            )

    @staticmethod
    async def _fail_if_owned(
        session_factory: async_sessionmaker[AsyncSession],
        run_id: UUID,
        execution_id: UUID,
    ) -> None:
        try:
            await transition_workflow_run(
                session_factory,
                WorkflowType.EXPLORATION,
                run_id,
                execution_id,
                ExplorationRunStatus.FAILED.value,
            )
        except Exception as error:  # noqa: BLE001 - preserve the workflow exception
            logger.warning(
                "exploration_failure_transition_failed",
                extra={"context": {"error_type": type(error).__name__}},
            )
