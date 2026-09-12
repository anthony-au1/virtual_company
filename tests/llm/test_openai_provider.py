"""Tests for the OpenAI LLM provider boundary."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel, SecretStr

from virtual_company.config import Settings
from virtual_company.llm import LLMConfigurationError, LLMResponseError, OpenAIProvider


class CompanyName(BaseModel):
    """Structured output used by provider tests."""

    name: str


def settings() -> Settings:
    """Build configured settings without reading the environment."""
    return Settings(openai_api_key=SecretStr("test-key"), openai_model="test-model")


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
    provider = OpenAIProvider(settings=settings(), client=client)

    result = await provider.generate_structured(
        system_prompt="Extract a company name.",
        user_prompt="Example Inc.",
        response_model=CompanyName,
    )

    assert result is parsed
    client.responses.parse.assert_awaited_once_with(
        model="test-model",
        instructions="Extract a company name.",
        input="Example Inc.",
        text_format=CompanyName,
    )


@pytest.mark.parametrize(
    "settings_kwargs",
    [{"openai_model": "test-model"}, {"openai_api_key": SecretStr("test-key")}],
)
def test_provider_requires_openai_configuration(
    settings_kwargs: dict[str, str | SecretStr],
) -> None:
    with pytest.raises(LLMConfigurationError, match="OPENAI_API_KEY and OPENAI_MODEL"):
        OpenAIProvider(settings=Settings(**settings_kwargs))


@pytest.mark.asyncio
async def test_generate_structured_raises_when_response_is_not_parsed() -> None:
    provider = OpenAIProvider(settings=settings(), client=client_with_response(None))

    with pytest.raises(LLMResponseError, match="no structured output"):
        await provider.generate_structured(
            system_prompt="System prompt",
            user_prompt="User prompt",
            response_model=CompanyName,
        )


@pytest.mark.asyncio
async def test_generate_structured_propagates_sdk_errors() -> None:
    client = client_with_response(CompanyName(name="Unused"))
    client.responses.parse.side_effect = RuntimeError("OpenAI unavailable")
    provider = OpenAIProvider(settings=settings(), client=client)

    with pytest.raises(RuntimeError, match="OpenAI unavailable"):
        await provider.generate_structured(
            system_prompt="System prompt",
            user_prompt="User prompt",
            response_model=CompanyName,
        )
