"""OpenAI-backed structured-output provider."""

from __future__ import annotations

from openai import AsyncOpenAI

from virtual_company.config import Settings, get_settings
from virtual_company.llm.base import LLMConfigurationError, LLMResponseError, T


class OpenAIProvider:
    """Generate structured output through the OpenAI Responses API."""

    def __init__(
        self, settings: Settings | None = None, client: AsyncOpenAI | None = None
    ) -> None:
        resolved_settings = settings or get_settings()
        api_key = (
            resolved_settings.openai_api_key.get_secret_value()
            if resolved_settings.openai_api_key is not None
            else None
        )
        if not api_key or not resolved_settings.openai_model:
            raise LLMConfigurationError(
                "OPENAI_API_KEY and OPENAI_MODEL must be configured to use OpenAIProvider"
            )

        self._model = resolved_settings.openai_model
        self._client = client or AsyncOpenAI(api_key=api_key)

    async def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
    ) -> T:
        """Generate Pydantic-validated structured output."""
        response = await self._client.responses.parse(
            model=self._model,
            instructions=system_prompt,
            input=user_prompt,
            text_format=response_model,
        )
        if response.output_parsed is None:
            raise LLMResponseError("OpenAI returned no structured output")
        return response.output_parsed
