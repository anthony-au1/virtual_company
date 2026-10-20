"""Read-only research-result projection and run deletion operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from virtual_company.domain.criteria import CompanySizeCriteria
from virtual_company.domain.qualification import (
    QualificationStatus,
    ResearchCompanyQualificationStatus,
)
from virtual_company.repositories.research_company_qualification import (
    ResearchCompanyQualificationRepository,
)
from virtual_company.repositories.research_evidence import ResearchEvidenceRepository
from virtual_company.repositories.exploration_run import ExplorationRunRepository
from virtual_company.repositories.research_run import ResearchRunRepository


class ResearchRunNotFoundError(LookupError):
    """Raised when a requested research run does not exist."""


class ActiveResearchRunError(ValueError):
    """Raised when a non-terminal run cannot be safely deleted."""


class ReferencedResearchRunError(ValueError):
    """Raised when an ExplorationRun preserves provenance to this run."""


TERMINAL_RESEARCH_RUN_STATUSES = frozenset({"COMPLETED", "FAILED"})


@dataclass(frozen=True)
class ResearchRunView:
    id: UUID
    campaign_id: UUID
    status: str
    started_at: datetime
    completed_at: datetime | None
    error: str | None
    companies_found: int
    created_at: datetime


@dataclass(frozen=True)
class CampaignCriteriaView:
    target_market: str | None
    industry: str | None
    keywords: list[str]
    company_size: CompanySizeCriteria | None


@dataclass(frozen=True)
class CampaignResultView:
    id: UUID
    name: str
    description: str | None
    target_count: int
    max_companies_to_research: int
    criteria: CampaignCriteriaView


@dataclass(frozen=True)
class StatusCountsView:
    matched: int = 0
    mismatched: int = 0
    unknown: int = 0


@dataclass(frozen=True)
class ResearchSummaryView:
    researched: int
    qualified: int
    not_qualified: int
    insufficient_evidence: int


@dataclass(frozen=True)
class ResearchCriterionEvidenceView:
    id: UUID
    claim: str
    evidence_text: str
    source_url: str
    source_title: str | None
    source_type: str | None


@dataclass(frozen=True)
class CriterionResultView:
    criterion: str
    subject: str | None
    status: QualificationStatus
    reason: str
    evidence: list[ResearchCriterionEvidenceView]


@dataclass(frozen=True)
class ResearchCompanyResultView:
    company_id: UUID
    name: str
    website: str | None
    qualification_status: ResearchCompanyQualificationStatus
    summary: StatusCountsView
    criteria: list[CriterionResultView]


@dataclass(frozen=True)
class ResearchResultsView:
    research_run: ResearchRunView
    campaign: CampaignResultView
    summary: ResearchSummaryView
    companies: list[ResearchCompanyResultView]


@dataclass(frozen=True)
class ResearchRunListSummaryView:
    researched: int
    qualified: int
    not_qualified: int
    insufficient_evidence: int


@dataclass(frozen=True)
class ResearchRunListItemView:
    run_id: UUID
    status: str
    created_at: datetime
    started_at: datetime
    completed_at: datetime | None
    campaign_id: UUID
    campaign_name: str
    target_count: int
    max_companies_to_research: int
    summary: ResearchRunListSummaryView


class ResearchResultsService:
    """Build product-facing results exclusively from persisted workflow state."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._runs = ResearchRunRepository(session)
        self._qualifications = ResearchCompanyQualificationRepository(session)
        self._evidence = ResearchEvidenceRepository(session)
        self._exploration_runs = ExplorationRunRepository(session)

    async def list_runs(self) -> list[ResearchRunListItemView]:
        """Return compact run summaries without loading result criteria or evidence."""
        return [
            ResearchRunListItemView(
                run_id=run.id,
                status=run.status,
                created_at=run.created_at,
                started_at=run.started_at,
                completed_at=run.completed_at,
                campaign_id=campaign.id,
                campaign_name=campaign.name,
                target_count=campaign.target_count,
                max_companies_to_research=campaign.max_companies_to_research,
                summary=ResearchRunListSummaryView(**counts),
            )
            for run, campaign, counts in await self._runs.list_with_summary()
        ]

    async def get_results(self, research_run_id: UUID) -> ResearchResultsView:
        run = await self._runs.get_by_id_with_campaign(research_run_id)
        if run is None:
            raise ResearchRunNotFoundError("Research run not found")

        rows = await self._qualifications.list_for_run(research_run_id)
        run_evidence = await self._evidence.list_by_research_run_id(research_run_id)
        evidence_by_company_and_id = {
            (item.company_id, item.id): item for item in run_evidence
        }

        qualification_counts = {
            status: 0 for status in ResearchCompanyQualificationStatus
        }
        companies: list[ResearchCompanyResultView] = []
        for snapshot, company in rows:
            qualification_status = ResearchCompanyQualificationStatus(snapshot.status)
            qualification_counts[qualification_status] += 1
            criteria: list[CriterionResultView] = []
            summary_counts = {status: 0 for status in QualificationStatus}
            for stored in snapshot.criteria_results.get("criteria", []):
                criterion_status = QualificationStatus(stored["status"])
                summary_counts[criterion_status] += 1
                evidence = []
                for stored_id in stored.get("evidence_ids", []):
                    item = evidence_by_company_and_id.get(
                        (company.id, UUID(str(stored_id)))
                    )
                    if item is not None:
                        evidence.append(
                            ResearchCriterionEvidenceView(
                                id=item.id,
                                claim=item.claim,
                                evidence_text=item.evidence_text,
                                source_url=item.source_url,
                                source_title=item.source_title,
                                source_type=item.source_type,
                            )
                        )
                criteria.append(
                    CriterionResultView(
                        criterion=stored["criterion"],
                        subject=stored.get("subject"),
                        status=criterion_status,
                        reason=stored["reason"],
                        evidence=evidence,
                    )
                )
            companies.append(
                ResearchCompanyResultView(
                    company_id=company.id,
                    name=company.name,
                    website=company.website,
                    qualification_status=qualification_status,
                    summary=self._status_counts(summary_counts),
                    criteria=criteria,
                )
            )

        campaign = run.campaign
        return ResearchResultsView(
            research_run=ResearchRunView(
                id=run.id,
                campaign_id=run.campaign_id,
                status=run.status,
                started_at=run.started_at,
                completed_at=run.completed_at,
                error=run.error,
                companies_found=run.companies_found,
                created_at=run.created_at,
            ),
            campaign=CampaignResultView(
                id=campaign.id,
                name=campaign.name,
                description=campaign.description,
                target_count=campaign.target_count,
                max_companies_to_research=campaign.max_companies_to_research,
                criteria=CampaignCriteriaView(
                    target_market=campaign.target_market,
                    industry=campaign.industry,
                    keywords=list(campaign.keywords or []),
                    company_size=(
                        CompanySizeCriteria.model_validate(campaign.company_size)
                        if campaign.company_size is not None
                        else None
                    ),
                ),
            ),
            summary=ResearchSummaryView(
                researched=len(companies),
                qualified=qualification_counts[
                    ResearchCompanyQualificationStatus.QUALIFIED
                ],
                not_qualified=qualification_counts[
                    ResearchCompanyQualificationStatus.NOT_QUALIFIED
                ],
                insufficient_evidence=qualification_counts[
                    ResearchCompanyQualificationStatus.INSUFFICIENT_EVIDENCE
                ],
            ),
            companies=companies,
        )

    async def delete_run(self, research_run_id: UUID) -> bool:
        """Delete one terminal run and its exclusively owned result data."""
        run = await self._runs.get_by_id_for_update(research_run_id)
        if run is None:
            return False
        if run.status not in TERMINAL_RESEARCH_RUN_STATUSES:
            raise ActiveResearchRunError(
                "A non-terminal research run cannot be deleted"
            )
        if await self._exploration_runs.exists_for_research_run(research_run_id):
            raise ReferencedResearchRunError(
                "A research run referenced by an Exploration cannot be deleted"
            )
        await self._evidence.delete_by_research_run_id(research_run_id)
        await self._qualifications.delete_by_research_run_id(research_run_id)
        await self._runs.delete(run)
        await self._session.commit()
        return True

    @staticmethod
    def _status_counts(
        values: dict[QualificationStatus, int],
    ) -> StatusCountsView:
        return StatusCountsView(
            matched=values[QualificationStatus.MATCH],
            mismatched=values[QualificationStatus.MISMATCH],
            unknown=values[QualificationStatus.UNKNOWN],
        )
