"""Application service for the research workflow's persistent state."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from virtual_company.db.models import ResearchCompany, ResearchEvidence, ResearchRun
from virtual_company.domain.qualification import ResearchCompanyQualification
from virtual_company.domain.research import DiscoveredCompany
from virtual_company.repositories.campaign import CampaignRepository
from virtual_company.repositories.campaign_target import CampaignTargetRepository
from virtual_company.repositories.dtos import (
    CampaignTargetCreate,
    ResearchCompanyCreate,
    ResearchCompanyQualificationUpsert,
    ResearchEvidenceCreate,
    ResearchRunCreate,
    ResearchRunUpdate,
)
from virtual_company.repositories.research_company import ResearchCompanyRepository
from virtual_company.repositories.research_company_qualification import (
    ResearchCompanyQualificationRepository,
)
from virtual_company.repositories.research_evidence import ResearchEvidenceRepository
from virtual_company.repositories.research_run import ResearchRunRepository
from virtual_company.utils.url_normalization import normalize_domain


@dataclass(frozen=True)
class PersistedResearchCompanies:
    """The new campaign-candidate count and exact company records resolved for one run."""

    companies_found: int
    companies: list[ResearchCompany]
    discovered_by_company_id: dict[UUID, DiscoveredCompany]


@dataclass(frozen=True)
class PersistedResearchEvidence:
    """Outcome of idempotently storing evidence for one research run."""

    created_count: int
    skipped_count: int
    created_by_company: dict[UUID, int]
    items: list[ResearchEvidence] | None = None


class ResearchService:
    """Persist research runs and campaign-company associations."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._campaigns = CampaignRepository(session)
        self._companies = ResearchCompanyRepository(session)
        self._targets = CampaignTargetRepository(session)
        self._runs = ResearchRunRepository(session)
        self._evidence = ResearchEvidenceRepository(session)
        self._qualifications = ResearchCompanyQualificationRepository(session)

    async def create_run(self, campaign_id: UUID) -> ResearchRun:
        """Create and commit a running research execution."""
        campaign = await self._campaigns.seal_for_research(campaign_id)
        if campaign is None:
            raise ValueError("Campaign was not found")
        created_at = datetime.now(UTC)
        run = await self._runs.create(
            ResearchRunCreate(
                campaign_id=campaign_id,
                status="RUNNING",
                companies_found=0,
                created_at=created_at,
                started_at=created_at,
            )
        )
        await self._session.commit()
        return run

    async def persist_companies(
        self,
        *,
        campaign_id: UUID,
        companies: list[DiscoveredCompany],
    ) -> PersistedResearchCompanies:
        """Persist discovery candidates and return their resolved records for this run."""
        created_targets = 0
        persisted_companies: list[ResearchCompany] = []
        discovered_by_company_id: dict[UUID, DiscoveredCompany] = {}
        for discovered in companies:
            domain = normalize_domain(discovered.domain or discovered.website)
            company = (
                await self._companies.get_by_normalized_domain(domain)
                if domain is not None
                else None
            )
            if company is None:
                company = await self._companies.create(
                    ResearchCompanyCreate(
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
            discovered_by_company_id[company.id] = discovered
        return PersistedResearchCompanies(
            companies_found=created_targets,
            companies=persisted_companies,
            discovered_by_company_id=discovered_by_company_id,
        )

    async def complete_run(
        self, research_run_id: UUID, companies_found: int
    ) -> ResearchRun:
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

    async def persist_research_evidence(
        self, *, research_run_id: UUID, evidence: list[ResearchEvidenceCreate]
    ) -> PersistedResearchEvidence:
        """Store distinct evidence items without duplicating a retried node's output."""
        existing = await self._evidence.list_by_research_run_id(research_run_id)
        existing_by_key = {self._research_evidence_key(item): item for item in existing}
        seen = set(existing_by_key)
        created_count = 0
        skipped_count = 0
        created_by_company: dict[UUID, int] = {}
        persisted_items: list[ResearchEvidence] = []
        for item in evidence:
            if item.research_run_id != research_run_id:
                raise ValueError("Evidence must belong to the active research run")
            key = self._research_evidence_key(item)
            if key in seen:
                skipped_count += 1
                if key in existing_by_key:
                    persisted_items.append(existing_by_key[key])
                continue
            persisted = await self._evidence.create(item)
            persisted_items.append(persisted)
            existing_by_key[key] = persisted
            seen.add(key)
            created_count += 1
            created_by_company[item.company_id] = (
                created_by_company.get(item.company_id, 0) + 1
            )
        return PersistedResearchEvidence(
            created_count=created_count,
            skipped_count=skipped_count,
            created_by_company=created_by_company,
            items=persisted_items,
        )

    async def persist_research_company_qualifications(
        self,
        *,
        campaign_id: UUID,
        research_run_id: UUID,
        qualifications: Sequence[ResearchCompanyQualification],
    ) -> None:
        """Stage final snapshots for the same transaction as run completion."""
        for result in qualifications:
            await self._qualifications.upsert(
                ResearchCompanyQualificationUpsert(
                    campaign_id=campaign_id,
                    research_run_id=research_run_id,
                    company_id=result.company_id,
                    status=result.status.value,
                    criteria_results={
                        "criteria": [
                            {
                                "criterion_id": f"criterion_{index}",
                                "criterion": item.criterion,
                                "subject": item.subject,
                                "status": item.status.value,
                                "evidence_ids": [
                                    str(value) for value in item.evidence_ids
                                ],
                                "reason": item.reason,
                            }
                            for index, item in enumerate(result.criteria)
                        ],
                        **(
                            {"provenance": result.provenance}
                            if result.provenance is not None
                            else {}
                        ),
                    },
                )
            )

    async def list_research_evidence_for_run(
        self, research_run_id: UUID
    ) -> list[ResearchEvidence]:
        """Load all accumulated Evidence for one research execution."""
        return await self._evidence.list_by_research_run_id(research_run_id)

    async def list_research_evidence_for_company(
        self, company_id: UUID
    ) -> list[ResearchEvidence]:
        """Load persisted company evidence across research runs."""
        return await self._evidence.list_by_research_company_id(company_id)

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
    def _research_evidence_key(
        evidence: ResearchEvidence | ResearchEvidenceCreate,
    ) -> tuple[str, ...]:
        """Return a conservative normalized identity for same-run evidence."""

        def normalized(value: object) -> str:
            return " ".join(str(value or "").split()).casefold()

        return (
            str(evidence.company_id),
            normalized(evidence.criterion),
            normalized(evidence.subject),
            normalized(evidence.evidence_text),
        )
