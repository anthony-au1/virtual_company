"""OpenAI-backed structured-output provider."""

from __future__ import annotations

import logging
from typing import cast

from openai import AsyncOpenAI, AuthenticationError, RateLimitError
from pydantic import SecretStr

from virtual_company.llm.base import (
    LLMAuthenticationError,
    LLMConfigurationError,
    LLMRateLimitError,
    LLMStructuredOutputError,
    T,
)

logger = logging.getLogger(__name__)


class OpenAIProvider:
    """Generate structured output through the OpenAI Responses API."""

    def __init__(
        self,
        *,
        api_key: SecretStr | str | None,
        model: str | None,
        role: str | None = None,
        client: AsyncOpenAI | None = None,
    ) -> None:
        resolved_api_key = (
            api_key.get_secret_value() if isinstance(api_key, SecretStr) else api_key
        )
        if not resolved_api_key or not model:
            raise LLMConfigurationError(
                "OPENAI_API_KEY and an OpenAI model must be configured to use OpenAIProvider"
            )

        self._model = model
        self._role = role
        self._client = client or AsyncOpenAI(api_key=resolved_api_key)

    @property
    def provider(self) -> str:
        """Return the provider identifier used for observability."""
        return "openai"

    @property
    def model(self) -> str:
        """Return the configured provider model."""
        return self._model

    @property
    def role(self) -> str | None:
        """Return the configured application role."""
        return self._role

    async def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
    ) -> T:
        """Generate Pydantic-validated structured output."""
        logger.info(
            "LLM structured generation provider=%s model=%s role=%s",
            "openai",
            self._model,
            self._role,
        )
        try:
            response = await self._client.responses.parse(
                model=self._model,
                instructions=system_prompt,
                input=user_prompt,
                text_format=response_model,
            )
        except AuthenticationError as error:
            raise LLMAuthenticationError("OpenAI authentication failed") from error
        except RateLimitError as error:
            raise LLMRateLimitError("OpenAI rate limit exceeded") from error
        if response.output_parsed is None:
            raise LLMStructuredOutputError("OpenAI returned no structured output")
        return cast(T, response.output_parsed)
