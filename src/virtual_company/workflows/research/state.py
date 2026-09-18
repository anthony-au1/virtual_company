"""Temporary LangGraph state for campaign research."""

from __future__ import annotations

from typing import TypedDict
from uuid import UUID

from virtual_company.research.models import DiscoveredCompany, SearchResult
from virtual_company.workflows.research.models import (
    AggregatedCompanyCandidate,
    CampaignCriteria,
    ExtractedCompanyCandidate,
    ResearchCompany,
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
    error: str | None
