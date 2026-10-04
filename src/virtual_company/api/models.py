"""Pydantic models exposed by the HTTP API."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from virtual_company.domain.criteria import (
    CompanySizeCriteria,
    CriterionRequirement,
    TechnologyCriteria,
)
from virtual_company.domain.qualification import (
    CompanyQualificationStatus,
    QualificationStatus,
)
from virtual_company.domain.review import ReviewStatus
from virtual_company.repositories.dtos import CampaignCreate, CampaignUpdate

CampaignStatus = Literal["DRAFT", "RUNNING", "PAUSED", "COMPLETED", "FAILED"]


class CampaignCreateRequest(CampaignCreate):
    """Request body for creating a campaign."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=255)
    target_count: int
    status: CampaignStatus
    description: str | None = None
    target_market: str | None = Field(default=None, max_length=255)
    industry: str | None = Field(default=None, max_length=255)
    technologies: TechnologyCriteria = Field(default_factory=TechnologyCriteria)
    company_size: CompanySizeCriteria | None = None


class CampaignUpdateRequest(CampaignUpdate):
    """Request body for partially updating a campaign."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=255)
    target_count: int | None = None
    status: CampaignStatus | None = None
    description: str | None = None
    target_market: str | None = Field(default=None, max_length=255)
    industry: str | None = Field(default=None, max_length=255)
    technologies: TechnologyCriteria | None = None
    company_size: CompanySizeCriteria | None = None

    @model_validator(mode="after")
    def reject_null_required_fields(self) -> CampaignUpdateRequest:
        """Prevent PATCH from clearing non-nullable database fields."""
        for field_name in {
            "name",
            "target_count",
            "status",
            "technologies",
        } & self.model_fields_set:
            if getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self


class CampaignResponse(BaseModel):
    """Campaign data returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None
    target_market: str | None
    industry: str | None
    technologies: TechnologyCriteria
    company_size: CompanySizeCriteria | None
    target_count: int
    status: str
    created_at: datetime
    updated_at: datetime


class ResearchWorkflowResponse(BaseModel):
    """Concise result from a completed campaign research workflow."""

    research_run_id: UUID
    status: str
    companies_found: int


class CompanyResponse(BaseModel):
    """Company data returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    website: str | None
    domain: str | None
    industry: str | None
    country: str | None
    state: str | None
    city: str | None
    employee_number: int | None
    created_at: datetime
    updated_at: datetime


class EvidenceResponse(BaseModel):
    """Evidence data returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_id: UUID
    research_run_id: UUID | None
    criterion: str | None
    subject: str | None
    claim: str
    evidence_text: str
    source_url: str
    source_title: str | None
    source_type: str | None
    confidence: Decimal | None
    observed_at: datetime
    created_at: datetime


class RequiredCriterionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    value: str | None
    requirement: CriterionRequirement


class CampaignCriteriaResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    target_market: RequiredCriterionResponse
    industry: RequiredCriterionResponse
    technologies: TechnologyCriteria
    company_size: CompanySizeCriteria | None


class ResearchResultCampaignResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None
    target_count: int
    criteria: CampaignCriteriaResponse


class ResearchRunResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    campaign_id: UUID
    status: str
    started_at: datetime
    completed_at: datetime | None
    error: str | None
    companies_found: int
    created_at: datetime


class QualificationCountsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    matched: int
    mismatched: int
    unknown: int


class CompanyCriterionSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    required: QualificationCountsResponse
    preferred: QualificationCountsResponse


class ResearchSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    researched: int
    qualified: int
    not_qualified: int
    insufficient_evidence: int


class CriterionEvidenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    claim: str
    evidence_text: str
    source_url: str
    source_title: str | None
    source_type: str | None


class CriterionResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    criterion: str
    subject: str | None
    requirement: CriterionRequirement
    status: QualificationStatus
    reason: str
    evidence: list[CriterionEvidenceResponse]


class CompanyResearchResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    company_id: UUID
    name: str
    website: str | None
    qualification_status: CompanyQualificationStatus
    review_status: ReviewStatus
    summary: CompanyCriterionSummaryResponse
    criteria: list[CriterionResultResponse]


class ResearchResultsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    research_run: ResearchRunResultResponse
    campaign: ResearchResultCampaignResponse
    summary: ResearchSummaryResponse
    companies: list[CompanyResearchResultResponse]


class ReviewUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ReviewStatus


class ReviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    company_id: UUID
    review_status: ReviewStatus
