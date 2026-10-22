"""Mocked unit and contract tests for real web-search adapters."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from pydantic import SecretStr
from tavily import InvalidAPIKeyError, UsageLimitExceededError

from virtual_company.config import Settings
from virtual_company.tools.exa_web_search import ExaWebSearchTool
from virtual_company.tools.instrumented_web_search import InstrumentedWebSearchTool
from virtual_company.tools.registry import create_web_search_tool
from virtual_company.tools.tavily_web_search import TavilyWebSearchTool
from virtual_company.tools.web_search import (
    SearchResponse,
    SearchResult,
    WebSearchAuthenticationError,
    WebSearchConfigurationError,
    WebSearchError,
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


class SequencedExaClientFake:
    def __init__(self, responses: list[object | Exception]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def search(self, query: str, **kwargs: object) -> object:
        self.calls.append((query, kwargs))
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def exa_success_response() -> SimpleNamespace:
    return SimpleNamespace(
        results=[
            SimpleNamespace(
                title="Acme", url="https://acme.example", highlights=["Relevant"]
            )
        ]
    )


async def install_no_wait_retry(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr("virtual_company.tools.exa_web_search.asyncio.sleep", fake_sleep)
    monkeypatch.setattr("virtual_company.tools.exa_web_search.random.uniform", lambda *_: 0.05)
    return delays


@pytest.mark.asyncio
async def test_tavily_maps_compact_results_and_forwards_limit() -> None:
    client = TavilyClientFake(
        {
            "results": [
                {"title": "Acme", "url": "https://acme.example", "content": "Fintech"}
            ]
        }
    )
    tool = TavilyWebSearchTool(api_key="test-key", search_depth="basic", client=client)

    assert await tool.search("Australian fintech", limit=7) == SearchResponse(
        results=[
            SearchResult(title="Acme", url="https://acme.example", snippet="Fintech")
        ]
    )
    assert client.calls == [
        {
            "query": "Australian fintech",
            "search_depth": "basic",
            "topic": "general",
            "max_results": 7,
            "include_answer": False,
            "include_raw_content": False,
            "include_images": False,
            "include_usage": True,
        }
    ]


@pytest.mark.asyncio
async def test_tavily_empty_response_and_known_failures() -> None:
    empty = TavilyWebSearchTool(
        api_key="test-key", client=TavilyClientFake({"results": []})
    )
    assert (await empty.search("nothing")).results == []

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
            SimpleNamespace(
                title="Acme", url="https://acme.example", highlights=["Fintech", "Java"]
            )
        ]
    )
    client = ExaClientFake(response)
    tool = ExaWebSearchTool(api_key="test-key", client=client)

    assert (await tool.search("Australian fintech", limit=6)).results == [
        SearchResult(title="Acme", url="https://acme.example", snippet="Fintech\nJava")
    ]
    assert client.calls == [
        (
            "Australian fintech",
            {
                "type": "instant",
                "num_results": 6,
                "contents": {"highlights": {"max_characters": 500}},
            },
        )
    ]


@pytest.mark.asyncio
async def test_exa_empty_response_and_known_failures() -> None:
    empty = ExaWebSearchTool(
        api_key="test-key", client=ExaClientFake(SimpleNamespace(results=[]))
    )
    assert (await empty.search("nothing")).results == []

    auth = ExaWebSearchTool(
        api_key="test-key",
        client=ExaClientFake(ValueError("Request failed with status code 401")),
    )
    with pytest.raises(WebSearchAuthenticationError, match="authentication"):
        await auth.search("query")

    limited = ExaWebSearchTool(
        api_key="test-key",
        client=ExaClientFake(ValueError("Request failed with status code 429")),
    )
    with pytest.raises(WebSearchRateLimitError, match="rate limit"):
        await limited.search("query")


@pytest.mark.asyncio
async def test_exa_success_on_first_attempt_makes_one_provider_call() -> None:
    client = SequencedExaClientFake([exa_success_response()])
    tool = ExaWebSearchTool(api_key="test-key", client=client)

    response = await tool.search("query")

    assert len(response.results) == 1
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_exa_retries_transient_gateway_error_then_succeeds(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    delays = await install_no_wait_retry(monkeypatch)
    client = SequencedExaClientFake(
        [ValueError("Request failed with status code 504: gateway body"), exa_success_response()]
    )
    tool = ExaWebSearchTool(api_key="test-key", client=client)

    response = await tool.search("query")

    assert len(response.results) == 1
    assert len(client.calls) == 2
    assert delays == [0.3]
    retry_record = next(
        record for record in caplog.records if record.getMessage() == "web_search_retry"
    )
    assert retry_record.context == {
        "provider": "exa",
        "attempt": 1,
        "max_attempts": 3,
        "failure_category": "http_5xx",
        "status_code": 504,
        "backoff_seconds": 0.3,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [502, 503])
async def test_exa_retries_502_and_503_provider_errors(
    monkeypatch: pytest.MonkeyPatch, status_code: int
) -> None:
    await install_no_wait_retry(monkeypatch)
    client = SequencedExaClientFake(
        [ValueError(f"Request failed with status code {status_code}"), exa_success_response()]
    )
    tool = ExaWebSearchTool(api_key="test-key", client=client)

    await tool.search("query")

    assert len(client.calls) == 2


@pytest.mark.asyncio
async def test_exa_transient_gateway_error_exhausts_three_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delays = await install_no_wait_retry(monkeypatch)
    failure = ValueError("Request failed with status code 504: gateway body")
    client = SequencedExaClientFake([failure, failure, failure])
    tool = ExaWebSearchTool(api_key="test-key", client=client)

    with pytest.raises(WebSearchError, match="Exa web search failed") as raised:
        await tool.search("query")

    assert len(client.calls) == 3
    assert delays == [0.3, 0.55]
    assert raised.value.__cause__ is failure


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [httpx.ReadTimeout("timed out"), httpx.ConnectError("connection failed")],
)
async def test_exa_retries_timeout_and_network_errors(
    monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    await install_no_wait_retry(monkeypatch)
    client = SequencedExaClientFake([failure, exa_success_response()])
    tool = ExaWebSearchTool(api_key="test-key", client=client)

    await tool.search("query")

    assert len(client.calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("message", "error_type"),
    [
        ("Request failed with status code 401", WebSearchAuthenticationError),
        ("Request failed with status code 403", WebSearchAuthenticationError),
        ("Request failed with status code 400", WebSearchError),
        ("Request failed with status code 429", WebSearchRateLimitError),
        ("Unsupported HTTP method: PUT", WebSearchError),
    ],
)
async def test_exa_does_not_retry_permanent_or_rate_limited_errors(
    monkeypatch: pytest.MonkeyPatch, message: str, error_type: type[Exception]
) -> None:
    delays = await install_no_wait_retry(monkeypatch)
    client = SequencedExaClientFake([ValueError(message)])
    tool = ExaWebSearchTool(api_key="test-key", client=client)

    with pytest.raises(error_type):
        await tool.search("query")

    assert len(client.calls) == 1
    assert delays == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool",
    [
        TavilyWebSearchTool(
            api_key="test-key",
            client=TavilyClientFake(
                {"results": [{"title": "T", "url": "https://t.example"}]}
            ),
        ),
        ExaWebSearchTool(
            api_key="test-key",
            client=ExaClientFake(
                SimpleNamespace(
                    results=[
                        SimpleNamespace(
                            title="E", url="https://e.example", highlights=None
                        )
                    ]
                )
            ),
        ),
    ],
)
async def test_provider_contract_returns_application_search_results(
    tool: object,
) -> None:
    results = await tool.search("query", limit=1)  # type: ignore[union-attr]
    assert all(isinstance(result, SearchResult) for result in results)
    assert len(results) == 1


@pytest.mark.asyncio
async def test_tavily_exposes_provider_reported_credit_usage() -> None:
    client = TavilyClientFake(
        {
            "results": [],
            "usage": {"credits": 3},
        }
    )
    tool = TavilyWebSearchTool(api_key="test-key", client=client)

    response = await tool.search("query")

    assert response.results == []
    assert response.usage is not None
    assert (response.usage.amount, response.usage.unit, response.usage.is_actual) == (
        3.0,
        "credits",
        True,
    )


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
