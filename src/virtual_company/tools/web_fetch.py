"""Web-page fetch provider contract."""

from __future__ import annotations

from typing import Protocol

from virtual_company.research.models import WebPage


class WebFetchTool(Protocol):
    """Retrieve web-page content for later analysis."""

    async def fetch(self, url: str) -> WebPage:
        """Fetch one web page."""
