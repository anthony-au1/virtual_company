"""Generate grounded Exploration Hypotheses from supplied company Facts."""

from __future__ import annotations

import asyncio
import re
import unicodedata
from collections.abc import Sequence
from time import perf_counter
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ValidationError

from virtual_company.config import Settings, get_settings
from virtual_company.domain.exploration.hypotheses import ExplorationHypothesis
from virtual_company.llm import (
    InstrumentedLLMProvider,
    LLMConfigurationError,
    LLMError,
    LLMProvider,
    LLMRegistry,
    LLMResponseError,
    LLMRole,
)
from virtual_company.observability import Observability, get_observability
from virtual_company.workflows.exploration.models import (
    ExplorationHypothesisCompanyContext,
    ExplorationHypothesisFactInput,
    ExplorationHypothesisGenerationFailureCategory,
    ExplorationHypothesisGenerationOutcome,
    ExtractedExplorationHypotheses,
)
from virtual_company.workflows.exploration.prompts import (
    GENERATE_EXPLORATION_HYPOTHESES_PROMPT,
    generate_exploration_hypotheses_system_prompt,
    generate_exploration_hypotheses_user_prompt,
)

DEFAULT_MAX_EXPLORATION_HYPOTHESES = 10
MAX_EXPLORATION_HYPOTHESES = 20
DEFAULT_EXPLORATION_HYPOTHESIS_GENERATION_TIMEOUT_SECONDS = 60.0
DEFAULT_EXPLORATION_HYPOTHESIS_GENERATION_MAX_INPUT_CHARS = 100_000


class ExplorationHypothesisInputValidationError(ValueError):
    """Raised when caller-supplied generation inputs are inconsistent."""


class ExplorationHypothesisGenerationResult(BaseModel):
    """Successful transient Hypotheses or one normalized generation failure."""

    outcome: ExplorationHypothesisGenerationOutcome
    hypotheses: tuple[ExplorationHypothesis, ...] = ()
    rejected_hypothesis_count: int = 0
    failure_category: ExplorationHypothesisGenerationFailureCategory | None = None


class ExplorationHypothesisGenerator:
    """Generate Hypotheses for one company without retrieval or persistence."""

    def __init__(
        self,
        provider: LLMProvider | None,
        *,
        timeout_seconds: float = (
            DEFAULT_EXPLORATION_HYPOTHESIS_GENERATION_TIMEOUT_SECONDS
        ),
        max_input_chars: int = DEFAULT_EXPLORATION_HYPOTHESIS_GENERATION_MAX_INPUT_CHARS,
        observability: Observability | None = None,
        configuration_error: bool = False,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        if max_input_chars < 1:
            raise ValueError("max_input_chars must be greater than zero")
        self._provider = provider
        self._timeout_seconds = timeout_seconds
        self._max_input_chars = max_input_chars
        self._configuration_error = configuration_error or provider is None
        self._observability = observability or get_observability()

    async def generate(
        self,
        company: ExplorationHypothesisCompanyContext,
        business_context: str,
        facts: Sequence[ExplorationHypothesisFactInput],
        max_hypotheses: int = DEFAULT_MAX_EXPLORATION_HYPOTHESES,
    ) -> ExplorationHypothesisGenerationResult:
        """Generate supported Hypotheses from the complete ordered Fact input."""
        if (
            not isinstance(max_hypotheses, int)
            or isinstance(max_hypotheses, bool)
            or not 1 <= max_hypotheses <= MAX_EXPLORATION_HYPOTHESES
        ):
            raise ValueError("max_hypotheses must be between 1 and 20")

        normalized_context = self._normalize_required_text(
            business_context, "business_context"
        )
        ordered_facts = tuple(facts)
        seen_ids: set[UUID] = set()
        for item in ordered_facts:
            if item.exploration_company_id != company.exploration_company_id:
                raise ExplorationHypothesisInputValidationError(
                    "All Facts must belong to the selected ExplorationCompany"
                )
            if item.fact_id in seen_ids:
                raise ExplorationHypothesisInputValidationError(
                    "Fact IDs must be unique within a generation call"
                )
            seen_ids.add(item.fact_id)

        provider_name = str(getattr(self._provider, "provider", "unknown"))
        model_name = str(getattr(self._provider, "model", "unknown"))
        metadata: dict[str, str | int | float] = {
            "capability": LLMRole.EXPLORATION_HYPOTHESIS_GENERATION.value,
            "exploration_company_id": str(company.exploration_company_id),
            "provider": provider_name,
            "model": model_name,
            "prompt_name": GENERATE_EXPLORATION_HYPOTHESES_PROMPT.name,
            "prompt_version": GENERATE_EXPLORATION_HYPOTHESES_PROMPT.version,
            "input_fact_count": len(ordered_facts),
            "max_hypotheses": max_hypotheses,
        }

        if not ordered_facts:
            self._observability.event(
                "exploration_hypothesis_generation_completed",
                duration_ms=0,
                generated_hypothesis_count=0,
                rejected_hypothesis_count=0,
                **metadata,
            )
            return ExplorationHypothesisGenerationResult(
                outcome=ExplorationHypothesisGenerationOutcome.SUCCEEDED
            )

        labels = {
            f"F{index}": fact for index, fact in enumerate(ordered_facts, start=1)
        }
        labeled_facts = [
            {"fact_ref": label, "statement": fact.statement}
            for label, fact in labels.items()
        ]
        system_prompt = generate_exploration_hypotheses_system_prompt()
        user_prompt = generate_exploration_hypotheses_user_prompt(
            company.company_name,
            normalized_context,
            labeled_facts,
            max_hypotheses,
        )
        if len(system_prompt) + len(user_prompt) > self._max_input_chars:
            return self._failed(
                ExplorationHypothesisGenerationFailureCategory.INPUT_LIMIT,
                started=perf_counter(),
                metadata=metadata,
            )

        if self._configuration_error:
            return self._failed(
                ExplorationHypothesisGenerationFailureCategory.CONFIGURATION,
                started=perf_counter(),
                metadata=metadata,
                error_type="LLMConfigurationError",
            )

        self._observability.event("exploration_hypothesis_generation_started", **metadata)
        started = perf_counter()
        generation_error: Exception | None = None
        try:
            assert self._provider is not None
            with self._observability.span(
                "exploration.hypothesis_generation", **metadata
            ):
                try:
                    async with asyncio.timeout(self._timeout_seconds):
                        response = await self._provider.generate_structured(
                            system_prompt=system_prompt,
                            user_prompt=user_prompt,
                            response_model=ExtractedExplorationHypotheses,
                        )
                    parsed = self._parse_response(response)
                    if len(parsed.hypotheses) > max_hypotheses:
                        raise _MalformedHypothesisOutput(
                            "Generated hypothesis count exceeds max_hypotheses"
                        )
                    hypotheses, rejected_count = self._resolve_candidates(
                        parsed, labels, company.exploration_company_id
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as error:  # noqa: BLE001 - sanitize before span exits
                    generation_error = error
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - normalize instrumentation failures
            generation_error = error

        if generation_error is not None:
            category = self._failure_category(generation_error)
            return self._failed(
                category,
                started=started,
                metadata=metadata,
                error_type=type(generation_error).__name__,
            )

        self._observability.event(
            "exploration_hypothesis_generation_completed",
            duration_ms=int((perf_counter() - started) * 1000),
            generated_hypothesis_count=len(hypotheses),
            rejected_hypothesis_count=rejected_count,
            **metadata,
        )
        return ExplorationHypothesisGenerationResult(
            outcome=ExplorationHypothesisGenerationOutcome.SUCCEEDED,
            hypotheses=tuple(hypotheses),
            rejected_hypothesis_count=rejected_count,
        )

    def _failed(
        self,
        category: ExplorationHypothesisGenerationFailureCategory,
        *,
        started: float,
        metadata: dict[str, str | int | float],
        error_type: str | None = None,
    ) -> ExplorationHypothesisGenerationResult:
        self._observability.event(
            "exploration_hypothesis_generation_failed",
            duration_ms=int((perf_counter() - started) * 1000),
            generated_hypothesis_count=0,
            rejected_hypothesis_count=0,
            failure_category=category.value,
            error_type=error_type,
            **metadata,
        )
        return ExplorationHypothesisGenerationResult(
            outcome=ExplorationHypothesisGenerationOutcome.FAILED,
            failure_category=category,
        )

    @staticmethod
    def _normalize_required_text(value: str, field_name: str) -> str:
        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be text")
        normalized = " ".join(unicodedata.normalize("NFKC", value).split())
        if not normalized:
            raise ValueError(f"{field_name} must not be blank")
        return normalized

    @staticmethod
    def _parse_response(response: Any) -> ExtractedExplorationHypotheses:
        raw = response.model_dump() if isinstance(response, BaseModel) else response
        try:
            return ExtractedExplorationHypotheses.model_validate(raw)
        except ValidationError as error:
            raise _MalformedHypothesisOutput(
                "Structured Hypothesis output is invalid"
            ) from error

    @staticmethod
    def _resolve_candidates(
        response: ExtractedExplorationHypotheses,
        labels: dict[str, ExplorationHypothesisFactInput],
        company_id: UUID,
    ) -> tuple[list[ExplorationHypothesis], int]:
        accepted: list[ExplorationHypothesis] = []
        positions: dict[tuple[UUID, str], int] = {}
        rejected_count = 0
        for candidate in response.hypotheses:
            statement = " ".join(
                unicodedata.normalize("NFKC", candidate.statement).split()
            )
            refs = candidate.fact_refs
            if not statement or len(statement) > 2_000 or not refs:
                rejected_count += 1
                continue
            if any(label not in labels for label in refs):
                rejected_count += 1
                continue
            fact_ids = tuple(dict.fromkeys(labels[label].fact_id for label in refs))
            if any(
                labels[label].exploration_company_id != company_id for label in refs
            ):
                rejected_count += 1
                continue
            try:
                hypothesis = ExplorationHypothesis(
                    exploration_company_id=company_id,
                    statement=statement,
                    fact_ids=fact_ids,
                )
            except (ValidationError, ValueError):
                rejected_count += 1
                continue

            key = (company_id, ExplorationHypothesisGenerator._dedupe_key(statement))
            position = positions.get(key)
            if position is None:
                positions[key] = len(accepted)
                accepted.append(hypothesis)
                continue
            existing = accepted[position]
            merged_ids = tuple(dict.fromkeys((*existing.fact_ids, *fact_ids)))
            accepted[position] = existing.model_copy(update={"fact_ids": merged_ids})
        return accepted, rejected_count

    @staticmethod
    def _dedupe_key(statement: str) -> str:
        return re.sub(r"\s+", " ", statement).strip().casefold()

    @staticmethod
    def _failure_category(
        error: Exception,
    ) -> ExplorationHypothesisGenerationFailureCategory:
        if isinstance(error, LLMConfigurationError):
            return ExplorationHypothesisGenerationFailureCategory.CONFIGURATION
        if isinstance(error, (TimeoutError, asyncio.TimeoutError)) or type(
            error
        ).__name__ in {"APITimeoutError", "ConnectTimeout", "ReadTimeout"}:
            return ExplorationHypothesisGenerationFailureCategory.TIMEOUT
        if isinstance(error, (_MalformedHypothesisOutput, ValidationError, LLMResponseError)):
            return ExplorationHypothesisGenerationFailureCategory.MALFORMED_OUTPUT
        if isinstance(error, LLMError) or type(error).__module__.startswith(
            ("openai", "anthropic", "virtual_company.llm")
        ):
            return ExplorationHypothesisGenerationFailureCategory.PROVIDER_ERROR
        return ExplorationHypothesisGenerationFailureCategory.UNEXPECTED_ERROR


class _MalformedHypothesisOutput(ValueError):
    """Internal marker for malformed or over-limit structured model output."""


def create_configured_exploration_hypothesis_generator(
    settings: Settings | None = None,
    *,
    observability: Observability | None = None,
) -> ExplorationHypothesisGenerator:
    """Build a safely instrumented generator from its dedicated role settings."""
    resolved_settings = settings or get_settings()
    try:
        provider = LLMRegistry(resolved_settings).for_role(
            LLMRole.EXPLORATION_HYPOTHESIS_GENERATION
        )
    except LLMConfigurationError:
        return ExplorationHypothesisGenerator(
            None,
            timeout_seconds=(
                resolved_settings.exploration_hypothesis_generation_timeout_seconds
            ),
            max_input_chars=(
                resolved_settings.exploration_hypothesis_generation_max_input_chars
            ),
            observability=observability,
            configuration_error=True,
        )

    instrumented = InstrumentedLLMProvider(
        provider,
        observability=observability,
        capture_io=False,
        sanitize_errors=True,
    )
    return ExplorationHypothesisGenerator(
        instrumented,
        timeout_seconds=resolved_settings.exploration_hypothesis_generation_timeout_seconds,
        max_input_chars=resolved_settings.exploration_hypothesis_generation_max_input_chars,
        observability=observability,
    )
