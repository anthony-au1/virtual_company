"""Worker-side execution claims, fenced updates, and heartbeat supervision."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable
from contextlib import suppress
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from virtual_company.repositories.workflow_execution import (
    WorkflowExecutionClaimOutcome,
    WorkflowExecutionClaimResult,
    WorkflowExecutionRepository,
)
from virtual_company.task_queue.dispatcher import WorkflowType

logger = logging.getLogger(__name__)


class ExecutionOwnershipLostError(RuntimeError):
    """The worker no longer owns the database execution claim."""


class HeartbeatUnavailableError(RuntimeError):
    """The worker could not persist heartbeats within its failure budget."""


def _safe_event(name: str, **fields: str) -> None:
    try:
        from virtual_company.observability import get_observability

        get_observability().event(name, **fields)
    except Exception as error:  # noqa: BLE001 - telemetry cannot affect lifecycle
        logger.warning(
            "workflow_lifecycle_observability_failed",
            extra={"context": {"event": name, "error_type": type(error).__name__}},
        )


async def claim_workflow_run(
    session_factory: async_sessionmaker[AsyncSession],
    workflow_type: WorkflowType,
    run_id: UUID,
) -> WorkflowExecutionClaimResult:
    """Claim the queued execution and business run in one transaction."""
    async with session_factory() as session, session.begin():
        result = await WorkflowExecutionRepository(session).claim(
            workflow_type.value, run_id
        )
    if result.outcome is not WorkflowExecutionClaimOutcome.CLAIMED:
        _safe_event(
            "workflow_execution_claim_skipped",
            workflow_type=workflow_type.value,
            run_id=str(run_id),
            outcome=result.outcome.value,
        )
        return result
    execution_id = result.execution_id
    if execution_id is None:
        raise RuntimeError("Claimed execution did not return an ownership token")
    _safe_event(
        "workflow_execution_claimed",
        workflow_type=workflow_type.value,
        run_id=str(run_id),
        execution_id=str(execution_id),
    )
    return result


async def heartbeat_workflow_run(
    session_factory: async_sessionmaker[AsyncSession],
    workflow_type: WorkflowType,
    run_id: UUID,
    execution_id: UUID,
) -> bool:
    """Persist one ownership-fenced heartbeat in its own short transaction."""
    async with session_factory() as session, session.begin():
        return await WorkflowExecutionRepository(session).heartbeat(execution_id)


class ExecutionHeartbeat:
    """Maintain a run heartbeat independently of graph node progress."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        workflow_type: WorkflowType,
        run_id: UUID,
        execution_id: UUID,
        interval_seconds: float,
        max_consecutive_failures: int = 3,
    ) -> None:
        self._session_factory = session_factory
        self._workflow_type = workflow_type
        self._run_id = run_id
        self._execution_id = execution_id
        self._interval_seconds = interval_seconds
        self._max_consecutive_failures = max_consecutive_failures

    async def run(self) -> None:
        """Update liveness until ownership is lost, persistence is unavailable, or cancelled."""
        consecutive_failures = 0
        while True:
            await asyncio.sleep(self._interval_seconds)
            try:
                still_owned = await heartbeat_workflow_run(
                    self._session_factory,
                    self._workflow_type,
                    self._run_id,
                    self._execution_id,
                )
            except asyncio.CancelledError:
                raise
            except Exception as error:
                consecutive_failures += 1
                logger.warning(
                    "workflow_heartbeat_update_failed",
                    extra={
                        "context": {
                            "workflow_type": self._workflow_type.value,
                            "run_id": str(self._run_id),
                            "execution_id": str(self._execution_id),
                            "error_type": type(error).__name__,
                            "consecutive_failures": consecutive_failures,
                        }
                    },
                )
                if consecutive_failures >= self._max_consecutive_failures:
                    raise HeartbeatUnavailableError(
                        "Execution heartbeat persistence unavailable"
                    ) from error
                continue

            consecutive_failures = 0
            if not still_owned:
                try:
                    from virtual_company.observability import get_observability

                    get_observability().event(
                        "workflow_heartbeat_ownership_lost",
                        workflow_type=self._workflow_type.value,
                        run_id=str(self._run_id),
                        execution_id=str(self._execution_id),
                    )
                except Exception as error:  # noqa: BLE001 - telemetry is best effort
                    logger.warning(
                        "workflow_heartbeat_observability_failed",
                        extra={"context": {"error_type": type(error).__name__}},
                    )
                raise ExecutionOwnershipLostError(
                    "Execution ownership is no longer valid"
                )


async def run_with_heartbeat[ResultT](
    heartbeat: ExecutionHeartbeat,
    operation: Awaitable[ResultT],
) -> ResultT:
    """Supervise an operation, cancelling it if heartbeat ownership is lost."""
    heartbeat_task = asyncio.create_task(heartbeat.run())
    operation_task = asyncio.ensure_future(operation)
    try:
        done, _ = await asyncio.wait(
            {heartbeat_task, operation_task}, return_when=asyncio.FIRST_COMPLETED
        )
        if operation_task in done:
            result = await operation_task
            heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat_task
            return result
        if heartbeat_task in done:
            error = heartbeat_task.exception()
            if error is None:
                raise RuntimeError("Heartbeat controller stopped unexpectedly")
            operation_task.cancel()
            with suppress(asyncio.CancelledError):
                await operation_task
            raise error
        raise RuntimeError("Heartbeat supervisor stopped unexpectedly")
    except asyncio.CancelledError:
        operation_task.cancel()
        heartbeat_task.cancel()
        await asyncio.gather(operation_task, heartbeat_task, return_exceptions=True)
        raise
    finally:
        for task in (operation_task, heartbeat_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(operation_task, heartbeat_task, return_exceptions=True)


async def transition_workflow_run(
    session_factory: async_sessionmaker[AsyncSession],
    workflow_type: WorkflowType,
    run_id: UUID,
    execution_id: UUID,
    target: str,
) -> bool:
    """Apply a terminal transition only if the execution UUID still owns the run."""
    async with session_factory() as session, session.begin():
        execution = await WorkflowExecutionRepository(session).get_by_id(execution_id)
        transitioned = False
        if execution is not None and execution.workflow_type == workflow_type.value and execution.run_id == run_id:
            transitioned = await WorkflowExecutionRepository(session).transition(
                execution_id, target
            )
    if transitioned:
        _safe_event(
            "workflow_execution_terminal",
            workflow_type=workflow_type.value,
            run_id=str(run_id),
            execution_id=str(execution_id),
            status=target,
        )
    return transitioned
