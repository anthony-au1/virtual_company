"""Nodes for the campaign research LangGraph workflow."""

from __future__ import annotations

import asyncio
from uuid import UUID

from virtual_company.llm.base import LLMProvider
from virtual_company.observability import get_observability
from virtual_company.research.models import DiscoveredCompany, SearchResult
from virtual_company.research.normalization import (
    normalize_company_name,
    normalize_domain,
    normalize_url,
)
from virtual_company.services import CampaignService, ResearchService
from virtual_company.tools.web_search import WebSearchTool
from virtual_company.workflows.research.models import (
    AggregatedCompanyCandidate,
    CampaignCriteria,
    DiscoveredCompanies,
    ExtractedCompanyCandidate,
    ExtractedCompanyIdentities,
    GeneratedCompanySearchQueries,
    GeneratedSearchQueries,
    ResearchCompany,
)
from virtual_company.workflows.research.prompts import (
    COMPANY_QUERY_PROMPT,
    EXTRACT_COMPANY_CANDIDATES_PROMPT,
    RANK_COMPANY_CANDIDATES_PROMPT,
    SEARCH_QUERY_PROMPT,
    company_query_system_prompt,
    company_query_user_prompt,
    extract_company_candidates_system_prompt,
    extract_company_candidates_user_prompt,
    rank_company_candidates_system_prompt,
    rank_company_candidates_user_prompt,
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
        research_llm: LLMProvider | None = None,
        extraction_llm: LLMProvider | None = None,
        llm: LLMProvider | None = None,
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
        self._research_llm = research_llm or llm
        self._extraction_llm = extraction_llm or llm
        if self._research_llm is None or self._extraction_llm is None:
            raise ValueError("Research and extraction LLM providers are required")
        self._web_search = web_search
        self._web_search_max_results = web_search_max_results
        self._web_search_max_total_results = web_search_max_total_results
        self._web_search_concurrency = web_search_concurrency
        self._discovery_candidate_multiplier = discovery_candidate_multiplier
        self._discovery_candidate_max = discovery_candidate_max
        self._company_research_query_count = company_research_query_count
        self._company_research_max_results_per_query = (
            company_research_max_results_per_query
        )
        self._company_research_max_results_per_company = (
            company_research_max_results_per_company
        )

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
        response = await self._research_llm.generate_structured(
            system_prompt=search_query_system_prompt(),
            user_prompt=search_query_user_prompt(campaign),
            response_model=GeneratedSearchQueries,
        )
        get_observability().event(
            "search_queries_generated", query_count=len(response.queries)
        )
        return {"queries": response.queries}

    async def search_web(
        self, state: ResearchWorkflowState
    ) -> dict[str, list[SearchResult]]:
        """Search queries with bounded concurrency, then deduplicate by URL."""
        semaphore = asyncio.Semaphore(self._web_search_concurrency)

        async def search_query(query: str) -> list[SearchResult]:
            async with semaphore:
                return await self._web_search.search(
                    query, limit=self._web_search_max_results
                )

        result_groups = await asyncio.gather(
            *(search_query(query) for query in state["queries"])
        )
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

    async def extract_company_candidates(
        self, state: ResearchWorkflowState
    ) -> dict[str, list[ExtractedCompanyCandidate]]:
        """Extract all plausible mentions with explicit attention per search result."""
        campaign = self._campaign(state)
        observability = get_observability()
        semaphore = asyncio.Semaphore(self._web_search_concurrency)

        async def extract_from_result(
            result: SearchResult,
        ) -> list[ExtractedCompanyCandidate]:
            async with semaphore:
                with observability.context(
                    prompt_name=EXTRACT_COMPANY_CANDIDATES_PROMPT.name,
                    prompt_version=EXTRACT_COMPANY_CANDIDATES_PROMPT.version,
                ):
                    response = await self._extraction_llm.generate_structured(
                        system_prompt=extract_company_candidates_system_prompt(),
                        user_prompt=extract_company_candidates_user_prompt(
                            campaign, result
                        ),
                        response_model=ExtractedCompanyIdentities,
                    )
            return [
                ExtractedCompanyCandidate(
                    **candidate.model_dump(),
                    source_url=result.url,
                    source_title=result.title,
                    source_snippet=result.snippet,
                )
                for candidate in response.companies
            ]

        groups = await asyncio.gather(
            *(extract_from_result(result) for result in state["search_results"])
        )
        candidates = [candidate for group in groups for candidate in group]
        context = {
            "search_result_count": len(state["search_results"]),
            "extracted_mention_count": len(candidates),
            "extracted_candidate_names": [candidate.name for candidate in candidates],
        }
        with observability.span("extract_company_candidates", **context):
            observability.event("company_candidates_extracted", **context)
        observability.record(
            "company_candidates_extracted_total",
            len(candidates),
            workflow="company_research",
        )
        return {"extracted_company_candidates": candidates}

    async def aggregate_company_candidates(
        self, state: ResearchWorkflowState
    ) -> dict[str, list[AggregatedCompanyCandidate]]:
        """Conservatively merge obvious identities without dropping single mentions."""
        grouped: dict[str, AggregatedCompanyCandidate] = {}
        for mention in state["extracted_company_candidates"]:
            domain = normalize_domain(mention.domain or mention.website)
            key = (
                f"domain:{domain}"
                if domain
                else f"name:{normalize_company_name(mention.name)}"
            )
            result = SearchResult(
                title=mention.source_title or mention.name,
                url=mention.source_url,
                snippet=mention.source_snippet,
            )
            existing = grouped.get(key)
            if existing is None:
                grouped[key] = AggregatedCompanyCandidate(
                    name=mention.name,
                    website=mention.website,
                    domain=domain,
                    mention_count=1,
                    supporting_urls=[mention.source_url],
                    supporting_results=[result],
                )
                continue
            urls = list(existing.supporting_urls)
            results = list(existing.supporting_results)
            if mention.source_url not in urls:
                urls.append(mention.source_url)
                results.append(result)
            grouped[key] = existing.model_copy(
                update={
                    "website": existing.website or mention.website,
                    "domain": existing.domain or domain,
                    "mention_count": existing.mention_count + 1,
                    "supporting_urls": urls,
                    "supporting_results": results,
                }
            )
        candidates = list(grouped.values())
        observability = get_observability()
        context = {
            "extracted_mention_count": len(state["extracted_company_candidates"]),
            "unique_candidate_count": len(candidates),
            "aggregated_candidates": [
                {
                    "name": candidate.name,
                    "mentions": candidate.mention_count,
                    "sources": len(candidate.supporting_urls),
                }
                for candidate in candidates
            ],
        }
        with observability.span("aggregate_company_candidates", **context):
            observability.event("company_candidates_aggregated", **context)
        observability.record(
            "company_candidates_aggregated_total",
            len(candidates),
            workflow="company_research",
        )
        return {"aggregated_company_candidates": candidates}

    async def rank_company_candidates(
        self, state: ResearchWorkflowState
    ) -> dict[str, list[DiscoveredCompany]]:
        """Rank the aggregate pool and limit only downstream investigation."""
        campaign = self._campaign(state)
        candidate_limit = self._discovery_candidate_limit(campaign.target_count)
        ranking_candidates = [
            candidate.model_copy(
                update={"supporting_results": candidate.supporting_results[:3]}
            )
            for candidate in state["aggregated_company_candidates"]
        ]
        observability = get_observability()
        with observability.context(
            prompt_name=RANK_COMPANY_CANDIDATES_PROMPT.name,
            prompt_version=RANK_COMPANY_CANDIDATES_PROMPT.version,
        ):
            response = await self._research_llm.generate_structured(
                system_prompt=rank_company_candidates_system_prompt(),
                user_prompt=rank_company_candidates_user_prompt(
                    campaign, ranking_candidates, candidate_limit
                ),
                response_model=DiscoveredCompanies,
            )
        companies = self._validated_ranked_companies(
            response.companies, state["aggregated_company_candidates"], candidate_limit
        )
        context = {
            "unique_candidate_count": len(ranking_candidates),
            "ranked_candidate_count": len(companies),
            "discovery_candidate_limit": candidate_limit,
            "ranked_candidate_names": [company.name for company in companies],
        }
        with observability.span("rank_company_candidates", **context):
            observability.event("company_candidates_ranked", **context)
        observability.record(
            "companies_discovered_total", len(companies), workflow="company_research"
        )
        return {"discovered_companies": companies}

    async def persist_companies(
        self, state: ResearchWorkflowState
    ) -> dict[str, object]:
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
                response = await self._research_llm.generate_structured(
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
                observability.event(
                    "company_research_sources_found", result_count=count
                )
        return {"company_search_results": results_by_company}

    async def complete_research_run(
        self, state: ResearchWorkflowState
    ) -> dict[str, str]:
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
    def _validated_ranked_companies(
        companies: list[DiscoveredCompany],
        candidates: list[AggregatedCompanyCandidate],
        candidate_limit: int,
    ) -> list[DiscoveredCompany]:
        """Keep ranked selections and provenance constrained to aggregate evidence."""
        by_domain = {
            domain: candidate
            for candidate in candidates
            if (domain := normalize_domain(candidate.domain or candidate.website))
            is not None
        }
        by_name = {
            normalize_company_name(candidate.name): candidate
            for candidate in candidates
        }
        selected: list[DiscoveredCompany] = []
        seen: set[str] = set()
        for company in companies:
            domain = normalize_domain(company.domain or company.website)
            candidate = by_domain.get(domain) if domain else None
            candidate = candidate or by_name.get(normalize_company_name(company.name))
            if candidate is None:
                continue
            key = normalize_domain(
                candidate.domain or candidate.website
            ) or normalize_company_name(candidate.name)
            if key in seen:
                continue
            supporting_urls = [
                url
                for url in company.supporting_urls
                if url in candidate.supporting_urls
            ]
            selected.append(
                DiscoveredCompany(
                    name=candidate.name,
                    website=candidate.website,
                    domain=candidate.domain,
                    discovery_reason=company.discovery_reason,
                    supporting_urls=supporting_urls,
                )
            )
            seen.add(key)
            if len(selected) == candidate_limit:
                break
        return selected
