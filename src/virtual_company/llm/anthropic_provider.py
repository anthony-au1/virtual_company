"""Anthropic-backed structured-output provider."""

from __future__ import annotations

import logging
import time
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
from virtual_company.llm.usage import report_llm_usage

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

    @property
    def provider(self) -> str:
        """Return the provider identifier used for observability."""
        return "anthropic"

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
        """Generate output with Anthropic's schema-constrained parser."""
        logger.info(
            "LLM structured generation provider=%s model=%s role=%s",
            "anthropic",
            self._model,
            self._role,
        )
        started = time.perf_counter()
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
        duration_ms = int((time.perf_counter() - started) * 1000)
        usage = getattr(response, "usage", None)
        stop_reason = getattr(response, "stop_reason", None)
        outcome = (
            "incomplete"
            if stop_reason in {"max_tokens", "model_context_window_exceeded"}
            else "completed"
            if stop_reason in {"end_turn", "stop_sequence"}
            else "unknown"
            if stop_reason is None
            else "other"
        )
        report_llm_usage(
            provider="anthropic",
            model=getattr(response, "model", None) or self._model,
            role=self._role,
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
            reasoning_tokens=None,
            cached_input_tokens=getattr(usage, "cache_read_input_tokens", None),
            cache_write_input_tokens=getattr(
                usage, "cache_creation_input_tokens", None
            ),
            response_id=getattr(response, "id", None),
            request_id=getattr(response, "_request_id", None),
            response_status=stop_reason,
            incomplete_reason=(stop_reason if outcome == "incomplete" else None),
            duration_ms=duration_ms,
            request_outcome=outcome,
        )
        if response.parsed_output is None:
            raise LLMStructuredOutputError("Anthropic returned no structured output")
        return cast(T, response.parsed_output)
