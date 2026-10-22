"""Occurrence-scoped search provenance recording for Research workflows."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from virtual_company.observability import Observability
from virtual_company.tools.web_search import SearchResult
from virtual_company.utils.url_normalization import (
    normalize_fetch_url,
    sanitize_observability_url,
)
from virtual_company.workflows.research.models import (
    CompanyInvestigationState,
    CompanySearchQueryTrace,
    CompanySearchResultTrace,
)


@dataclass(frozen=True)
class SearchResultOccurrenceRef:
    """Correlation fields for one provider result occurrence."""

    query_id: UUID
    result_id: UUID
    rank: int
    url: str


class SearchProvenanceRecorder:
    """Stateless trace transformations and events for search source provenance."""

    def __init__(self, observability: Observability) -> None:
        self._observability = observability

    @staticmethod
    def new_query_id() -> UUID:
        return uuid4()

    @staticmethod
    def create_query_trace(
        *,
        query_id: UUID,
        query: str,
        provider: str,
        search_phase: str,
        investigation_round: int,
        results: Sequence[SearchResult],
    ) -> CompanySearchQueryTrace:
        """Create compact occurrence DTOs from the provider's ordered results."""
        return CompanySearchQueryTrace(
            query_id=query_id,
            query=query,
            provider=provider,
            search_phase=search_phase,  # type: ignore[arg-type]
            investigation_round=investigation_round,
            success=True,
            result_count=len(results),
            results=[
                CompanySearchResultTrace(
                    result_id=uuid4(),
                    rank=rank,
                    url=result.url,
                    title=result.title[:300] if result.title else None,
                )
                for rank, result in enumerate(results, start=1)
            ],
        )

    def query_started(self, metadata: Mapping[str, Any]) -> None:
        self._observability.event("company_search_query_started", **metadata)

    def query_failed(self, error: Exception, metadata: Mapping[str, Any]) -> None:
        self._observability.event(
            "company_search_query_failed",
            error_type=type(error).__name__,
            failure_category=getattr(error, "category", None),
            http_status=getattr(error, "status_code", None),
            **metadata,
        )

    def query_completed(
        self, trace: CompanySearchQueryTrace, metadata: Mapping[str, Any]
    ) -> None:
        self._observability.event(
            "company_search_query_completed",
            result_count=trace.result_count,
            results=[
                {
                    "result_id": str(result.result_id),
                    "rank": result.rank,
                    "url": sanitize_observability_url(result.url),
                    "title": result.title,
                }
                for result in trace.results
            ],
            **metadata,
        )

    @staticmethod
    def record_merge_outcomes(
        query_traces: Sequence[CompanySearchQueryTrace],
        *,
        included_origins: Sequence[tuple[int, int]],
        seen_urls: set[str],
        included_urls: set[str],
    ) -> list[CompanySearchQueryTrace]:
        """Project the completed merge decision onto each query occurrence."""
        included_origin_set = set(included_origins)
        updated_traces = list(query_traces)
        for group_index, query_trace in enumerate(query_traces):
            updated_results = []
            for result in query_trace.results:
                origin = (group_index, result.rank)
                try:
                    normalized = normalize_fetch_url(result.url)
                except ValueError:
                    outcome = "invalid_url"
                else:
                    if normalized in seen_urls:
                        outcome = "already_processed"
                    elif origin in included_origin_set:
                        outcome = "included"
                    elif normalized in included_urls:
                        outcome = "duplicate_url"
                    else:
                        outcome = "result_limit"
                updated_results.append(
                    result.model_copy(update={"merge_outcome": outcome})
                )
            updated_traces[group_index] = query_trace.model_copy(
                update={"results": updated_results}
            )
        return updated_traces

    @staticmethod
    def append_queries(
        investigation: CompanyInvestigationState,
        query_traces: Sequence[CompanySearchQueryTrace],
    ) -> CompanyInvestigationState:
        return investigation.model_copy(
            update={"search_queries": [*investigation.search_queries, *query_traces]}
        )

    def record_merge_completed(
        self,
        *,
        company_id: UUID,
        company_domain: str | None,
        query_count: int,
        result_count: int,
        contributions: list[int],
    ) -> None:
        with self._observability.context(
            company_id=str(company_id), company_domain=company_domain
        ):
            self._observability.event(
                "company_search_results_merged",
                query_count=query_count,
                result_count=result_count,
                result_contributions=contributions,
            )

    def record_sources_found(
        self,
        *,
        company_id: UUID,
        company_domain: str | None,
        result_count: int,
    ) -> None:
        with self._observability.context(
            company_id=str(company_id), company_domain=company_domain
        ):
            self._observability.record(
                "company_research_sources_found_total",
                result_count,
                workflow="company_research",
            )
            self._observability.event(
                "company_research_sources_found", result_count=result_count
            )

    @staticmethod
    def included_occurrences(
        investigation: CompanyInvestigationState, investigation_round: int
    ) -> list[SearchResultOccurrenceRef]:
        """Return the merged survivor occurrences for one investigation round."""
        return [
            SearchResultOccurrenceRef(
                query_id=query.query_id,
                result_id=result.result_id,
                rank=result.rank,
                url=result.url,
            )
            for query in investigation.search_queries
            if query.investigation_round == investigation_round
            for result in query.results
            if result.merge_outcome == "included"
        ]

    @staticmethod
    def occurrence_for_url(
        occurrences: Sequence[SearchResultOccurrenceRef], url: str
    ) -> SearchResultOccurrenceRef | None:
        """Bridge one physical source URL to its included occurrence."""
        try:
            key = normalize_fetch_url(url)
        except ValueError:
            key = url.strip().casefold()
        return next(
            (
                occurrence
                for occurrence in occurrences
                if SearchProvenanceRecorder._source_key(occurrence.url) == key
            ),
            None,
        )

    @staticmethod
    def record_selection(
        investigation: CompanyInvestigationState,
        *,
        investigation_round: int,
        decisions_by_result_id: Mapping[UUID, Mapping[str, Any]],
    ) -> CompanyInvestigationState:
        """Record selection fields against included result IDs in this round."""
        updated_queries = []
        for query in investigation.search_queries:
            if query.investigation_round != investigation_round:
                updated_queries.append(query)
                continue
            updated_results = []
            for result in query.results:
                if result.merge_outcome != "included":
                    updated_results.append(result)
                    continue
                decision = decisions_by_result_id.get(result.result_id)
                if decision is None:
                    updated_results.append(
                        result.model_copy(update={"selection_outcome": "not_selected"})
                    )
                    continue
                updated_results.append(
                    result.model_copy(
                        update={
                            "selection_outcome": (
                                "selected"
                                if decision["preferred"]
                                else "backfill_candidate"
                            ),
                            "candidate_position": decision["candidate_position"],
                            "preferred_position": decision["preferred_position"],
                        }
                    )
                )
            updated_queries.append(
                query.model_copy(update={"results": updated_results})
            )
        return investigation.model_copy(update={"search_queries": updated_queries})

    def record_selection_events(
        self,
        *,
        company_id: UUID,
        company_name: str,
        company_domain: str | None,
        research_phase: str,
        fetch_phase: str,
        fetch_target: int,
        available_source_count: int,
        selected_source_count: int,
        candidate_decisions: list[dict[str, object]],
    ) -> None:
        with self._observability.context(
            company_id=str(company_id), company_domain=company_domain
        ):
            metadata = {
                "company_id": str(company_id),
                "company_name": company_name,
                "research_phase": research_phase,
                "fetch_phase": fetch_phase,
                "fetch_target": fetch_target,
                "candidate_decisions": candidate_decisions,
            }
            with self._observability.span("company_source_selection", **metadata):
                pass
            self._observability.event(
                "company_sources_selected",
                company_name=company_name,
                available_source_count=available_source_count,
                selected_source_count=selected_source_count,
                fetch_target=fetch_target,
                fetch_phase=fetch_phase,
                research_phase=research_phase,
                candidate_decisions=candidate_decisions,
            )
            self._observability.record(
                "company_research_sources_selected_total",
                selected_source_count,
                workflow="company_research",
            )

    def record_selection_completed(
        self,
        *,
        company_count: int,
        total_selected_source_count: int,
        fetch_target: int,
    ) -> None:
        context = {
            "company_count": company_count,
            "selected_source_count": total_selected_source_count,
            "successful_fetch_target_per_company": fetch_target,
        }
        with self._observability.span("select_company_sources", **context):
            self._observability.event("company_sources_selection_completed", **context)

    @staticmethod
    def occurrence_refs_for_url(
        investigation: CompanyInvestigationState,
        url: str,
        *,
        investigation_round: int,
        included_only: bool = True,
    ) -> list[SearchResultOccurrenceRef]:
        try:
            key = normalize_fetch_url(url)
        except ValueError:
            key = url.strip().casefold()
        return [
            SearchResultOccurrenceRef(
                query_id=query.query_id,
                result_id=result.result_id,
                rank=result.rank,
                url=result.url,
            )
            for query in investigation.search_queries
            if query.investigation_round == investigation_round
            for result in query.results
            if (not included_only or result.merge_outcome == "included")
            and SearchProvenanceRecorder._source_key(result.url) == key
        ]

    @staticmethod
    def fetch_context(refs: Sequence[SearchResultOccurrenceRef]) -> dict[str, str]:
        return {
            "result_ids": ",".join(str(item.result_id) for item in refs),
            "query_ids": ",".join(str(item.query_id) for item in refs),
            "result_ranks": ",".join(str(item.rank) for item in refs),
        }

    def record_fetch_failure(
        self,
        *,
        company_id: UUID,
        url: str,
        error: Exception,
        attempt_number: int,
        retryable: bool,
        retry_remaining: bool,
        refs: Sequence[SearchResultOccurrenceRef],
    ) -> None:
        self._observability.event(
            "company_source_fetch_failed",
            company_id=str(company_id),
            url=sanitize_observability_url(url),
            failure_category=getattr(error, "category", "unknown"),
            http_status=getattr(error, "status_code", None),
            attempt_number=attempt_number,
            retryable=retryable,
            retry_remaining=retry_remaining,
            exhausted=not retry_remaining,
            result_ids=[str(item.result_id) for item in refs],
            query_ids=[str(item.query_id) for item in refs],
            result_ranks=[item.rank for item in refs],
        )

    def record_fetch_batch_events(
        self,
        *,
        company_id: UUID,
        company_name: str,
        company_domain: str | None,
        research_phase: str,
        fetch_phase: str,
        fetch_target: int,
        candidate_outcomes: list[dict[str, object]],
        target_reached: bool,
        candidates_exhausted: bool,
        stop_reason: str | None,
        stats: Mapping[str, object],
        selected_source_count: int,
        candidate_count: int,
        success_count: int,
        failure_count: int,
    ) -> None:
        with self._observability.context(
            company_id=str(company_id),
            company_name=company_name,
            company_domain=company_domain,
        ):
            metadata = {
                "company_id": str(company_id),
                "company_name": company_name,
                "research_phase": research_phase,
                "fetch_phase": fetch_phase,
                "fetch_target": fetch_target,
                "candidate_outcomes": candidate_outcomes,
                "target_reached": target_reached,
                "candidates_exhausted": candidates_exhausted,
                "stop_reason": stop_reason,
            }
            with self._observability.span("company_source_fetch_batch", **metadata):
                pass
        self._observability.event(
            "company_sources_fetch_batch_completed",
            company_id=str(company_id),
            fetch_phase=fetch_phase,
            research_phase=research_phase,
            candidate_outcomes=candidate_outcomes,
            stop_reason=stop_reason,
            **stats,
        )
        self._observability.event(
            "company_sources_fetch_completed",
            company_id=str(company_id),
            selected_source_count=selected_source_count,
            candidate_count=candidate_count,
            fetch_success_count=success_count,
            fetch_failure_count=failure_count,
        )

    @staticmethod
    def record_fetch_outcomes(
        investigation: CompanyInvestigationState,
        *,
        investigation_round: int,
        outcomes_by_result_id: Mapping[UUID, Mapping[str, Any]],
    ) -> CompanyInvestigationState:
        """Attach the physical fetch outcome to its included occurrence ID."""
        updated_queries = []
        for query in investigation.search_queries:
            if query.investigation_round != investigation_round:
                updated_queries.append(query)
                continue
            updated_results = []
            for result in query.results:
                if result.merge_outcome != "included":
                    updated_results.append(result)
                    continue
                outcome = outcomes_by_result_id.get(result.result_id)
                if outcome is None:
                    updated_results.append(result)
                    continue
                error = outcome.get("error")
                updated_results.append(
                    result.model_copy(
                        update={
                            "fetch_outcome": outcome["outcome"],
                            "fetch_attempt": outcome.get("fetch_attempt"),
                            "failure_category": (
                                getattr(error, "category", None)
                                if error is not None
                                else None
                            ),
                            "http_status": (
                                getattr(error, "status_code", None)
                                if error is not None
                                else None
                            ),
                        }
                    )
                )
            updated_queries.append(
                query.model_copy(update={"results": updated_results})
            )
        return investigation.model_copy(update={"search_queries": updated_queries})

    @staticmethod
    def link_evidence(
        investigation: CompanyInvestigationState,
        *,
        result_id: UUID,
        evidence_id: UUID,
        investigation_round: int,
    ) -> tuple[CompanyInvestigationState, SearchResultOccurrenceRef | None]:
        """Link persisted evidence to one successful included result occurrence."""
        found: SearchResultOccurrenceRef | None = None
        updated_queries = []
        for query in investigation.search_queries:
            updated_results = []
            for result in query.results:
                if (
                    query.investigation_round == investigation_round
                    and result.result_id == result_id
                    and result.merge_outcome == "included"
                    and result.fetch_outcome == "ATTEMPTED_SUCCESS"
                ):
                    result = result.model_copy(
                        update={
                            "evidence_ids": list(
                                dict.fromkeys([*result.evidence_ids, evidence_id])
                            )
                        }
                    )
                    found = SearchResultOccurrenceRef(
                        query_id=query.query_id,
                        result_id=result.result_id,
                        rank=result.rank,
                        url=result.url,
                    )
                updated_results.append(result)
            updated_queries.append(
                query.model_copy(update={"results": updated_results})
            )
        return investigation.model_copy(
            update={"search_queries": updated_queries}
        ), found

    def record_evidence_extracted(
        self,
        *,
        research_run_id: UUID,
        evidence_id: UUID,
        company_id: UUID,
        criterion: str,
        subject: str | None,
        source_url: str,
        source_title: str | None,
        claim: str,
        excerpt: str,
        confidence: float | None,
        refs: Sequence[SearchResultOccurrenceRef],
        prompt_name: str,
        prompt_version: str,
        model: str,
    ) -> None:
        with self._observability.context(
            research_run_id=str(research_run_id),
            company_id=str(company_id),
            workflow_stage="evidence_extraction_persisted",
            prompt_name=prompt_name,
            prompt_version=prompt_version,
            model=model,
        ):
            self._observability.event(
                "research_evidence_extracted",
                evidence_id=str(evidence_id),
                criterion=criterion,
                subject=subject,
                source_url=sanitize_observability_url(source_url),
                source_title=source_title,
                claim=claim[:300],
                excerpt=excerpt[:500],
                confidence=confidence,
                company_attribution_validated=True,
                query_ids=[str(item.query_id) for item in refs],
                result_ids=[str(item.result_id) for item in refs],
                result_ranks=[item.rank for item in refs],
            )

    @staticmethod
    def snapshot(investigation: CompanyInvestigationState) -> dict[str, object]:
        """Build the compact, sanitized source-search persistence shape."""
        queries = []
        for query in investigation.search_queries:
            query_data = query.model_dump(mode="json")
            query_data["results"] = [
                {
                    **result.model_dump(mode="json"),
                    "url": sanitize_observability_url(result.url),
                }
                for result in query.results
            ]
            queries.append(query_data)
        return {"queries": queries}

    @staticmethod
    def _source_key(url: str) -> str:
        try:
            return normalize_fetch_url(url)
        except ValueError:
            return url.strip().casefold()
