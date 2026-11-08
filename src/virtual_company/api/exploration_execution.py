"""Background execution adapter for Exploration's LangGraph workflow."""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from virtual_company.db.session import session_factory
from virtual_company.domain.exploration.run import ExplorationRunStatus
from virtual_company.repositories.exploration_run import (
    ExplorationRunRepository,
    InvalidExplorationRunTransitionError,
)
from virtual_company.workflows.exploration.graph import (
    create_configured_exploration_workflow,
)

logger = logging.getLogger(__name__)


async def fail_if_still_queued(exploration_run_id: UUID) -> None:
    """Guardedly fail a run only when its workflow has not started."""
    try:
        async with session_factory() as session, session.begin():
            repository = ExplorationRunRepository(session)
            run = await repository.get_by_id(exploration_run_id)
            if run is not None and run.status == ExplorationRunStatus.QUEUED.value:
                await repository.transition(
                    exploration_run_id, ExplorationRunStatus.FAILED
                )
    except InvalidExplorationRunTransitionError:
        # The workflow may already have made a lifecycle transition.
        return
    except Exception as error:  # noqa: BLE001 - safe metadata only
        logger.error(
            "exploration_background_failure_transition_failed",
            extra={
                "context": {
                    "exploration_run_id": str(exploration_run_id),
                    "error_type": type(error).__name__,
                }
            },
        )


async def execute_exploration_run(exploration_run_id: UUID) -> None:
    """Build and invoke the configured graph without request-scoped state."""
    try:
        workflow = create_configured_exploration_workflow()
    except asyncio.CancelledError:
        logger.info(
            "exploration_background_startup_cancelled",
            extra={"context": {"exploration_run_id": str(exploration_run_id)}},
        )
        await fail_if_still_queued(exploration_run_id)
        raise
    except Exception as error:  # noqa: BLE001 - safe metadata only
        logger.error(
            "exploration_background_startup_failed",
            extra={
                "context": {
                    "exploration_run_id": str(exploration_run_id),
                    "error_type": type(error).__name__,
                }
            },
        )
        await fail_if_still_queued(exploration_run_id)
        return

    try:
        result = await workflow.run(exploration_run_id)
    except asyncio.CancelledError:
        await fail_if_still_queued(exploration_run_id)
        logger.info(
            "exploration_background_cancelled",
            extra={"context": {"exploration_run_id": str(exploration_run_id)}},
        )
        raise
    except Exception as error:  # noqa: BLE001 - never log provider error text
        await fail_if_still_queued(exploration_run_id)
        logger.error(
            "exploration_background_failed",
            extra={
                "context": {
                    "exploration_run_id": str(exploration_run_id),
                    "error_type": type(error).__name__,
                }
            },
        )
        return

    logger.info(
        "exploration_background_completed",
        extra={
            "context": {
                "exploration_run_id": str(exploration_run_id),
                "status": result.status.value,
            }
        },
    )
