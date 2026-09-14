"""Nodes for the campaign research LangGraph workflow."""

from __future__ import annotations

import asyncio

from virtual_company.llm.base import LLMProvider
from virtual_company.observability import get_observability
from virtual_company.research.models import DiscoveredCompany, SearchResult
from virtual_company.research.normalization import normalize_domain, normalize_url
from virtual_company.services import CampaignService, ResearchService
from virtual_company.tools.web_search import WebSearchTool
from virtual_company.workflows.research.models import (
    CampaignCriteria,
    DiscoveredCompanies,
    GeneratedSearchQueries,
)
from virtual_company.workflows.research.prompts import (
    COMPANY_DISCOVERY_PROMPT,
    SEARCH_QUERY_PROMPT,
    company_discovery_system_prompt,
    company_discovery_user_prompt,
    search_query_system_prompt,
    search_query_user_prompt,
)
from virtual_company.workflows.research.state import ResearchWorkflowState


class CampaignNotFoundError(LookupError):
    """Raised when a requested campaign does not exist."""


class ResearchNodes:
    """Dependencies and node implementations for one research workflow."""

    def __init__(
        self,
        *,
        campaigns: CampaignService,
        research: ResearchService,
        llm: LLMProvider,
        web_search: WebSearchTool,
        web_search_max_results: int = 10,
        web_search_max_total_results: int = 30,
        web_search_concurrency: int = 3,
    ) -> None:
        self._campaigns = campaigns
        self._research = research
        self._llm = llm
        self._web_search = web_search
        self._web_search_max_results = web_search_max_results
        self._web_search_max_total_results = web_search_max_total_results
        self._web_search_concurrency = web_search_concurrency

    async def load_campaign(
        self, state: ResearchWorkflowState
    ) -> dict[str, CampaignCriteria]:
        """Load the campaign into a compact workflow DTO."""
        campaign = await self._campaigns.get_by_id(state["campaign_id"])
        if campaign is None:
            raise CampaignNotFoundError("Campaign not found")
        return {"campaign": CampaignCriteria.model_validate(campaign)}

    async def create_research_run(
        self, state: ResearchWorkflowState
    ) -> dict[str, object]:
        """Create a committed RUNNING research run."""
        run = await self._research.create_run(state["campaign_id"])
        return {"research_run_id": run.id}

    async def generate_search_queries(
        self, state: ResearchWorkflowState
    ) -> dict[str, list[str]]:
        """Generate bounded search queries from campaign criteria."""
        campaign = self._campaign(state)
        get_observability().bind(
            prompt_name=SEARCH_QUERY_PROMPT.name,
            prompt_version=SEARCH_QUERY_PROMPT.version,
        )
        response = await self._llm.generate_structured(
            system_prompt=search_query_system_prompt(),
            user_prompt=search_query_user_prompt(campaign),
            response_model=GeneratedSearchQueries,
        )
        get_observability().event("search_queries_generated", query_count=len(response.queries))
        return {"queries": response.queries}

    async def search_web(
        self, state: ResearchWorkflowState
    ) -> dict[str, list[SearchResult]]:
        """Search queries with bounded concurrency, then deduplicate by URL."""
        semaphore = asyncio.Semaphore(self._web_search_concurrency)

        async def search_query(query: str) -> list[SearchResult]:
            async with semaphore:
                return await self._web_search.search(query, limit=self._web_search_max_results)

        result_groups = await asyncio.gather(*(search_query(query) for query in state["queries"]))
        seen_urls: set[str] = set()
        results: list[SearchResult] = []
        for result_group in result_groups:
            for result in result_group:
                normalized_url = normalize_url(result.url)
                if normalized_url not in seen_urls:
                    seen_urls.add(normalized_url)
                    results.append(result)
                    if len(results) == self._web_search_max_total_results:
                        return {"search_results": results}
        return {"search_results": results}

    async def discover_companies(
        self, state: ResearchWorkflowState
    ) -> dict[str, list[DiscoveredCompany]]:
        """Extract bounded, evidence-supported companies without persisting them."""
        campaign = self._campaign(state)
        get_observability().bind(
            prompt_name=COMPANY_DISCOVERY_PROMPT.name,
            prompt_version=COMPANY_DISCOVERY_PROMPT.version,
        )
        response = await self._llm.generate_structured(
            system_prompt=company_discovery_system_prompt(),
            user_prompt=company_discovery_user_prompt(campaign, state["search_results"]),
            response_model=DiscoveredCompanies,
        )
        companies = self._deduplicate_companies(response.companies)
        get_observability().record("companies_discovered_total", len(companies), workflow="company_research")
        get_observability().event("companies_discovered", company_count=len(companies))
        return {"discovered_companies": companies[: campaign.target_count]}

    async def persist_companies(self, state: ResearchWorkflowState) -> dict[str, int]:
        """Persist discovered companies and their campaign associations."""
        companies_found = await self._research.persist_companies(
            campaign_id=state["campaign_id"],
            companies=state["discovered_companies"],
        )
        get_observability().event("companies_persisted", companies_found=companies_found)
        return {"companies_found": companies_found}

    async def complete_research_run(self, state: ResearchWorkflowState) -> dict[str, str]:
        """Mark the run complete and commit all pending workflow persistence."""
        research_run_id = state["research_run_id"]
        if research_run_id is None:
            raise ValueError("Research run was not created")
        await self._research.complete_run(research_run_id, state["companies_found"])
        return {"error": None}

    @staticmethod
    def _campaign(state: ResearchWorkflowState) -> CampaignCriteria:
        campaign = state["campaign"]
        if campaign is None:
            raise ValueError("Campaign was not loaded")
        return campaign

    @staticmethod
    def _deduplicate_companies(
        companies: list[DiscoveredCompany],
    ) -> list[DiscoveredCompany]:
        """Deduplicate by normalized domain, falling back to normalized company name."""
        deduplicated = []
        seen: set[str] = set()
        for company in companies:
            domain = normalize_domain(company.domain or company.website)
            key = f"domain:{domain}" if domain else f"name:{company.name.strip().casefold()}"
            if key not in seen:
                seen.add(key)
                deduplicated.append(company)
        return deduplicated
