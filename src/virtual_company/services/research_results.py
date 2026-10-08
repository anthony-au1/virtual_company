"""Read-only research-result projection and human review updates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from virtual_company.domain.criteria import CompanySizeCriteria
from virtual_company.domain.qualification import (
    CompanyQualificationStatus,
    QualificationStatus,
)
from virtual_company.domain.review import ReviewStatus
from virtual_company.repositories.company_qualification import (
    CompanyQualificationRepository,
)
from virtual_company.repositories.evidence import EvidenceRepository
from virtual_company.repositories.research_run import ResearchRunRepository


class ResearchRunNotFoundError(LookupError):
    """Raised when a requested research run does not exist."""


class ResearchCompanyNotFoundError(LookupError):
    """Raised when a company has no result within the requested run."""


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
    technologies: list[str]
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
class CriterionEvidenceView:
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
    evidence: list[CriterionEvidenceView]


@dataclass(frozen=True)
class CompanyResultView:
    company_id: UUID
    name: str
    website: str | None
    qualification_status: CompanyQualificationStatus
    review_status: ReviewStatus
    summary: StatusCountsView
    criteria: list[CriterionResultView]


@dataclass(frozen=True)
class ResearchResultsView:
    research_run: ResearchRunView
    campaign: CampaignResultView
    summary: ResearchSummaryView
    companies: list[CompanyResultView]


@dataclass(frozen=True)
class ReviewResultView:
    company_id: UUID
    review_status: ReviewStatus


@dataclass(frozen=True)
class ResearchRunListSummaryView:
    researched: int
    qualified: int
    not_qualified: int
    insufficient_evidence: int
    accepted: int
    rejected: int
    unreviewed: int


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
        self._qualifications = CompanyQualificationRepository(session)
        self._evidence = EvidenceRepository(session)

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

        qualification_counts = {status: 0 for status in CompanyQualificationStatus}
        companies: list[CompanyResultView] = []
        for snapshot, company in rows:
            qualification_status = CompanyQualificationStatus(snapshot.status)
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
                            CriterionEvidenceView(
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
                CompanyResultView(
                    company_id=company.id,
                    name=company.name,
                    website=company.website,
                    qualification_status=qualification_status,
                    review_status=ReviewStatus(snapshot.review_status),
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
                    technologies=list(campaign.technologies or []),
                    company_size=(
                        CompanySizeCriteria.model_validate(campaign.company_size)
                        if campaign.company_size is not None
                        else None
                    ),
                ),
            ),
            summary=ResearchSummaryView(
                researched=len(companies),
                qualified=qualification_counts[CompanyQualificationStatus.QUALIFIED],
                not_qualified=qualification_counts[
                    CompanyQualificationStatus.NOT_QUALIFIED
                ],
                insufficient_evidence=qualification_counts[
                    CompanyQualificationStatus.INSUFFICIENT_EVIDENCE
                ],
            ),
            companies=companies,
        )

    async def update_review(
        self,
        *,
        research_run_id: UUID,
        company_id: UUID,
        review_status: ReviewStatus,
    ) -> ReviewResultView:
        if await self._runs.get_by_id(research_run_id) is None:
            raise ResearchRunNotFoundError("Research run not found")
        snapshot = await self._qualifications.update_review_status(
            research_run_id=research_run_id,
            company_id=company_id,
            review_status=review_status,
        )
        if snapshot is None:
            raise ResearchCompanyNotFoundError("Company not found in research run")
        await self._session.commit()
        return ReviewResultView(
            company_id=snapshot.company_id,
            review_status=ReviewStatus(snapshot.review_status),
        )

    @staticmethod
    def _status_counts(
        values: dict[QualificationStatus, int],
    ) -> StatusCountsView:
        return StatusCountsView(
            matched=values[QualificationStatus.MATCH],
            mismatched=values[QualificationStatus.MISMATCH],
            unknown=values[QualificationStatus.UNKNOWN],
        )
