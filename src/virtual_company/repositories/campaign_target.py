"""Persistence operations for campaign targets."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from virtual_company.db.models import CampaignTarget
from virtual_company.repositories._helpers import apply_updates, create_values
from virtual_company.repositories.dtos import CampaignTargetCreate, CampaignTargetUpdate


class CampaignTargetRepository:
    """Provide asynchronous persistence operations for campaign targets."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, data: CampaignTargetCreate) -> CampaignTarget:
        target = CampaignTarget(**create_values(data))
        self._session.add(target)
        await self._session.flush()
        await self._session.refresh(target)
        return target

    async def get_by_id(
        self, campaign_id: UUID, company_id: UUID
    ) -> CampaignTarget | None:
        return await self._session.get(CampaignTarget, (campaign_id, company_id))

    async def list(self) -> list[CampaignTarget]:
        return list(await self._session.scalars(select(CampaignTarget)))

    async def update(
        self,
        campaign_id: UUID,
        company_id: UUID,
        data: CampaignTargetUpdate,
    ) -> CampaignTarget | None:
        target = await self.get_by_id(campaign_id, company_id)
        if target is None:
            return None

        apply_updates(target, data)
        await self._session.flush()
        await self._session.refresh(target)
        return target
