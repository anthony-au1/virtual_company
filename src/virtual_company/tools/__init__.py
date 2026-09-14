"""Provider-independent external research tool contracts."""

from virtual_company.tools.registry import create_web_search_tool
from virtual_company.tools.web_fetch import WebFetchTool
from virtual_company.tools.web_search import (
    UnavailableWebSearchTool,
    WebSearchAuthenticationError,
    WebSearchConfigurationError,
    WebSearchError,
    WebSearchNotConfiguredError,
    WebSearchRateLimitError,
    WebSearchTimeoutError,
    WebSearchTool,
)

__all__ = [
    "UnavailableWebSearchTool",
    "WebFetchTool",
    "WebSearchAuthenticationError",
    "WebSearchConfigurationError",
    "WebSearchError",
    "WebSearchNotConfiguredError",
    "WebSearchRateLimitError",
    "WebSearchTimeoutError",
    "WebSearchTool",
    "create_web_search_tool",
]
