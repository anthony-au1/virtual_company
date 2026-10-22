"""Typed inputs accepted by persistence repositories."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from virtual_company.domain.research.criteria import CompanySizeCriteria


class CampaignCreate(BaseModel):
    name: str
    target_count: int
    max_companies_to_research: int = Field(default=15, ge=1)
    status: str
    description: str | None = None
    target_market: str | None = None
    industry: str | None = None
    keywords: list[str] = Field(default_factory=list)
    company_size: CompanySizeCriteria | None = None

    @model_validator(mode="before")
    @classmethod
    def default_research_limit(cls, value: object) -> object:
        if isinstance(value, dict) and "max_companies_to_research" not in value:
            value = dict(value)
            value["max_companies_to_research"] = max(
                15, int(value.get("target_count", 1))
            )
        return value

    @model_validator(mode="after")
    def validate_research_limit(self) -> CampaignCreate:
        if self.max_companies_to_research < self.target_count:
            raise ValueError(
                "max_companies_to_research cannot be less than target_count"
            )
        return self


class CampaignUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    target_market: str | None = None
    industry: str | None = None
    keywords: list[str] | None = None
    company_size: CompanySizeCriteria | None = None
    target_count: int | None = None
    max_companies_to_research: int | None = Field(default=None, ge=1)
    status: str | None = None


class ResearchCompanyCreate(BaseModel):
    name: str
    website: str | None = None
    domain: str | None = None
    industry: str | None = None
    country: str | None = None
    state: str | None = None
    city: str | None = None
    employee_number: int | None = None


class ResearchCompanyUpdate(BaseModel):
    name: str | None = None
    website: str | None = None
    domain: str | None = None
    industry: str | None = None
    country: str | None = None
    state: str | None = None
    city: str | None = None
    employee_number: int | None = None


class CampaignTargetCreate(BaseModel):
    campaign_id: UUID
    company_id: UUID
    score: Decimal | None = None
    status: str | None = None


class CampaignTargetUpdate(BaseModel):
    score: Decimal | None = None
    status: str | None = None


class ResearchEvidenceCreate(BaseModel):
    company_id: UUID
    research_run_id: UUID | None = None
    criterion: str | None = None
    subject: str | None = None
    claim: str
    evidence_text: str
    source_url: str
    source_title: str | None = None
    source_type: str | None = None
    confidence: Decimal | None = None
    observed_at: datetime | None = None


class ResearchEvidenceUpdate(BaseModel):
    criterion: str | None = None
    subject: str | None = None
    claim: str | None = None
    evidence_text: str | None = None
    source_url: str | None = None
    source_title: str | None = None
    source_type: str | None = None
    confidence: Decimal | None = None
    observed_at: datetime | None = None


class ResearchRunCreate(BaseModel):
    campaign_id: UUID
    status: str
    companies_found: int
    started_at: datetime | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None


class ResearchRunUpdate(BaseModel):
    status: str | None = None
    completed_at: datetime | None = None
    error: str | None = None
    companies_found: int | None = None


class ResearchCompanyQualificationUpsert(BaseModel):
    research_run_id: UUID
    campaign_id: UUID
    company_id: UUID
    status: str
    criteria_results: dict[str, Any]


class ExplorationCreate(BaseModel):
    business_context: str
    status: str
    max_obligations: int = 10


class ExplorationUpdate(BaseModel):
    business_context: str | None = None
    max_obligations: int | None = None
    status: str | None = None


class ExplorationObligationCreate(BaseModel):
    exploration_id: UUID
    description: str


class ExplorationObligationUpdate(BaseModel):
    description: str | None = None


class ExplorationRunCreate(BaseModel):
    exploration_id: UUID
    research_run_id: UUID
    status: str
    started_at: datetime | None = None
    completed_at: datetime | None = None


class ExplorationRunUpdate(BaseModel):
    status: str | None = None
    completed_at: datetime | None = None


class ExplorationCompanyCreate(BaseModel):
    exploration_run_id: UUID
    company_id: UUID


class ExplorationEvidenceCreate(BaseModel):
    exploration_company_id: UUID
    exploration_obligation_id: UUID
    source_url: str | None = None
    source_type: str | None = None
    content: str | None = None


class ExplorationEvidenceUpdate(BaseModel):
    exploration_obligation_id: UUID | None = None
    source_url: str | None = None
    source_type: str | None = None
    content: str | None = None


class ExplorationFactCreate(BaseModel):
    statement: str
    evidence_ids: list[UUID] = Field(min_length=1)


class ExplorationFactUpdate(BaseModel):
    statement: str | None = None


class ExplorationHypothesisCreate(BaseModel):
    statement: str
    fact_ids: list[UUID] = Field(min_length=1)


class ExplorationHypothesisUpdate(BaseModel):
    statement: str | None = None
