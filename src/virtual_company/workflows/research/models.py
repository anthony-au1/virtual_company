"""Workflow-only data models for campaign research."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from virtual_company.research.models import DiscoveredCompany

NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class CampaignCriteria(BaseModel):
    """The campaign fields needed by research prompts and persistence limits."""

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


class GeneratedSearchQueries(BaseModel):
    """Structured LLM output used to search for candidate companies."""

    queries: list[NonEmptyString] = Field(min_length=1, max_length=5)


class DiscoveredCompanies(BaseModel):
    """Structured LLM output of campaign-relevant companies."""

    companies: list[DiscoveredCompany] = Field(default_factory=list)


class ResearchCompany(BaseModel):
    """Persisted company context used for transient company-specific research."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: NonEmptyString
    website: str | None = None
    domain: str | None = None


class GeneratedCompanySearchQueries(BaseModel):
    """Structured LLM output used to locate candidate evidence sources for one company."""

    queries: list[NonEmptyString] = Field(min_length=1, max_length=6)


class ResearchWorkflowResult(BaseModel):
    """Public result returned by a completed workflow execution."""

    research_run_id: UUID
    status: str
    companies_found: int
