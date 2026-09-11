"""Persistence operations for campaigns."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from virtual_company.db.models import Campaign
from virtual_company.repositories._helpers import apply_updates, create_values
from virtual_company.repositories.dtos import CampaignCreate, CampaignUpdate


class CampaignRepository:
    """Provide asynchronous persistence operations for campaigns."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, data: CampaignCreate) -> Campaign:
        campaign = Campaign(**create_values(data))
        self._session.add(campaign)
        await self._session.flush()
        await self._session.refresh(campaign)
        return campaign

    async def get_by_id(self, campaign_id: UUID) -> Campaign | None:
        return await self._session.get(Campaign, campaign_id)

    async def list(self) -> list[Campaign]:
        return list(await self._session.scalars(select(Campaign)))

    async def update(self, campaign_id: UUID, data: CampaignUpdate) -> Campaign | None:
        campaign = await self.get_by_id(campaign_id)
        if campaign is None:
            return None

        apply_updates(campaign, data)
        await self._session.flush()
        await self._session.refresh(campaign)
        return campaign
