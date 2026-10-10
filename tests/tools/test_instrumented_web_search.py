"""Tests for provider-neutral search observability."""

from __future__ import annotations

import json
from contextlib import contextmanager

import pytest

from virtual_company.research.models import SearchResult, WebPage
from virtual_company.tools.instrumented_web_fetch import InstrumentedWebFetchTool
from virtual_company.tools.instrumented_web_search import InstrumentedWebSearchTool
from virtual_company.tools.web_search import SearchResponse, SearchUsage


class ObservabilityFake:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.event_contexts: list[tuple[str, dict[str, object]]] = []
        self.metrics: list[tuple[str, dict[str, object]]] = []
        self.spans: list[tuple[str, dict[str, object], dict[str, object]]] = []

    def event(self, name: str, **context: object) -> None:
        self.events.append(name)
        self.event_contexts.append((name, context))

    def record(self, name: str, _value: float = 1, **attributes: object) -> None:
        self.metrics.append((name, attributes))

    @contextmanager
    def span(self, name: str, **attributes: object):
        updated: dict[str, object] = {}
        self.spans.append((name, attributes, updated))
        yield SpanFake(updated)


class SpanFake:
    def __init__(self, updated: dict[str, object]) -> None:
        self.updated = updated

    def update(self, *, metadata: dict[str, object]) -> None:
        self.updated.update(metadata)


class ToolFake:
    provider = "tavily"
    search_depth = "basic"

    async def search(self, _query: str, _limit: int) -> list[SearchResult]:
        return [SearchResult(title="Acme", url="https://acme.example")]


class FetchToolFake:
    provider = "httpx"

    async def fetch(self, url: str) -> WebPage:
        return WebPage(
            url=url,
            final_url=url,
            content="Useful content",
            content_type="text/html",
            truncated=True,
        )


@pytest.mark.asyncio
async def test_instrumented_search_records_low_cardinality_metrics() -> None:
    observability = ObservabilityFake()
    tool = InstrumentedWebSearchTool(ToolFake(), observability=observability)  # type: ignore[arg-type]

    await tool.search("not a metric attribute", limit=1)

    assert observability.events == ["web_search_started", "web_search_completed"]
    assert (
        "web_search_requests_total",
        {"status": "completed", "provider": "tavily", "search_depth": "basic"},
    ) in observability.metrics
    assert (
        "web_search_results_total",
        {"provider": "tavily", "search_depth": "basic"},
    ) in observability.metrics
    name, attributes, updated = observability.spans[0]
    assert name == "web_search"
    assert attributes["query"] == "not a metric attribute"
    assert attributes["max_results"] == 1
    assert json.loads(str(updated["search_results_json"])) == [
        {
            "rank": 1,
            "title": "Acme",
            "url": "https://acme.example",
            "snippet": None,
        }
    ]


@pytest.mark.asyncio
async def test_search_trace_preserves_provider_order_and_bounds_snippets() -> None:
    long_snippet = "x" * 900
    returned = SearchResponse(
        results=[
            SearchResult(
                title="First",
                url="https://example.com/first",
                snippet=long_snippet,
            ),
            SearchResult(
                title="Second",
                url="https://example.com/second",
                snippet="Second snippet",
            ),
        ]
    )

    class ResultsToolFake(ToolFake):
        async def search(self, _query: str, _limit: int) -> SearchResponse:
            return returned

    observability = ObservabilityFake()
    tool = InstrumentedWebSearchTool(
        ResultsToolFake(), observability=observability  # type: ignore[arg-type]
    )

    response = await tool.search("exact Tavily query", limit=7)

    assert response is returned
    assert response.results[0].snippet == long_snippet
    _name, attributes, updated = observability.spans[0]
    assert attributes["query"] == "exact Tavily query"
    assert attributes["max_results"] == 7
    assert attributes["search_depth"] == "basic"
    traced_results = json.loads(str(updated["search_results_json"]))
    assert [item["rank"] for item in traced_results] == [1, 2]
    assert [item["url"] for item in traced_results] == [
        "https://example.com/first",
        "https://example.com/second",
    ]
    assert [item["title"] for item in traced_results] == ["First", "Second"]
    assert traced_results[0]["snippet"] == "x" * 800
    assert traced_results[1]["snippet"] == "Second snippet"


@pytest.mark.asyncio
async def test_empty_search_results_are_recorded_as_empty_json_list() -> None:
    class EmptyToolFake(ToolFake):
        async def search(self, _query: str, _limit: int) -> SearchResponse:
            return SearchResponse(results=[])

    observability = ObservabilityFake()
    tool = InstrumentedWebSearchTool(
        EmptyToolFake(), observability=observability  # type: ignore[arg-type]
    )

    response = await tool.search("no matching results")

    assert response.results == []
    assert json.loads(str(observability.spans[0][2]["search_results_json"])) == []


@pytest.mark.asyncio
async def test_instrumented_search_emits_provider_usage_as_actual() -> None:
    class UsageToolFake(ToolFake):
        async def search(self, _query: str, _limit: int) -> SearchResponse:
            return SearchResponse(
                results=[SearchResult(title="Acme", url="https://acme.example")],
                usage=SearchUsage(amount=2, unit="credits", is_actual=True),
            )

    observability = ObservabilityFake()
    tool = InstrumentedWebSearchTool(
        UsageToolFake(),
        observability=observability,  # type: ignore[arg-type]
    )

    response = await tool.search("query", limit=1)

    assert response.usage == SearchUsage(amount=2, unit="credits", is_actual=True)
    assert any(name == "web_search_usage_reported" for name in observability.events)


@pytest.mark.asyncio
async def test_instrumented_fetch_records_low_cardinality_metrics() -> None:
    observability = ObservabilityFake()
    tool = InstrumentedWebFetchTool(FetchToolFake(), observability=observability)  # type: ignore[arg-type]

    await tool.fetch("https://acme.example/careers/backend")

    assert observability.events == ["web_fetch_started", "web_fetch_completed"]
    assert (
        "web_fetch_requests_total",
        {"status": "completed", "provider": "httpx", "content_type": "html"},
    ) in observability.metrics
    assert (
        "web_pages_truncated_total",
        {"provider": "httpx", "content_type": "html"},
    ) in observability.metrics
