"""LangGraph construction and application entry point for campaign research."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from time import perf_counter
from uuid import UUID

from langgraph.graph import END, START, StateGraph

from virtual_company.config import Settings, get_settings
from virtual_company.llm.base import LLMProvider
from virtual_company.observability import get_observability
from virtual_company.services import CampaignService, ResearchService
from virtual_company.tools.web_fetch import WebFetchTool
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
        research_llm: LLMProvider | None = None,
        extraction_llm: LLMProvider | None = None,
        llm: LLMProvider | None = None,
        web_search: WebSearchTool,
        web_fetch: WebFetchTool,
        settings: Settings | None = None,
    ) -> None:
        resolved_settings = settings or get_settings()
        self._nodes = ResearchNodes(
            campaigns=campaigns,
            research=research,
            research_llm=research_llm,
            extraction_llm=extraction_llm,
            llm=llm,
            web_search=web_search,
            web_fetch=web_fetch,
            web_search_max_results=resolved_settings.web_search_max_results,
            web_search_max_total_results=resolved_settings.web_search_max_total_results,
            web_search_concurrency=resolved_settings.web_search_concurrency,
            discovery_candidate_multiplier=resolved_settings.discovery_candidate_multiplier,
            discovery_candidate_max=resolved_settings.discovery_candidate_max,
            company_research_query_count=resolved_settings.company_research_query_count,
            company_research_max_results_per_query=(
                resolved_settings.company_research_max_results_per_query
            ),
            company_research_max_results_per_company=(
                resolved_settings.company_research_max_results_per_company
            ),
            company_research_max_fetches_per_company=(
                resolved_settings.company_research_max_fetches_per_company
            ),
            company_research_max_investigation_rounds=(
                resolved_settings.company_research_max_investigation_rounds
            ),
            company_research_followup_search_queries_per_company=(
                resolved_settings.company_research_followup_search_queries_per_company
            ),
            company_research_followup_max_fetches_per_company=(
                resolved_settings.company_research_followup_max_fetches_per_company
            ),
            web_fetch_concurrency=resolved_settings.web_fetch_concurrency,
            evidence_extraction_concurrency=resolved_settings.evidence_extraction_concurrency,
            evidence_max_excerpt_chars=resolved_settings.evidence_max_excerpt_chars,
        )
        self._research = research
        self._graph = build_research_graph(self._nodes, research)

    async def run(self, campaign_id: UUID) -> ResearchWorkflowResult:
        """Execute research and return its concise application result."""
        observability = get_observability()
        observability.bind(campaign_id=str(campaign_id), workflow="company_research")
        observability.event("research_run_started")
        observability.record(
            "research_runs_total", status="started", workflow="company_research"
        )
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
                        "extracted_company_candidates": [],
                        "aggregated_company_candidates": [],
                        "discovered_companies": [],
                        "companies_found": 0,
                        "research_companies": [],
                        "company_research_queries": {},
                        "company_search_results": {},
                        "selected_company_sources": {},
                        "company_web_pages": {},
                        "attributable_company_web_pages": {},
                        "validated_evidence": [],
                        "investigations": {},
                        "active_company_ids": [],
                        "adaptive_mode": False,
                        "company_qualifications": {},
                        "error": None,
                    },
                    config={"recursion_limit": 100},
                )
        except Exception as error:
            observability.record(
                "research_runs_total", status="failed", workflow="company_research"
            )
            observability.record(
                "research_run_failures_total", workflow="company_research"
            )
            observability.event("research_run_failed", error_type=type(error).__name__)
            raise
        research_run_id = state["research_run_id"]
        if research_run_id is None:
            raise ValueError("Research workflow completed without a research run")
        observability.bind(research_run_id=str(research_run_id))
        observability.record(
            "research_runs_total", status="completed", workflow="company_research"
        )
        observability.record(
            "research_run_duration_seconds",
            perf_counter() - started,
            workflow="company_research",
        )
        observability.event(
            "research_run_completed", companies_found=state["companies_found"]
        )
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
        _with_failure_handling(
            nodes.generate_search_queries, "generate_search_queries", research
        ),
    )
    graph.add_node(
        "search_web", _with_failure_handling(nodes.search_web, "search_web", research)
    )
    graph.add_node(
        "extract_company_candidates",
        _with_failure_handling(
            nodes.extract_company_candidates, "extract_company_candidates", research
        ),
    )
    graph.add_node(
        "aggregate_company_candidates",
        _with_failure_handling(
            nodes.aggregate_company_candidates, "aggregate_company_candidates", research
        ),
    )
    graph.add_node(
        "rank_company_candidates",
        _with_failure_handling(
            nodes.rank_company_candidates, "rank_company_candidates", research
        ),
    )
    graph.add_node(
        "persist_companies",
        _with_failure_handling(nodes.persist_companies, "persist_companies", research),
    )
    graph.add_node(
        "generate_company_queries",
        _with_failure_handling(
            nodes.generate_company_queries, "generate_company_queries", research
        ),
    )
    graph.add_node(
        "search_company_sources",
        _with_failure_handling(
            nodes.search_company_sources, "search_company_sources", research
        ),
    )
    graph.add_node(
        "select_company_sources",
        _with_failure_handling(
            nodes.select_company_sources, "select_company_sources", research
        ),
    )
    graph.add_node(
        "fetch_company_sources",
        _with_failure_handling(
            nodes.fetch_company_sources, "fetch_company_sources", research
        ),
    )
    graph.add_node(
        "validate_company_page_attribution",
        _with_failure_handling(
            nodes.validate_company_page_attribution,
            "validate_company_page_attribution",
            research,
        ),
    )
    graph.add_node(
        "extract_company_evidence",
        _with_failure_handling(
            nodes.extract_company_evidence, "extract_company_evidence", research
        ),
    )
    graph.add_node(
        "persist_evidence",
        _with_failure_handling(nodes.persist_evidence, "persist_evidence", research),
    )
    graph.add_node(
        "check_evidence_coverage",
        _with_failure_handling(
            nodes.check_evidence_coverage, "check_evidence_coverage", research
        ),
    )
    graph.add_node(
        "generate_followup_queries",
        _with_failure_handling(
            nodes.generate_followup_queries, "generate_followup_queries", research
        ),
    )
    graph.add_node(
        "qualify_companies",
        _with_failure_handling(nodes.qualify_companies, "qualify_companies", research),
    )
    graph.add_node(
        "persist_company_qualifications",
        _with_failure_handling(
            nodes.persist_company_qualifications,
            "persist_company_qualifications",
            research,
        ),
    )
    graph.add_node(
        "complete_research_run",
        _with_failure_handling(
            nodes.complete_research_run, "complete_research_run", research
        ),
    )
    graph.add_edge(START, "load_campaign")
    graph.add_edge("load_campaign", "create_research_run")
    graph.add_edge("create_research_run", "generate_search_queries")
    graph.add_edge("generate_search_queries", "search_web")
    graph.add_edge("search_web", "extract_company_candidates")
    graph.add_edge("extract_company_candidates", "aggregate_company_candidates")
    graph.add_edge("aggregate_company_candidates", "rank_company_candidates")
    graph.add_edge("rank_company_candidates", "persist_companies")
    graph.add_edge("persist_companies", "generate_company_queries")
    graph.add_edge("generate_company_queries", "search_company_sources")
    graph.add_edge("search_company_sources", "select_company_sources")
    graph.add_edge("select_company_sources", "fetch_company_sources")
    graph.add_edge("fetch_company_sources", "validate_company_page_attribution")
    graph.add_edge("validate_company_page_attribution", "extract_company_evidence")
    graph.add_edge("extract_company_evidence", "persist_evidence")
    graph.add_edge("persist_evidence", "check_evidence_coverage")
    graph.add_conditional_edges(
        "check_evidence_coverage",
        route_investigation,
        {
            "follow_up": "generate_followup_queries",
            "done": "qualify_companies",
        },
    )
    graph.add_edge("generate_followup_queries", "search_company_sources")
    graph.add_edge("qualify_companies", "persist_company_qualifications")
    graph.add_edge("persist_company_qualifications", "complete_research_run")
    graph.add_edge("complete_research_run", END)
    return graph.compile()


def route_investigation(state: ResearchWorkflowState) -> str:
    """Continue only while at least one company remains independently active."""
    return "follow_up" if state["active_company_ids"] else "done"


def _with_failure_handling(
    node: Node, node_name: str, research: ResearchService
) -> Node:
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
