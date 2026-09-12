"""Provider-independent LLM contracts."""

from __future__ import annotations

from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMConfigurationError(ValueError):
    """Raised when an LLM provider cannot be configured."""


class LLMResponseError(RuntimeError):
    """Raised when an LLM provider does not return a structured response."""


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
