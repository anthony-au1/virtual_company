"""Pydantic models exposed by the HTTP API."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from virtual_company.domain.criteria import (
    CompanySizeCriteria,
)
from virtual_company.domain.qualification import (
    QualificationStatus,
)
from virtual_company.repositories.dtos import CampaignCreate, CampaignUpdate

CampaignStatus = Literal["DRAFT", "RUNNING", "PAUSED", "COMPLETED", "FAILED"]


class CompanyQualificationStatus(StrEnum):
    """Stable public OpenAPI enum for Research company qualification status."""

    QUALIFIED = "QUALIFIED"
    NOT_QUALIFIED = "NOT_QUALIFIED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class CampaignCreateRequest(CampaignCreate):
    """Request body for creating a campaign."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=255)
    target_count: int
    status: CampaignStatus
    description: str | None = None
    target_market: str | None = Field(default=None, max_length=255)
    industry: str | None = Field(default=None, max_length=255)
    keywords: list[str] = Field(default_factory=list)
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
    keywords: list[str] | None = None
    company_size: CompanySizeCriteria | None = None
    max_companies_to_research: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def reject_null_required_fields(self) -> CampaignUpdateRequest:
        """Prevent PATCH from clearing non-nullable database fields."""
        for field_name in {
            "name",
            "target_count",
            "status",
            "keywords",
        } & self.model_fields_set:
            if getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self


class ExplorationCreateRequest(BaseModel):
    """Client supplied fields for creating an Exploration."""

    model_config = ConfigDict(extra="forbid")

    business_context: str
    max_obligations: int = Field(default=10, ge=1, le=20)


class ExplorationUpdateRequest(BaseModel):
    """Editable Exploration fields accepted by PATCH."""

    model_config = ConfigDict(extra="forbid")

    business_context: str | None = None
    max_obligations: int | None = Field(default=None, ge=1, le=20)

    @model_validator(mode="after")
    def reject_null_required_fields(self) -> ExplorationUpdateRequest:
        if (
            "business_context" in self.model_fields_set
            and self.business_context is None
        ):
            raise ValueError("business_context cannot be null")
        if "max_obligations" in self.model_fields_set and self.max_obligations is None:
            raise ValueError("max_obligations cannot be null")
        return self


class ExplorationResponse(BaseModel):
    """Exploration data returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    business_context: str
    max_obligations: int
    status: str
    created_at: datetime
    updated_at: datetime


class ExplorationObligationResponse(BaseModel):
    """Obligation data returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    exploration_id: UUID
    description: str
    created_at: datetime


class CampaignResponse(BaseModel):
    """Campaign data returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None
    target_market: str | None
    industry: str | None
    keywords: list[str]
    company_size: CompanySizeCriteria | None
    target_count: int
    max_companies_to_research: int
    status: str
    created_at: datetime
    updated_at: datetime
    sealed_at: datetime | None


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


class CampaignCriteriaResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    target_market: str | None
    industry: str | None
    keywords: list[str]
    company_size: CompanySizeCriteria | None


class ResearchResultCampaignResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None
    target_count: int
    max_companies_to_research: int
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
    status: QualificationStatus
    reason: str
    evidence: list[CriterionEvidenceResponse]


class CompanyResearchResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    company_id: UUID
    name: str
    website: str | None
    qualification_status: CompanyQualificationStatus
    summary: QualificationCountsResponse
    criteria: list[CriterionResultResponse]


class ResearchResultsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    research_run: ResearchRunResultResponse
    campaign: ResearchResultCampaignResponse
    summary: ResearchSummaryResponse
    companies: list[CompanyResearchResultResponse]


class ResearchRunListCampaignResponse(BaseModel):
    id: UUID
    name: str
    target_count: int
    max_companies_to_research: int


class ResearchRunListSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    researched: int
    qualified: int
    not_qualified: int
    insufficient_evidence: int


class ResearchRunListItemResponse(BaseModel):
    run_id: UUID
    status: str
    created_at: datetime
    started_at: datetime
    completed_at: datetime | None
    campaign: ResearchRunListCampaignResponse
    summary: ResearchRunListSummaryResponse
