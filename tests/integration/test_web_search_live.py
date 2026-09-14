"""Opt-in live smoke test for the selected real web-search provider."""

from __future__ import annotations

import os

import pytest

from virtual_company.config import Settings
from virtual_company.research.models import SearchResult
from virtual_company.tools.registry import create_web_search_tool


@pytest.mark.integration
@pytest.mark.asyncio
async def test_selected_provider_returns_search_results() -> None:
    if os.getenv("RUN_WEB_SEARCH_INTEGRATION_TESTS") != "true":
        pytest.skip("set RUN_WEB_SEARCH_INTEGRATION_TESTS=true to run live search tests")
    settings = Settings()
    if settings.web_search_provider == "tavily" and settings.tavily_api_key is None:
        pytest.skip("TAVILY_API_KEY is required for Tavily live search")
    if settings.web_search_provider == "exa" and settings.exa_api_key is None:
        pytest.skip("EXA_API_KEY is required for Exa live search")

    results = await create_web_search_tool(settings).search("Java Spring fintech Australia careers")

    assert results
    assert all(isinstance(result, SearchResult) and result.url for result in results)
