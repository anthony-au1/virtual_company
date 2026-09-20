"""Application service for the research workflow's persistent state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from virtual_company.db.models import Company, Evidence, ResearchRun
from virtual_company.repositories.campaign_target import CampaignTargetRepository
from virtual_company.repositories.company import CompanyRepository
from virtual_company.repositories.dtos import (
    CampaignTargetCreate,
    CompanyCreate,
    EvidenceCreate,
    ResearchRunCreate,
    ResearchRunUpdate,
)
from virtual_company.repositories.evidence import EvidenceRepository
from virtual_company.repositories.research_run import ResearchRunRepository
from virtual_company.research.models import DiscoveredCompany
from virtual_company.research.normalization import normalize_domain


@dataclass(frozen=True)
class PersistedCompanies:
    """The new campaign-candidate count and exact company records resolved for one run."""

    companies_found: int
    companies: list[Company]


@dataclass(frozen=True)
class PersistedEvidence:
    """Outcome of idempotently storing evidence for one research run."""

    created_count: int
    skipped_count: int


class ResearchService:
    """Persist research runs and campaign-company associations."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._companies = CompanyRepository(session)
        self._targets = CampaignTargetRepository(session)
        self._runs = ResearchRunRepository(session)
        self._evidence = EvidenceRepository(session)

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
    ) -> PersistedCompanies:
        """Persist discovery candidates and return their resolved records for this run."""
        created_targets = 0
        persisted_companies: list[Company] = []
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
            persisted_companies.append(company)
        return PersistedCompanies(
            companies_found=created_targets,
            companies=persisted_companies,
        )

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

    async def persist_evidence(
        self, *, research_run_id: UUID, evidence: list[EvidenceCreate]
    ) -> PersistedEvidence:
        """Store distinct evidence items without duplicating a retried node's output."""
        existing = await self._evidence.list_by_research_run_id(research_run_id)
        seen = {self._evidence_key(item) for item in existing}
        created_count = 0
        skipped_count = 0
        for item in evidence:
            if item.research_run_id != research_run_id:
                raise ValueError("Evidence must belong to the active research run")
            key = self._evidence_key(item)
            if key in seen:
                skipped_count += 1
                continue
            await self._evidence.create(item)
            seen.add(key)
            created_count += 1
        return PersistedEvidence(created_count=created_count, skipped_count=skipped_count)

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

    @staticmethod
    def _evidence_key(evidence: Evidence | EvidenceCreate) -> tuple[str, ...]:
        """Return a conservative normalized identity for same-run evidence."""

        def normalized(value: object) -> str:
            return " ".join(str(value or "").split()).casefold()

        return (
            str(evidence.company_id),
            normalized(evidence.source_url),
            normalized(evidence.criterion),
            normalized(evidence.subject),
            normalized(evidence.claim),
            normalized(evidence.evidence_text),
        )
