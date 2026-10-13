"""Persistence operations for Exploration evidence."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from virtual_company.db.models import ExplorationEvidence
from virtual_company.repositories._helpers import apply_updates, create_values
from virtual_company.repositories.dtos import (
    ExplorationEvidenceCreate,
    ExplorationEvidenceUpdate,
)


class ExplorationEvidenceRepository:
    """Provide asynchronous persistence operations for evidence."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, data: ExplorationEvidenceCreate) -> ExplorationEvidence:
        evidence = ExplorationEvidence(**create_values(data))
        self._session.add(evidence)
        await self._session.flush()
        await self._session.refresh(evidence)
        return evidence

    async def get_by_id(self, evidence_id: UUID) -> ExplorationEvidence | None:
        return await self._session.get(ExplorationEvidence, evidence_id)

    async def get_by_id_with_facts(
        self, evidence_id: UUID
    ) -> ExplorationEvidence | None:
        statement = (
            select(ExplorationEvidence)
            .options(selectinload(ExplorationEvidence.facts))
            .where(ExplorationEvidence.id == evidence_id)
        )
        return await self._session.scalar(statement)

    async def list_by_exploration_company_id(
        self, exploration_company_id: UUID
    ) -> list[ExplorationEvidence]:
        statement = select(ExplorationEvidence).where(
            ExplorationEvidence.exploration_company_id == exploration_company_id
        )
        return list(await self._session.scalars(statement))

    async def list_by_obligation_id(
        self, obligation_id: UUID
    ) -> list[ExplorationEvidence]:
        statement = select(ExplorationEvidence).where(
            ExplorationEvidence.exploration_obligation_id == obligation_id
        )
        return list(await self._session.scalars(statement))

    async def update(
        self, evidence_id: UUID, data: ExplorationEvidenceUpdate
    ) -> ExplorationEvidence | None:
        evidence = await self.get_by_id(evidence_id)
        if evidence is None:
            return None
        apply_updates(evidence, data)
        await self._session.flush()
        await self._session.refresh(evidence)
        return evidence
