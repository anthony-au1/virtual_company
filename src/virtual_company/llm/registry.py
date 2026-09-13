"""Configuration-based construction and selection of LLM providers."""

from __future__ import annotations

from virtual_company.config import Settings, get_settings
from virtual_company.llm.anthropic_provider import AnthropicProvider
from virtual_company.llm.base import LLMConfigurationError, LLMProvider
from virtual_company.llm.openai_provider import OpenAIProvider
from virtual_company.llm.roles import LLMRole


def create_llm_provider(
    *, provider: str, model: str, api_key: object, role: LLMRole
) -> LLMProvider:
    """Construct one provider without exposing provider selection to workflows."""
    normalized_provider = provider.lower()
    if normalized_provider == "openai":
        return OpenAIProvider(api_key=api_key, model=model, role=role.value)
    if normalized_provider == "anthropic":
        return AnthropicProvider(api_key=api_key, model=model, role=role.value)
    raise LLMConfigurationError(
        f"Unsupported LLM provider {provider!r}; expected 'openai' or 'anthropic'"
    )


class LLMRegistry:
    """Resolve configured providers for application workload roles."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def for_role(self, role: LLMRole) -> LLMProvider:
        """Return the provider configured for one workload role."""
        provider = self._provider_for_role(role)
        if provider == "openai":
            return create_llm_provider(
                provider=provider,
                model=self._openai_model_for_role(role),
                api_key=self._settings.openai_api_key,
                role=role,
            )
        if provider == "anthropic":
            return create_llm_provider(
                provider=provider,
                model=self._settings.anthropic_model,
                api_key=self._settings.anthropic_api_key,
                role=role,
            )
        raise LLMConfigurationError(
            f"Unsupported LLM provider {provider!r}; expected 'openai' or 'anthropic'"
        )

    def _provider_for_role(self, role: LLMRole) -> str:
        if role is LLMRole.RESEARCH:
            return (self._settings.llm_research_provider or self._settings.llm_provider).lower()
        return (self._settings.llm_extraction_provider or self._settings.llm_provider).lower()

    def _openai_model_for_role(self, role: LLMRole) -> str:
        if role is LLMRole.RESEARCH:
            return self._settings.openai_research_model
        return self._settings.openai_extraction_model
