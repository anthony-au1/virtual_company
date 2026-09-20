"""Pydantic models exposed by the HTTP API."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from virtual_company.repositories.dtos import CampaignCreate, CampaignUpdate

CampaignStatus = Literal["DRAFT", "RUNNING", "PAUSED", "COMPLETED", "FAILED"]


class CampaignCreateRequest(CampaignCreate):
    """Request body for creating a campaign."""

    name: str = Field(max_length=255)
    target_count: int
    status: CampaignStatus
    description: str | None = None
    target_market: str | None = Field(default=None, max_length=255)
    industry: str | None = Field(default=None, max_length=255)
    technologies: dict[str, Any] | list[Any] | None = None
    company_size_min: int | None = None
    company_size_max: int | None = None


class CampaignUpdateRequest(CampaignUpdate):
    """Request body for partially updating a campaign."""

    name: str | None = Field(default=None, max_length=255)
    target_count: int | None = None
    status: CampaignStatus | None = None
    description: str | None = None
    target_market: str | None = Field(default=None, max_length=255)
    industry: str | None = Field(default=None, max_length=255)
    technologies: dict[str, Any] | list[Any] | None = None
    company_size_min: int | None = None
    company_size_max: int | None = None

    @model_validator(mode="after")
    def reject_null_required_fields(self) -> CampaignUpdateRequest:
        """Prevent PATCH from clearing non-nullable database fields."""
        for field_name in {"name", "target_count", "status"} & self.model_fields_set:
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
    technologies: dict[str, Any] | list[Any] | None
    company_size_min: int | None
    company_size_max: int | None
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
