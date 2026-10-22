"""Typed inputs accepted by persistence repositories."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

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
    claim: str
    supporting_excerpt: str
    source_url: str
    requested_url: str | None = None
    source_title: str | None = None

    @field_validator("claim", "supporting_excerpt", "source_url")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("requested_url")
    @classmethod
    def strip_requested_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("requested_url must not be blank")
        return value

    @field_validator("source_title")
    @classmethod
    def normalize_source_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @model_validator(mode="after")
    def omit_unredirected_requested_url(self) -> ExplorationEvidenceCreate:
        if self.requested_url == self.source_url:
            self.requested_url = None
        return self


class ExplorationFactCreate(BaseModel):
    exploration_company_id: UUID
    statement: str
    evidence_ids: list[UUID] = Field(min_length=1)

    @field_validator("statement")
    @classmethod
    def strip_statement(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("statement must not be blank")
        return value


class ExplorationHypothesisCreate(BaseModel):
    exploration_company_id: UUID
    statement: str
    fact_ids: list[UUID] = Field(min_length=1)

    @field_validator("statement")
    @classmethod
    def strip_statement(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("statement must not be blank")
        return value
