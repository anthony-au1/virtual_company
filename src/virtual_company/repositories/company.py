"""Persistence operations for companies."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from virtual_company.db.models import Company
from virtual_company.repositories._helpers import apply_updates, create_values
from virtual_company.repositories.dtos import CompanyCreate, CompanyUpdate


class CompanyRepository:
    """Provide asynchronous persistence operations for companies."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, data: CompanyCreate) -> Company:
        company = Company(**create_values(data))
        self._session.add(company)
        await self._session.flush()
        await self._session.refresh(company)
        return company

    async def get_by_id(self, company_id: UUID) -> Company | None:
        return await self._session.get(Company, company_id)

    async def list(self) -> list[Company]:
        return list(await self._session.scalars(select(Company)))

    async def update(self, company_id: UUID, data: CompanyUpdate) -> Company | None:
        company = await self.get_by_id(company_id)
        if company is None:
            return None

        apply_updates(company, data)
        await self._session.flush()
        await self._session.refresh(company)
        return company
