"""Tests for provider-neutral search observability."""

from __future__ import annotations

import pytest

from virtual_company.research.models import SearchResult, WebPage
from virtual_company.tools.instrumented_web_fetch import InstrumentedWebFetchTool
from virtual_company.tools.instrumented_web_search import InstrumentedWebSearchTool


class ObservabilityFake:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.metrics: list[tuple[str, dict[str, object]]] = []

    def event(self, name: str, **_context: object) -> None:
        self.events.append(name)

    def record(self, name: str, _value: float = 1, **attributes: object) -> None:
        self.metrics.append((name, attributes))

    def span(self, *_args: object, **_kwargs: object):
        from contextlib import nullcontext

        return nullcontext()


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
    assert ("web_search_requests_total", {"status": "completed", "provider": "tavily", "search_depth": "basic"}) in observability.metrics
    assert ("web_search_results_total", {"provider": "tavily", "search_depth": "basic"}) in observability.metrics


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
