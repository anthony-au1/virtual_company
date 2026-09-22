"""Temporary LangGraph state for campaign research."""

from __future__ import annotations

from typing import TypedDict
from uuid import UUID

from virtual_company.domain.qualification import CompanyQualification
from virtual_company.research.models import DiscoveredCompany, SearchResult, WebPage
from virtual_company.workflows.research.models import (
    AggregatedCompanyCandidate,
    CampaignCriteria,
    CompanyInvestigationState,
    ExtractedCompanyCandidate,
    ResearchCompany,
    ValidatedEvidence,
)


class ResearchWorkflowState(TypedDict):
    """Values passed between the research workflow's sequential nodes."""

    campaign_id: UUID
    campaign: CampaignCriteria | None
    research_run_id: UUID | None
    queries: list[str]
    search_results: list[SearchResult]
    extracted_company_candidates: list[ExtractedCompanyCandidate]
    aggregated_company_candidates: list[AggregatedCompanyCandidate]
    discovered_companies: list[DiscoveredCompany]
    companies_found: int
    research_companies: list[ResearchCompany]
    company_research_queries: dict[UUID, list[str]]
    company_search_results: dict[UUID, list[SearchResult]]
    selected_company_sources: dict[UUID, list[SearchResult]]
    company_web_pages: dict[UUID, list[WebPage]]
    attributable_company_web_pages: dict[UUID, list[WebPage]]
    validated_evidence: list[ValidatedEvidence]
    investigations: dict[UUID, CompanyInvestigationState]
    active_company_ids: list[UUID]
    adaptive_mode: bool
    company_qualifications: dict[UUID, CompanyQualification]
    error: str | None
