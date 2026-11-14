"""Shared, explicit dispatch boundary for background workflow tasks."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from virtual_company.observability import get_observability
from virtual_company.task_queue.adapters.base import WorkflowAdapter
from virtual_company.task_queue.adapters.exploration import (
    ExplorationWorkflowAdapter,
)
from virtual_company.task_queue.adapters.research import ResearchWorkflowAdapter
from virtual_company.task_queue.workflow_types import WorkflowType

logger = logging.getLogger(__name__)


class InvalidWorkflowDispatchError(ValueError):
    """A task contains an invalid workflow type or run identifier."""


DEFAULT_ADAPTERS: dict[WorkflowType, WorkflowAdapter] = {
    WorkflowType.RESEARCH: ResearchWorkflowAdapter(),
    WorkflowType.EXPLORATION: ExplorationWorkflowAdapter(),
}


def _safe_event(name: str, **fields: str) -> None:
    try:
        get_observability().event(name, **fields)
    except Exception as error:  # noqa: BLE001 - telemetry cannot affect execution
        logger.warning(
            "workflow_dispatch_observability_failed",
            extra={"context": {"event": name, "error_type": type(error).__name__}},
        )


def _safe_clear_context() -> None:
    try:
        get_observability().clear_context()
    except Exception as error:  # noqa: BLE001 - telemetry cannot affect execution
        logger.warning(
            "workflow_dispatch_context_clear_failed",
            extra={"context": {"error_type": type(error).__name__}},
        )


async def dispatch_workflow(
    workflow_type: str,
    run_id: str,
    *,
    adapters: Mapping[WorkflowType, WorkflowAdapter] | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    task_id: str | None = None,
) -> None:
    """Validate identifiers and invoke exactly one registered adapter."""
    try:
        resolved_type = WorkflowType(workflow_type)
    except (TypeError, ValueError) as error:
        _safe_event("workflow_dispatch_rejected", error_type="invalid_workflow_type")
        raise InvalidWorkflowDispatchError("Unsupported workflow type") from error
    try:
        resolved_run_id = UUID(run_id)
    except (TypeError, ValueError, AttributeError) as error:
        _safe_event(
            "workflow_dispatch_rejected",
            workflow_type=resolved_type.value,
            error_type="invalid_run_id",
        )
        raise InvalidWorkflowDispatchError("Invalid workflow run identifier") from error

    selected_adapters = adapters if adapters is not None else DEFAULT_ADAPTERS
    adapter = selected_adapters.get(resolved_type)
    if adapter is None:
        _safe_event(
            "workflow_dispatch_rejected",
            workflow_type=resolved_type.value,
            run_id=str(resolved_run_id),
            error_type="adapter_not_registered",
        )
        raise InvalidWorkflowDispatchError("Workflow adapter is not registered")

    try:
        try:
            observability = get_observability()
            observability.clear_context()
            observability.bind(
                workflow_type=resolved_type.value,
                run_id=str(resolved_run_id),
                task_id=task_id,
            )
        except Exception as error:  # noqa: BLE001 - telemetry cannot block work
            logger.warning(
                "workflow_dispatch_context_bind_failed",
                extra={"context": {"error_type": type(error).__name__}},
            )
        _safe_event(
            "workflow_dispatch_received",
            workflow_type=resolved_type.value,
            run_id=str(resolved_run_id),
        )
        try:
            await adapter.execute(
                resolved_run_id,
                session_factory=session_factory,
                task_id=task_id,
            )
        except asyncio.CancelledError:
            _safe_event(
                "workflow_dispatch_cancelled",
                workflow_type=resolved_type.value,
                run_id=str(resolved_run_id),
            )
            raise
        except Exception as error:
            _safe_event(
                "workflow_dispatch_failed",
                workflow_type=resolved_type.value,
                run_id=str(resolved_run_id),
                error_type=type(error).__name__,
            )
            raise
        _safe_event(
            "workflow_dispatch_completed",
            workflow_type=resolved_type.value,
            run_id=str(resolved_run_id),
        )
    finally:
        _safe_clear_context()
