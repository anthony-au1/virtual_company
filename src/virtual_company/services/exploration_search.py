"""Search generated Exploration queries without workflow-specific orchestration."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from enum import StrEnum
from time import perf_counter
from typing import cast

from pydantic import BaseModel, ConfigDict

from virtual_company.config import Settings, get_settings
from virtual_company.observability import Observability, get_observability
from virtual_company.services.exploration_query_generator import (
    GeneratedExplorationQuery,
)
from virtual_company.tools import (
    WebSearchAuthenticationError,
    WebSearchConfigurationError,
    WebSearchError,
    WebSearchRateLimitError,
    WebSearchTimeoutError,
    WebSearchTool,
    create_web_search_tool,
)
from virtual_company.tools.web_search import SearchResponse
from virtual_company.utils.url_normalization import normalize_fetch_url

DEFAULT_EXPLORATION_SEARCH_CONCURRENCY = 3
DEFAULT_EXPLORATION_SEARCH_RESULT_LIMIT = 10


class ExplorationSearchOutcome(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class ExplorationSearchFailureCategory(StrEnum):
    CONFIGURATION = "configuration"
    AUTHENTICATION = "authentication"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    PROVIDER_ERROR = "provider_error"
    UNEXPECTED_ERROR = "unexpected_error"


class ExplorationSearchResultItem(BaseModel):
    """Minimal provider-neutral result information for later source selection."""

    model_config = ConfigDict(extra="forbid")

    url: str
    title: str
    snippet: str | None = None


class ExplorationQuerySearchResult(BaseModel):
    """Outcome and results for one generated query."""

    model_config = ConfigDict(extra="forbid")

    query: str
    outcome: ExplorationSearchOutcome
    results: list[ExplorationSearchResultItem]
    error_category: ExplorationSearchFailureCategory | None = None


class ExplorationSearchBatchResult(BaseModel):
    """Ordered per-query outcomes from one Exploration search batch."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    query_results: list[ExplorationQuerySearchResult]


class ExplorationSearchService:
    """Run bounded, failure-isolated searches for generated Exploration queries."""

    def __init__(
        self,
        web_search: WebSearchTool,
        *,
        max_results: int = DEFAULT_EXPLORATION_SEARCH_RESULT_LIMIT,
        concurrency: int = DEFAULT_EXPLORATION_SEARCH_CONCURRENCY,
        observability: Observability | None = None,
    ) -> None:
        if max_results < 1:
            raise ValueError("max_results must be greater than zero")
        if concurrency < 1:
            raise ValueError("concurrency must be greater than zero")
        self._web_search = web_search
        self._max_results = max_results
        self._concurrency = concurrency
        self._observability = observability or get_observability()

    async def search(
        self, queries: Sequence[GeneratedExplorationQuery]
    ) -> ExplorationSearchBatchResult:
        """Search queries concurrently while preserving order and per-query outcomes."""
        provider = str(getattr(self._web_search, "provider", "unknown"))
        metadata = {
            "provider": provider,
            "query_count": len(queries),
            "max_results": self._max_results,
            "concurrency_limit": self._concurrency,
        }
        self._observability.event("exploration_search_batch_started", **metadata)
        batch_started = perf_counter()

        outcomes: list[ExplorationQuerySearchResult | None] = [None] * len(queries)
        queue: asyncio.Queue[tuple[int, GeneratedExplorationQuery]] = asyncio.Queue()
        for index, query in enumerate(queries):
            queue.put_nowait((index, query))

        async def worker() -> None:
            while True:
                try:
                    index, query = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                try:
                    outcomes[index] = await self._search_one(query.query, provider)
                finally:
                    queue.task_done()

        worker_count = min(self._concurrency, len(queries))
        try:
            with self._observability.span("exploration.search_batch", **metadata):
                if worker_count:
                    await asyncio.gather(*(worker() for _ in range(worker_count)))
        except Exception as error:
            duration_ms = int((perf_counter() - batch_started) * 1000)
            self._observability.event(
                "exploration_search_batch_failed",
                duration_ms=duration_ms,
                error_type=type(error).__name__,
                **metadata,
            )
            raise

        ordered_outcomes = [cast(ExplorationQuerySearchResult, item) for item in outcomes]
        success_count = sum(
            item.outcome is ExplorationSearchOutcome.SUCCEEDED
            for item in ordered_outcomes
        )
        failed_count = len(ordered_outcomes) - success_count
        result_count = sum(len(item.results) for item in ordered_outcomes)
        duration_ms = int((perf_counter() - batch_started) * 1000)
        self._observability.event(
            "exploration_search_batch_completed",
            duration_ms=duration_ms,
            succeeded_query_count=success_count,
            failed_query_count=failed_count,
            result_count=result_count,
            **metadata,
        )
        return ExplorationSearchBatchResult(
            provider=provider,
            query_results=ordered_outcomes,
        )

    async def _search_one(
        self, query: str, provider: str
    ) -> ExplorationQuerySearchResult:
        metadata = {"provider": provider, "query": query, "limit": self._max_results}
        self._observability.event("exploration_query_search_started", **metadata)
        started = perf_counter()
        try:
            with self._observability.span("exploration.query_search", **metadata):
                response = await self._web_search.search(
                    query, limit=self._max_results
                )
                if not isinstance(response, SearchResponse):
                    response = SearchResponse(results=response)
                results = self._normalize_results(response, self._max_results)
        except Exception as error:  # noqa: BLE001 - isolate failures to this query
            category = self._failure_category(error)
            self._observability.event(
                "exploration_query_search_failed",
                duration_ms=int((perf_counter() - started) * 1000),
                error_category=category.value,
                **metadata,
            )
            return ExplorationQuerySearchResult(
                query=query,
                outcome=ExplorationSearchOutcome.FAILED,
                results=[],
                error_category=category,
            )

        duration_ms = int((perf_counter() - started) * 1000)
        self._observability.event(
            "exploration_query_search_completed",
            duration_ms=duration_ms,
            outcome="zero_results" if not results else "results",
            result_count=len(results),
            **metadata,
        )
        return ExplorationQuerySearchResult(
            query=query,
            outcome=ExplorationSearchOutcome.SUCCEEDED,
            results=results,
        )

    @staticmethod
    def _normalize_results(
        response: SearchResponse, max_results: int
    ) -> list[ExplorationSearchResultItem]:
        normalized: list[ExplorationSearchResultItem] = []
        seen_urls: set[str] = set()
        for result in response.results:
            url_key = normalize_fetch_url(result.url)
            if url_key in seen_urls:
                continue
            seen_urls.add(url_key)
            normalized.append(
                ExplorationSearchResultItem(
                    url=result.url,
                    title=result.title,
                    snippet=result.snippet,
                )
            )
            if len(normalized) >= max_results:
                break
        return normalized

    @staticmethod
    def _failure_category(error: Exception) -> ExplorationSearchFailureCategory:
        if isinstance(error, WebSearchConfigurationError):
            return ExplorationSearchFailureCategory.CONFIGURATION
        if isinstance(error, WebSearchAuthenticationError):
            return ExplorationSearchFailureCategory.AUTHENTICATION
        if isinstance(error, WebSearchRateLimitError):
            return ExplorationSearchFailureCategory.RATE_LIMITED
        if isinstance(error, WebSearchTimeoutError):
            return ExplorationSearchFailureCategory.TIMEOUT
        if isinstance(error, WebSearchError):
            return ExplorationSearchFailureCategory.PROVIDER_ERROR
        return ExplorationSearchFailureCategory.UNEXPECTED_ERROR


def create_configured_exploration_search_service(
    settings: Settings | None = None,
    *,
    observability: Observability | None = None,
) -> ExplorationSearchService:
    """Build Exa-backed search using the existing instrumented provider factory."""
    resolved_settings = settings or get_settings()
    exa_settings = resolved_settings.model_copy(update={"web_search_provider": "exa"})
    return ExplorationSearchService(
        create_web_search_tool(exa_settings),
        max_results=resolved_settings.web_search_max_results,
        concurrency=resolved_settings.web_search_concurrency,
        observability=observability,
    )
