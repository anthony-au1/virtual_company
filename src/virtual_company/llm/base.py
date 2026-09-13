"""Provider-independent LLM contracts."""

from __future__ import annotations

from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """Base class for provider-neutral LLM failures."""


class LLMConfigurationError(ValueError, LLMError):
    """Raised when an LLM provider cannot be configured."""


class LLMAuthenticationError(LLMError):
    """Raised when an LLM provider rejects credentials."""


class LLMRateLimitError(LLMError):
    """Raised when an LLM provider rate limits a request."""


class LLMResponseError(LLMError):
    """Raised when an LLM provider does not return a structured response."""


class LLMStructuredOutputError(LLMResponseError):
    """Raised when a provider response cannot satisfy the requested schema."""


class LLMProvider(Protocol):
    """Generate Pydantic-validated structured output from an LLM."""

    async def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
    ) -> T:
        """Generate output matching ``response_model``."""
