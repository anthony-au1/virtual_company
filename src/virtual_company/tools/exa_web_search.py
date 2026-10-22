"""Exa implementation of the provider-neutral web-search contract."""

from __future__ import annotations

import asyncio
import logging
import random
import re
from typing import Any

import httpx
from exa_py import AsyncExa
from pydantic import SecretStr

from virtual_company.tools.web_search import (
    SearchResponse,
    SearchResult,
    WebSearchAuthenticationError,
    WebSearchConfigurationError,
    WebSearchError,
    WebSearchRateLimitError,
    WebSearchTimeoutError,
)

EXA_HIGHLIGHT_MAX_CHARACTERS = 500
_MAX_SEARCH_ATTEMPTS = 3
_RETRYABLE_HTTP_STATUS_CODES = {502, 503, 504}
_RETRY_BACKOFF_BASE_SECONDS = 0.25
_RETRY_BACKOFF_JITTER_SECONDS = 0.1
_STATUS_CODE_PATTERN = re.compile(r"\bstatus code\s+(\d{3})\b", re.IGNORECASE)
logger = logging.getLogger(__name__)


class ExaWebSearchTool:
    """Retrieve compact, semantic discovery results from Exa Search."""

    provider = "exa"

    def __init__(
        self, *, api_key: SecretStr | str | None, client: AsyncExa | Any | None = None
    ) -> None:
        resolved_api_key = api_key.get_secret_value() if isinstance(api_key, SecretStr) else api_key
        if not resolved_api_key:
            raise WebSearchConfigurationError(
                "EXA_API_KEY must be configured when WEB_SEARCH_PROVIDER=exa"
            )
        self._client = client or AsyncExa(api_key=resolved_api_key)

    async def search(self, query: str, limit: int = 10) -> SearchResponse:
        """Return Exa's auto-ranked results with short source highlights only."""
        for attempt in range(1, _MAX_SEARCH_ATTEMPTS + 1):
            try:
                response = await self._client.search(
                    query,
                    type="instant",
                    num_results=limit,
                    contents={"highlights": {"max_characters": EXA_HIGHLIGHT_MAX_CHARACTERS}},
                )
                break
            except Exception as error:
                status_code = _http_status_code(error)
                if status_code in {401, 403}:
                    raise WebSearchAuthenticationError(
                        "Exa authentication failed"
                    ) from error
                if status_code == 429:
                    raise WebSearchRateLimitError("Exa rate limit exceeded") from error

                failure_category = _transient_failure_category(error, status_code)
                if failure_category is None:
                    if isinstance(error, httpx.TimeoutException):
                        raise WebSearchTimeoutError(
                            "Exa web search timed out"
                        ) from error
                    raise WebSearchError("Exa web search failed") from error

                if attempt == _MAX_SEARCH_ATTEMPTS:
                    if isinstance(error, httpx.TimeoutException):
                        raise WebSearchTimeoutError(
                            "Exa web search timed out"
                        ) from error
                    raise WebSearchError("Exa web search failed") from error

                backoff_seconds = _retry_backoff_seconds(attempt)
                logger.warning(
                    "web_search_retry",
                    extra={
                        "context": {
                            "provider": self.provider,
                            "attempt": attempt,
                            "max_attempts": _MAX_SEARCH_ATTEMPTS,
                            "failure_category": failure_category,
                            "status_code": status_code,
                            "backoff_seconds": round(backoff_seconds, 3),
                        }
                    },
                )
                await asyncio.sleep(backoff_seconds)
        return SearchResponse(
            results=[
                SearchResult(
                    title=result.title or "",
                    url=result.url,
                    snippet="\n".join(result.highlights) if result.highlights else None,
                )
                for result in response.results
                if result.url
            ]
        )


def _http_status_code(error: Exception) -> int | None:
    """Read structured status first, then narrowly parse exa-py's ValueError."""
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code
    if isinstance(error, ValueError):
        match = _STATUS_CODE_PATTERN.search(str(error))
        if match is not None:
            return int(match.group(1))
    return None


def _transient_failure_category(
    error: Exception, status_code: int | None
) -> str | None:
    """Return a safe category only for provider failures that can recover."""
    if status_code in _RETRYABLE_HTTP_STATUS_CODES:
        return "http_5xx"
    if isinstance(error, httpx.TimeoutException):
        return "timeout"
    if isinstance(error, httpx.TransportError):
        return "network"
    return None


def _retry_backoff_seconds(attempt: int) -> float:
    """Use short exponential delays with bounded jitter before another attempt."""
    delay = _RETRY_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
    return delay + random.uniform(0, _RETRY_BACKOFF_JITTER_SECONDS)
