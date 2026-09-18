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
