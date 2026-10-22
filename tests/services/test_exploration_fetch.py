"""Tests for the Exploration fetch boundary."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from pathlib import Path
from typing import cast

import pytest

from virtual_company.observability import Observability
from virtual_company.services.exploration_fetch import (
    ExplorationFetchFailureCategory,
    ExplorationFetchOutcome,
    ExplorationFetchService,
)
from virtual_company.services.exploration_search import (
    ExplorationQuerySearchResult,
    ExplorationSearchBatchResult,
    ExplorationSearchOutcome,
    ExplorationSearchResultItem,
)
from virtual_company.tools.web_fetch import (
    WebFetchEmptyContentError,
    WebFetchHttpError,
    WebFetchInvalidUrlError,
    WebFetchNetworkError,
    WebFetchResponseTooLargeError,
    WebFetchSsrfError,
    WebFetchTimeoutError,
    WebFetchUnsupportedContentError,
    WebPage,
)


class ObservabilityStub:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []
        self.spans: list[tuple[str, dict[str, object]]] = []

    def event(self, name: str, **context: object) -> None:
        self.events.append((name, context))

    @contextmanager
    def span(self, name: str, **attributes: object):
        self.spans.append((name, attributes))
        yield None


class FetchToolStub:
    provider = "fake-fetch"

    def __init__(self, results: dict[str, WebPage | Exception]) -> None:
        self.results = results
        self.calls: list[str] = []
        self.active = 0
        self.max_active = 0
        self.delay = 0.0

    async def fetch(self, url: str) -> WebPage:
        self.calls.append(url)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            result = self.results[url]
            if isinstance(result, Exception):
                raise result
            return result
        finally:
            self.active -= 1


def item(url: str, title: str | None = None) -> ExplorationSearchResultItem:
    return ExplorationSearchResultItem(
        url=url,
        title=title or f"Search title for {url}",
        snippet=f"Snippet for {url}",
    )


def search_batch(
    *queries: tuple[str, list[ExplorationSearchResultItem]],
) -> ExplorationSearchBatchResult:
    return ExplorationSearchBatchResult(
        provider="exa",
        query_results=[
            ExplorationQuerySearchResult(
                query=query,
                outcome=ExplorationSearchOutcome.SUCCEEDED,
                results=items,
            )
            for query, items in queries
        ],
    )


def page(url: str, **overrides: object) -> WebPage:
    return WebPage(
        url=url,
        final_url=f"{url}/final",
        title="Fetched page title",
        content="Fetched text",
        content_type="text/html",
        truncated=True,
        **overrides,
    )


@pytest.mark.asyncio
async def test_fetch_maps_page_and_preserves_query_result_provenance() -> None:
    search_result = item("https://example.com/page", "Search result title")
    fetch_tool = FetchToolStub({search_result.url: page(search_result.url)})

    result = await ExplorationFetchService(fetch_tool).fetch(
        search_batch(("Acme pricing", [search_result]))
    )

    assert fetch_tool.calls == [search_result.url]
    assert result.results[0].query == "Acme pricing"
    assert result.results[0].search_result == search_result
    assert result.results[0].outcome is ExplorationFetchOutcome.SUCCEEDED
    assert result.results[0].page is not None
    assert result.results[0].page.model_dump() == {
        "url": search_result.url,
        "final_url": f"{search_result.url}/final",
        "title": "Fetched page title",
        "content": "Fetched text",
        "content_type": "text/html",
        "truncated": True,
    }


@pytest.mark.asyncio
async def test_multiple_results_keep_input_order_and_bound_concurrency() -> None:
    urls = [f"https://example.com/{index}" for index in range(7)]
    fetch_tool = FetchToolStub({url: page(url) for url in urls})
    fetch_tool.delay = 0.005
    service = ExplorationFetchService(fetch_tool, concurrency=2)

    result = await service.fetch(
        search_batch(("query", [item(url) for url in urls]))
    )

    assert [outcome.search_result.url for outcome in result.results] == urls
    assert fetch_tool.max_active == 2


@pytest.mark.asyncio
async def test_duplicate_normalized_urls_fetch_once_and_keep_each_provenance() -> None:
    canonical = "https://example.com/article"
    first = item(canonical, "First query title")
    second = item("HTTPS://EXAMPLE.COM:443/article/?utm_source=mail", "Second title")
    fetch_tool = FetchToolStub({canonical: page(canonical)})

    result = await ExplorationFetchService(fetch_tool).fetch(
        search_batch(("query one", [first]), ("query two", [second]))
    )

    assert fetch_tool.calls == [canonical]
    assert [outcome.query for outcome in result.results] == ["query one", "query two"]
    assert [outcome.search_result.title for outcome in result.results] == [
        "First query title",
        "Second title",
    ]
    assert all(outcome.page is not None for outcome in result.results)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "category"),
    [
        (WebFetchTimeoutError("secret timeout detail"), ExplorationFetchFailureCategory.TIMEOUT),
        (WebFetchHttpError(404), ExplorationFetchFailureCategory.HTTP_ERROR),
        (WebFetchInvalidUrlError("private user data"), ExplorationFetchFailureCategory.INVALID_URL),
        (WebFetchSsrfError("private address"), ExplorationFetchFailureCategory.SSRF_BLOCKED),
        (WebFetchNetworkError("body secret"), ExplorationFetchFailureCategory.NETWORK_ERROR),
        (WebFetchUnsupportedContentError("application/pdf"), ExplorationFetchFailureCategory.UNSUPPORTED_CONTENT),
        (WebFetchResponseTooLargeError("body too large"), ExplorationFetchFailureCategory.RESPONSE_TOO_LARGE),
        (WebFetchEmptyContentError("page body"), ExplorationFetchFailureCategory.EMPTY_CONTENT),
        (RuntimeError("unexpected response body secret"), ExplorationFetchFailureCategory.UNEXPECTED_ERROR),
    ],
)
async def test_failures_are_safe_and_isolated_from_successful_siblings(
    error: Exception,
    category: ExplorationFetchFailureCategory,
) -> None:
    good_url = "https://example.com/good"
    bad_url = "https://example.com/bad"
    fetch_tool = FetchToolStub({good_url: page(good_url), bad_url: error})
    observability = ObservabilityStub()

    result = await ExplorationFetchService(
        fetch_tool, observability=cast(Observability, observability)
    ).fetch(search_batch(("query", [item(good_url), item(bad_url)])))

    assert [outcome.outcome for outcome in result.results] == [
        ExplorationFetchOutcome.SUCCEEDED,
        ExplorationFetchOutcome.FAILED,
    ]
    failed = result.results[1]
    assert failed.page is None
    assert failed.failure_category is category
    assert str(failed.model_dump()) .find(str(error)) == -1
    assert str(observability.events).find(str(error)) == -1


@pytest.mark.asyncio
async def test_multiple_failures_are_represented_independently_without_retries() -> None:
    urls = ["https://example.com/timeout", "https://example.com/not-found"]
    fetch_tool = FetchToolStub(
        {
            urls[0]: WebFetchTimeoutError("timeout"),
            urls[1]: WebFetchHttpError(404),
        }
    )

    result = await ExplorationFetchService(fetch_tool).fetch(
        search_batch(("query", [item(url) for url in urls]))
    )

    assert [outcome.failure_category for outcome in result.results] == [
        ExplorationFetchFailureCategory.TIMEOUT,
        ExplorationFetchFailureCategory.HTTP_ERROR,
    ]
    assert fetch_tool.calls == urls


@pytest.mark.asyncio
async def test_failed_search_query_is_not_fetched() -> None:
    fetch_tool = FetchToolStub({})
    batch = ExplorationSearchBatchResult(
        provider="exa",
        query_results=[
            ExplorationQuerySearchResult(
                query="failed query",
                outcome=ExplorationSearchOutcome.FAILED,
                results=[item("https://example.com/ignored")],
            )
        ],
    )

    result = await ExplorationFetchService(fetch_tool).fetch(batch)

    assert result.results == []
    assert fetch_tool.calls == []


def test_service_has_no_research_domain_or_workflow_imports() -> None:
    source = Path("src/virtual_company/services/exploration_fetch.py").read_text()

    assert "virtual_company.domain.research" not in source
    assert "virtual_company.workflows.research" not in source
