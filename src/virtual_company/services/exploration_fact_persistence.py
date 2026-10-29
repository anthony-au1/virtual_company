"""Persist validated Exploration Facts through the Fact repository."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from sqlalchemy.ext.asyncio import AsyncSession

from virtual_company.db.models import ExplorationFact as PersistedFact
from virtual_company.domain.exploration.facts import ExplorationFact as DomainFact
from virtual_company.observability import Observability, get_observability
from virtual_company.repositories.dtos import ExplorationFactCreate
from virtual_company.repositories.exploration_fact import ExplorationFactRepository
from virtual_company.workflows.exploration.models import (
    ExplorationFactExtractionBatchResult,
)


@dataclass(frozen=True)
class ExplorationFactPersistenceResult:
    """Created Fact rows and accounting, in extractor order."""

    input_count: int
    persisted_count: int
    facts: tuple[PersistedFact, ...]


class ExplorationFactPersistenceService:
    """Map final validated Facts into immutable repository records.

    The caller owns the transaction and must roll it back if persistence fails.
    This service never commits or rolls back the caller's session.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        observability: Observability | None = None,
    ) -> None:
        self._facts = ExplorationFactRepository(session)
        self._observability = observability or get_observability()

    async def persist(
        self,
        batch: ExplorationFactExtractionBatchResult,
    ) -> ExplorationFactPersistenceResult:
        """Persist only ``batch.facts``, preserving input order and all support."""
        selected = batch.facts
        evidence_reference_count = sum(len(fact.evidence_ids) for fact in selected)
        metadata = {
            "capability": "exploration_fact_persistence",
            "input_fact_count": len(selected),
            "supporting_evidence_reference_count": evidence_reference_count,
        }
        self._observability.event("exploration_fact_persistence_started", **metadata)
        started = perf_counter()
        persisted: list[PersistedFact] = []
        try:
            with self._observability.span("exploration.fact_persistence", **metadata):
                for fact in selected:
                    persisted.append(await self._facts.create(self._to_create(fact)))
        except Exception as error:
            self._observability.event(
                "exploration_fact_persistence_failed",
                duration_ms=int((perf_counter() - started) * 1000),
                persisted_count=len(persisted),
                failure_category="repository_error",
                error_type=type(error).__name__,
                **metadata,
            )
            raise

        result = ExplorationFactPersistenceResult(
            input_count=len(selected),
            persisted_count=len(persisted),
            facts=tuple(persisted),
        )
        self._observability.event(
            "exploration_fact_persistence_completed",
            duration_ms=int((perf_counter() - started) * 1000),
            persisted_count=result.persisted_count,
            **metadata,
        )
        return result

    @staticmethod
    def _to_create(fact: DomainFact) -> ExplorationFactCreate:
        return ExplorationFactCreate(
            exploration_company_id=fact.exploration_company_id,
            statement=fact.statement,
            evidence_ids=list(fact.evidence_ids),
        )
