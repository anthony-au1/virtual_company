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


def test_obligation_generation_has_an_independent_reasoning_model() -> None:
    registry = LLMRegistry(Settings(openai_api_key=SecretStr("test-key")))

    generator = registry.for_role(LLMRole.OBLIGATION_GENERATION)

    assert isinstance(generator, OpenAIProvider)
    assert generator._model == "gpt-5.6-terra"
    assert generator.role == "obligation_generation"


def test_obligation_generation_provider_and_model_can_be_overridden() -> None:
    registry = LLMRegistry(
        Settings(
            openai_api_key=SecretStr("openai-key"),
            anthropic_api_key=SecretStr("anthropic-key"),
            llm_obligation_generation_provider="anthropic",
            anthropic_obligation_generation_model="custom-reasoning-model",
        )
    )

    generator = registry.for_role(LLMRole.OBLIGATION_GENERATION)

    assert isinstance(generator, AnthropicProvider)
    assert generator._model == "custom-reasoning-model"
    assert isinstance(registry.for_role(LLMRole.EXTRACTION), OpenAIProvider)


def test_exploration_query_generation_has_an_independent_model() -> None:
    registry = LLMRegistry(Settings(openai_api_key=SecretStr("test-key")))

    generator = registry.for_role(LLMRole.EXPLORATION_QUERY_GENERATION)

    assert isinstance(generator, OpenAIProvider)
    assert generator._model == "gpt-5.6-terra"
    assert generator.role == "exploration_query_generation"


def test_exploration_query_provider_and_model_can_be_overridden() -> None:
    registry = LLMRegistry(
        Settings(
            openai_api_key=SecretStr("openai-key"),
            anthropic_api_key=SecretStr("anthropic-key"),
            llm_exploration_query_generation_provider="anthropic",
            anthropic_exploration_query_generation_model="custom-query-model",
        )
    )

    generator = registry.for_role(LLMRole.EXPLORATION_QUERY_GENERATION)

    assert isinstance(generator, AnthropicProvider)
    assert generator._model == "custom-query-model"
    assert isinstance(registry.for_role(LLMRole.OBLIGATION_GENERATION), OpenAIProvider)


def test_exploration_evidence_extraction_defaults_to_luna_independently() -> None:
    registry = LLMRegistry(Settings(openai_api_key=SecretStr("test-key")))

    provider = registry.for_role(LLMRole.EXPLORATION_EVIDENCE_EXTRACTION)

    assert isinstance(provider, OpenAIProvider)
    assert provider._model == "gpt-5.6-luna"
    assert provider.role == "exploration_evidence_extraction"


def test_exploration_evidence_provider_and_models_are_independently_configurable() -> None:
    registry = LLMRegistry(
        Settings(
            openai_api_key=SecretStr("openai-key"),
            anthropic_api_key=SecretStr("anthropic-key"),
            llm_exploration_evidence_extraction_provider="anthropic",
            anthropic_exploration_evidence_extraction_model="custom-extraction-model",
        )
    )

    provider = registry.for_role(LLMRole.EXPLORATION_EVIDENCE_EXTRACTION)

    assert isinstance(provider, AnthropicProvider)
    assert provider._model == "custom-extraction-model"
    assert isinstance(registry.for_role(LLMRole.RESEARCH), OpenAIProvider)


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
