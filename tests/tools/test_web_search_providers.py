"""Mocked unit and contract tests for real web-search adapters."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import SecretStr
from tavily import InvalidAPIKeyError, UsageLimitExceededError

from virtual_company.config import Settings
from virtual_company.research.models import SearchResult
from virtual_company.tools.exa_web_search import ExaWebSearchTool
from virtual_company.tools.instrumented_web_search import InstrumentedWebSearchTool
from virtual_company.tools.registry import create_web_search_tool
from virtual_company.tools.tavily_web_search import TavilyWebSearchTool
from virtual_company.tools.web_search import (
    WebSearchAuthenticationError,
    WebSearchConfigurationError,
    WebSearchRateLimitError,
)


class TavilyClientFake:
    def __init__(self, response: dict[str, object] | Exception) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    async def search(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(kwargs)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class ExaClientFake:
    def __init__(self, response: object | Exception) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def search(self, query: str, **kwargs: object) -> object:
        self.calls.append((query, kwargs))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


@pytest.mark.asyncio
async def test_tavily_maps_compact_results_and_forwards_limit() -> None:
    client = TavilyClientFake(
        {"results": [{"title": "Acme", "url": "https://acme.example", "content": "Fintech"}]}
    )
    tool = TavilyWebSearchTool(api_key="test-key", search_depth="basic", client=client)

    assert await tool.search("Australian fintech", limit=7) == [
        SearchResult(title="Acme", url="https://acme.example", snippet="Fintech")
    ]
    assert client.calls == [
        {
            "query": "Australian fintech",
            "search_depth": "basic",
            "topic": "general",
            "max_results": 7,
            "include_answer": False,
            "include_raw_content": False,
            "include_images": False,
        }
    ]


@pytest.mark.asyncio
async def test_tavily_empty_response_and_known_failures() -> None:
    empty = TavilyWebSearchTool(api_key="test-key", client=TavilyClientFake({"results": []}))
    assert await empty.search("nothing") == []

    auth = TavilyWebSearchTool(
        api_key="test-key", client=TavilyClientFake(InvalidAPIKeyError("bad key"))
    )
    with pytest.raises(WebSearchAuthenticationError, match="authentication"):
        await auth.search("query")

    limited = TavilyWebSearchTool(
        api_key="test-key", client=TavilyClientFake(UsageLimitExceededError("limited"))
    )
    with pytest.raises(WebSearchRateLimitError, match="rate limit"):
        await limited.search("query")


@pytest.mark.asyncio
async def test_exa_maps_highlights_and_forwards_limit() -> None:
    response = SimpleNamespace(
        results=[
            SimpleNamespace(title="Acme", url="https://acme.example", highlights=["Fintech", "Java"])
        ]
    )
    client = ExaClientFake(response)
    tool = ExaWebSearchTool(api_key="test-key", client=client)

    assert await tool.search("Australian fintech", limit=6) == [
        SearchResult(title="Acme", url="https://acme.example", snippet="Fintech\nJava")
    ]
    assert client.calls == [
        (
            "Australian fintech",
            {
                "type": "auto",
                "num_results": 6,
                "contents": {"highlights": {"max_characters": 500}},
            },
        )
    ]


@pytest.mark.asyncio
async def test_exa_empty_response_and_known_failures() -> None:
    empty = ExaWebSearchTool(api_key="test-key", client=ExaClientFake(SimpleNamespace(results=[])))
    assert await empty.search("nothing") == []

    auth = ExaWebSearchTool(
        api_key="test-key", client=ExaClientFake(ValueError("Request failed with status code 401"))
    )
    with pytest.raises(WebSearchAuthenticationError, match="authentication"):
        await auth.search("query")

    limited = ExaWebSearchTool(
        api_key="test-key", client=ExaClientFake(ValueError("Request failed with status code 429"))
    )
    with pytest.raises(WebSearchRateLimitError, match="rate limit"):
        await limited.search("query")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool",
    [
        TavilyWebSearchTool(
            api_key="test-key",
            client=TavilyClientFake({"results": [{"title": "T", "url": "https://t.example"}]}),
        ),
        ExaWebSearchTool(
            api_key="test-key",
            client=ExaClientFake(
                SimpleNamespace(results=[SimpleNamespace(title="E", url="https://e.example", highlights=None)])
            ),
        ),
    ],
)
async def test_provider_contract_returns_application_search_results(tool: object) -> None:
    results = await tool.search("query", limit=1)  # type: ignore[union-attr]
    assert all(isinstance(result, SearchResult) for result in results)
    assert len(results) == 1


def test_factory_selects_only_configured_provider_and_validates_key() -> None:
    tavily = create_web_search_tool(Settings(tavily_api_key=SecretStr("test-key")))
    assert isinstance(tavily, InstrumentedWebSearchTool)
    assert tavily.provider == "tavily"

    exa = create_web_search_tool(
        Settings(web_search_provider="exa", exa_api_key=SecretStr("test-key"))
    )
    assert exa.provider == "exa"

    with pytest.raises(WebSearchConfigurationError, match="TAVILY_API_KEY"):
        create_web_search_tool(Settings())
    with pytest.raises(WebSearchConfigurationError, match="EXA_API_KEY"):
        create_web_search_tool(Settings(web_search_provider="exa"))
