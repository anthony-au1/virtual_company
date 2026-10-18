"""Persistence operations for campaigns."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from virtual_company.db.models import Campaign
from virtual_company.repositories.dtos import CampaignCreate, CampaignUpdate


class CampaignRepository:
    """Provide asynchronous persistence operations for campaigns."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, data: CampaignCreate) -> Campaign:
        campaign = Campaign(**data.model_dump(mode="json", exclude_none=True))
        self._session.add(campaign)
        await self._session.flush()
        await self._session.refresh(campaign)
        return campaign

    async def get_by_id(self, campaign_id: UUID) -> Campaign | None:
        return await self._session.get(Campaign, campaign_id)

    async def get_by_id_for_update(self, campaign_id: UUID) -> Campaign | None:
        return await self._session.scalar(
            select(Campaign).where(Campaign.id == campaign_id).with_for_update()
        )

    async def seal_for_research(self, campaign_id: UUID) -> Campaign | None:
        campaign = await self.get_by_id_for_update(campaign_id)
        if campaign is None:
            return None
        if campaign.sealed_at is None:
            campaign.sealed_at = datetime.now(UTC)
            await self._session.flush()
        return campaign

    async def list(self) -> list[Campaign]:
        return list(await self._session.scalars(select(Campaign)))

    async def delete(self, campaign: Campaign) -> None:
        await self._session.delete(campaign)
        await self._session.flush()

    async def update(self, campaign_id: UUID, data: CampaignUpdate) -> Campaign | None:
        campaign = await self.get_by_id(campaign_id)
        if campaign is None:
            return None

        for field_name, value in data.model_dump(
            mode="json", exclude_unset=True
        ).items():
            setattr(campaign, field_name, value)
        await self._session.flush()
        await self._session.refresh(campaign)
        return campaign
