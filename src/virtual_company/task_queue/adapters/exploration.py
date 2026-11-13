"""Exploration adapter placeholder pending the Phase 3 migration."""

from uuid import UUID

from virtual_company.task_queue.adapters.base import InactiveWorkflowAdapterError


class ExplorationWorkflowAdapter:
    """Fail closed until Taskiq ownership is integrated with the graph."""

    async def execute(self, run_id: UUID) -> None:
        del run_id
        raise InactiveWorkflowAdapterError(
            "Exploration Taskiq execution is not active in Phase 2"
        )
