"""Unit tests for query-scoped Exploration search."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from typing import cast

import pytest

from virtual_company.config import Settings
from virtual_company.observability import Observability
from virtual_company.services.exploration_query_generator import (
    GeneratedExplorationQuery,
)
from virtual_company.services.exploration_search import (
    ExplorationQuerySearchResult,
    ExplorationSearchBatchResult,
    ExplorationSearchFailureCategory,
    ExplorationSearchOutcome,
    ExplorationSearchService,
    create_configured_exploration_search_service,
)
from virtual_company.tools.web_search import (
    SearchResponse,
    SearchResult,
    WebSearchAuthenticationError,
    WebSearchConfigurationError,
    WebSearchError,
    WebSearchRateLimitError,
    WebSearchTimeoutError,
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


class SearchToolStub:
    provider = "exa"

    def __init__(self, responses: dict[str, object]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, int]] = []
        self.active = 0
        self.max_active = 0
        self.delay_by_query: dict[str, float] = {}

    async def search(self, query: str, limit: int = 10) -> SearchResponse:
        self.calls.append((query, limit))
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if delay := self.delay_by_query.get(query):
                await asyncio.sleep(delay)
            response = self.responses[query]
            if isinstance(response, BaseException):
                raise response
            return cast(SearchResponse, response)
        finally:
            self.active -= 1


def query_results(*queries: str) -> list[GeneratedExplorationQuery]:
    return [GeneratedExplorationQuery(query=query) for query in queries]


def response(*items: tuple[str, str, str | None]) -> SearchResponse:
    return SearchResponse(
        results=[
            SearchResult(title=title, url=url, snippet=snippet)
            for title, url, snippet in items
        ]
    )


@pytest.mark.asyncio
async def test_one_generated_query_is_searched_and_mapped_to_owned_dto() -> None:
    tool = SearchToolStub(
        {
            "Acme Java platform": response(
                ("Acme engineering", "https://acme.example/engineering", "Java stack")
            )
        }
    )

    batch = await ExplorationSearchService(tool).search(
        query_results("Acme Java platform")
    )

    assert tool.calls == [("Acme Java platform", 10)]
    assert batch == ExplorationSearchBatchResult(
        provider="exa",
        query_results=[
            ExplorationQuerySearchResult(
                query="Acme Java platform",
                outcome=ExplorationSearchOutcome.SUCCEEDED,
                results=[
                    {
                        "title": "Acme engineering",
                        "url": "https://acme.example/engineering",
                        "snippet": "Java stack",
                    }
                ],
            )
        ],
    )


@pytest.mark.asyncio
async def test_multiple_queries_keep_association_and_input_order() -> None:
    tool = SearchToolStub(
        {
            "slow query": response(("Slow result", "https://slow.example", None)),
            "fast query": response(("Fast result", "https://fast.example", None)),
        }
    )
    tool.delay_by_query = {"slow query": 0.02}

    batch = await ExplorationSearchService(tool, concurrency=2).search(
        query_results("slow query", "fast query")
    )

    assert [item.query for item in batch.query_results] == ["slow query", "fast query"]
    assert [item.results[0].title for item in batch.query_results] == [
        "Slow result",
        "Fast result",
    ]


@pytest.mark.asyncio
async def test_successful_zero_results_are_not_a_failure() -> None:
    batch = await ExplorationSearchService(
        SearchToolStub({"no results": SearchResponse(results=[])})
    ).search(query_results("no results"))

    query_result = batch.query_results[0]
    assert query_result.outcome is ExplorationSearchOutcome.SUCCEEDED
    assert query_result.results == []
    assert query_result.error_category is None


@pytest.mark.asyncio
async def test_one_query_failure_preserves_successful_sibling_results() -> None:
    tool = SearchToolStub(
        {
            "query A": response(("A result", "https://a.example", None)),
            "query B": WebSearchTimeoutError("safe timeout"),
            "query C": response(("C result", "https://c.example", None)),
        }
    )

    batch = await ExplorationSearchService(tool, concurrency=2).search(
        query_results("query A", "query B", "query C")
    )

    assert [result.outcome for result in batch.query_results] == [
        ExplorationSearchOutcome.SUCCEEDED,
        ExplorationSearchOutcome.FAILED,
        ExplorationSearchOutcome.SUCCEEDED,
    ]
    assert [item.title for item in batch.query_results[0].results] == ["A result"]
    assert batch.query_results[1].error_category is ExplorationSearchFailureCategory.TIMEOUT
    assert [item.title for item in batch.query_results[2].results] == ["C result"]


@pytest.mark.asyncio
async def test_multiple_failed_queries_are_reported_independently() -> None:
    tool = SearchToolStub(
        {
            "first": WebSearchTimeoutError("timeout"),
            "second": WebSearchRateLimitError("rate limit"),
        }
    )

    batch = await ExplorationSearchService(tool).search(query_results("first", "second"))

    assert [item.outcome for item in batch.query_results] == [
        ExplorationSearchOutcome.FAILED,
        ExplorationSearchOutcome.FAILED,
    ]
    assert [item.error_category for item in batch.query_results] == [
        ExplorationSearchFailureCategory.TIMEOUT,
        ExplorationSearchFailureCategory.RATE_LIMITED,
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "category"),
    [
        (WebSearchConfigurationError("secret"), "configuration"),
        (WebSearchAuthenticationError("secret"), "authentication"),
        (WebSearchRateLimitError("secret"), "rate_limited"),
        (WebSearchTimeoutError("secret"), "timeout"),
        (WebSearchError("secret"), "provider_error"),
        (RuntimeError("secret provider body"), "unexpected_error"),
    ],
)
async def test_typed_and_unexpected_failures_are_normalized_safely(
    error: Exception, category: str
) -> None:
    tool = SearchToolStub({"failed": error})
    observability = ObservabilityStub()

    batch = await ExplorationSearchService(
        tool, observability=cast(Observability, observability)
    ).search(query_results("failed"))

    assert batch.query_results[0].outcome is ExplorationSearchOutcome.FAILED
    assert batch.query_results[0].error_category == category
    assert "secret" not in str(batch.query_results[0].model_dump())
    assert "secret provider body" not in str(observability.events)


@pytest.mark.asyncio
async def test_failure_is_not_retried_by_exploration_search_layer() -> None:
    tool = SearchToolStub({"failing": WebSearchTimeoutError("timeout")})

    batch = await ExplorationSearchService(tool).search(query_results("failing"))

    assert batch.query_results[0].outcome is ExplorationSearchOutcome.FAILED
    assert tool.calls == [("failing", 10)]


@pytest.mark.asyncio
async def test_result_limit_is_passed_and_results_are_capped() -> None:
    tool = SearchToolStub(
        {
            "query": response(
                ("One", "https://one.example", None),
                ("Two", "https://two.example", None),
                ("Three", "https://three.example", None),
            )
        }
    )

    batch = await ExplorationSearchService(tool, max_results=2).search(
        query_results("query")
    )

    assert tool.calls == [("query", 2)]
    assert [item.title for item in batch.query_results[0].results] == ["One", "Two"]


@pytest.mark.asyncio
async def test_worker_pool_bounds_concurrency() -> None:
    queries = [f"query {index}" for index in range(8)]
    tool = SearchToolStub({query: response() for query in queries})
    tool.delay_by_query = {query: 0.005 for query in queries}

    await ExplorationSearchService(tool, concurrency=2).search(query_results(*queries))

    assert tool.max_active == 2


@pytest.mark.asyncio
async def test_duplicate_urls_are_removed_within_query_only() -> None:
    shared = ("Same page", "https://example.com/page?utm_source=first", None)
    tool = SearchToolStub(
        {
            "first query": response(
                shared,
                ("Duplicate", "https://EXAMPLE.com/page/", "duplicate"),
                ("Next", "https://example.com/next", None),
            ),
            "second query": response(
                ("Same page", "https://example.com/page?utm_campaign=second", None)
            ),
        }
    )

    batch = await ExplorationSearchService(tool).search(
        query_results("first query", "second query")
    )

    assert [item.title for item in batch.query_results[0].results] == ["Same page", "Next"]
    assert [item.title for item in batch.query_results[1].results] == ["Same page"]


@pytest.mark.asyncio
async def test_observability_records_query_and_batch_outcomes() -> None:
    observability = ObservabilityStub()
    tool = SearchToolStub(
        {
            "has results": response(("Result", "https://example.com/path?token=secret", None)),
            "empty": response(),
            "failed": WebSearchRateLimitError("provider response detail"),
        }
    )

    batch = await ExplorationSearchService(
        tool, observability=cast(Observability, observability)
    ).search(query_results("has results", "empty", "failed"))

    assert batch.provider == "exa"
    assert observability.events[0][0] == "exploration_search_batch_started"
    completed = next(
        context
        for name, context in observability.events
        if name == "exploration_search_batch_completed"
    )
    assert completed["succeeded_query_count"] == 2
    assert completed["failed_query_count"] == 1
    assert completed["result_count"] == 1
    empty = next(
        context
        for name, context in observability.events
        if name == "exploration_query_search_completed"
        and context["query"] == "empty"
    )
    assert empty["outcome"] == "zero_results"
    failure = next(
        context
        for name, context in observability.events
        if name == "exploration_query_search_failed"
    )
    assert failure["error_category"] == "rate_limited"
    assert all("token=secret" not in str(context) for _, context in observability.events)
    assert "provider response detail" not in str(observability.events)
    assert [name for name, _ in observability.spans] == [
        "exploration.search_batch",
        "exploration.query_search",
        "exploration.query_search",
        "exploration.query_search",
    ]


def test_configured_service_forces_exa_but_uses_generic_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import virtual_company.services.exploration_search as module

    created_with: list[Settings] = []
    search_tool = SearchToolStub({})

    def create_tool(settings: Settings):
        created_with.append(settings)
        return search_tool

    monkeypatch.setattr(module, "create_web_search_tool", create_tool)
    configured = Settings(
        web_search_provider="tavily",
        web_search_max_results=4,
        web_search_concurrency=2,
    )

    service = create_configured_exploration_search_service(configured)

    assert created_with[0].web_search_provider == "exa"
    assert service._max_results == 4
    assert service._concurrency == 2


def test_search_boundary_accepts_only_generated_queries() -> None:
    import inspect

    parameters = inspect.signature(ExplorationSearchService.search).parameters
    assert tuple(parameters) == ("self", "queries")
