"""Persistence operations for companies."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from virtual_company.db.models import CampaignTarget, ResearchCompany
from virtual_company.repositories._helpers import apply_updates, create_values
from virtual_company.repositories.dtos import (
    ResearchCompanyCreate,
    ResearchCompanyUpdate,
)
from virtual_company.utils.url_normalization import normalize_domain


class ResearchCompanyRepository:
    """Provide asynchronous persistence operations for companies."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, data: ResearchCompanyCreate) -> ResearchCompany:
        company = ResearchCompany(**create_values(data))
        self._session.add(company)
        await self._session.flush()
        await self._session.refresh(company)
        return company

    async def get_by_id(self, company_id: UUID) -> ResearchCompany | None:
        return await self._session.get(ResearchCompany, company_id)

    async def get_by_normalized_domain(self, domain: str) -> ResearchCompany | None:
        """Return the company whose stored domain normalizes to ``domain``."""
        companies = await self._session.scalars(
            select(ResearchCompany).where(ResearchCompany.domain.is_not(None))
        )
        return next(
            (
                company
                for company in companies
                if normalize_domain(company.domain) == domain
            ),
            None,
        )

    async def list(self) -> list[ResearchCompany]:
        return list(await self._session.scalars(select(ResearchCompany)))

    async def list_by_campaign_id(self, campaign_id: UUID) -> list[ResearchCompany]:
        statement = (
            select(ResearchCompany)
            .join(CampaignTarget)
            .where(CampaignTarget.campaign_id == campaign_id)
        )
        return list(await self._session.scalars(statement))

    async def update(
        self, company_id: UUID, data: ResearchCompanyUpdate
    ) -> ResearchCompany | None:
        company = await self.get_by_id(company_id)
        if company is None:
            return None

        apply_updates(company, data)
        await self._session.flush()
        await self._session.refresh(company)
        return company
