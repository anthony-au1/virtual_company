"""Application service for the research workflow's persistent state."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from virtual_company.db.models import ResearchRun
from virtual_company.repositories.campaign_target import CampaignTargetRepository
from virtual_company.repositories.company import CompanyRepository
from virtual_company.repositories.dtos import (
    CampaignTargetCreate,
    CompanyCreate,
    ResearchRunCreate,
    ResearchRunUpdate,
)
from virtual_company.repositories.research_run import ResearchRunRepository
from virtual_company.research.models import DiscoveredCompany
from virtual_company.research.normalization import normalize_domain


class ResearchService:
    """Persist research runs and campaign-company associations."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._companies = CompanyRepository(session)
        self._targets = CampaignTargetRepository(session)
        self._runs = ResearchRunRepository(session)

    async def create_run(self, campaign_id: UUID) -> ResearchRun:
        """Create and commit a running research execution."""
        run = await self._runs.create(
            ResearchRunCreate(
                campaign_id=campaign_id,
                status="RUNNING",
                companies_found=0,
                started_at=datetime.now(UTC),
            )
        )
        await self._session.commit()
        return run

    async def persist_companies(
        self,
        *,
        campaign_id: UUID,
        companies: list[DiscoveredCompany],
    ) -> int:
        """Persist companies and return newly created campaign associations."""
        created_targets = 0
        for discovered in companies:
            domain = normalize_domain(discovered.domain or discovered.website)
            company = (
                await self._companies.get_by_normalized_domain(domain)
                if domain is not None
                else None
            )
            if company is None:
                company = await self._companies.create(
                    CompanyCreate(
                        name=discovered.name,
                        website=discovered.website,
                        domain=domain,
                    )
                )

            if await self._targets.get_by_id(campaign_id, company.id) is None:
                await self._targets.create(
                    CampaignTargetCreate(campaign_id=campaign_id, company_id=company.id)
                )
                created_targets += 1
        return created_targets

    async def complete_run(self, research_run_id: UUID, companies_found: int) -> ResearchRun:
        """Mark a run complete and commit its associated persistence work."""
        run = await self._runs.update(
            research_run_id,
            ResearchRunUpdate(
                status="COMPLETED",
                completed_at=datetime.now(UTC),
                companies_found=companies_found,
            ),
        )
        if run is None:
            raise ValueError("Research run was not found")
        await self._session.commit()
        return run

    async def fail_run(self, research_run_id: UUID, error: str) -> ResearchRun:
        """Discard uncommitted work and persist a failed run."""
        await self._session.rollback()
        run = await self._runs.update(
            research_run_id,
            ResearchRunUpdate(
                status="FAILED", completed_at=datetime.now(UTC), error=error
            ),
        )
        if run is None:
            raise ValueError("Research run was not found")
        await self._session.commit()
        return run
