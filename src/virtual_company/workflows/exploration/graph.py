"""LangGraph construction and execution entry point for Exploration."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from time import perf_counter
from uuid import UUID

from langgraph.errors import NodeCancelledError
from langgraph.graph import END, START, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from virtual_company.config import Settings, get_settings
from virtual_company.db.session import session_factory
from virtual_company.domain.exploration.run import ExplorationRunStatus
from virtual_company.observability import Observability, get_observability
from virtual_company.repositories.exploration_run import (
    ExplorationRunRepository,
    InvalidExplorationRunTransitionError,
)
from virtual_company.services.exploration_evidence_extractor import (
    ExplorationEvidenceExtractor,
    create_configured_exploration_evidence_extractor,
)
from virtual_company.services.exploration_fact_extractor import (
    ExplorationFactExtractor,
    create_configured_exploration_fact_extractor,
)
from virtual_company.services.exploration_fetch import (
    ExplorationFetchService,
    create_configured_exploration_fetch_service,
)
from virtual_company.services.exploration_hypothesis_generator import (
    ExplorationHypothesisGenerator,
    create_configured_exploration_hypothesis_generator,
)
from virtual_company.services.exploration_query_generator import (
    ExplorationQueryGenerator,
    create_configured_exploration_query_generator,
)
from virtual_company.services.exploration_search import (
    ExplorationSearchOutcome,
    ExplorationSearchService,
    create_configured_exploration_search_service,
)
from virtual_company.workflows.exploration.models import (
    ExplorationHypothesisGenerationOutcome,
)
from virtual_company.workflows.exploration.nodes import (
    ExplorationNodes,
    ExplorationWorkflowFatalError,
    ExplorationWorkflowInputError,
)
from virtual_company.workflows.exploration.state import (
    ExplorationWorkflowResult,
    ExplorationWorkflowState,
)

Node = Callable[
    [ExplorationWorkflowState], Awaitable[dict[str, object]]
]
RECURSION_LIMIT = 1_000


class ExplorationWorkflow:
    """Execute one already-queued ExplorationRun through a compiled graph."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        query_generator: ExplorationQueryGenerator,
        search_service: ExplorationSearchService,
        fetch_service: ExplorationFetchService,
        evidence_extractor: ExplorationEvidenceExtractor,
        fact_extractor: ExplorationFactExtractor,
        hypothesis_generator: ExplorationHypothesisGenerator,
        observability: Observability | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._observability = observability or get_observability()
        self._nodes = ExplorationNodes(
            session_factory,
            query_generator=query_generator,
            search_service=search_service,
            fetch_service=fetch_service,
            evidence_extractor=evidence_extractor,
            fact_extractor=fact_extractor,
            hypothesis_generator=hypothesis_generator,
            observability=self._observability,
        )
        self._graph = build_exploration_graph(self._nodes, self._observability)

    async def run(self, exploration_run_id: UUID) -> ExplorationWorkflowResult:
        """Run only QUEUED records; fatal errors and cancellation are propagated."""
        started = perf_counter()
        run_started = False
        self._observability.clear_context()
        self._observability.bind(
            exploration_run_id=str(exploration_run_id),
            workflow="exploration",
        )
        self._observability.event("exploration_workflow_started")
        try:
            transition_task = asyncio.create_task(
                self._transition(exploration_run_id, ExplorationRunStatus.RUNNING)
            )
            try:
                await asyncio.shield(transition_task)
            except asyncio.CancelledError:
                try:
                    await transition_task
                except Exception as error:  # noqa: BLE001 - keep cancellation primary
                    self._observability.event(
                        "exploration_workflow_start_transition_failed",
                        error_type=type(error).__name__,
                    )
                else:
                    run_started = True
                raise
            run_started = True
            graph_error: Exception | None = None
            state: ExplorationWorkflowState = {}
            with self._observability.span("exploration_workflow"):
                try:
                    state = await self._graph.ainvoke(
                        {"exploration_run_id": exploration_run_id},
                        config={"recursion_limit": RECURSION_LIMIT},
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as error:  # noqa: BLE001 - avoid raw error telemetry
                    graph_error = error
            if graph_error is not None:
                raise graph_error
        except asyncio.CancelledError:
            if run_started:
                await self._cleanup_transition(
                    exploration_run_id, ExplorationRunStatus.CANCELLED
                )
            self._observability.event(
                "exploration_workflow_cancelled",
                final_status=(
                    ExplorationRunStatus.CANCELLED.value
                    if run_started
                    else "not_started"
                ),
                duration_ms=int((perf_counter() - started) * 1000),
            )
            raise
        except NodeCancelledError as error:
            if run_started:
                await self._cleanup_transition(
                    exploration_run_id, ExplorationRunStatus.CANCELLED
                )
            self._observability.event(
                "exploration_workflow_cancelled",
                final_status=(
                    ExplorationRunStatus.CANCELLED.value
                    if run_started
                    else "not_started"
                ),
                duration_ms=int((perf_counter() - started) * 1000),
            )
            raise asyncio.CancelledError from error
        except Exception as error:
            if run_started:
                await self._cleanup_transition(
                    exploration_run_id, ExplorationRunStatus.FAILED
                )
            self._observability.event(
                "exploration_workflow_failed",
                failure_category=self._failure_category(error),
                error_type=type(error).__name__,
                final_status=(
                    ExplorationRunStatus.FAILED.value if run_started else None
                ),
                duration_ms=int((perf_counter() - started) * 1000),
            )
            raise

        final_status = state.get("final_status")
        if final_status not in {
            ExplorationRunStatus.COMPLETED,
            ExplorationRunStatus.PARTIAL,
        }:
            error = ExplorationWorkflowFatalError(
                "internal_invariant", "Graph finished without a terminal run status"
            )
            await self._cleanup_transition(
                exploration_run_id, ExplorationRunStatus.FAILED
            )
            raise error
        result = ExplorationWorkflowResult(
            exploration_run_id=exploration_run_id,
            status=final_status,
            selected_company_count=len(state["companies"]),
            obligation_count=len(state["obligations"]),
            completed_company_obligation_count=(
                state["completed_company_obligation_count"]
            ),
            evidence_persisted_count=state["evidence_persisted_count"],
            facts_persisted_count=state["facts_persisted_count"],
            hypotheses_persisted_count=state["hypotheses_persisted_count"],
            recoverable_failure_count=state["recoverable_failure_count"],
            failure_categories=tuple(state["failure_categories"]),
            duration_ms=int((perf_counter() - started) * 1000),
        )
        self._observability.event(
            "exploration_workflow_completed",
            final_status=result.status.value,
            selected_company_count=result.selected_company_count,
            obligation_count=result.obligation_count,
            completed_company_obligation_count=(
                result.completed_company_obligation_count
            ),
            evidence_persisted_count=result.evidence_persisted_count,
            facts_persisted_count=result.facts_persisted_count,
            hypotheses_persisted_count=result.hypotheses_persisted_count,
            recoverable_failure_count=result.recoverable_failure_count,
            duration_ms=result.duration_ms,
        )
        return result

    async def _transition(
        self, run_id: UUID, target: ExplorationRunStatus
    ) -> None:
        async with self._session_factory() as session, session.begin():
            run = await ExplorationRunRepository(session).transition(run_id, target)
            if run is None:
                raise ExplorationWorkflowInputError("ExplorationRun does not exist")

    async def _cleanup_transition(
        self, run_id: UUID, target: ExplorationRunStatus
    ) -> None:
        try:
            await self._transition(run_id, target)
        except Exception as error:  # noqa: BLE001 - cleanup must not mask original
            self._observability.event(
                "exploration_workflow_cleanup_transition_failed",
                target_status=target.value,
                error_type=type(error).__name__,
            )

    @staticmethod
    def _failure_category(error: Exception) -> str:
        if isinstance(error, ExplorationWorkflowFatalError):
            return error.category
        if isinstance(error, ExplorationWorkflowInputError):
            return "invalid_run_input"
        if isinstance(error, InvalidExplorationRunTransitionError):
            return "invalid_lifecycle_transition"
        return "database_or_internal_error"


def build_exploration_graph(
    nodes: ExplorationNodes,
    observability: Observability | None = None,
):
    """Compile the explicit sequential Exploration processing graph."""
    telemetry = observability or get_observability()
    graph = StateGraph(ExplorationWorkflowState)
    graph.add_node("load_context", _instrument(nodes.load_context, "load_context", telemetry))
    graph.add_node("select_company", _instrument(nodes.select_company, "select_company", telemetry))
    graph.add_node("select_obligation", _instrument(nodes.select_obligation, "select_obligation", telemetry))
    graph.add_node("generate_queries", _instrument(nodes.generate_queries, "generate_queries", telemetry))
    graph.add_node("search", _instrument(nodes.search, "search", telemetry))
    graph.add_node("fetch", _instrument(nodes.fetch, "fetch", telemetry))
    graph.add_node("extract_evidence", _instrument(nodes.extract_evidence, "extract_evidence", telemetry))
    graph.add_node("persist_evidence", _instrument(nodes.persist_evidence, "persist_evidence", telemetry))
    graph.add_node("advance_obligation", _instrument(nodes.advance_obligation, "advance_obligation", telemetry))
    graph.add_node("load_company_evidence", _instrument(nodes.load_company_evidence, "load_company_evidence", telemetry))
    graph.add_node("extract_facts", _instrument(nodes.extract_facts, "extract_facts", telemetry))
    graph.add_node("persist_facts", _instrument(nodes.persist_facts, "persist_facts", telemetry))
    graph.add_node("load_company_facts", _instrument(nodes.load_company_facts, "load_company_facts", telemetry))
    graph.add_node("generate_hypotheses", _instrument(nodes.generate_hypotheses, "generate_hypotheses", telemetry))
    graph.add_node("persist_hypotheses", _instrument(nodes.persist_hypotheses, "persist_hypotheses", telemetry))
    graph.add_node("advance_company", _instrument(nodes.advance_company, "advance_company", telemetry))
    graph.add_node("finalize_run", _instrument(nodes.finalize_run, "finalize_run", telemetry))

    graph.add_edge(START, "load_context")
    graph.add_edge("load_context", "select_company")
    graph.add_conditional_edges(
        "select_company",
        route_company,
        {"selected": "select_obligation", "done": "finalize_run"},
    )
    graph.add_conditional_edges(
        "select_obligation",
        route_obligation,
        {"selected": "generate_queries", "done": "load_company_evidence"},
    )
    graph.add_conditional_edges(
        "generate_queries",
        route_queries,
        {"search": "search", "skip": "advance_obligation"},
    )
    graph.add_conditional_edges(
        "search",
        route_search,
        {"fetch": "fetch", "skip": "advance_obligation"},
    )
    graph.add_conditional_edges(
        "fetch",
        route_fetch,
        {"extract": "extract_evidence", "skip": "advance_obligation"},
    )
    graph.add_conditional_edges(
        "extract_evidence",
        route_evidence,
        {"persist": "persist_evidence", "skip": "advance_obligation"},
    )
    graph.add_edge("persist_evidence", "advance_obligation")
    graph.add_edge("advance_obligation", "select_obligation")
    graph.add_conditional_edges(
        "load_company_evidence",
        route_company_evidence,
        {"extract": "extract_facts", "skip": "load_company_facts"},
    )
    graph.add_conditional_edges(
        "extract_facts",
        route_facts,
        {"persist": "persist_facts", "skip": "load_company_facts"},
    )
    graph.add_edge("persist_facts", "load_company_facts")
    graph.add_conditional_edges(
        "load_company_facts",
        route_company_facts,
        {"generate": "generate_hypotheses", "skip": "advance_company"},
    )
    graph.add_conditional_edges(
        "generate_hypotheses",
        route_hypotheses,
        {"persist": "persist_hypotheses", "skip": "advance_company"},
    )
    graph.add_edge("persist_hypotheses", "advance_company")
    graph.add_edge("advance_company", "select_company")
    graph.add_edge("finalize_run", END)
    return graph.compile()


def route_company(state: ExplorationWorkflowState) -> str:
    return "done" if state.get("current_company") is None else "selected"


def route_obligation(state: ExplorationWorkflowState) -> str:
    return "done" if state.get("current_obligation") is None else "selected"


def route_queries(state: ExplorationWorkflowState) -> str:
    result = state.get("query_result")
    return "search" if result is not None and result.queries else "skip"


def route_search(state: ExplorationWorkflowState) -> str:
    result = state.get("search_result")
    if result is None:
        return "skip"
    return (
        "fetch"
        if any(
            item.outcome is ExplorationSearchOutcome.SUCCEEDED and item.results
            for item in result.query_results
        )
        else "skip"
    )


def route_fetch(state: ExplorationWorkflowState) -> str:
    result = state.get("fetch_result")
    return (
        "extract"
        if result is not None and any(item.page is not None for item in result.results)
        else "skip"
    )


def route_evidence(state: ExplorationWorkflowState) -> str:
    result = state.get("evidence_result")
    return (
        "persist"
        if result is not None and any(item.evidence for item in result.results)
        else "skip"
    )


def route_company_evidence(state: ExplorationWorkflowState) -> str:
    return "extract" if state.get("company_evidence") else "skip"


def route_facts(state: ExplorationWorkflowState) -> str:
    result = state.get("fact_result")
    return "persist" if result is not None and result.facts else "skip"


def route_company_facts(state: ExplorationWorkflowState) -> str:
    return "generate" if state.get("company_facts") else "skip"


def route_hypotheses(state: ExplorationWorkflowState) -> str:
    result = state.get("hypothesis_result")
    return (
        "persist"
        if result is not None
        and result.outcome is ExplorationHypothesisGenerationOutcome.SUCCEEDED
        and result.hypotheses
        else "skip"
    )


def _instrument(node: Node, name: str, observability: Observability) -> Node:
    async def wrapped(state: ExplorationWorkflowState) -> dict[str, object]:
        run_id = state.get("exploration_run_id")
        company = state.get("current_company")
        obligation = state.get("current_obligation")
        metadata = {
            "workflow_node": name,
            "exploration_run_id": str(run_id) if run_id else None,
            "exploration_company_id": (
                str(company.exploration_company_id) if company else None
            ),
            "exploration_obligation_id": str(obligation.id) if obligation else None,
        }
        observability.event("exploration_workflow_node_started", **metadata)
        started = perf_counter()
        result: dict[str, object] = {}
        node_error: Exception | None = None
        try:
            with observability.span(name, **metadata):
                try:
                    result = await node(state)
                except asyncio.CancelledError:
                    raise
                except Exception as error:  # noqa: BLE001 - emit only safe error data
                    node_error = error
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - instrumentation is non-semantic
            node_error = error

        if node_error is not None:
            observability.event(
                "exploration_workflow_node_failed",
                duration_ms=int((perf_counter() - started) * 1000),
                failure_category=_failure_category(node_error),
                error_type=type(node_error).__name__,
                **metadata,
            )
            raise node_error
        observability.event(
            "exploration_workflow_node_completed",
            duration_ms=int((perf_counter() - started) * 1000),
            **metadata,
        )
        return result

    return wrapped


def _failure_category(error: Exception) -> str:
    if isinstance(error, ExplorationWorkflowFatalError):
        return error.category
    if isinstance(error, ExplorationWorkflowInputError):
        return "invalid_run_input"
    return "internal_or_persistence_error"


def create_configured_exploration_workflow(
    settings: Settings | None = None,
    *,
    database_session_factory: async_sessionmaker[AsyncSession] = session_factory,
    observability: Observability | None = None,
) -> ExplorationWorkflow:
    """Build the Exploration graph with configured provider-backed services."""
    resolved_settings = settings or get_settings()
    return ExplorationWorkflow(
        session_factory=database_session_factory,
        query_generator=create_configured_exploration_query_generator(
            resolved_settings
        ),
        search_service=create_configured_exploration_search_service(
            resolved_settings, observability=observability
        ),
        fetch_service=create_configured_exploration_fetch_service(
            resolved_settings, observability=observability
        ),
        evidence_extractor=create_configured_exploration_evidence_extractor(
            resolved_settings, observability=observability
        ),
        fact_extractor=create_configured_exploration_fact_extractor(
            resolved_settings, observability=observability
        ),
        hypothesis_generator=create_configured_exploration_hypothesis_generator(
            resolved_settings, observability=observability
        ),
        observability=observability,
    )
