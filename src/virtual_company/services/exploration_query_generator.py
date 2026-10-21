"""Generate bounded search queries for one Exploration company obligation."""

from __future__ import annotations

import asyncio
import re
import unicodedata
from time import perf_counter
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from virtual_company.config import Settings
from virtual_company.llm import (
    InstrumentedLLMProvider,
    LLMProvider,
    LLMRegistry,
    LLMRole,
)
from virtual_company.observability import Observability, get_observability
from virtual_company.workflows.exploration.prompts import (
    GENERATE_EXPLORATION_QUERIES_PROMPT,
    generate_exploration_queries_system_prompt,
    generate_exploration_queries_user_prompt,
)

DEFAULT_MAX_EXPLORATION_QUERIES = 5
MAX_EXPLORATION_QUERIES = 10
MAX_EXPLORATION_QUERY_LENGTH = 500
QUERY_GENERATION_TIMEOUT_SECONDS = 30


class ExplorationQueryCompanyContext(BaseModel):
    """Company profile fields relevant to search, without Research conclusions."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    name: str
    website: str | None = None
    domain: str | None = None
    industry: str | None = None
    country: str | None = None
    state: str | None = None
    city: str | None = None


class ExplorationQueryObligationContext(BaseModel):
    """The single Exploration obligation under investigation."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    description: str


class GeneratedExplorationQuery(BaseModel):
    """One candidate query returned by structured generation."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(strict=True)

    @field_validator("query", mode="before")
    @classmethod
    def normalize_query_whitespace(cls, value: Any) -> Any:
        if isinstance(value, str):
            return " ".join(unicodedata.normalize("NFKC", value).split())
        return value


class ExplorationQueryGenerationResult(BaseModel):
    """Zero or more useful queries for one company-obligation pair."""

    model_config = ConfigDict(extra="forbid")

    queries: list[GeneratedExplorationQuery] = Field(strict=True)


class ExplorationQueryGenerationValidationError(ValueError):
    """Raised when structured query output does not match the expected shape."""


class ExplorationQueryGenerator:
    """Generate queries without persistence, search, or workflow orchestration."""

    def __init__(
        self,
        provider: LLMProvider,
        *,
        timeout_seconds: float = QUERY_GENERATION_TIMEOUT_SECONDS,
        observability: Observability | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        self._provider = provider
        self._timeout_seconds = timeout_seconds
        self._observability = observability or get_observability()

    async def generate(
        self,
        business_context: str,
        company: ExplorationQueryCompanyContext,
        obligation: ExplorationQueryObligationContext,
        max_queries: int = DEFAULT_MAX_EXPLORATION_QUERIES,
    ) -> ExplorationQueryGenerationResult:
        """Return validated, normalized queries; zero results is a valid outcome."""
        if (
            not isinstance(max_queries, int)
            or isinstance(max_queries, bool)
            or not 0 <= max_queries <= MAX_EXPLORATION_QUERIES
        ):
            raise ValueError(
                f"max_queries must be between 0 and {MAX_EXPLORATION_QUERIES}"
            )

        metadata = self._metadata(max_queries)
        self._observability.event("exploration_query_generation_started", **metadata)
        started = perf_counter()
        try:
            with self._observability.span(
                "exploration.query_generation", **metadata
            ):
                async with asyncio.timeout(self._timeout_seconds):
                    response = await self._provider.generate_structured(
                        system_prompt=generate_exploration_queries_system_prompt(),
                        user_prompt=generate_exploration_queries_user_prompt(
                            business_context, company, obligation, max_queries
                        ),
                        response_model=ExplorationQueryGenerationResult,
                    )
                result, removed_count = self._validate_response(response, max_queries)
        except Exception as error:
            self._observability.event(
                "exploration_query_generation_failed",
                duration_ms=int((perf_counter() - started) * 1000),
                error_type=type(error).__name__,
                **metadata,
            )
            raise

        self._observability.event(
            "exploration_query_generation_completed",
            duration_ms=int((perf_counter() - started) * 1000),
            generated_query_count=len(result.queries),
            removed_query_count=removed_count,
            **metadata,
        )
        return result

    @staticmethod
    def _validate_response(
        response: Any, max_queries: int
    ) -> tuple[ExplorationQueryGenerationResult, int]:
        raw = response.model_dump() if isinstance(response, BaseModel) else response
        try:
            parsed = ExplorationQueryGenerationResult.model_validate(raw)
        except ValidationError as error:
            raise ExplorationQueryGenerationValidationError(
                "Structured Exploration query output is invalid"
            ) from error

        validated: list[GeneratedExplorationQuery] = []
        seen: set[str] = set()
        removed_count = 0
        for item in parsed.queries:
            query = item.query
            if not query or len(query) > MAX_EXPLORATION_QUERY_LENGTH:
                removed_count += 1
                continue
            normalized_key = ExplorationQueryGenerator._normalized_key(query)
            if not normalized_key or normalized_key in seen:
                removed_count += 1
                continue
            seen.add(normalized_key)
            validated.append(item)

        retained = validated[:max_queries]
        removed_count += len(validated) - len(retained)
        return (
            ExplorationQueryGenerationResult(queries=retained),
            removed_count,
        )

    @staticmethod
    def _normalized_key(query: str) -> str:
        normalized = unicodedata.normalize("NFKC", query)
        normalized = re.sub(r"\s+", " ", normalized).strip().casefold()
        return normalized

    def _metadata(self, max_queries: int) -> dict[str, str | int]:
        return {
            "capability": LLMRole.EXPLORATION_QUERY_GENERATION.value,
            "provider": str(getattr(self._provider, "provider", "unknown")),
            "model": str(getattr(self._provider, "model", "unknown")),
            "prompt_name": GENERATE_EXPLORATION_QUERIES_PROMPT.name,
            "prompt_version": GENERATE_EXPLORATION_QUERIES_PROMPT.version,
            "max_queries": max_queries,
        }


def create_configured_exploration_query_generator(
    settings: Settings | None = None,
) -> ExplorationQueryGenerator:
    """Build the standalone generator with its dedicated LLM capability."""
    provider = LLMRegistry(settings).for_role(LLMRole.EXPLORATION_QUERY_GENERATION)
    return ExplorationQueryGenerator(InstrumentedLLMProvider(provider))
