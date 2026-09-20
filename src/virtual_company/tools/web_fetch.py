"""Provider-neutral web-page fetch contract and failures."""

from __future__ import annotations

from typing import Protocol

from virtual_company.research.models import WebPage


class WebFetchTool(Protocol):
    """Retrieve web-page content for later analysis."""

    async def fetch(self, url: str) -> WebPage:
        """Fetch one web page."""


class WebFetchError(Exception):
    """Base class for source-level web fetch failures."""

    category = "unknown"


class WebFetchConfigurationError(ValueError, WebFetchError):
    """Raised when the fetch implementation is not configured correctly."""

    category = "configuration"


class WebFetchInvalidUrlError(WebFetchError):
    """Raised when a URL cannot safely be fetched."""

    category = "invalid_url"


class WebFetchSsrfError(WebFetchError):
    """Raised when a URL resolves to an internal network address."""

    category = "ssrf_blocked"


class WebFetchTimeoutError(WebFetchError):
    """Raised when a fetch exceeds its configured timeout."""

    category = "timeout"


class WebFetchHttpError(WebFetchError):
    """Raised for non-successful HTTP responses."""

    category = "http_error"

    def __init__(self, status_code: int) -> None:
        super().__init__(f"Web page request failed with HTTP {status_code}")
        self.status_code = status_code


class WebFetchUnsupportedContentError(WebFetchError):
    """Raised when a response is not supported by this fetch slice."""

    category = "unsupported_content"


class WebFetchResponseTooLargeError(WebFetchError):
    """Raised when a response exceeds the configured byte limit."""

    category = "response_too_large"


class WebFetchEmptyContentError(WebFetchError):
    """Raised when useful readable content cannot be extracted."""

    category = "empty_content"
