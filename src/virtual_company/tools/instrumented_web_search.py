"""Provider-neutral observability wrapper for web search."""

from __future__ import annotations

from time import perf_counter

from virtual_company.observability import Observability, get_observability
from virtual_company.research.models import SearchResult
from virtual_company.tools.web_search import WebSearchTool


class InstrumentedWebSearchTool:
    """Record one correlated span and bounded metrics per provider request."""

    def __init__(self, tool: WebSearchTool, observability: Observability | None = None) -> None:
        self._tool = tool
        self._observability = observability or get_observability()
        self.provider = getattr(tool, "provider", "unknown")
        self._search_depth = getattr(tool, "search_depth", None)

    async def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        """Search while recording provider-level timing and result-count telemetry."""
        metadata = {"provider": self.provider}
        if self._search_depth is not None:
            metadata["search_depth"] = self._search_depth
        self._observability.event("web_search_started", **metadata)
        started = perf_counter()
        try:
            with self._observability.span("web_search", **metadata):
                results = await self._tool.search(query, limit)
        except Exception as error:
            duration = perf_counter() - started
            self._observability.record("web_search_requests_total", status="failed", **metadata)
            self._observability.record("web_search_request_failures_total", **metadata)
            self._observability.record(
                "web_search_request_duration_seconds", duration, status="failed", **metadata
            )
            self._observability.event(
                "web_search_failed", duration_ms=int(duration * 1000), error_type=type(error).__name__, **metadata
            )
            raise
        duration = perf_counter() - started
        self._observability.record("web_search_requests_total", status="completed", **metadata)
        self._observability.record(
            "web_search_request_duration_seconds", duration, status="completed", **metadata
        )
        self._observability.record("web_search_results_total", len(results), **metadata)
        self._observability.event(
            "web_search_completed", duration_ms=int(duration * 1000), result_count=len(results), **metadata
        )
        return results
