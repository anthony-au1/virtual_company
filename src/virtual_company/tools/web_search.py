"""Web search provider contract."""

from __future__ import annotations

from typing import Protocol

from virtual_company.research.models import SearchResult


class WebSearchTool(Protocol):
    """Find web pages relevant to a query."""

    async def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        """Return up to ``limit`` search results for ``query``."""
