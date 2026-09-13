"""Tests for configuration-based LLM role resolution."""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from virtual_company.config import Settings
from virtual_company.llm import (
    AnthropicProvider,
    LLMConfigurationError,
    LLMRegistry,
    LLMRole,
    OpenAIProvider,
)


def test_default_roles_resolve_to_openai_terra_and_luna() -> None:
    registry = LLMRegistry(Settings(openai_api_key=SecretStr("test-key")))

    research = registry.for_role(LLMRole.RESEARCH)
    extraction = registry.for_role(LLMRole.EXTRACTION)

    assert isinstance(research, OpenAIProvider)
    assert research._model == "gpt-5.6-terra"
    assert isinstance(extraction, OpenAIProvider)
    assert extraction._model == "gpt-5.6-luna"


def test_anthropic_configuration_resolves_sonnet_for_research() -> None:
    registry = LLMRegistry(
        Settings(
            llm_provider="anthropic",
            anthropic_api_key=SecretStr("test-key"),
        )
    )

    provider = registry.for_role(LLMRole.RESEARCH)

    assert isinstance(provider, AnthropicProvider)
    assert provider._model == "claude-sonnet-5"


def test_role_override_can_select_anthropic_without_changing_global_provider() -> None:
    registry = LLMRegistry(
        Settings(
            openai_api_key=SecretStr("openai-key"),
            anthropic_api_key=SecretStr("anthropic-key"),
            llm_extraction_provider="anthropic",
        )
    )

    assert isinstance(registry.for_role(LLMRole.RESEARCH), OpenAIProvider)
    assert isinstance(registry.for_role(LLMRole.EXTRACTION), AnthropicProvider)


def test_unknown_provider_fails_clearly() -> None:
    registry = LLMRegistry(Settings(llm_provider="unknown"))

    with pytest.raises(LLMConfigurationError, match="Unsupported LLM provider"):
        registry.for_role(LLMRole.RESEARCH)


def test_selected_provider_requires_its_api_key() -> None:
    registry = LLMRegistry(Settings(llm_provider="anthropic"))

    with pytest.raises(LLMConfigurationError, match="ANTHROPIC_API_KEY"):
        registry.for_role(LLMRole.RESEARCH)
