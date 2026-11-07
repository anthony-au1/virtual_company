"""Persist validated Exploration Hypotheses through the Hypothesis repository."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from sqlalchemy.ext.asyncio import AsyncSession

from virtual_company.db.models import ExplorationHypothesis as PersistedHypothesis
from virtual_company.domain.exploration.hypotheses import (
    ExplorationHypothesis as DomainHypothesis,
)
from virtual_company.observability import Observability, get_observability
from virtual_company.repositories.dtos import ExplorationHypothesisCreate
from virtual_company.repositories.exploration_hypothesis import (
    ExplorationHypothesisRepository,
)
from virtual_company.services.exploration_hypothesis_generator import (
    ExplorationHypothesisGenerationResult,
)
from virtual_company.workflows.exploration.models import (
    ExplorationHypothesisGenerationFailureCategory,
    ExplorationHypothesisGenerationOutcome,
)


@dataclass(frozen=True)
class ExplorationHypothesisPersistenceResult:
    """Persisted Hypothesis rows and the generation outcome, in input order."""

    input_count: int
    persisted_count: int
    hypotheses: tuple[PersistedHypothesis, ...]
    generation_outcome: ExplorationHypothesisGenerationOutcome
    failure_category: ExplorationHypothesisGenerationFailureCategory | None = None


class ExplorationHypothesisPersistenceService:
    """Persist final validated Hypotheses in the caller-managed transaction."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        observability: Observability | None = None,
    ) -> None:
        self._hypotheses = ExplorationHypothesisRepository(session)
        self._observability = observability or get_observability()

    async def persist(
        self,
        batch: ExplorationHypothesisGenerationResult,
    ) -> ExplorationHypothesisPersistenceResult:
        """Persist final domain Hypotheses only when generation succeeded."""
        selected = batch.hypotheses
        metadata = {
            "capability": "exploration_hypothesis_persistence",
            "input_hypothesis_count": len(selected),
        }
        self._observability.event(
            "exploration_hypothesis_persistence_started", **metadata
        )
        started = perf_counter()

        if batch.outcome is ExplorationHypothesisGenerationOutcome.FAILED:
            self._observability.event(
                "exploration_hypothesis_persistence_failed",
                duration_ms=int((perf_counter() - started) * 1000),
                persisted_count=0,
                failure_category=(
                    batch.failure_category.value
                    if batch.failure_category is not None
                    else "generation_failed"
                ),
                outcome=batch.outcome.value,
                **metadata,
            )
            return ExplorationHypothesisPersistenceResult(
                input_count=len(selected),
                persisted_count=0,
                hypotheses=(),
                generation_outcome=batch.outcome,
                failure_category=batch.failure_category,
            )

        persisted: list[PersistedHypothesis] = []
        try:
            with self._observability.span(
                "exploration.hypothesis_persistence", **metadata
            ):
                for hypothesis in selected:
                    persisted.append(
                        await self._hypotheses.create(self._to_create(hypothesis))
                    )
        except Exception as error:
            self._observability.event(
                "exploration_hypothesis_persistence_failed",
                duration_ms=int((perf_counter() - started) * 1000),
                persisted_count=len(persisted),
                failure_category="repository_error",
                outcome="FAILED",
                error_type=type(error).__name__,
                **metadata,
            )
            raise

        result = ExplorationHypothesisPersistenceResult(
            input_count=len(selected),
            persisted_count=len(persisted),
            hypotheses=tuple(persisted),
            generation_outcome=batch.outcome,
        )
        self._observability.event(
            "exploration_hypothesis_persistence_completed",
            duration_ms=int((perf_counter() - started) * 1000),
            persisted_count=result.persisted_count,
            outcome=batch.outcome.value,
            **metadata,
        )
        return result

    @staticmethod
    def _to_create(
        hypothesis: DomainHypothesis,
    ) -> ExplorationHypothesisCreate:
        return ExplorationHypothesisCreate(
            exploration_company_id=hypothesis.exploration_company_id,
            statement=hypothesis.statement,
            fact_ids=list(hypothesis.fact_ids),
        )
