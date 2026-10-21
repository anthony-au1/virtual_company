"""Persistence operations for company membership in Exploration runs."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from virtual_company.db.models import ExplorationCompany
from virtual_company.repositories._helpers import create_values
from virtual_company.repositories.dtos import ExplorationCompanyCreate


class ExplorationCompanyRepository:
    """Provide asynchronous persistence operations for run companies."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, data: ExplorationCompanyCreate) -> ExplorationCompany:
        link = ExplorationCompany(**create_values(data))
        self._session.add(link)
        await self._session.flush()
        await self._session.refresh(link)
        return link

    async def create_many(
        self, exploration_run_id: UUID, company_ids: list[UUID]
    ) -> list[ExplorationCompany]:
        """Stage the selected company references together and flush atomically."""
        links = [
            ExplorationCompany(
                exploration_run_id=exploration_run_id, company_id=company_id
            )
            for company_id in company_ids
        ]
        self._session.add_all(links)
        await self._session.flush()
        return links

    async def get_by_id(self, link_id: UUID) -> ExplorationCompany | None:
        return await self._session.get(ExplorationCompany, link_id)

    async def get_by_run_and_company(
        self, exploration_run_id: UUID, company_id: UUID
    ) -> ExplorationCompany | None:
        statement = (
            select(ExplorationCompany)
            .options(selectinload(ExplorationCompany.company))
            .where(
                ExplorationCompany.exploration_run_id == exploration_run_id,
                ExplorationCompany.company_id == company_id,
            )
        )
        return await self._session.scalar(statement)

    async def list_by_run_id(self, run_id: UUID) -> list[ExplorationCompany]:
        statement = (
            select(ExplorationCompany)
            .options(selectinload(ExplorationCompany.company))
            .where(ExplorationCompany.exploration_run_id == run_id)
        )
        return list(await self._session.scalars(statement))
