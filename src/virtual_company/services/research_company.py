"""Company application service."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from virtual_company.db.models import ResearchCompany
from virtual_company.repositories.research_company import ResearchCompanyRepository


class ResearchCompanyService:
    """Coordinate company retrieval operations."""

    def __init__(self, session: AsyncSession) -> None:
        self._companies = ResearchCompanyRepository(session)

    async def get_by_id(self, company_id: UUID) -> ResearchCompany | None:
        return await self._companies.get_by_id(company_id)
