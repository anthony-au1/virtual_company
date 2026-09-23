"""Nodes for the campaign research LangGraph workflow."""

from __future__ import annotations

import asyncio
from urllib.parse import urlsplit
from uuid import UUID

from virtual_company.domain.qualification import (
    CompanyQualification,
    QualificationStatus,
)
from virtual_company.llm.base import LLMProvider
from virtual_company.observability import get_observability
from virtual_company.repositories.dtos import EvidenceCreate
from virtual_company.research.models import (
    DiscoveredCompany,
    EvidenceCriterion,
    ExtractedEvidence,
    ExtractedEvidenceItems,
    SearchResult,
    WebPage,
)
from virtual_company.research.normalization import (
    normalize_company_name,
    normalize_domain,
    normalize_fetch_url,
    normalize_url,
)
from virtual_company.services import CampaignService, ResearchService
from virtual_company.services.coverage import assess_evidence_coverage
from virtual_company.services.qualification import (
    aggregate_qualification,
    qualify_company,
)
from virtual_company.tools.web_fetch import WebFetchError, WebFetchTool
from virtual_company.tools.web_search import WebSearchTool
from virtual_company.workflows.research.models import (
    AggregatedCompanyCandidate,
    CampaignCriteria,
    CompanyInvestigationState,
    CompanyPageAttribution,
    CoverageStatus,
    CriterionCoverage,
    DiscoveredCompanies,
    ExtractedCompanyCandidate,
    ExtractedCompanyIdentities,
    GeneratedCompanySearchQueries,
    GeneratedSearchQueries,
    InvestigationStopReason,
    ResearchCompany,
    ValidatedEvidence,
)
from virtual_company.workflows.research.prompts import (
    COMPANY_QUERY_PROMPT,
    EXTRACT_COMPANY_CANDIDATES_PROMPT,
    EXTRACT_COMPANY_EVIDENCE_PROMPT,
    FOLLOWUP_COMPANY_QUERY_PROMPT,
    RANK_COMPANY_CANDIDATES_PROMPT,
    SEARCH_QUERY_PROMPT,
    VALIDATE_COMPANY_PAGE_ATTRIBUTION_PROMPT,
    company_query_system_prompt,
    company_query_user_prompt,
    extract_company_candidates_system_prompt,
    extract_company_candidates_user_prompt,
    extract_company_evidence_system_prompt,
    extract_company_evidence_user_prompt,
    followup_company_query_system_prompt,
    followup_company_query_user_prompt,
    rank_company_candidates_system_prompt,
    rank_company_candidates_user_prompt,
    search_query_system_prompt,
    search_query_user_prompt,
    validate_company_page_attribution_system_prompt,
    validate_company_page_attribution_user_prompt,
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
        web_fetch: WebFetchTool,
        web_search_max_results: int = 10,
        web_search_max_total_results: int = 30,
        web_search_concurrency: int = 3,
        discovery_candidate_multiplier: int = 3,
        discovery_candidate_max: int = 15,
        company_research_query_count: int = 5,
        company_research_max_results_per_query: int = 5,
        company_research_max_results_per_company: int = 15,
        company_research_max_fetches_per_company: int = 5,
        company_research_max_investigation_rounds: int = 2,
        company_research_followup_search_queries_per_company: int = 3,
        company_research_followup_max_fetches_per_company: int = 3,
        web_fetch_concurrency: int = 5,
        evidence_extraction_concurrency: int = 3,
        evidence_max_excerpt_chars: int = 1_000,
    ) -> None:
        self._campaigns = campaigns
        self._research = research
        self._research_llm = research_llm or llm
        self._extraction_llm = extraction_llm or llm
        if self._research_llm is None or self._extraction_llm is None:
            raise ValueError("Research and extraction LLM providers are required")
        self._web_search = web_search
        self._web_fetch = web_fetch
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
        self._company_research_max_fetches_per_company = (
            company_research_max_fetches_per_company
        )
        self._company_research_max_investigation_rounds = (
            company_research_max_investigation_rounds
        )
        self._company_research_followup_search_queries_per_company = (
            company_research_followup_search_queries_per_company
        )
        self._company_research_followup_max_fetches_per_company = (
            company_research_followup_max_fetches_per_company
        )
        self._web_fetch_concurrency = web_fetch_concurrency
        self._evidence_extraction_concurrency = evidence_extraction_concurrency
        self._evidence_max_excerpt_chars = evidence_max_excerpt_chars

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
            "active_company_ids": [company.id for company in research_companies],
            "investigations": {
                company.id: CompanyInvestigationState(company_id=company.id)
                for company in research_companies
            },
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
                company_name=company.name,
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

    async def generate_followup_queries(
        self, state: ResearchWorkflowState
    ) -> dict[str, object, bool]:
        """Generate targeted searches for each active company's missing criteria."""
        campaign = self._campaign(state)
        investigations = dict(state["investigations"])
        queries_by_company: dict[UUID, list[str]] = {}
        observability = get_observability()
        for company in self._active_companies(state):
            investigation = investigations[company.id]
            missing = [
                item
                for item in investigation.coverage
                if item.status is CoverageStatus.MISSING
            ]
            next_round = investigation.round + 1
            with observability.context(
                company_id=str(company.id),
                company_name=company.name,
                company_domain=company.domain,
                prompt_name=FOLLOWUP_COMPANY_QUERY_PROMPT.name,
                prompt_version=FOLLOWUP_COMPANY_QUERY_PROMPT.version,
                investigation_round=str(next_round),
            ):
                response = await self._research_llm.generate_structured(
                    system_prompt=followup_company_query_system_prompt(),
                    user_prompt=followup_company_query_user_prompt(
                        campaign, company, missing
                    ),
                    response_model=GeneratedCompanySearchQueries,
                )
                queries = response.queries[
                    : self._company_research_followup_search_queries_per_company
                ]
                queries_by_company[company.id] = queries
                observability.event(
                    "followup_company_queries_generated",
                    investigation_round=next_round,
                    missing_criteria=[
                        f"{item.criterion.value}/{item.subject}"
                        if item.subject
                        else item.criterion.value
                        for item in missing
                    ],
                    query_count=len(queries),
                )
                observability.record(
                    "followup_queries_generated_total",
                    len(queries),
                    workflow="company_research",
                )
            investigations[company.id] = investigation.model_copy(
                update={
                    "round": next_round,
                    "missing_before": len(missing),
                    "new_evidence_count": 0,
                }
            )
        return {
            "company_research_queries": queries_by_company,
            "investigations": investigations,
            "adaptive_mode": True,
        }

    async def search_company_sources(
        self, state: ResearchWorkflowState
    ) -> dict[str, dict[UUID, list[SearchResult]]]:
        """Search all company queries with one bounded provider-request fan-out."""
        observability = get_observability()
        semaphore = asyncio.Semaphore(self._web_search_concurrency)
        company_queries = state["company_research_queries"]
        active_companies = self._active_companies(state)
        work = [
            (company, query)
            for company in active_companies
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
            company.id: [] for company in active_companies
        }
        seen_urls_by_company: dict[UUID, set[str]] = {
            company.id: set(
                state.get("investigations", {})
                .get(company.id, CompanyInvestigationState(company_id=company.id))
                .attempted_urls
            )
            for company in active_companies
        }
        for (company, _query), result_group in zip(work, result_groups, strict=True):
            results = results_by_company[company.id]
            seen_urls = seen_urls_by_company[company.id]
            for result in result_group:
                if len(results) >= self._company_research_max_results_per_company:
                    break
                try:
                    normalized_url = normalize_fetch_url(result.url)
                except ValueError:
                    continue
                if normalized_url not in seen_urls:
                    seen_urls.add(normalized_url)
                    results.append(result)
        for company in active_companies:
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

    async def select_company_sources(
        self, state: ResearchWorkflowState
    ) -> dict[str, dict[UUID, list[SearchResult]]]:
        """Deterministically select a small, useful source set per company."""
        selected: dict[UUID, list[SearchResult]] = {}
        observability = get_observability()
        investigations = dict(state.get("investigations", {}))
        active_companies = self._active_companies(state)
        adaptive_mode = state.get("adaptive_mode", False)
        fetch_limit = (
            self._company_research_followup_max_fetches_per_company
            if adaptive_mode
            else self._company_research_max_fetches_per_company
        )
        for company in active_companies:
            seen_urls: set[str] = set(
                investigations.get(
                    company.id, CompanyInvestigationState(company_id=company.id)
                ).attempted_urls
            )
            unique_results: list[tuple[int, SearchResult]] = []
            for index, result in enumerate(
                state["company_search_results"].get(company.id, [])
            ):
                try:
                    key = normalize_fetch_url(result.url)
                except ValueError:
                    continue
                if key in seen_urls:
                    continue
                seen_urls.add(key)
                unique_results.append((index, result))
            ordered = sorted(
                unique_results,
                key=lambda item: (
                    -self._source_selection_score(
                        item[1],
                        company,
                        investigations.get(
                            company.id,
                            CompanyInvestigationState(company_id=company.id),
                        ).coverage
                        if adaptive_mode
                        else [],
                    ),
                    item[0],
                ),
            )
            sources = [result for _, result in ordered[:fetch_limit]]
            selected[company.id] = sources
            investigation = investigations.get(
                company.id, CompanyInvestigationState(company_id=company.id)
            )
            attempted = set(investigation.attempted_urls)
            attempted.update(normalize_fetch_url(source.url) for source in sources)
            investigations[company.id] = investigation.model_copy(
                update={"attempted_urls": attempted}
            )
            with observability.context(
                company_id=str(company.id), company_domain=company.domain
            ):
                observability.event(
                    "company_sources_selected",
                    available_source_count=len(unique_results),
                    selected_source_count=len(sources),
                )
                observability.record(
                    "company_research_sources_selected_total",
                    len(sources),
                    workflow="company_research",
                )
        context = {
            "company_count": len(active_companies),
            "selected_source_count": sum(len(sources) for sources in selected.values()),
            "max_fetches_per_company": fetch_limit,
        }
        with observability.span("select_company_sources", **context):
            observability.event("company_sources_selection_completed", **context)
        return {
            "selected_company_sources": selected,
            "investigations": investigations,
        }

    async def fetch_company_sources(
        self, state: ResearchWorkflowState
    ) -> dict[str, dict[UUID, list[WebPage]]]:
        """Fetch selected sources with a bounded worker pool and partial failures."""
        observability = get_observability()
        work = [
            (company.id, index, result)
            for company in self._active_companies(state)
            for index, result in enumerate(
                state["selected_company_sources"].get(company.id, [])
            )
        ]
        successes: dict[tuple[UUID, int], WebPage] = {}
        queue: asyncio.Queue[tuple[UUID, int, SearchResult]] = asyncio.Queue()
        for item in work:
            queue.put_nowait(item)

        async def worker() -> None:
            while True:
                try:
                    company_id, index, source = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                try:
                    with observability.context(
                        company_id=str(company_id), source_url=source.url
                    ):
                        page = await self._web_fetch.fetch(source.url)
                    successes[(company_id, index)] = page.model_copy(
                        update={"title": page.title or source.title}
                    )
                except WebFetchError as error:
                    observability.event(
                        "company_source_fetch_failed",
                        company_id=str(company_id),
                        url=source.url,
                        failure_category=error.category,
                        http_status=getattr(error, "status_code", None),
                    )
                finally:
                    queue.task_done()

        workers = [
            asyncio.create_task(worker())
            for _ in range(min(self._web_fetch_concurrency, len(work)))
        ]
        if workers:
            await asyncio.gather(*workers)
        pages_by_company = {
            company.id: [
                successes[(company.id, index)]
                for index, _ in enumerate(
                    state["selected_company_sources"].get(company.id, [])
                )
                if (company.id, index) in successes
            ]
            for company in self._active_companies(state)
        }
        context = {
            "selected_source_count": len(work),
            "web_page_count": sum(len(pages) for pages in pages_by_company.values()),
            "failed_source_count": len(work) - len(successes),
        }
        with observability.span("fetch_company_sources", **context):
            observability.event("company_sources_fetch_completed", **context)
        return {"company_web_pages": pages_by_company}

    async def extract_company_evidence(
        self, state: ResearchWorkflowState
    ) -> dict[str, list[ValidatedEvidence]]:
        """Extract and validate page-specific campaign evidence without failing on one page."""
        campaign = self._campaign(state)
        research_run_id = state["research_run_id"]
        if research_run_id is None:
            raise ValueError("Research run was not created")
        observability = get_observability()
        semaphore = asyncio.Semaphore(self._evidence_extraction_concurrency)
        pages_by_company = state.get(
            "attributable_company_web_pages", state["company_web_pages"]
        )
        work = [
            (company, page)
            for company in self._active_companies(state)
            for page in pages_by_company.get(company.id, [])
        ]

        async def extract_page(
            company: ResearchCompany, page: WebPage
        ) -> tuple[ResearchCompany, WebPage, list[ExtractedEvidence], bool]:
            with observability.context(
                company_id=str(company.id),
                company_domain=company.domain,
                source_url=page.url,
                prompt_name=EXTRACT_COMPANY_EVIDENCE_PROMPT.name,
                prompt_version=EXTRACT_COMPANY_EVIDENCE_PROMPT.version,
            ):
                try:
                    async with semaphore:
                        response = await self._extraction_llm.generate_structured(
                            system_prompt=extract_company_evidence_system_prompt(),
                            user_prompt=extract_company_evidence_user_prompt(
                                campaign, company, page
                            ),
                            response_model=ExtractedEvidenceItems,
                        )
                    evidence = response.evidence
                except Exception as error:  # noqa: BLE001 - one page must not abort the run
                    observability.event(
                        "company_evidence_extraction_failed",
                        error_type=type(error).__name__,
                    )
                    observability.record(
                        "evidence_extraction_failures_total",
                        workflow="company_research",
                    )
                    return company, page, [], False
            return company, page, evidence, True

        groups = await asyncio.gather(
            *(extract_page(company, page) for company, page in work)
        )
        validated: list[ValidatedEvidence] = []
        extracted_count = 0
        rejected_count = 0
        pages_with_evidence = 0
        successful_pages = 0
        for company, page, extracted, succeeded in groups:
            if not succeeded:
                continue
            successful_pages += 1
            extracted_count += len(extracted)
            page_validated = [
                candidate
                for item in extracted
                if (
                    candidate := self._validated_evidence(
                        campaign, company, research_run_id, page, item
                    )
                )
                is not None
            ]
            rejected_count += len(extracted) - len(page_validated)
            with (
                observability.context(
                    company_id=str(company.id),
                    company_domain=company.domain,
                    source_url=page.url,
                ),
                observability.span(
                    "validate_company_evidence",
                    extracted_item_count=len(extracted),
                    validated_item_count=len(page_validated),
                    rejected_item_count=len(extracted) - len(page_validated),
                ),
            ):
                observability.event(
                    "company_page_evidence_validated",
                    extracted_item_count=len(extracted),
                    validated_item_count=len(page_validated),
                    rejected_item_count=len(extracted) - len(page_validated),
                )
            if page_validated:
                pages_with_evidence += 1
            validated.extend(page_validated)
        deduplicated = self._deduplicate_evidence(validated)
        rejected_count += len(validated) - len(deduplicated)
        context = {
            "web_pages_considered": len(work),
            "evidence_items_extracted": extracted_count,
            "evidence_items_validated": len(deduplicated),
            "evidence_items_rejected": rejected_count,
            "pages_with_evidence": pages_with_evidence,
            "pages_without_evidence": successful_pages - pages_with_evidence,
        }
        with observability.span("extract_company_evidence", **context):
            observability.event("company_evidence_extraction_completed", **context)
        for name, value in context.items():
            observability.record(f"{name}_total", value, workflow="company_research")
        observability.record(
            "evidence_extraction_calls_total", len(work), workflow="company_research"
        )
        for company in self._active_companies(state):
            company_evidence = [
                item for item in deduplicated if item.company_id == company.id
            ]
            fetched_pages = pages_by_company.get(company.id, [])
            selected_count = len(
                state.get("selected_company_sources", {}).get(company.id, [])
            )
            with observability.context(
                company_id=str(company.id), company_domain=company.domain
            ):
                observability.event(
                    "company_evidence_funnel",
                    selected_source_count=selected_count,
                    fetch_success_count=len(fetched_pages),
                    fetch_failure_count=selected_count - len(fetched_pages),
                    pages_with_evidence_count=len(
                        {item.source_url for item in company_evidence}
                    ),
                    validated_evidence_count=len(company_evidence),
                )
        return {"validated_evidence": deduplicated}

    async def validate_company_page_attribution(
        self, state: ResearchWorkflowState
    ) -> dict[str, dict[UUID, list[WebPage]]]:
        """Reject fetched pages that cannot be tied to their intended company."""
        observability = get_observability()
        semaphore = asyncio.Semaphore(self._evidence_extraction_concurrency)
        work = [
            (company, page)
            for company in self._active_companies(state)
            for page in state["company_web_pages"].get(company.id, [])
        ]

        async def validate(
            company: ResearchCompany, page: WebPage
        ) -> tuple[UUID, WebPage, bool]:
            with observability.context(
                company_id=str(company.id),
                source_url=page.url,
                prompt_name=VALIDATE_COMPANY_PAGE_ATTRIBUTION_PROMPT.name,
                prompt_version=VALIDATE_COMPANY_PAGE_ATTRIBUTION_PROMPT.version,
            ):
                try:
                    async with semaphore:
                        result = await self._extraction_llm.generate_structured(
                            system_prompt=validate_company_page_attribution_system_prompt(),
                            user_prompt=validate_company_page_attribution_user_prompt(
                                company, page
                            ),
                            response_model=CompanyPageAttribution,
                        )
                except Exception as error:  # noqa: BLE001 - reject one uncertain page
                    observability.event(
                        "company_page_attribution_failed",
                        error_type=type(error).__name__,
                    )
                    return company.id, page, False
                observability.event(
                    "company_page_attribution_validated",
                    attributable=result.attributable,
                    reason=result.reason,
                )
                return company.id, page, result.attributable

        results = await asyncio.gather(
            *(validate(company, page) for company, page in work)
        )
        attributable = {company.id: [] for company in self._active_companies(state)}
        for company_id, page, accepted in results:
            if accepted:
                attributable[company_id].append(page)
        accepted_count = sum(len(pages) for pages in attributable.values())
        observability.event(
            "company_page_attribution_completed",
            pages_considered=len(work),
            attributable_pages=accepted_count,
            rejected_pages=len(work) - accepted_count,
        )
        observability.record(
            "attributable_pages_total", accepted_count, workflow="company_research"
        )
        return {"attributable_company_web_pages": attributable}

    async def persist_evidence(self, state: ResearchWorkflowState) -> dict[str, object]:
        """Persist validated evidence with run-scoped duplicate protection."""
        research_run_id = state["research_run_id"]
        if research_run_id is None:
            raise ValueError("Research run was not created")
        evidence = [
            EvidenceCreate(
                company_id=item.company_id,
                research_run_id=item.research_run_id,
                criterion=item.criterion,
                subject=item.subject,
                claim=item.claim,
                evidence_text=item.evidence_text,
                source_url=item.source_url,
                source_title=item.source_title,
            )
            for item in state["validated_evidence"]
        ]
        outcome = await self._research.persist_evidence(
            research_run_id=research_run_id, evidence=evidence
        )
        context = {
            "evidence_items_persisted": outcome.created_count,
            "evidence_items_skipped": outcome.skipped_count,
        }
        observability = get_observability()
        with observability.span("persist_evidence", **context):
            observability.event("company_evidence_persisted", **context)
        observability.record(
            "evidence_items_persisted_total",
            outcome.created_count,
            workflow="company_research",
        )
        investigations = dict(state.get("investigations", {}))
        created_by_company = getattr(outcome, "created_by_company", None)
        if created_by_company is None:
            created_by_company = {}
            for item in evidence[: outcome.created_count]:
                created_by_company[item.company_id] = (
                    created_by_company.get(item.company_id, 0) + 1
                )
        for company_id, count in created_by_company.items():
            investigation = investigations.get(
                company_id, CompanyInvestigationState(company_id=company_id)
            )
            investigations[company_id] = investigation.model_copy(
                update={"new_evidence_count": count}
            )
        return {"investigations": investigations}

    async def check_evidence_coverage(
        self, state: ResearchWorkflowState
    ) -> dict[str, object]:
        """Recompute coverage and deterministic stop decisions for every company."""
        campaign = self._campaign(state)
        research_run_id = state["research_run_id"]
        if research_run_id is None:
            raise ValueError("Research run was not created")
        evidence = await self._research.list_evidence_for_run(research_run_id)
        investigations = dict(state["investigations"])
        active_company_ids: list[UUID] = []
        observability = get_observability()
        for company in state["research_companies"]:
            previous = investigations[company.id]
            if previous.stopped:
                continue
            coverage = assess_evidence_coverage(
                campaign,
                evidence,
                company_id=company.id,
                research_run_id=research_run_id,
            )
            missing = sum(item.status is CoverageStatus.MISSING for item in coverage)
            stop_reason: InvestigationStopReason | None = None
            if missing == 0:
                stop_reason = InvestigationStopReason.COVERAGE_COMPLETE
            elif (
                previous.round > 0
                and previous.missing_before == missing
                and previous.new_evidence_count == 0
            ):
                stop_reason = InvestigationStopReason.NO_PROGRESS
            elif previous.round >= self._company_research_max_investigation_rounds:
                stop_reason = InvestigationStopReason.MAX_ROUNDS
            investigation = previous.model_copy(
                update={
                    "coverage": coverage,
                    "stopped": stop_reason is not None,
                    "stop_reason": stop_reason,
                }
            )
            investigations[company.id] = investigation
            if stop_reason is None:
                active_company_ids.append(company.id)
            found_items = [
                item for item in coverage if item.status is CoverageStatus.FOUND
            ]
            missing_items = [
                item for item in coverage if item.status is CoverageStatus.MISSING
            ]
            with observability.context(
                company_id=str(company.id), company_name=company.name
            ):
                observability.event(
                    "company_evidence_coverage_checked",
                    investigation_round=previous.round,
                    coverage_total=len(coverage),
                    coverage_found=len(found_items),
                    coverage_missing=len(missing_items),
                    found=[item.model_dump(mode="json") for item in found_items],
                    missing=[item.model_dump(mode="json") for item in missing_items],
                    new_evidence_items=previous.new_evidence_count,
                    stop_reason=stop_reason.value if stop_reason else None,
                )
            observability.record(
                "coverage_criteria_total", len(coverage), workflow="company_research"
            )
            observability.record(
                "coverage_found_total", len(found_items), workflow="company_research"
            )
            observability.record(
                "coverage_missing_total",
                len(missing_items),
                workflow="company_research",
            )
        return {
            "investigations": investigations,
            "active_company_ids": active_company_ids,
        }

    @staticmethod
    def _source_selection_score(
        result: SearchResult,
        company: ResearchCompany,
        coverage: list[CriterionCoverage] | None = None,
    ) -> int:
        """Rank clear first-party and research-relevant result signals conservatively."""
        try:
            parsed = urlsplit(result.url)
            host = normalize_domain(parsed.hostname)
        except ValueError:
            return -100
        path = parsed.path.casefold()
        text = " ".join(
            value for value in (result.title, result.snippet or "") if value
        ).casefold()
        score = 0
        if company.domain and host == normalize_domain(company.domain):
            score += 30
        if any(token in path or token in text for token in ("career", "job")):
            score += 25
        elif "engineering" in path or "engineering" in text:
            score += 15
        if any(
            token in path or token in text
            for token in ("blog", "technology", "product")
        ):
            score += 8
        missing = [
            item for item in (coverage or []) if item.status is CoverageStatus.MISSING
        ]
        for item in missing:
            subject_match = bool(item.subject and item.subject.casefold() in text)
            size_match = item.criterion is EvidenceCriterion.COMPANY_SIZE and any(
                token in text or token in path
                for token in ("employee", "people", "team", "about", "company-size")
            )
            if subject_match or size_match:
                score += 12
        if result.snippet:
            score += 3
        if path in {"", "/"} and not result.snippet:
            score -= 30
        if host in {
            "google.com",
            "linkedin.com",
            "facebook.com",
            "instagram.com",
            "x.com",
            "twitter.com",
        }:
            score -= 25
        return score

    async def qualify_companies(
        self, state: ResearchWorkflowState
    ) -> dict[str, object]:
        """Qualify final persisted evidence only after every investigation stops."""
        if state["active_company_ids"] or any(
            not state["investigations"][company.id].stopped
            for company in state["research_companies"]
        ):
            raise ValueError("Qualification requires all investigations to be terminal")
        campaign = self._campaign(state)
        results: dict[UUID, CompanyQualification] = {}
        observability = get_observability()
        for company in state["research_companies"]:
            evidence = await self._research.list_evidence_for_company(company.id)
            result = aggregate_qualification(
                company.id, qualify_company(campaign, evidence)
            )
            metadata = {
                "company_id": str(company.id),
                "company_name": company.name,
                "qualification_status": result.status.value,
                "criteria_total": len(result.criteria),
                "criteria_match": sum(
                    item.status is QualificationStatus.MATCH for item in result.criteria
                ),
                "criteria_mismatch": sum(
                    item.status is QualificationStatus.MISMATCH
                    for item in result.criteria
                ),
                "criteria_unknown": sum(
                    item.status is QualificationStatus.UNKNOWN
                    for item in result.criteria
                ),
            }
            with observability.span("company_qualification", **metadata):
                observability.event("company_qualified", **metadata)
            results[company.id] = result
        return {"company_qualifications": results}

    async def persist_company_qualifications(
        self, state: ResearchWorkflowState
    ) -> dict[str, object]:
        """Persist already calculated final results before committing the run."""
        run_id = state["research_run_id"]
        if run_id is None:
            raise ValueError("Research run was not created")
        company_ids = {company.id for company in state["research_companies"]}
        if state["active_company_ids"] or any(
            company_id not in state["investigations"]
            or not state["investigations"][company_id].stopped
            for company_id in company_ids
        ):
            raise ValueError(
                "Qualification persistence requires terminal investigations"
            )
        results = state["company_qualifications"]
        if set(results) != company_ids or any(
            result.company_id != company_id for company_id, result in results.items()
        ):
            raise ValueError(
                "Every researched company must have one final qualification"
            )
        await self._research.persist_company_qualifications(
            campaign_id=state["campaign_id"],
            research_run_id=run_id,
            qualifications=list(results.values()),
        )
        return {}

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

    @staticmethod
    def _active_companies(state: ResearchWorkflowState) -> list[ResearchCompany]:
        active_ids = set(
            state.get(
                "active_company_ids",
                [company.id for company in state["research_companies"]],
            )
        )
        return [
            company
            for company in state["research_companies"]
            if company.id in active_ids
        ]

    def _discovery_candidate_limit(self, target_count: int) -> int:
        """Return the bounded investigation pool size for a campaign."""
        return max(
            target_count,
            min(
                target_count * self._discovery_candidate_multiplier,
                self._discovery_candidate_max,
            ),
        )

    def _validated_evidence(
        self,
        campaign: CampaignCriteria,
        company: ResearchCompany,
        research_run_id: UUID,
        page: WebPage,
        item: ExtractedEvidence,
    ) -> ValidatedEvidence | None:
        """Accept only short excerpts that literally occur in their supplied page."""
        excerpt = self._normalize_whitespace(item.evidence_text)
        if not excerpt or len(excerpt) > self._evidence_max_excerpt_chars:
            return None
        if excerpt not in self._normalize_whitespace(page.content):
            return None
        subject = self._subject_for_criterion(campaign, item)
        if subject is None and item.criterion is not EvidenceCriterion.COMPANY_SIZE:
            return None
        return ValidatedEvidence(
            company_id=company.id,
            research_run_id=research_run_id,
            criterion=item.criterion,
            subject=subject,
            claim=item.claim,
            evidence_text=excerpt,
            source_url=page.url,
            source_title=(page.title[:500] if page.title else None),
        )

    @staticmethod
    def _normalize_whitespace(value: str) -> str:
        return " ".join(value.split())

    def _subject_for_criterion(
        self, campaign: CampaignCriteria, item: ExtractedEvidence
    ) -> str | None:
        if item.criterion is EvidenceCriterion.TARGET_MARKET:
            return campaign.target_market
        if item.criterion is EvidenceCriterion.INDUSTRY:
            return campaign.industry
        if item.criterion is EvidenceCriterion.COMPANY_SIZE:
            return item.subject
        technologies = self._campaign_technologies(campaign)
        subject_key = self._compact(item.subject or "")
        for technology in technologies:
            if self._compact(technology) == subject_key:
                return technology
        return None

    @staticmethod
    def _campaign_technologies(campaign: CampaignCriteria) -> list[str]:
        if isinstance(campaign.technologies, list):
            return [str(item) for item in campaign.technologies if str(item).strip()]
        if isinstance(campaign.technologies, dict):
            return [
                str(item)
                for item in campaign.technologies.values()
                if str(item).strip()
            ]
        return []

    @staticmethod
    def _compact(value: str) -> str:
        return "".join(
            character for character in value.casefold() if character.isalnum()
        )

    @classmethod
    def _deduplicate_evidence(
        cls, evidence: list[ValidatedEvidence]
    ) -> list[ValidatedEvidence]:
        seen: set[tuple[str, ...]] = set()
        deduplicated: list[ValidatedEvidence] = []
        for item in evidence:
            key = (
                str(item.company_id),
                cls._normalize_whitespace(item.source_url).casefold(),
                item.criterion.value,
                cls._normalize_whitespace(item.subject or "").casefold(),
                cls._normalize_whitespace(item.claim).casefold(),
                cls._normalize_whitespace(item.evidence_text).casefold(),
            )
            if key not in seen:
                seen.add(key)
                deduplicated.append(item)
        return deduplicated

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
