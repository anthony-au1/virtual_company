"""Tests for the Anthropic LLM provider boundary."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel, SecretStr

from virtual_company.llm import (
    AnthropicProvider,
    LLMConfigurationError,
    LLMStructuredOutputError,
)


class CompanyName(BaseModel):
    """Structured output used by provider tests."""

    name: str


def client_with_response(parsed: CompanyName | None) -> MagicMock:
    """Build a mock Anthropic client with a structured response."""
    client = MagicMock()
    client.messages.parse = AsyncMock(
        return_value=SimpleNamespace(parsed_output=parsed)
    )
    return client


@pytest.mark.asyncio
async def test_generate_structured_returns_parsed_pydantic_model() -> None:
    parsed = CompanyName(name="Example Inc.")
    client = client_with_response(parsed)
    provider = AnthropicProvider(
        api_key=SecretStr("test-key"), model="claude-sonnet-5", client=client
    )

    result = await provider.generate_structured(
        system_prompt="Extract a company name.",
        user_prompt="Example Inc.",
        response_model=CompanyName,
    )

    assert result is parsed
    client.messages.parse.assert_awaited_once_with(
        model="claude-sonnet-5",
        max_tokens=4096,
        system="Extract a company name.",
        messages=[{"role": "user", "content": "Example Inc."}],
        output_format=CompanyName,
    )


@pytest.mark.parametrize(
    ("api_key", "model"),
    [(None, "claude-sonnet-5"), (SecretStr("test-key"), None)],
)
def test_provider_requires_anthropic_configuration(
    api_key: SecretStr | None, model: str | None
) -> None:
    with pytest.raises(LLMConfigurationError, match="ANTHROPIC_API_KEY"):
        AnthropicProvider(api_key=api_key, model=model)


@pytest.mark.asyncio
async def test_generate_structured_raises_when_response_is_not_parsed() -> None:
    provider = AnthropicProvider(
        api_key="test-key",
        model="claude-sonnet-5",
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
    client.messages.parse.side_effect = RuntimeError("Anthropic unavailable")
    provider = AnthropicProvider(
        api_key=SecretStr("test-key"), model="claude-sonnet-5", client=client
    )

    with pytest.raises(RuntimeError, match="Anthropic unavailable"):
        await provider.generate_structured(
            system_prompt="System prompt",
            user_prompt="User prompt",
            response_model=CompanyName,
        )


@pytest.mark.asyncio
async def test_anthropic_retains_max_tokens_and_reports_native_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from virtual_company.llm import usage as usage_module

    class TelemetryFake:
        def __init__(self) -> None:
            self.current_context: dict[str, str] = {}
            self.events: list[tuple[str, dict[str, object]]] = []

        def event(self, name: str, **fields: object) -> None:
            self.events.append((name, fields))

        def record(self, *_: object, **__: object) -> None:
            pass

    telemetry = TelemetryFake()
    monkeypatch.setattr(usage_module, "get_observability", lambda: telemetry)
    client = client_with_response(CompanyName(name="Example"))
    client.messages.parse.return_value = SimpleNamespace(
        parsed_output=CompanyName(name="Example"),
        id="msg-1",
        _request_id="req-anthropic-1",
        model="claude-sonnet-5",
        stop_reason="end_turn",
        usage=SimpleNamespace(
            input_tokens=200,
            output_tokens=32,
            cache_read_input_tokens=70,
            cache_creation_input_tokens=40,
        ),
    )
    provider = AnthropicProvider(
        api_key="test-key", model="claude-sonnet-5", role="research", client=client
    )

    result = await provider.generate_structured(
        system_prompt="system", user_prompt="user", response_model=CompanyName
    )

    assert result == CompanyName(name="Example")
    assert client.messages.parse.await_args.kwargs["max_tokens"] == 4096
    name, fields = telemetry.events[0]
    assert name == "llm_usage_reported"
    assert fields["provider"] == "anthropic"
    assert fields["input_tokens"] == 200
    assert fields["output_tokens"] == 32
    assert fields["reasoning_tokens"] is None
    assert fields["cached_input_tokens"] == 70
    assert fields["cache_write_input_tokens"] == 40
    assert fields["response_id"] == "msg-1"
    assert fields["request_id"] == "req-anthropic-1"
    assert fields["response_status"] == "end_turn"
    assert fields["service_tier"] is None
