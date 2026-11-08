"""Exploration workflow components with lazy LangGraph exports."""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from virtual_company.workflows.exploration.graph import ExplorationWorkflow
    from virtual_company.workflows.exploration.state import ExplorationWorkflowResult

__all__ = ["ExplorationWorkflow", "ExplorationWorkflowResult"]


def __getattr__(name: str) -> Any:
    if name == "ExplorationWorkflow":
        from virtual_company.workflows.exploration.graph import ExplorationWorkflow

        return ExplorationWorkflow
    if name == "ExplorationWorkflowResult":
        from virtual_company.workflows.exploration.state import (
            ExplorationWorkflowResult,
        )

        return ExplorationWorkflowResult
    raise AttributeError(name)
