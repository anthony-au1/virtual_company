"""Persistence operations for evidence."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from virtual_company.db.models import ResearchEvidence
from virtual_company.repositories._helpers import apply_updates, create_values
from virtual_company.repositories.dtos import (
    ResearchEvidenceCreate,
    ResearchEvidenceUpdate,
)


class ResearchEvidenceRepository:
    """Provide asynchronous persistence operations for evidence."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, data: ResearchEvidenceCreate) -> ResearchEvidence:
        evidence = ResearchEvidence(**create_values(data))
        self._session.add(evidence)
        await self._session.flush()
        await self._session.refresh(evidence)
        return evidence

    async def get_by_id(self, evidence_id: UUID) -> ResearchEvidence | None:
        return await self._session.get(ResearchEvidence, evidence_id)

    async def list(self) -> list[ResearchEvidence]:
        return list(await self._session.scalars(select(ResearchEvidence)))

    async def list_by_research_company_id(
        self, company_id: UUID
    ) -> list[ResearchEvidence]:
        statement = select(ResearchEvidence).where(
            ResearchEvidence.company_id == company_id
        )
        return list(await self._session.scalars(statement))

    async def list_by_research_run_id(
        self, research_run_id: UUID
    ) -> list[ResearchEvidence]:
        statement = select(ResearchEvidence).where(
            ResearchEvidence.research_run_id == research_run_id
        )
        return list(await self._session.scalars(statement))

    async def delete_by_research_run_id(self, research_run_id: UUID) -> None:
        for evidence in await self._session.scalars(
            select(ResearchEvidence).where(
                ResearchEvidence.research_run_id == research_run_id
            )
        ):
            await self._session.delete(evidence)
        await self._session.flush()

    async def update(
        self, evidence_id: UUID, data: ResearchEvidenceUpdate
    ) -> ResearchEvidence | None:
        evidence = await self.get_by_id(evidence_id)
        if evidence is None:
            return None

        apply_updates(evidence, data)
        await self._session.flush()
        await self._session.refresh(evidence)
        return evidence
