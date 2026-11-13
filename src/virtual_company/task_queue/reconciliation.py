"""Periodic failure of abandoned Taskiq-managed workflow runs."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from virtual_company.config import Settings, get_settings
from virtual_company.observability import get_observability
from virtual_company.repositories.workflow_execution import WorkflowExecutionRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReconciliationResult:
    queued_failed: int
    running_failed: int


async def reconcile_taskiq_runs_once(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings | None = None,
    *,
    now: datetime | None = None,
) -> ReconciliationResult:
    """Fail abandoned shared executions and nonterminal corresponding business runs."""
    resolved_settings = settings or get_settings()
    current_time = now or datetime.now(UTC)
    queued_before = current_time - timedelta(
        seconds=resolved_settings.taskiq_queued_stale_after_seconds
    )
    running_before = current_time - timedelta(
        seconds=resolved_settings.taskiq_running_stale_after_seconds
    )
    async with session_factory() as session, session.begin():
        queued_count, running_count = await WorkflowExecutionRepository(
            session
        ).fail_stale(
            queued_before=queued_before,
            running_before=running_before,
        )
    if queued_count or running_count:
        try:
            get_observability().event(
                "taskiq_stale_runs_reconciled",
                queued_failed=str(queued_count),
                running_failed=str(running_count),
            )
        except Exception as error:  # noqa: BLE001 - telemetry cannot block service
            logger.warning(
                "taskiq_reconciliation_observability_failed",
                extra={"context": {"error_type": type(error).__name__}},
            )
    return ReconciliationResult(queued_failed=queued_count, running_failed=running_count)


async def run_reconciliation_loop(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings | None = None,
) -> None:
    """Run small independent scans until application lifespan cancellation."""
    resolved_settings = settings or get_settings()
    while True:
        await asyncio.sleep(resolved_settings.taskiq_reconciliation_interval_seconds)
        try:
            result = await reconcile_taskiq_runs_once(session_factory, resolved_settings)
            logger.info(
                "taskiq_reconciliation_completed",
                extra={
                    "context": {
                        "queued_failed": result.queued_failed,
                        "running_failed": result.running_failed,
                    }
                },
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - next periodic pass may recover
            logger.error(
                "taskiq_reconciliation_failed",
                extra={"context": {"error_type": type(error).__name__}},
            )
