"""Persist validated Exploration Evidence without coupling extraction to storage."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from sqlalchemy.ext.asyncio import AsyncSession

from virtual_company.db.models import ExplorationEvidence as PersistedEvidence
from virtual_company.domain.exploration.evidence import (
    ExplorationEvidence as DomainEvidence,
)
from virtual_company.observability import Observability, get_observability
from virtual_company.repositories.dtos import ExplorationEvidenceCreate
from virtual_company.repositories.exploration_evidence import (
    ExplorationEvidenceRepository,
)
from virtual_company.services.exploration_evidence_extractor import (
    ExplorationEvidenceExtractionBatchResult,
    ExplorationEvidenceExtractionOutcome,
)


@dataclass(frozen=True)
class ExplorationEvidencePersistenceResult:
    """Created Evidence rows and batch accounting, in first-seen order."""

    input_count: int
    unique_count: int
    persisted_count: int
    evidence: tuple[PersistedEvidence, ...]


class ExplorationEvidencePersistenceService:
    """Map successful validated Evidence into immutable persistence records."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        observability: Observability | None = None,
    ) -> None:
        self._evidence = ExplorationEvidenceRepository(session)
        self._observability = observability or get_observability()

    async def persist(
        self,
        extraction_batch: ExplorationEvidenceExtractionBatchResult,
    ) -> ExplorationEvidencePersistenceResult:
        """Persist successful Evidence, deduplicating fan-out within this batch."""
        input_count = sum(len(result.evidence) for result in extraction_batch.results)
        selected: list[ExplorationEvidenceCreate] = []
        seen: set[tuple[str, str, str, str, str]] = set()

        for page_result in extraction_batch.results:
            if (
                page_result.outcome
                is not ExplorationEvidenceExtractionOutcome.SUCCEEDED
            ):
                continue
            for evidence in page_result.evidence:
                create = self._to_create(evidence)
                key = self._identity(create)
                if key in seen:
                    continue
                seen.add(key)
                selected.append(create)

        metadata = {
            "provider": extraction_batch.provider,
            "model": extraction_batch.model,
            "input_evidence_count": input_count,
            "unique_evidence_count": len(selected),
        }
        self._observability.event(
            "exploration_evidence_persistence_started", **metadata
        )
        started = perf_counter()
        persisted: list[PersistedEvidence] = []
        try:
            with self._observability.span(
                "exploration.evidence_persistence", **metadata
            ):
                for create in selected:
                    persisted.append(await self._evidence.create(create))
        except Exception as error:
            self._observability.event(
                "exploration_evidence_persistence_failed",
                duration_ms=int((perf_counter() - started) * 1000),
                persisted_count=len(persisted),
                error_type=type(error).__name__,
                **metadata,
            )
            raise

        result = ExplorationEvidencePersistenceResult(
            input_count=input_count,
            unique_count=len(selected),
            persisted_count=len(persisted),
            evidence=tuple(persisted),
        )
        self._observability.event(
            "exploration_evidence_persistence_completed",
            duration_ms=int((perf_counter() - started) * 1000),
            persisted_count=result.persisted_count,
            **metadata,
        )
        return result

    @staticmethod
    def _to_create(evidence: DomainEvidence) -> ExplorationEvidenceCreate:
        final_url = evidence.final_url
        source_url = (
            final_url
            if final_url is not None and final_url.strip()
            else evidence.source_url
        )
        requested_url = (
            evidence.source_url if evidence.source_url != source_url else None
        )
        return ExplorationEvidenceCreate(
            exploration_company_id=evidence.exploration_company_id,
            exploration_obligation_id=evidence.exploration_obligation_id,
            claim=evidence.claim,
            supporting_excerpt=evidence.supporting_excerpt,
            source_url=source_url,
            requested_url=requested_url,
            source_title=evidence.source_title,
        )

    @staticmethod
    def _identity(
        evidence: ExplorationEvidenceCreate,
    ) -> tuple[str, str, str, str, str]:
        return (
            str(evidence.exploration_company_id),
            str(evidence.exploration_obligation_id),
            evidence.source_url,
            " ".join(evidence.claim.split()),
            " ".join(evidence.supporting_excerpt.split()),
        )
