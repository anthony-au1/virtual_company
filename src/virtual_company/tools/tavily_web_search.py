"""Tavily implementation of the provider-neutral web-search contract."""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import SecretStr
from tavily import AsyncTavilyClient, InvalidAPIKeyError, UsageLimitExceededError

from virtual_company.research.models import SearchResult
from virtual_company.tools.web_search import (
    WebSearchAuthenticationError,
    WebSearchConfigurationError,
    WebSearchError,
    WebSearchRateLimitError,
    WebSearchTimeoutError,
)


class TavilyWebSearchTool:
    """Retrieve compact discovery results from Tavily Search."""

    provider = "tavily"

    def __init__(
        self,
        *,
        api_key: SecretStr | str | None,
        search_depth: str = "basic",
        client: AsyncTavilyClient | Any | None = None,
    ) -> None:
        resolved_api_key = api_key.get_secret_value() if isinstance(api_key, SecretStr) else api_key
        if not resolved_api_key:
            raise WebSearchConfigurationError(
                "TAVILY_API_KEY must be configured when WEB_SEARCH_PROVIDER=tavily"
            )
        self.search_depth = search_depth
        self._client = client or AsyncTavilyClient(api_key=resolved_api_key)

    async def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        """Return Tavily-ranked search results without generated answers or page text."""
        try:
            response = await self._client.search(
                query=query,
                search_depth=self.search_depth,
                topic="general",
                max_results=limit,
                include_answer=False,
                include_raw_content=False,
                include_images=False,
            )
        except InvalidAPIKeyError as error:
            raise WebSearchAuthenticationError("Tavily authentication failed") from error
        except UsageLimitExceededError as error:
            raise WebSearchRateLimitError("Tavily rate limit exceeded") from error
        except httpx.TimeoutException as error:
            raise WebSearchTimeoutError("Tavily web search timed out") from error
        except Exception as error:
            raise WebSearchError("Tavily web search failed") from error
        return [
            SearchResult(
                title=result.get("title") or "",
                url=result["url"],
                snippet=result.get("content"),
            )
            for result in response.get("results", [])
            if result.get("url")
        ]
