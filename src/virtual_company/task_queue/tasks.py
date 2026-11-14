"""Infrastructure-only tasks for validating the Taskiq worker."""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from taskiq import Context, TaskiqDepends, TaskiqEvents, TaskiqState

from virtual_company.config import get_settings
from virtual_company.observability import (
    configure_observability,
    get_observability,
    shutdown_observability,
)
from virtual_company.task_queue.broker import broker
from virtual_company.task_queue.dispatcher import dispatch_workflow

logger = logging.getLogger(__name__)
_TASKIQ_CONTEXT = TaskiqDepends()


@broker.task(ack_type="when_executed")
async def execute_workflow(
    workflow_type: str, run_id: str, context: Context = _TASKIQ_CONTEXT
) -> None:
    """Route one identifier-only message to its registered workflow adapter."""
    await dispatch_workflow(
        workflow_type,
        run_id,
        session_factory=getattr(context.state, "database_session_factory", None),
        task_id=context.message.task_id,
    )


@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def on_worker_startup(state: TaskiqState) -> None:
    """Initialize process-local application logging and telemetry."""
    configure_observability(get_settings())
    get_observability().clear_context()
    engine = create_async_engine(get_settings().database_url)
    state.database_engine = engine
    state.database_session_factory = async_sessionmaker(
        engine, expire_on_commit=False
    )
    logger.info("taskiq_worker_started", extra={"context": {"worker": "taskiq"}})


@broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
async def on_worker_shutdown(state: TaskiqState) -> None:
    """Flush application telemetry when the worker exits."""
    logger.info("taskiq_worker_stopped", extra={"context": {"worker": "taskiq"}})
    engine = getattr(state, "database_engine", None)
    try:
        if engine is not None:
            await engine.dispose()
    finally:
        shutdown_observability()


@broker.task(ack_type="when_executed")
async def infrastructure_probe(
    identifier: str, sleep_seconds: float = 0
) -> dict[str, str]:
    """Emit safe lifecycle events and return a small serializable result."""
    if not identifier or len(identifier) > 100:
        raise ValueError("identifier must contain 1 to 100 characters")
    if not 0 <= sleep_seconds <= 300:
        raise ValueError("sleep_seconds must be between 0 and 300")

    observability = get_observability()
    observability.clear_context()
    observability.bind(task="infrastructure_probe", probe_id=identifier)
    observability.event("taskiq_probe_started")
    if sleep_seconds:
        await asyncio.sleep(sleep_seconds)
    observability.event("taskiq_probe_completed")
    return {"probe_id": identifier, "status": "COMPLETED"}
