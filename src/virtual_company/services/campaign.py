"""Campaign application service."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from virtual_company.db.models import Campaign, ResearchCompany
from virtual_company.repositories.campaign import CampaignRepository
from virtual_company.repositories.dtos import CampaignCreate, CampaignUpdate
from virtual_company.repositories.research_company import ResearchCompanyRepository


class CampaignLimitValidationError(ValueError):
    """Raised when a campaign research limit is below its qualification target."""


class CampaignSealedError(ValueError):
    """Raised when a sealed campaign's research definition is changed."""


class CampaignService:
    """Coordinate campaign persistence operations."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._campaigns = CampaignRepository(session)
        self._companies = ResearchCompanyRepository(session)

    async def create(self, data: CampaignCreate) -> Campaign:
        async with self._session.begin():
            return await self._campaigns.create(data)

    async def get_by_id(self, campaign_id: UUID) -> Campaign | None:
        return await self._campaigns.get_by_id(campaign_id)

    async def list(self) -> list[Campaign]:
        return await self._campaigns.list()

    async def seal_for_research(self, campaign_id: UUID) -> Campaign | None:
        """Persist the campaign's first-run seal while holding its row lock."""
        return await self._campaigns.seal_for_research(campaign_id)

    async def update(self, campaign_id: UUID, data: CampaignUpdate) -> Campaign | None:
        async with self._session.begin():
            current = await self._campaigns.get_by_id_for_update(campaign_id)
            if current is None:
                return None
            definition_fields = {
                "name",
                "description",
                "target_market",
                "industry",
                "technologies",
                "company_size",
                "target_count",
                "max_companies_to_research",
            }
            changed_fields = data.model_fields_set & definition_fields
            if current.sealed_at is not None and changed_fields:
                fields = ", ".join(sorted(changed_fields))
                raise CampaignSealedError(
                    f"Campaign research definition is sealed; cannot change: {fields}"
                )
            target_count = (
                data.target_count
                if data.target_count is not None
                else current.target_count
            )
            max_companies = (
                data.max_companies_to_research
                if data.max_companies_to_research is not None
                else current.max_companies_to_research
            )
            if max_companies < target_count:
                raise CampaignLimitValidationError(
                    "max_companies_to_research cannot be less than target_count"
                )
            return await self._campaigns.update(campaign_id, data)

    async def list_research_companies(
        self, campaign_id: UUID
    ) -> list[ResearchCompany] | None:
        if await self._campaigns.get_by_id(campaign_id) is None:
            return None
        return await self._companies.list_by_campaign_id(campaign_id)
