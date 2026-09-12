"""Campaign application service."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from virtual_company.db.models import Campaign, Company
from virtual_company.repositories.campaign import CampaignRepository
from virtual_company.repositories.company import CompanyRepository
from virtual_company.repositories.dtos import CampaignCreate, CampaignUpdate


class CampaignService:
    """Coordinate campaign persistence operations."""

    def __init__(self, session: AsyncSession) -> None:
        self._campaigns = CampaignRepository(session)
        self._companies = CompanyRepository(session)

    async def create(self, data: CampaignCreate) -> Campaign:
        return await self._campaigns.create(data)

    async def get_by_id(self, campaign_id: UUID) -> Campaign | None:
        return await self._campaigns.get_by_id(campaign_id)

    async def list(self) -> list[Campaign]:
        return await self._campaigns.list()

    async def update(self, campaign_id: UUID, data: CampaignUpdate) -> Campaign | None:
        return await self._campaigns.update(campaign_id, data)

    async def list_companies(self, campaign_id: UUID) -> list[Company] | None:
        if await self._campaigns.get_by_id(campaign_id) is None:
            return None
        return await self._companies.list_by_campaign_id(campaign_id)
