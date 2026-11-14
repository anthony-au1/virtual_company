"""Research adapter placeholder pending the Phase 4 migration."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from virtual_company.task_queue.adapters.base import InactiveWorkflowAdapterError


class ResearchWorkflowAdapter:
    """Fail closed until Research supports a pre-created QUEUED run."""

    async def execute(
        self,
        run_id: UUID,
        *,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        task_id: str | None = None,
    ) -> None:
        del run_id
        del session_factory
        del task_id
        raise InactiveWorkflowAdapterError(
            "Research Taskiq execution is not active in Phase 2"
        )
