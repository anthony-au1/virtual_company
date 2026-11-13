"""Research adapter placeholder pending the Phase 4 migration."""

from uuid import UUID

from virtual_company.task_queue.adapters.base import InactiveWorkflowAdapterError


class ResearchWorkflowAdapter:
    """Fail closed until Research supports a pre-created QUEUED run."""

    async def execute(self, run_id: UUID) -> None:
        del run_id
        raise InactiveWorkflowAdapterError(
            "Research Taskiq execution is not active in Phase 2"
        )
