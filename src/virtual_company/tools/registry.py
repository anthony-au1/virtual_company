"""Configuration-based construction of external research tools."""

from __future__ import annotations

from virtual_company.config import Settings, get_settings
from virtual_company.tools.exa_web_search import ExaWebSearchTool
from virtual_company.tools.httpx_web_fetch import HttpxWebFetchTool
from virtual_company.tools.instrumented_web_fetch import InstrumentedWebFetchTool
from virtual_company.tools.instrumented_web_search import InstrumentedWebSearchTool
from virtual_company.tools.tavily_web_search import TavilyWebSearchTool
from virtual_company.tools.web_fetch import WebFetchTool
from virtual_company.tools.web_search import WebSearchTool


def create_web_search_tool(settings: Settings | None = None) -> WebSearchTool:
    """Build exactly one configured and instrumented web-search provider."""
    resolved_settings = settings or get_settings()
    if resolved_settings.web_search_provider == "tavily":
        tool = TavilyWebSearchTool(
            api_key=resolved_settings.tavily_api_key,
            search_depth=resolved_settings.tavily_search_depth,
        )
    elif resolved_settings.web_search_provider == "exa":
        tool = ExaWebSearchTool(api_key=resolved_settings.exa_api_key)
    else:  # Kept for protection if Settings is constructed outside normal validation.
        raise ValueError(f"Unsupported web search provider {resolved_settings.web_search_provider!r}")
    return InstrumentedWebSearchTool(tool)


def create_web_fetch_tool(settings: Settings | None = None) -> WebFetchTool:
    """Build the instrumented direct-HTTP fetch implementation."""
    resolved_settings = settings or get_settings()
    return InstrumentedWebFetchTool(
        HttpxWebFetchTool(
            timeout_seconds=resolved_settings.web_fetch_timeout_seconds,
            max_response_bytes=resolved_settings.web_fetch_max_response_bytes,
            max_content_chars=resolved_settings.web_fetch_max_content_chars,
        )
    )
