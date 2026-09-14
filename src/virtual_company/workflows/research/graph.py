"""LangGraph construction and application entry point for campaign research."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from time import perf_counter
from uuid import UUID

from langgraph.graph import END, START, StateGraph

from virtual_company.llm.base import LLMProvider
from virtual_company.observability import get_observability
from virtual_company.services import CampaignService, ResearchService
from virtual_company.tools.web_search import WebSearchTool
from virtual_company.workflows.research.models import ResearchWorkflowResult
from virtual_company.workflows.research.nodes import ResearchNodes
from virtual_company.workflows.research.state import ResearchWorkflowState

Node = Callable[[ResearchWorkflowState], Awaitable[dict[str, object]]]


class ResearchWorkflow:
    """Run the first vertical slice of campaign research."""

    def __init__(
        self,
        *,
        campaigns: CampaignService,
        research: ResearchService,
        llm: LLMProvider,
        web_search: WebSearchTool,
    ) -> None:
        self._nodes = ResearchNodes(
            campaigns=campaigns,
            research=research,
            llm=llm,
            web_search=web_search,
        )
        self._research = research
        self._graph = build_research_graph(self._nodes, research)

    async def run(self, campaign_id: UUID) -> ResearchWorkflowResult:
        """Execute research and return its concise application result."""
        observability = get_observability()
        observability.bind(campaign_id=str(campaign_id), workflow="company_research")
        observability.event("research_run_started")
        observability.record("research_runs_total", status="started", workflow="company_research")
        started = perf_counter()
        try:
            with observability.span("research_workflow", workflow="company_research"):
                state = await self._graph.ainvoke(
                    {
                        "campaign_id": campaign_id,
                        "campaign": None,
                        "research_run_id": None,
                        "queries": [],
                        "search_results": [],
                        "discovered_companies": [],
                        "companies_found": 0,
                        "error": None,
                    }
                )
        except Exception as error:
            observability.record("research_runs_total", status="failed", workflow="company_research")
            observability.record("research_run_failures_total", workflow="company_research")
            observability.event("research_run_failed", error_type=type(error).__name__)
            raise
        research_run_id = state["research_run_id"]
        if research_run_id is None:
            raise ValueError("Research workflow completed without a research run")
        observability.bind(research_run_id=str(research_run_id))
        observability.record("research_runs_total", status="completed", workflow="company_research")
        observability.record(
            "research_run_duration_seconds", perf_counter() - started, workflow="company_research"
        )
        observability.event("research_run_completed", companies_found=state["companies_found"])
        return ResearchWorkflowResult(
            research_run_id=research_run_id,
            status="COMPLETED",
            companies_found=state["companies_found"],
        )


def build_research_graph(nodes: ResearchNodes, research: ResearchService):
    """Compile the fixed, sequential research workflow graph."""
    graph = StateGraph(ResearchWorkflowState)
    graph.add_node("load_campaign", nodes.load_campaign)
    graph.add_node("create_research_run", nodes.create_research_run)
    graph.add_node(
        "generate_search_queries",
        _with_failure_handling(nodes.generate_search_queries, "generate_search_queries", research),
    )
    graph.add_node("search_web", _with_failure_handling(nodes.search_web, "search_web", research))
    graph.add_node(
        "discover_companies",
        _with_failure_handling(nodes.discover_companies, "discover_companies", research),
    )
    graph.add_node(
        "persist_companies",
        _with_failure_handling(nodes.persist_companies, "persist_companies", research),
    )
    graph.add_node(
        "complete_research_run",
        _with_failure_handling(nodes.complete_research_run, "complete_research_run", research),
    )
    graph.add_edge(START, "load_campaign")
    graph.add_edge("load_campaign", "create_research_run")
    graph.add_edge("create_research_run", "generate_search_queries")
    graph.add_edge("generate_search_queries", "search_web")
    graph.add_edge("search_web", "discover_companies")
    graph.add_edge("discover_companies", "persist_companies")
    graph.add_edge("persist_companies", "complete_research_run")
    graph.add_edge("complete_research_run", END)
    return graph.compile()


def _with_failure_handling(node: Node, node_name: str, research: ResearchService) -> Node:
    """Mark an already-created run failed before propagating a node exception."""

    async def wrapped(state: ResearchWorkflowState) -> dict[str, object]:
        observability = get_observability()
        observability.event("workflow_node_started", workflow_node=node_name)
        started = perf_counter()
        try:
            with observability.span(node_name, workflow_node=node_name):
                result = await node(state)
            research_run_id = result.get("research_run_id")
            if research_run_id is not None:
                observability.bind(research_run_id=str(research_run_id))
            observability.event(
                "workflow_node_completed",
                workflow_node=node_name,
                duration_ms=int((perf_counter() - started) * 1000),
            )
            return result
        except Exception as error:
            research_run_id = state["research_run_id"]
            if research_run_id is not None:
                await research.fail_run(
                    research_run_id,
                    f"Research workflow failed in {node_name}: {type(error).__name__}",
                )
            observability.event(
                "workflow_node_failed",
                workflow_node=node_name,
                duration_ms=int((perf_counter() - started) * 1000),
                error_type=type(error).__name__,
            )
            raise

    return wrapped
