"""Fetch Exploration search results through generic web-fetch infrastructure."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from enum import StrEnum
from time import perf_counter

from pydantic import BaseModel, ConfigDict

from virtual_company.config import Settings, get_settings
from virtual_company.observability import Observability, get_observability
from virtual_company.services.exploration_search import (
    ExplorationSearchBatchResult,
    ExplorationSearchOutcome,
    ExplorationSearchResultItem,
)
from virtual_company.tools import create_web_fetch_tool
from virtual_company.tools.web_fetch import (
    WebFetchEmptyContentError,
    WebFetchHttpError,
    WebFetchInvalidUrlError,
    WebFetchNetworkError,
    WebFetchResponseTooLargeError,
    WebFetchSsrfError,
    WebFetchTimeoutError,
    WebFetchTool,
    WebFetchUnsupportedContentError,
    WebPage,
)
from virtual_company.utils.url_normalization import (
    normalize_fetch_url,
    sanitize_observability_url,
)


class ExplorationFetchOutcome(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class ExplorationFetchFailureCategory(StrEnum):
    CONFIGURATION = "configuration"
    INVALID_URL = "invalid_url"
    SSRF_BLOCKED = "ssrf_blocked"
    TIMEOUT = "timeout"
    NETWORK_ERROR = "network_error"
    HTTP_ERROR = "http_error"
    UNSUPPORTED_CONTENT = "unsupported_content"
    RESPONSE_TOO_LARGE = "response_too_large"
    EMPTY_CONTENT = "empty_content"
    UNEXPECTED_ERROR = "unexpected_error"


class ExplorationFetchedPage(BaseModel):
    """Transient page fields useful to later Exploration evidence extraction."""

    model_config = ConfigDict(extra="forbid")

    url: str
    final_url: str | None = None
    title: str | None = None
    content: str
    content_type: str | None = None
    truncated: bool = False


class ExplorationFetchResult(BaseModel):
    """One fetch outcome associated with its originating query and result."""

    model_config = ConfigDict(extra="forbid")

    query: str
    search_result: ExplorationSearchResultItem
    outcome: ExplorationFetchOutcome
    page: ExplorationFetchedPage | None = None
    failure_category: ExplorationFetchFailureCategory | None = None


class ExplorationFetchBatchResult(BaseModel):
    """Ordered fetch outcomes for all results from successful search queries."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    results: list[ExplorationFetchResult]


class ExplorationFetchService:
    """Fetch search result URLs with bounded concurrency and per-URL isolation."""

    def __init__(
        self,
        web_fetch: WebFetchTool,
        *,
        concurrency: int = 5,
        observability: Observability | None = None,
    ) -> None:
        if concurrency < 1:
            raise ValueError("concurrency must be greater than zero")
        self._web_fetch = web_fetch
        self._concurrency = concurrency
        self._observability = observability or get_observability()

    async def fetch(
        self, search_batch: ExplorationSearchBatchResult
    ) -> ExplorationFetchBatchResult:
        """Fetch successful search results once per normalized URL, preserving provenance."""
        associations = [
            (query_result.query, item)
            for query_result in search_batch.query_results
            if query_result.outcome is ExplorationSearchOutcome.SUCCEEDED
            for item in query_result.results
        ]
        urls_by_key: dict[str, str] = {}
        for _, item in associations:
            urls_by_key.setdefault(self._url_key(item.url), item.url)
        unique_urls = list(urls_by_key.values())
        provider = str(getattr(self._web_fetch, "provider", "unknown"))
        metadata = {
            "provider": provider,
            "result_count": len(associations),
            "unique_url_count": len(unique_urls),
            "concurrency_limit": self._concurrency,
        }
        self._observability.event("exploration_fetch_batch_started", **metadata)
        batch_started = perf_counter()
        pages: list[ExplorationFetchedPage | None] = [None] * len(unique_urls)
        failures: list[ExplorationFetchFailureCategory | None] = [None] * len(unique_urls)
        queue: asyncio.Queue[tuple[int, str]] = asyncio.Queue()
        for index, url in enumerate(unique_urls):
            queue.put_nowait((index, url))

        async def worker() -> None:
            while True:
                try:
                    index, url = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                try:
                    pages[index], failures[index] = await self._fetch_one(url, provider)
                finally:
                    queue.task_done()

        try:
            with self._observability.span("exploration.fetch_batch", **metadata):
                await asyncio.gather(
                    *(worker() for _ in range(min(self._concurrency, len(unique_urls))))
                )
        except Exception as error:
            self._observability.event(
                "exploration_fetch_batch_failed",
                duration_ms=int((perf_counter() - batch_started) * 1000),
                error_type=type(error).__name__,
                **metadata,
            )
            raise

        key_to_index = {self._url_key(url): index for index, url in enumerate(unique_urls)}
        results: list[ExplorationFetchResult] = []
        for query, search_result in associations:
            index = key_to_index[self._url_key(search_result.url)]
            page = pages[index]
            failure = failures[index]
            results.append(
                ExplorationFetchResult(
                    query=query,
                    search_result=search_result,
                    outcome=(
                        ExplorationFetchOutcome.SUCCEEDED
                        if page is not None
                        else ExplorationFetchOutcome.FAILED
                    ),
                    page=page,
                    failure_category=failure,
                )
            )

        success_count = sum(result.outcome is ExplorationFetchOutcome.SUCCEEDED for result in results)
        self._observability.event(
            "exploration_fetch_batch_completed",
            duration_ms=int((perf_counter() - batch_started) * 1000),
            succeeded_result_count=success_count,
            failed_result_count=len(results) - success_count,
            **metadata,
        )
        return ExplorationFetchBatchResult(provider=provider, results=results)

    async def _fetch_one(
        self, url: str, provider: str
    ) -> tuple[ExplorationFetchedPage | None, ExplorationFetchFailureCategory | None]:
        safe_url = sanitize_observability_url(url)
        metadata = {"provider": provider, "url": safe_url}
        started = perf_counter()
        self._observability.event("exploration_fetch_started", **metadata)
        try:
            page = await self._web_fetch.fetch(url)
        except Exception as error:  # noqa: BLE001 - isolate each source failure
            category = self._failure_category(error)
            self._observability.event(
                "exploration_fetch_failed",
                duration_ms=int((perf_counter() - started) * 1000),
                failure_category=category.value,
                **metadata,
            )
            return None, category

        mapped_page = self._map_page(page)
        self._observability.event(
            "exploration_fetch_completed",
            duration_ms=int((perf_counter() - started) * 1000),
            content_type=page.content_type,
            content_chars=len(page.content),
            truncated=page.truncated,
            final_url=sanitize_observability_url(page.final_url)
            if page.final_url
            else None,
            **metadata,
        )
        return mapped_page, None

    @staticmethod
    def _map_page(page: WebPage) -> ExplorationFetchedPage:
        return ExplorationFetchedPage(
            url=page.url,
            final_url=page.final_url,
            title=page.title,
            content=page.content,
            content_type=page.content_type,
            truncated=page.truncated,
        )

    @staticmethod
    def _failure_category(error: Exception) -> ExplorationFetchFailureCategory:
        categories: Sequence[
            tuple[type[Exception], ExplorationFetchFailureCategory]
        ] = (
            (WebFetchTimeoutError, ExplorationFetchFailureCategory.TIMEOUT),
            (WebFetchNetworkError, ExplorationFetchFailureCategory.NETWORK_ERROR),
            (WebFetchHttpError, ExplorationFetchFailureCategory.HTTP_ERROR),
            (WebFetchInvalidUrlError, ExplorationFetchFailureCategory.INVALID_URL),
            (WebFetchSsrfError, ExplorationFetchFailureCategory.SSRF_BLOCKED),
            (
                WebFetchUnsupportedContentError,
                ExplorationFetchFailureCategory.UNSUPPORTED_CONTENT,
            ),
            (
                WebFetchResponseTooLargeError,
                ExplorationFetchFailureCategory.RESPONSE_TOO_LARGE,
            ),
            (WebFetchEmptyContentError, ExplorationFetchFailureCategory.EMPTY_CONTENT),
        )
        for error_type, category in categories:
            if isinstance(error, error_type):
                return category
        if getattr(error, "category", None) == "configuration":
            return ExplorationFetchFailureCategory.CONFIGURATION
        return ExplorationFetchFailureCategory.UNEXPECTED_ERROR

    @staticmethod
    def _url_key(url: str) -> str:
        try:
            return normalize_fetch_url(url)
        except ValueError:
            return url.strip()


def create_configured_exploration_fetch_service(
    settings: Settings | None = None,
    *,
    observability: Observability | None = None,
) -> ExplorationFetchService:
    """Build Exploration fetch using generic configured WebFetch infrastructure."""
    resolved_settings = settings or get_settings()
    return ExplorationFetchService(
        create_web_fetch_tool(resolved_settings),
        concurrency=resolved_settings.web_fetch_concurrency,
        observability=observability,
    )
