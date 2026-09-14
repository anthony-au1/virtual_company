"""Configuration-based construction of web-search providers."""

from __future__ import annotations

from virtual_company.config import Settings, get_settings
from virtual_company.tools.exa_web_search import ExaWebSearchTool
from virtual_company.tools.instrumented_web_search import InstrumentedWebSearchTool
from virtual_company.tools.tavily_web_search import TavilyWebSearchTool
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
