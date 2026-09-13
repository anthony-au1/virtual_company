"""Anthropic-backed structured-output provider."""

from __future__ import annotations

import logging
from typing import cast

from anthropic import AsyncAnthropic, AuthenticationError, RateLimitError
from pydantic import SecretStr

from virtual_company.llm.base import (
    LLMAuthenticationError,
    LLMConfigurationError,
    LLMRateLimitError,
    LLMStructuredOutputError,
    T,
)

DEFAULT_MAX_TOKENS = 4096
logger = logging.getLogger(__name__)


class AnthropicProvider:
    """Generate Pydantic-validated structured output through Anthropic."""

    def __init__(
        self,
        *,
        api_key: SecretStr | str | None,
        model: str | None,
        role: str | None = None,
        client: AsyncAnthropic | None = None,
    ) -> None:
        resolved_api_key = (
            api_key.get_secret_value() if isinstance(api_key, SecretStr) else api_key
        )
        if not resolved_api_key or not model:
            raise LLMConfigurationError(
                "ANTHROPIC_API_KEY and an Anthropic model must be configured to use AnthropicProvider"
            )

        self._model = model
        self._role = role
        self._client = client or AsyncAnthropic(api_key=resolved_api_key)

    async def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
    ) -> T:
        """Generate output with Anthropic's schema-constrained parser."""
        logger.info(
            "LLM structured generation provider=%s model=%s role=%s",
            "anthropic",
            self._model,
            self._role,
        )
        try:
            response = await self._client.messages.parse(
                model=self._model,
                max_tokens=DEFAULT_MAX_TOKENS,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
                output_format=response_model,
            )
        except AuthenticationError as error:
            raise LLMAuthenticationError("Anthropic authentication failed") from error
        except RateLimitError as error:
            raise LLMRateLimitError("Anthropic rate limit exceeded") from error
        if response.parsed_output is None:
            raise LLMStructuredOutputError("Anthropic returned no structured output")
        return cast(T, response.parsed_output)
