"""Persistence operations for evidence."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from virtual_company.db.models import Evidence
from virtual_company.repositories._helpers import apply_updates, create_values
from virtual_company.repositories.dtos import EvidenceCreate, EvidenceUpdate


class EvidenceRepository:
    """Provide asynchronous persistence operations for evidence."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, data: EvidenceCreate) -> Evidence:
        evidence = Evidence(**create_values(data))
        self._session.add(evidence)
        await self._session.flush()
        await self._session.refresh(evidence)
        return evidence

    async def get_by_id(self, evidence_id: UUID) -> Evidence | None:
        return await self._session.get(Evidence, evidence_id)

    async def list(self) -> list[Evidence]:
        return list(await self._session.scalars(select(Evidence)))

    async def list_by_company_id(self, company_id: UUID) -> list[Evidence]:
        statement = select(Evidence).where(Evidence.company_id == company_id)
        return list(await self._session.scalars(statement))

    async def list_by_research_run_id(self, research_run_id: UUID) -> list[Evidence]:
        statement = select(Evidence).where(Evidence.research_run_id == research_run_id)
        return list(await self._session.scalars(statement))

    async def update(self, evidence_id: UUID, data: EvidenceUpdate) -> Evidence | None:
        evidence = await self.get_by_id(evidence_id)
        if evidence is None:
            return None

        apply_updates(evidence, data)
        await self._session.flush()
        await self._session.refresh(evidence)
        return evidence
