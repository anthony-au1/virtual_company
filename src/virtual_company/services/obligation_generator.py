"""Generate evidence-investigable obligations for an Exploration context."""

from __future__ import annotations

import asyncio
import re
import unicodedata
from time import perf_counter
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
)

from virtual_company.config import Settings
from virtual_company.llm import (
    InstrumentedLLMProvider,
    LLMProvider,
    LLMRegistry,
    LLMRole,
)
from virtual_company.observability import Observability, get_observability
from virtual_company.workflows.exploration.prompts import (
    GENERATE_EXPLORATION_OBLIGATIONS_PROMPT,
    generate_exploration_obligations_system_prompt,
    generate_exploration_obligations_user_prompt,
)

NonEmptyDescription = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1)
]
GENERATION_TIMEOUT_SECONDS = 30


class GeneratedObligation(BaseModel):
    """One minimal, system-managed research requirement."""

    model_config = ConfigDict(extra="forbid")

    description: NonEmptyDescription

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description_whitespace(cls, value: Any) -> Any:
        if isinstance(value, str):
            return " ".join(unicodedata.normalize("NFKC", value).split())
        return value


class ObligationGenerationResult(BaseModel):
    """Zero or more obligations derived from one Exploration context."""

    model_config = ConfigDict(extra="forbid")

    obligations: list[GeneratedObligation] = Field(strict=True)


class ObligationGenerationValidationError(ValueError):
    """Raised when structured model output violates generator invariants."""


class ObligationGenerator:
    """Generate and validate obligations without accessing persistence."""

    def __init__(
        self,
        provider: LLMProvider,
        *,
        timeout_seconds: float = GENERATION_TIMEOUT_SECONDS,
        observability: Observability | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        self._provider = provider
        self._timeout_seconds = timeout_seconds
        self._observability = observability or get_observability()

    async def generate(
        self, business_context: str, max_obligations: int
    ) -> ObligationGenerationResult:
        """Generate a validated result; an empty list is a successful result."""
        if (
            not isinstance(max_obligations, int)
            or isinstance(max_obligations, bool)
            or not 1 <= max_obligations <= 20
        ):
            raise ValueError("max_obligations must be between 1 and 20")

        metadata = self._metadata(max_obligations)
        self._observability.event("obligation_generation_started", **metadata)
        started = perf_counter()
        try:
            with self._observability.span(
                "exploration.obligation_generation", **metadata
            ):
                async with asyncio.timeout(self._timeout_seconds):
                    response = await self._provider.generate_structured(
                        system_prompt=generate_exploration_obligations_system_prompt(),
                        user_prompt=generate_exploration_obligations_user_prompt(
                            business_context, max_obligations
                        ),
                        response_model=ObligationGenerationResult,
                    )
                    result = self._validate_response(response, max_obligations)
        except Exception as error:
            self._observability.event(
                "obligation_generation_failed",
                duration_ms=int((perf_counter() - started) * 1000),
                error_type=type(error).__name__,
                **metadata,
            )
            raise

        self._observability.event(
            "obligation_generation_completed",
            duration_ms=int((perf_counter() - started) * 1000),
            generated_obligation_count=len(result.obligations),
            **metadata,
        )
        return result

    @staticmethod
    def _validate_response(
        response: Any, max_obligations: int
    ) -> ObligationGenerationResult:
        raw = response.model_dump() if isinstance(response, BaseModel) else response
        try:
            result = ObligationGenerationResult.model_validate(raw)
        except ValidationError as error:
            raise ObligationGenerationValidationError(
                "Structured obligation output is invalid"
            ) from error

        if len(result.obligations) > max_obligations:
            raise ObligationGenerationValidationError(
                "Generated obligation count exceeds max_obligations"
            )

        seen: set[str] = set()
        for obligation in result.obligations:
            normalized = ObligationGenerator._normalize_description(
                obligation.description
            )
            if not any(character.isalnum() for character in normalized):
                raise ObligationGenerationValidationError(
                    "Generated obligation descriptions must contain meaningful text"
                )
            if normalized in seen:
                raise ObligationGenerationValidationError(
                    "Generated obligations contain duplicate descriptions"
                )
            seen.add(normalized)
        return result

    @staticmethod
    def _normalize_description(description: str) -> str:
        normalized = unicodedata.normalize("NFKC", description)
        normalized = re.sub(r"\s+", " ", normalized).strip().casefold()
        return normalized.rstrip(" .!?")

    def _metadata(self, max_obligations: int) -> dict[str, str | int]:
        return {
            "capability": LLMRole.OBLIGATION_GENERATION.value,
            "provider": str(getattr(self._provider, "provider", "unknown")),
            "model": str(getattr(self._provider, "model", "unknown")),
            "prompt_name": GENERATE_EXPLORATION_OBLIGATIONS_PROMPT.name,
            "prompt_version": GENERATE_EXPLORATION_OBLIGATIONS_PROMPT.version,
            "max_obligations": max_obligations,
        }


def create_configured_obligation_generator(
    settings: Settings | None = None,
) -> ObligationGenerator:
    """Build the standalone generator from obligation-generation LLM settings."""
    provider = LLMRegistry(settings).for_role(LLMRole.OBLIGATION_GENERATION)
    return ObligationGenerator(InstrumentedLLMProvider(provider))
