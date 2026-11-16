"""Tests for the OpenAI LLM provider boundary."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from pydantic import BaseModel, SecretStr

from virtual_company.config import Settings
from virtual_company.llm import (
    LLMConfigurationError,
    LLMStructuredOutputError,
    OpenAIProvider,
)


class CompanyName(BaseModel):
    """Structured output used by provider tests."""

    name: str


def client_with_response(parsed: CompanyName | None) -> MagicMock:
    """Build a mock OpenAI client with a structured response."""
    client = MagicMock()
    client.responses.parse = AsyncMock(
        return_value=SimpleNamespace(output_parsed=parsed)
    )
    return client


@pytest.mark.asyncio
async def test_generate_structured_returns_parsed_pydantic_model() -> None:
    parsed = CompanyName(name="Example Inc.")
    client = client_with_response(parsed)
    provider = OpenAIProvider(
        api_key=SecretStr("test-key"), model="gpt-5.6-terra", client=client
    )

    result = await provider.generate_structured(
        system_prompt="Extract a company name.",
        user_prompt="Example Inc.",
        response_model=CompanyName,
    )

    assert result is parsed
    client.responses.parse.assert_awaited_once_with(
        model="gpt-5.6-terra",
        instructions="Extract a company name.",
        input="Example Inc.",
        text_format=CompanyName,
        max_output_tokens=32_768,
    )


@pytest.mark.parametrize(
    ("api_key", "model"),
    [(None, "gpt-5.6-terra"), (SecretStr("test-key"), None)],
)
def test_provider_requires_openai_configuration(
    api_key: SecretStr | None, model: str | None
) -> None:
    with pytest.raises(LLMConfigurationError, match="OPENAI_API_KEY"):
        OpenAIProvider(api_key=api_key, model=model)


@pytest.mark.asyncio
async def test_generate_structured_raises_when_response_is_not_parsed() -> None:
    provider = OpenAIProvider(
        api_key="test-key",
        model="gpt-5.6-terra",
        client=client_with_response(None),
    )

    with pytest.raises(LLMStructuredOutputError, match="no structured output"):
        await provider.generate_structured(
            system_prompt="System prompt",
            user_prompt="User prompt",
            response_model=CompanyName,
        )


@pytest.mark.asyncio
async def test_generate_structured_propagates_unexpected_sdk_errors() -> None:
    client = client_with_response(CompanyName(name="Unused"))
    client.responses.parse.side_effect = RuntimeError("OpenAI unavailable")
    provider = OpenAIProvider(
        api_key="test-key", model="gpt-5.6-terra", client=client
    )

    with pytest.raises(RuntimeError, match="OpenAI unavailable"):
        await provider.generate_structured(
            system_prompt="System prompt",
            user_prompt="User prompt",
            response_model=CompanyName,
        )


@pytest.mark.asyncio
async def test_model_rejected_reasoning_effort_propagates_provider_error() -> None:
    client = client_with_response(CompanyName(name="Unused"))
    client.responses.parse.side_effect = RuntimeError(
        "configured model does not support this reasoning effort"
    )
    provider = OpenAIProvider(
        api_key="test-key",
        model="configured-model",
        client=client,
        reasoning_effort="high",
    )

    with pytest.raises(RuntimeError, match="does not support"):
        await provider.generate_structured(
            system_prompt="System prompt",
            user_prompt="User prompt",
            response_model=CompanyName,
        )

    assert client.responses.parse.await_args.kwargs["reasoning"] == {
        "effort": "high"
    }


def test_client_uses_configured_timeout_and_retry_settings(monkeypatch) -> None:
    settings = Settings(
        openai_connect_timeout_seconds=4.5,
        openai_read_timeout_seconds=90,
        openai_max_retries=1,
    )
    captured: dict[str, object] = {}

    def create_client(**kwargs):
        captured.update(kwargs)
        return client_with_response(CompanyName(name="Unused"))

    monkeypatch.setattr("virtual_company.llm.openai_provider.get_settings", lambda: settings)
    monkeypatch.setattr("virtual_company.llm.openai_provider.AsyncOpenAI", create_client)

    OpenAIProvider(api_key="test-key", model="gpt-6.1-terra")

    timeout = captured["timeout"]
    assert isinstance(timeout, httpx.Timeout)
    assert timeout.connect == 4.5
    assert timeout.read == 90
    assert timeout.write == 90
    assert timeout.pool == 90
    assert captured["max_retries"] == 1
    assert captured["api_key"] == "test-key"


@pytest.mark.asyncio
async def test_timeout_after_sdk_retries_propagates_from_provider() -> None:
    timeout_error = httpx.ReadTimeout("socket read timed out")
    client = client_with_response(CompanyName(name="Unused"))
    client.responses.parse.side_effect = timeout_error
    provider = OpenAIProvider(
        api_key="test-key", model="gpt-6.1-terra", client=client
    )

    with pytest.raises(httpx.ReadTimeout) as raised:
        await provider.generate_structured(
            system_prompt="System prompt",
            user_prompt="User prompt",
            response_model=CompanyName,
        )

    assert raised.value is timeout_error
    client.responses.parse.assert_awaited_once()


class UsageTelemetryFake:
    def __init__(self) -> None:
        self.current_context: dict[str, str] = {}
        self.events: list[tuple[str, dict[str, object]]] = []
        self.metrics: list[tuple[str, float, dict[str, str]]] = []

    def event(self, name: str, **fields: object) -> None:
        self.events.append((name, fields))

    def record(self, name: str, value: float = 1, **fields: str) -> None:
        self.metrics.append((name, value, fields))


@pytest.mark.asyncio
async def test_openai_maps_output_limit_reasoning_and_provider_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from virtual_company.llm import usage as usage_module

    telemetry = UsageTelemetryFake()
    monkeypatch.setattr(usage_module, "get_observability", lambda: telemetry)
    usage = SimpleNamespace(
        input_tokens=120,
        output_tokens=45,
        total_tokens=165,
        input_tokens_details=SimpleNamespace(cached_tokens=20, cache_write_tokens=30),
        output_tokens_details=SimpleNamespace(reasoning_tokens=12),
    )
    client = client_with_response(CompanyName(name="Example"))
    client.responses.parse.return_value = SimpleNamespace(
        output_parsed=CompanyName(name="Example"),
        id="resp-1",
        _request_id="req-1",
        model="custom-openai-model",
        service_tier="default",
        status="completed",
        incomplete_details=None,
        usage=usage,
    )
    provider = OpenAIProvider(
        api_key="test-key",
        model="custom-openai-model",
        role="research",
        client=client,
        max_output_tokens=512,
        reasoning_effort="low",
    )

    result = await provider.generate_structured(
        system_prompt="system", user_prompt="user", response_model=CompanyName
    )

    assert result == CompanyName(name="Example")
    assert client.responses.parse.await_args.kwargs["max_output_tokens"] == 512
    assert client.responses.parse.await_args.kwargs["reasoning"] == {"effort": "low"}
    name, fields = telemetry.events[0]
    assert name == "llm_usage_reported"
    assert fields["provider"] == "openai"
    assert fields["model"] == "custom-openai-model"
    assert fields["role"] == "research"
    assert fields["input_tokens"] == 120
    assert fields["output_tokens"] == 45
    assert fields["total_tokens"] == 165
    assert fields["reasoning_tokens"] == 12
    assert fields["configured_output_tokens"] == 512
    assert fields["configured_max_retries"] == 1
    assert fields["cached_input_tokens"] == 20
    assert fields["cache_write_input_tokens"] == 30
    assert fields["response_id"] == "resp-1"
    assert fields["request_id"] == "req-1"
    assert fields["service_tier"] == "default"
    assert fields["response_status"] == "completed"
    assert fields["request_outcome"] == "completed"
    assert sum(value for metric, value, _ in telemetry.metrics if metric == "llm_input_tokens_total") == 120


@pytest.mark.asyncio
async def test_openai_omits_reasoning_parameter_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(openai_reasoning_effort=None)
    monkeypatch.setattr("virtual_company.llm.openai_provider.get_settings", lambda: settings)
    client = client_with_response(CompanyName(name="Example"))
    provider = OpenAIProvider(
        api_key="test-key", model="arbitrary-model", client=client
    )

    await provider.generate_structured(
        system_prompt="system", user_prompt="user", response_model=CompanyName
    )

    assert "reasoning" not in client.responses.parse.await_args.kwargs
    assert client.responses.parse.await_args.kwargs["max_output_tokens"] == 32_768


@pytest.mark.asyncio
async def test_openai_incomplete_response_is_reported_then_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from virtual_company.llm import usage as usage_module

    telemetry = UsageTelemetryFake()
    monkeypatch.setattr(usage_module, "get_observability", lambda: telemetry)
    client = client_with_response(CompanyName(name="Partial"))
    client.responses.parse.return_value = SimpleNamespace(
        output_parsed=CompanyName(name="Partial"),
        id="resp-incomplete",
        status="incomplete",
        incomplete_details=SimpleNamespace(reason="max_output_tokens"),
        usage=SimpleNamespace(
            input_tokens=15,
            output_tokens=500,
            input_tokens_details=None,
            output_tokens_details=SimpleNamespace(reasoning_tokens=300),
        ),
    )
    provider = OpenAIProvider(
        api_key="test-key", model="some-model", client=client, max_output_tokens=500
    )

    with pytest.raises(LLMStructuredOutputError, match="max_output_tokens"):
        await provider.generate_structured(
            system_prompt="system", user_prompt="user", response_model=CompanyName
        )

    assert telemetry.events[0][1]["request_outcome"] == "incomplete"
    assert telemetry.events[0][1]["reasoning_tokens"] == 300
    assert telemetry.events[0][1]["configured_output_tokens"] == 500
