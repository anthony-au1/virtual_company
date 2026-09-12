"""Evidence application service."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from virtual_company.db.models import Evidence
from virtual_company.repositories.company import CompanyRepository
from virtual_company.repositories.evidence import EvidenceRepository


class EvidenceService:
    """Coordinate evidence retrieval operations."""

    def __init__(self, session: AsyncSession) -> None:
        self._companies = CompanyRepository(session)
        self._evidence = EvidenceRepository(session)

    async def list_for_company(self, company_id: UUID) -> list[Evidence] | None:
        if await self._companies.get_by_id(company_id) is None:
            return None
        return await self._evidence.list_by_company_id(company_id)
