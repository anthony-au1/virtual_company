"""Web search provider contract."""

from __future__ import annotations

from typing import Protocol

from virtual_company.research.models import SearchResult


class WebSearchNotConfiguredError(RuntimeError):
    """Raised when no concrete web-search provider is configured."""


class WebSearchTool(Protocol):
    """Find web pages relevant to a query."""

    async def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        """Return up to ``limit`` search results for ``query``."""


class UnavailableWebSearchTool:
    """Placeholder used until a concrete web-search provider is configured."""

    async def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        """Raise a clear configuration error without making a network request."""
        raise WebSearchNotConfiguredError("Web search is not configured")
