"""Provider-independent external tool contracts and factories.

Exports are loaded on demand so importing web-search contracts does not also
load fetch implementations or their workflow-specific model dependencies.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORT_MODULES = {
    "UnavailableWebSearchTool": "virtual_company.tools.web_search",
    "WebSearchAuthenticationError": "virtual_company.tools.web_search",
    "WebSearchConfigurationError": "virtual_company.tools.web_search",
    "WebSearchError": "virtual_company.tools.web_search",
    "WebSearchNotConfiguredError": "virtual_company.tools.web_search",
    "WebSearchRateLimitError": "virtual_company.tools.web_search",
    "WebSearchTimeoutError": "virtual_company.tools.web_search",
    "WebSearchTool": "virtual_company.tools.web_search",
    "WebFetchConfigurationError": "virtual_company.tools.web_fetch",
    "WebFetchEmptyContentError": "virtual_company.tools.web_fetch",
    "WebFetchError": "virtual_company.tools.web_fetch",
    "WebFetchHttpError": "virtual_company.tools.web_fetch",
    "WebFetchInvalidUrlError": "virtual_company.tools.web_fetch",
    "WebFetchResponseTooLargeError": "virtual_company.tools.web_fetch",
    "WebFetchSsrfError": "virtual_company.tools.web_fetch",
    "WebFetchTimeoutError": "virtual_company.tools.web_fetch",
    "WebFetchTool": "virtual_company.tools.web_fetch",
    "WebFetchUnsupportedContentError": "virtual_company.tools.web_fetch",
    "create_web_fetch_tool": "virtual_company.tools.registry",
    "create_web_search_tool": "virtual_company.tools.registry",
}

__all__ = list(_EXPORT_MODULES)


def __getattr__(name: str) -> Any:
    """Load a public tool contract or factory when it is first requested."""
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value
