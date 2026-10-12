"""Evidence application service."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from virtual_company.db.models import ResearchEvidence
from virtual_company.repositories.research_company import ResearchCompanyRepository
from virtual_company.repositories.research_evidence import ResearchEvidenceRepository


class ResearchEvidenceService:
    """Coordinate evidence retrieval operations."""

    def __init__(self, session: AsyncSession) -> None:
        self._companies = ResearchCompanyRepository(session)
        self._evidence = ResearchEvidenceRepository(session)

    async def list_for_research_company(
        self, company_id: UUID
    ) -> list[ResearchEvidence] | None:
        if await self._companies.get_by_id(company_id) is None:
            return None
        return await self._evidence.list_by_research_company_id(company_id)
