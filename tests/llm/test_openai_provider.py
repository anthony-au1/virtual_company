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
