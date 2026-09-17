"""Nodes for the campaign research LangGraph workflow."""

from __future__ import annotations

import asyncio
from uuid import UUID

from virtual_company.llm.base import LLMProvider
from virtual_company.observability import get_observability
from virtual_company.research.models import DiscoveredCompany, SearchResult
from virtual_company.research.normalization import normalize_domain, normalize_url
from virtual_company.services import CampaignService, ResearchService
from virtual_company.tools.web_search import WebSearchTool
from virtual_company.workflows.research.models import (
    CampaignCriteria,
    DiscoveredCompanies,
    GeneratedCompanySearchQueries,
    GeneratedSearchQueries,
    ResearchCompany,
)
from virtual_company.workflows.research.prompts import (
    COMPANY_DISCOVERY_PROMPT,
    COMPANY_QUERY_PROMPT,
    SEARCH_QUERY_PROMPT,
    company_discovery_system_prompt,
    company_discovery_user_prompt,
    company_query_system_prompt,
    company_query_user_prompt,
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
        discovery_candidate_multiplier: int = 3,
        discovery_candidate_max: int = 15,
        company_research_query_count: int = 5,
        company_research_max_results_per_query: int = 5,
        company_research_max_results_per_company: int = 15,
    ) -> None:
        self._campaigns = campaigns
        self._research = research
        self._llm = llm
        self._web_search = web_search
        self._web_search_max_results = web_search_max_results
        self._web_search_max_total_results = web_search_max_total_results
        self._web_search_concurrency = web_search_concurrency
        self._discovery_candidate_multiplier = discovery_candidate_multiplier
        self._discovery_candidate_max = discovery_candidate_max
        self._company_research_query_count = company_research_query_count
        self._company_research_max_results_per_query = company_research_max_results_per_query
        self._company_research_max_results_per_company = company_research_max_results_per_company

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
        """Extract a bounded pool of plausible companies without persisting them."""
        campaign = self._campaign(state)
        candidate_limit = self._discovery_candidate_limit(campaign.target_count)
        get_observability().bind(
            prompt_name=COMPANY_DISCOVERY_PROMPT.name,
            prompt_version=COMPANY_DISCOVERY_PROMPT.version,
        )
        response = await self._llm.generate_structured(
            system_prompt=company_discovery_system_prompt(),
            user_prompt=company_discovery_user_prompt(
                campaign, state["search_results"], candidate_limit
            ),
            response_model=DiscoveredCompanies,
        )
        companies = self._deduplicate_companies(
            self._validate_supporting_urls(response.companies, state["search_results"])
        )[:candidate_limit]
        observability = get_observability()
        supporting_source_count = sum(len(company.supporting_urls) for company in companies)
        selection_context = {
            "campaign_target_count": campaign.target_count,
            "discovery_candidate_limit": candidate_limit,
            "discovered_candidate_count": len(companies),
            "selected_company_names": [company.name for company in companies],
            "supporting_source_count": supporting_source_count,
        }
        with observability.span("discovery_candidate_selection", **selection_context):
            observability.event("companies_discovered", **selection_context)
        get_observability().record("companies_discovered_total", len(companies), workflow="company_research")
        return {"discovered_companies": companies}

    async def persist_companies(self, state: ResearchWorkflowState) -> dict[str, object]:
        """Persist discovered companies and their campaign associations."""
        persisted = await self._research.persist_companies(
            campaign_id=state["campaign_id"],
            companies=state["discovered_companies"],
        )
        research_companies = [
            ResearchCompany.model_validate(company) for company in persisted.companies
        ]
        get_observability().event(
            "companies_persisted", companies_found=persisted.companies_found
        )
        return {
            "companies_found": persisted.companies_found,
            "research_companies": research_companies,
        }

    async def generate_company_queries(
        self, state: ResearchWorkflowState
    ) -> dict[str, dict[UUID, list[str]]]:
        """Generate bounded, evidence-seeking queries for each persisted company."""
        campaign = self._campaign(state)
        observability = get_observability()
        company_queries: dict[UUID, list[str]] = {}
        for company in state["research_companies"]:
            with observability.context(
                company_id=str(company.id),
                company_domain=company.domain,
                prompt_name=COMPANY_QUERY_PROMPT.name,
                prompt_version=COMPANY_QUERY_PROMPT.version,
            ):
                response = await self._llm.generate_structured(
                    system_prompt=company_query_system_prompt(),
                    user_prompt=company_query_user_prompt(campaign, company),
                    response_model=GeneratedCompanySearchQueries,
                )
                queries = response.queries[: self._company_research_query_count]
                company_queries[company.id] = queries
                observability.event(
                    "company_research_queries_generated", query_count=len(queries)
                )
                observability.record(
                    "company_research_queries_generated_total",
                    len(queries),
                    workflow="company_research",
                )
        return {"company_research_queries": company_queries}

    async def search_company_sources(
        self, state: ResearchWorkflowState
    ) -> dict[str, dict[UUID, list[SearchResult]]]:
        """Search all company queries with one bounded provider-request fan-out."""
        observability = get_observability()
        semaphore = asyncio.Semaphore(self._web_search_concurrency)
        company_queries = state["company_research_queries"]
        work = [
            (company, query)
            for company in state["research_companies"]
            for query in company_queries.get(company.id, [])
        ]

        async def search_company_query(
            company: ResearchCompany, query: str
        ) -> list[SearchResult]:
            with observability.context(
                company_id=str(company.id), company_domain=company.domain
            ):
                async with semaphore:
                    return await self._web_search.search(
                        query, limit=self._company_research_max_results_per_query
                    )

        result_groups = await asyncio.gather(
            *(search_company_query(company, query) for company, query in work)
        )
        results_by_company: dict[UUID, list[SearchResult]] = {
            company.id: [] for company in state["research_companies"]
        }
        seen_urls_by_company: dict[UUID, set[str]] = {
            company.id: set() for company in state["research_companies"]
        }
        for (company, _query), result_group in zip(work, result_groups, strict=True):
            results = results_by_company[company.id]
            seen_urls = seen_urls_by_company[company.id]
            for result in result_group:
                if len(results) >= self._company_research_max_results_per_company:
                    break
                normalized_url = normalize_url(result.url)
                if normalized_url not in seen_urls:
                    seen_urls.add(normalized_url)
                    results.append(result)
        for company in state["research_companies"]:
            with observability.context(
                company_id=str(company.id), company_domain=company.domain
            ):
                count = len(results_by_company[company.id])
                observability.record(
                    "company_research_sources_found_total",
                    count,
                    workflow="company_research",
                )
                observability.event("company_research_sources_found", result_count=count)
        return {"company_search_results": results_by_company}

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

    def _discovery_candidate_limit(self, target_count: int) -> int:
        """Return the bounded investigation pool size for a campaign."""
        return max(
            target_count,
            min(
                target_count * self._discovery_candidate_multiplier,
                self._discovery_candidate_max,
            ),
        )

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

    @staticmethod
    def _validate_supporting_urls(
        companies: list[DiscoveredCompany], search_results: list[SearchResult]
    ) -> list[DiscoveredCompany]:
        """Keep only provenance URLs present in the supplied discovery results."""
        source_urls: dict[str, str] = {}
        for result in search_results:
            try:
                source_urls.setdefault(normalize_url(result.url), result.url)
            except ValueError:
                continue

        validated_companies = []
        for company in companies:
            supporting_urls = []
            for url in company.supporting_urls:
                try:
                    source_url = source_urls.get(normalize_url(url))
                except ValueError:
                    source_url = None
                if source_url is not None and source_url not in supporting_urls:
                    supporting_urls.append(source_url)
            validated_companies.append(
                company.model_copy(update={"supporting_urls": supporting_urls})
            )
        return validated_companies
