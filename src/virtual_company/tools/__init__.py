"""Provider-independent external research tool contracts."""

from virtual_company.tools.registry import create_web_fetch_tool, create_web_search_tool
from virtual_company.tools.web_fetch import (
    WebFetchConfigurationError,
    WebFetchEmptyContentError,
    WebFetchError,
    WebFetchHttpError,
    WebFetchInvalidUrlError,
    WebFetchResponseTooLargeError,
    WebFetchSsrfError,
    WebFetchTimeoutError,
    WebFetchTool,
    WebFetchUnsupportedContentError,
)
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
    "WebFetchConfigurationError",
    "WebFetchEmptyContentError",
    "WebFetchError",
    "WebFetchHttpError",
    "WebFetchInvalidUrlError",
    "WebFetchResponseTooLargeError",
    "WebFetchSsrfError",
    "WebFetchTimeoutError",
    "WebFetchTool",
    "WebFetchUnsupportedContentError",
    "WebSearchAuthenticationError",
    "WebSearchConfigurationError",
    "WebSearchError",
    "WebSearchNotConfiguredError",
    "WebSearchRateLimitError",
    "WebSearchTimeoutError",
    "WebSearchTool",
    "create_web_fetch_tool",
    "create_web_search_tool",
]
