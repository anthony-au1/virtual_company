"""Provider-independent external research tool contracts."""

from virtual_company.tools.web_fetch import WebFetchTool
from virtual_company.tools.web_search import (
    UnavailableWebSearchTool,
    WebSearchNotConfiguredError,
    WebSearchTool,
)

__all__ = [
    "UnavailableWebSearchTool",
    "WebFetchTool",
    "WebSearchNotConfiguredError",
    "WebSearchTool",
]
