"""Provider-neutral observability wrapper for web page fetching."""

from __future__ import annotations

from time import perf_counter

from virtual_company.observability import Observability, get_observability
from virtual_company.research.models import WebPage
from virtual_company.tools.web_fetch import WebFetchTool


class InstrumentedWebFetchTool:
    """Record correlated source-fetch telemetry without exposing page content."""

    def __init__(self, tool: WebFetchTool, observability: Observability | None = None) -> None:
        self._tool = tool
        self._observability = observability or get_observability()
        self.provider = getattr(tool, "provider", "unknown")

    async def fetch(self, url: str) -> WebPage:
        """Fetch one page while emitting bounded metrics and metadata events."""
        metadata = {"provider": self.provider, "url": url}
        self._observability.event("web_fetch_started", **metadata)
        started = perf_counter()
        try:
            with self._observability.span("web_fetch", **metadata):
                page = await self._tool.fetch(url)
        except Exception as error:
            duration = perf_counter() - started
            category = getattr(error, "category", "unknown")
            metric_metadata = {"provider": self.provider, "failure_category": category}
            self._observability.record("web_fetch_requests_total", status="failed", **metric_metadata)
            self._observability.record("web_fetch_failures_total", **metric_metadata)
            self._observability.record(
                "web_fetch_duration_seconds", duration, status="failed", **metric_metadata
            )
            self._observability.event(
                "web_fetch_failed",
                duration_ms=int(duration * 1000),
                error_type=type(error).__name__,
                failure_category=category,
                **metadata,
            )
            raise
        duration = perf_counter() - started
        content_type = self._metric_content_type(page.content_type)
        metric_metadata = {"provider": self.provider, "content_type": content_type}
        self._observability.record("web_fetch_requests_total", status="completed", **metric_metadata)
        self._observability.record(
            "web_fetch_duration_seconds", duration, status="completed", **metric_metadata
        )
        self._observability.record("web_fetch_content_chars", len(page.content), **metric_metadata)
        self._observability.record("web_pages_fetched_total", **metric_metadata)
        if page.truncated:
            self._observability.record("web_pages_truncated_total", **metric_metadata)
        self._observability.event(
            "web_fetch_completed",
            duration_ms=int(duration * 1000),
            content_type=page.content_type,
            extracted_content_chars=len(page.content),
            truncated=page.truncated,
            final_url=page.final_url,
            **metadata,
        )
        return page

    @staticmethod
    def _metric_content_type(content_type: str | None) -> str:
        if content_type == "text/html":
            return "html"
        if content_type == "text/plain":
            return "text"
        return "other"
