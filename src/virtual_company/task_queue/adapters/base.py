"""Minimal workflow adapter contract for the Taskiq dispatcher."""

from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class WorkflowAdapter(Protocol):
    """An adapter receives only a stable workflow run identifier."""

    async def execute(
        self,
        run_id: UUID,
        *,
        session_factory: async_sessionmaker[AsyncSession] | None,
        task_id: str | None,
    ) -> None: ...


class InactiveWorkflowAdapterError(RuntimeError):
    """Raised until a workflow is explicitly migrated to Taskiq execution."""
