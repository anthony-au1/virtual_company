"""Provider-neutral observability wrapper for web search."""

from __future__ import annotations

import json
from time import perf_counter

from virtual_company.observability import Observability, get_observability
from virtual_company.tools.web_search import SearchResponse, WebSearchTool

TRACE_SNIPPET_MAX_CHARACTERS = 800


def _trace_search_results(response: SearchResponse) -> str:
    """Serialize bounded result details without changing application results."""
    return json.dumps(
        [
            {
                "rank": rank,
                "title": result.title,
                "url": result.url,
                "snippet": (
                    result.snippet[:TRACE_SNIPPET_MAX_CHARACTERS]
                    if result.snippet is not None
                    else None
                ),
            }
            for rank, result in enumerate(response.results, start=1)
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _update_span_metadata(span: object, metadata: dict[str, str]) -> None:
    """Attach result details to either Langfuse or plain OpenTelemetry spans."""
    update = getattr(span, "update", None)
    if callable(update):
        update(metadata=metadata)
        return
    set_attribute = getattr(span, "set_attribute", None)
    if callable(set_attribute):
        for key, value in metadata.items():
            set_attribute(key, value)


class InstrumentedWebSearchTool:
    """Record one correlated span and bounded metrics per provider request."""

    def __init__(
        self, tool: WebSearchTool, observability: Observability | None = None
    ) -> None:
        self._tool = tool
        self._observability = observability or get_observability()
        self.provider = getattr(tool, "provider", "unknown")
        self._search_depth = getattr(tool, "search_depth", None)

    async def search(self, query: str, limit: int = 10) -> SearchResponse:
        """Search while recording provider-level timing and result-count telemetry."""
        metadata = {"provider": self.provider}
        if self._search_depth is not None:
            metadata["search_depth"] = self._search_depth
        span_metadata = {**metadata, "query": query, "max_results": limit}
        self._observability.event("web_search_started", **metadata)
        started = perf_counter()
        try:
            with self._observability.span("web_search", **span_metadata) as span:
                response = await self._tool.search(query, limit)
                search_response = (
                    response
                    if isinstance(response, SearchResponse)
                    else SearchResponse(results=response)  # type: ignore[arg-type]
                )
                _update_span_metadata(
                    span,
                    {"search_results_json": _trace_search_results(search_response)},
                )
        except Exception as error:
            duration = perf_counter() - started
            self._observability.record(
                "web_search_requests_total", status="failed", **metadata
            )
            self._observability.record("web_search_request_failures_total", **metadata)
            self._observability.record(
                "web_search_request_duration_seconds",
                duration,
                status="failed",
                **metadata,
            )
            self._observability.event(
                "web_search_failed",
                duration_ms=int(duration * 1000),
                error_type=type(error).__name__,
                **metadata,
            )
            raise
        duration = perf_counter() - started
        self._observability.record(
            "web_search_requests_total", status="completed", **metadata
        )
        self._observability.record(
            "web_search_request_duration_seconds",
            duration,
            status="completed",
            **metadata,
        )
        self._observability.record(
            "web_search_results_total", len(search_response.results), **metadata
        )
        self._observability.event(
            "web_search_completed",
            duration_ms=int(duration * 1000),
            result_count=len(search_response.results),
            **metadata,
        )
        if search_response.usage is not None:
            self._observability.event(
                "web_search_usage_reported",
                usage_amount=search_response.usage.amount,
                usage_unit=search_response.usage.unit,
                usage_is_actual=search_response.usage.is_actual,
                **metadata,
            )
        return search_response
