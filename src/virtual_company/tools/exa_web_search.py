"""Exa implementation of the provider-neutral web-search contract."""

from __future__ import annotations

from typing import Any

import httpx
from exa_py import AsyncExa
from pydantic import SecretStr

from virtual_company.research.models import SearchResult
from virtual_company.tools.web_search import (
    WebSearchAuthenticationError,
    WebSearchConfigurationError,
    WebSearchError,
    WebSearchRateLimitError,
    WebSearchTimeoutError,
)

EXA_HIGHLIGHT_MAX_CHARACTERS = 500


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

    async def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        """Return Exa's auto-ranked results with short source highlights only."""
        try:
            response = await self._client.search(
                query,
                type="auto",
                num_results=limit,
                contents={"highlights": {"max_characters": EXA_HIGHLIGHT_MAX_CHARACTERS}},
            )
        except httpx.TimeoutException as error:
            raise WebSearchTimeoutError("Exa web search timed out") from error
        except ValueError as error:
            message = str(error)
            if "status code 401" in message or "status code 403" in message:
                raise WebSearchAuthenticationError("Exa authentication failed") from error
            if "status code 429" in message:
                raise WebSearchRateLimitError("Exa rate limit exceeded") from error
            raise WebSearchError("Exa web search failed") from error
        except Exception as error:
            raise WebSearchError("Exa web search failed") from error
        return [
            SearchResult(
                title=result.title or "",
                url=result.url,
                snippet="\n".join(result.highlights) if result.highlights else None,
            )
            for result in response.results
            if result.url
        ]
