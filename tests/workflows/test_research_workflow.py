"""Tests for the first LangGraph campaign research workflow."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from virtual_company.config import Settings
from virtual_company.db.models import Campaign
from virtual_company.research.models import DiscoveredCompany, SearchResult
from virtual_company.workflows.research.graph import ResearchWorkflow
from virtual_company.workflows.research.models import (
    CampaignCriteria,
    DiscoveredCompanies,
    GeneratedCompanySearchQueries,
    GeneratedSearchQueries,
    ResearchCompany,
)
from virtual_company.workflows.research.nodes import (
    CampaignNotFoundError,
    ResearchNodes,
)
from virtual_company.workflows.research.prompts import (
    COMPANY_DISCOVERY_PROMPT,
    SEARCH_QUERY_PROMPT,
    company_discovery_system_prompt,
    search_query_system_prompt,
)


class CampaignServiceFake:
    """In-memory campaign lookup substitute."""

    def __init__(self, campaign: Campaign | None) -> None:
        self.campaign = campaign

    async def get_by_id(self, _campaign_id: UUID) -> Campaign | None:
        return self.campaign


class ResearchServiceFake:
    """In-memory persistence substitute recording workflow side effects."""

    def __init__(self, existing_domains: set[str] | None = None) -> None:
        self.runs: dict[UUID, SimpleNamespace] = {}
        self.companies_by_domain = {
            domain: uuid4() for domain in (existing_domains or set())
        }
        self.targets: set[tuple[UUID, UUID]] = set()
        self.created_runs = 0

    async def create_run(self, campaign_id: UUID) -> SimpleNamespace:
        run = SimpleNamespace(
            id=uuid4(), campaign_id=campaign_id, status="RUNNING", companies_found=0
        )
        self.runs[run.id] = run
        self.created_runs += 1
        return run

    async def persist_companies(
        self, *, campaign_id: UUID, companies: list[DiscoveredCompany]
    ) -> SimpleNamespace:
        created_targets = 0
        persisted_companies = []
        for company in companies:
            domain = (company.domain or company.website or company.name).lower()
            company_id = self.companies_by_domain.setdefault(domain, uuid4())
            target = (campaign_id, company_id)
            if target not in self.targets:
                self.targets.add(target)
                created_targets += 1
            persisted_companies.append(
                SimpleNamespace(
                    id=company_id,
                    name=company.name,
                    website=company.website,
                    domain=company.domain,
                )
            )
        return SimpleNamespace(companies_found=created_targets, companies=persisted_companies)

    async def complete_run(self, research_run_id: UUID, companies_found: int) -> None:
        run = self.runs[research_run_id]
        run.status = "COMPLETED"
        run.companies_found = companies_found

    async def fail_run(self, research_run_id: UUID, error: str) -> None:
        run = self.runs[research_run_id]
        run.status = "FAILED"
        run.error = error


class LLMFake:
    """Structured-output fake returning query and company responses in order."""

    def __init__(
        self,
        queries: list[str] | None = None,
        company_queries: list[str] | None = None,
        companies: list[DiscoveredCompany] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.queries = queries or ["Australian fintech companies"]
        self.company_queries = company_queries or ["company engineering evidence"]
        self.companies = companies or []
        self.error = error
        self.response_models: list[type[object]] = []
        self.user_prompts: list[str] = []

    async def generate_structured(self, **kwargs: object) -> object:
        self.response_models.append(kwargs["response_model"])
        self.user_prompts.append(kwargs["user_prompt"])
        if self.error is not None:
            raise self.error
        if kwargs["response_model"] is GeneratedSearchQueries:
            return GeneratedSearchQueries(queries=self.queries)
        if kwargs["response_model"] is GeneratedCompanySearchQueries:
            return GeneratedCompanySearchQueries(queries=self.company_queries)
        return DiscoveredCompanies(companies=self.companies)


class WebSearchFake:
    """In-memory web search fake."""

    def __init__(
        self, results: list[SearchResult] | None = None, error: Exception | None = None
    ) -> None:
        self.results = results or []
        self.error = error
        self.queries: list[str] = []
        self.calls: list[tuple[str, int]] = []

    async def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        self.queries.append(query)
        self.calls.append((query, limit))
        if self.error is not None:
            raise self.error
        return self.results


class QueryResultsWebSearchFake:
    """Search fake that makes result ordering and call concurrency observable."""

    def __init__(self, results_by_query: dict[str, list[SearchResult]]) -> None:
        self.results_by_query = results_by_query
        self.queries: list[str] = []
        self.active = 0
        self.max_active = 0

    async def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        assert limit == 2
        self.queries.append(query)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            import asyncio

            await asyncio.sleep(0)
            return self.results_by_query[query]
        finally:
            self.active -= 1


def campaign() -> Campaign:
    """Create a campaign with enough criteria for workflow prompts."""
    return Campaign(
        id=uuid4(),
        name="Australian fintech",
        description="Find engineering-focused fintech companies.",
        target_market="Australia",
        industry="Financial services",
        technologies=["Java", "Spring Boot", "Kafka"],
        company_size_min=50,
        company_size_max=500,
        target_count=5,
        status="DRAFT",
    )


def discovered_company(name: str, **values: object) -> DiscoveredCompany:
    """Build structured discovery output with realistic transient provenance."""
    payload = {
        "name": name,
        "discovery_reason": "Supplied search evidence supports further investigation.",
        "supporting_urls": [],
    }
    payload.update(values)
    return DiscoveredCompany(**payload)


def test_discovery_query_prompt_defines_company_discovery_semantics() -> None:
    prompt = search_query_system_prompt().lower()

    assert SEARCH_QUERY_PROMPT.version == "v2"
    assert "company discovery" in prompt
    assert "downstream investigation criteria" in prompt
    assert "jobs, vacancies, careers" in prompt
    assert "linkedin jobs, seek, indeed, glassdoor" in prompt
    assert "company websites, company directories, industry associations" in prompt
    assert "distinct, complementary search strategies" in prompt
    assert "3 to 5" in prompt


def test_discovery_query_schema_rejects_more_than_five_queries() -> None:
    with pytest.raises(ValidationError):
        GeneratedSearchQueries(queries=[f"query {index}" for index in range(12)])


def test_company_discovery_prompt_prioritizes_candidate_recall() -> None:
    prompt = company_discovery_system_prompt().lower()

    assert COMPANY_DISCOVERY_PROMPT.version == "v3"
    assert "candidate discovery, not final qualification" in prompt
    assert "favor recall over strict qualification" in prompt
    assert "supplied discovery candidate limit, not the campaign target count" in prompt
    assert "ranking signals, not hard gates" in prompt
    assert "unknown size is not a reason to exclude" in prompt
    assert "technology information is not required during discovery" in prompt
    assert "clearly irrelevant entities" in prompt
    assert "do not invent companies, websites, domains, or supporting urls" in prompt
    assert "material uncertainty" in prompt


@pytest.mark.asyncio
async def test_successful_workflow_persists_deduplicated_campaign_companies() -> None:
    model = campaign()
    research = ResearchServiceFake()
    llm = LLMFake(
        companies=[
            discovered_company(
                "Acme",
                website="https://www.acme.example",
                domain="acme.example",
                supporting_urls=["https://acme.example/jobs"],
            ),
            discovered_company(
                "Acme duplicate",
                domain="www.acme.example",
                supporting_urls=["https://acme.example/jobs/"],
            ),
            discovered_company("Beta", domain="beta.example"),
        ]
    )
    search = WebSearchFake(
        [
            SearchResult(title="Acme", url="https://acme.example/jobs"),
            SearchResult(title="Acme duplicate", url="https://acme.example/jobs/"),
        ]
    )
    workflow = ResearchWorkflow(
        campaigns=CampaignServiceFake(model), research=research, llm=llm, web_search=search
    )

    result = await workflow.run(model.id)

    run = research.runs[result.research_run_id]
    assert run.status == "COMPLETED"
    assert result.companies_found == 2
    assert len(research.companies_by_domain) == 2
    assert len(research.targets) == 2
    assert search.calls == [
        ("Australian fintech companies", 10),
        ("company engineering evidence", 5),
        ("company engineering evidence", 5),
    ]
    assert llm.response_models == [
        GeneratedSearchQueries,
        DiscoveredCompanies,
        GeneratedCompanySearchQueries,
        GeneratedCompanySearchQueries,
    ]


@pytest.mark.asyncio
async def test_existing_company_is_reused_and_existing_target_is_not_duplicated() -> None:
    model = campaign()
    research = ResearchServiceFake(existing_domains={"acme.example"})
    existing_company_id = research.companies_by_domain["acme.example"]
    research.targets.add((model.id, existing_company_id))
    workflow = ResearchWorkflow(
        campaigns=CampaignServiceFake(model),
        research=research,
        llm=LLMFake(companies=[discovered_company("Acme", domain="acme.example")]),
        web_search=WebSearchFake(),
    )

    result = await workflow.run(model.id)

    assert result.companies_found == 0
    assert len(research.companies_by_domain) == 1
    assert len(research.targets) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [RuntimeError("LLM unavailable"), RuntimeError("Search unavailable")])
async def test_failure_after_run_creation_marks_run_failed(failure: Exception) -> None:
    model = campaign()
    research = ResearchServiceFake()
    llm = LLMFake(error=failure) if "LLM" in str(failure) else LLMFake()
    search = WebSearchFake(error=failure) if "Search" in str(failure) else WebSearchFake()
    workflow = ResearchWorkflow(
        campaigns=CampaignServiceFake(model), research=research, llm=llm, web_search=search
    )

    with pytest.raises(RuntimeError, match=str(failure)):
        await workflow.run(model.id)

    run = next(iter(research.runs.values()))
    assert run.status == "FAILED"
    assert "Research workflow failed" in run.error
    assert "unavailable" not in run.error


@pytest.mark.asyncio
async def test_unknown_campaign_does_not_create_research_run() -> None:
    research = ResearchServiceFake()
    workflow = ResearchWorkflow(
        campaigns=CampaignServiceFake(None),
        research=research,
        llm=LLMFake(),
        web_search=WebSearchFake(),
    )

    with pytest.raises(CampaignNotFoundError, match="Campaign not found"):
        await workflow.run(uuid4())

    assert research.created_runs == 0


@pytest.mark.asyncio
async def test_multiple_queries_are_concurrent_deduplicated_and_bounded() -> None:
    model = campaign()
    research = ResearchServiceFake()
    search = QueryResultsWebSearchFake(
        {
            "first": [
                SearchResult(title="Acme", url="https://acme.example/jobs"),
                SearchResult(title="Beta", url="https://beta.example"),
            ],
            "second": [
                SearchResult(title="Acme duplicate", url="https://ACME.example/jobs/"),
                SearchResult(title="Gamma", url="https://gamma.example"),
            ],
            "third": [SearchResult(title="Delta", url="https://delta.example")],
        }
    )
    llm = LLMFake(queries=["first", "second", "third"])
    workflow = ResearchWorkflow(
        campaigns=CampaignServiceFake(model),
        research=research,
        llm=llm,
        web_search=search,
        settings=Settings(
            web_search_max_results=2,
            web_search_max_total_results=3,
            web_search_concurrency=2,
        ),
    )

    await workflow.run(model.id)

    assert search.queries == ["first", "second", "third"]
    assert search.max_active == 2
    discovery_prompt = llm.user_prompts[-1]
    assert "https://acme.example/jobs" in discovery_prompt
    assert "https://beta.example" in discovery_prompt
    assert "https://gamma.example" in discovery_prompt
    assert "https://delta.example" not in discovery_prompt


@pytest.mark.asyncio
async def test_discovery_keeps_incomplete_candidates_and_validates_provenance() -> None:
    model = campaign()
    model.target_count = 3
    source_a = "https://industry.example/acme"
    source_b = "https://report.example/beta"
    nodes = ResearchNodes(
        campaigns=CampaignServiceFake(model),
        research=ResearchServiceFake(),
        llm=LLMFake(
            companies=[
                discovered_company(
                    "Acme",
                    discovery_reason=(
                        "An industry source identifies Acme as an Australian payments fintech; "
                        "size and technology stack require investigation."
                    ),
                    supporting_urls=[source_a, "https://invented.example/acme"],
                ),
                discovered_company(
                    "Beta",
                    discovery_reason=(
                        "A credible report identifies Beta as an Australian fintech; "
                        "employee count and technologies are unknown."
                    ),
                    supporting_urls=[source_b],
                ),
            ]
        ),
        web_search=WebSearchFake(),
    )

    discovered = await nodes.discover_companies(  # type: ignore[arg-type]
        {
            "campaign": CampaignCriteria.model_validate(model),
            "search_results": [
                SearchResult(title="Acme profile", url=source_a),
                SearchResult(title="Beta report", url=source_b),
            ],
        }
    )

    companies = discovered["discovered_companies"]
    assert [company.name for company in companies] == ["Acme", "Beta"]
    assert len(companies) == 2
    assert "technology stack require investigation" in companies[0].discovery_reason
    assert companies[0].supporting_urls == [source_a]
    assert companies[1].supporting_urls == [source_b]


@pytest.mark.asyncio
async def test_discovery_uses_broader_candidate_limit_than_target_count() -> None:
    model = campaign()
    model.target_count = 3
    source_urls = [f"https://directory.example/company-{index}" for index in range(7)]
    llm = LLMFake(
        companies=[
            discovered_company(
                f"Candidate {index}",
                discovery_reason=(
                    "A credible Australian fintech directory identifies this company; "
                    "size and technologies require investigation."
                ),
                supporting_urls=[source_url],
            )
            for index, source_url in enumerate(source_urls)
        ]
    )
    nodes = ResearchNodes(
        campaigns=CampaignServiceFake(model),
        research=ResearchServiceFake(),
        llm=llm,
        web_search=WebSearchFake(),
        discovery_candidate_multiplier=3,
        discovery_candidate_max=15,
    )

    discovered = await nodes.discover_companies(  # type: ignore[arg-type]
        {
            "campaign": CampaignCriteria.model_validate(model),
            "search_results": [
                SearchResult(title=f"Candidate {index}", url=source_url)
                for index, source_url in enumerate(source_urls)
            ],
        }
    )

    assert len(discovered["discovered_companies"]) == 7
    assert "Discovery candidate limit: 9" in llm.user_prompts[-1]


def test_discovery_candidate_limit_caps_at_configured_maximum() -> None:
    nodes = ResearchNodes(
        campaigns=CampaignServiceFake(campaign()),
        research=ResearchServiceFake(),
        llm=LLMFake(),
        web_search=WebSearchFake(),
        discovery_candidate_multiplier=3,
        discovery_candidate_max=15,
    )

    assert nodes._discovery_candidate_limit(3) == 9
    assert nodes._discovery_candidate_limit(10) == 15


@pytest.mark.asyncio
async def test_workflow_investigates_candidate_pool_beyond_target_count() -> None:
    model = campaign()
    model.target_count = 3
    candidates = [
        discovered_company(f"Candidate {index}", domain=f"candidate-{index}.example")
        for index in range(7)
    ]
    research = ResearchServiceFake()
    llm = LLMFake(companies=candidates, company_queries=["candidate investigation"])
    search = WebSearchFake()
    workflow = ResearchWorkflow(
        campaigns=CampaignServiceFake(model),
        research=research,
        llm=llm,
        web_search=search,
        settings=Settings(
            discovery_candidate_multiplier=3,
            discovery_candidate_max=15,
        ),
    )

    result = await workflow.run(model.id)

    assert result.companies_found == 7
    assert len(research.targets) == 7
    assert llm.response_models.count(GeneratedCompanySearchQueries) == 7
    assert search.calls == [("Australian fintech companies", 10)] + [
        ("candidate investigation", 5)
    ] * 7


@pytest.mark.asyncio
async def test_discovery_allows_zero_candidates() -> None:
    model = campaign()
    nodes = ResearchNodes(
        campaigns=CampaignServiceFake(model),
        research=ResearchServiceFake(),
        llm=LLMFake(companies=[]),
        web_search=WebSearchFake(),
    )

    discovered = await nodes.discover_companies(  # type: ignore[arg-type]
        {"campaign": CampaignCriteria.model_validate(model), "search_results": []}
    )

    assert discovered["discovered_companies"] == []


@pytest.mark.asyncio
async def test_company_queries_and_sources_are_separated_deduplicated_and_bounded() -> None:
    model = campaign()
    acme_id, beta_id = uuid4(), uuid4()
    llm = LLMFake(company_queries=["company source one", "company source two", "unused"])
    search = QueryResultsWebSearchFake(
        {
            "company source one": [
                SearchResult(title="Careers", url="https://acme.example/careers"),
                SearchResult(title="Blog", url="https://acme.example/blog"),
            ],
            "company source two": [
                SearchResult(title="Careers duplicate", url="https://acme.example/careers/"),
                SearchResult(title="Third", url="https://acme.example/third"),
            ],
            "unused": [SearchResult(title="Unused", url="https://acme.example/unused")],
        }
    )
    nodes = ResearchNodes(
        campaigns=CampaignServiceFake(model),
        research=ResearchServiceFake(),
        llm=llm,
        web_search=search,
        web_search_concurrency=2,
        company_research_query_count=2,
        company_research_max_results_per_query=2,
        company_research_max_results_per_company=3,
    )
    state = {
        "campaign": CampaignCriteria.model_validate(model),
        "research_companies": [
            ResearchCompany(id=acme_id, name="Acme", domain="acme.example"),
            ResearchCompany(id=beta_id, name="Beta", domain="beta.example"),
        ],
    }

    generated = await nodes.generate_company_queries(state)  # type: ignore[arg-type]
    state["company_research_queries"] = generated["company_research_queries"]
    sources = await nodes.search_company_sources(state)  # type: ignore[arg-type]

    assert llm.response_models == [GeneratedCompanySearchQueries, GeneratedCompanySearchQueries]
    assert '"target_market":"Australia"' in llm.user_prompts[0]
    assert '"technologies":["Java","Spring Boot","Kafka"]' in llm.user_prompts[0]
    assert '"name":"Acme"' in llm.user_prompts[0]
    assert '"domain":"acme.example"' in llm.user_prompts[0]
    assert len(generated["company_research_queries"][acme_id]) == 2
    assert search.max_active == 2
    assert len(sources["company_search_results"][acme_id]) == 3
    assert len(sources["company_search_results"][beta_id]) == 3
    assert sources["company_search_results"][acme_id][0].url == "https://acme.example/careers"


@pytest.mark.asyncio
async def test_company_source_failure_marks_existing_research_run_failed() -> None:
    model = campaign()

    class CompanySearchFailureFake(WebSearchFake):
        async def search(self, query: str, limit: int = 10) -> list[SearchResult]:
            if limit == 5:
                raise RuntimeError("Company search unavailable")
            return await super().search(query, limit)

    research = ResearchServiceFake()
    workflow = ResearchWorkflow(
        campaigns=CampaignServiceFake(model),
        research=research,
        llm=LLMFake(companies=[discovered_company("Acme", domain="acme.example")]),
        web_search=CompanySearchFailureFake(),
    )

    with pytest.raises(RuntimeError, match="Company search unavailable"):
        await workflow.run(model.id)

    run = next(iter(research.runs.values()))
    assert run.status == "FAILED"
    assert "search_company_sources" in run.error
