"""Campaign research workflow with lazy graph loading."""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from virtual_company.workflows.research.graph import ResearchWorkflow

__all__ = ["ResearchWorkflow"]


def __getattr__(name: str) -> Any:
    if name == "ResearchWorkflow":
        from virtual_company.workflows.research.graph import ResearchWorkflow

        return ResearchWorkflow
    raise AttributeError(name)
