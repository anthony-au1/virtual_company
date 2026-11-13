"""Minimal workflow adapter contract for the Taskiq dispatcher."""

from typing import Protocol
from uuid import UUID


class WorkflowAdapter(Protocol):
    """An adapter receives only a stable workflow run identifier."""

    async def execute(self, run_id: UUID) -> None: ...


class InactiveWorkflowAdapterError(RuntimeError):
    """Raised until a workflow is explicitly migrated to Taskiq execution."""
