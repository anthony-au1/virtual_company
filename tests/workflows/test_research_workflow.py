"""Tests for the first LangGraph campaign research workflow."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

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
        technologies=["Java"],
        company_size_min=50,
        company_size_max=500,
        target_count=5,
        status="DRAFT",
    )


@pytest.mark.asyncio
async def test_successful_workflow_persists_deduplicated_campaign_companies() -> None:
    model = campaign()
    research = ResearchServiceFake()
    llm = LLMFake(
        companies=[
            DiscoveredCompany(
                name="Acme", website="https://www.acme.example", domain="acme.example"
            ),
            DiscoveredCompany(name="Acme duplicate", domain="www.acme.example"),
            DiscoveredCompany(name="Beta", domain="beta.example"),
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
        llm=LLMFake(companies=[DiscoveredCompany(name="Acme", domain="acme.example")]),
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
        llm=LLMFake(companies=[DiscoveredCompany(name="Acme", domain="acme.example")]),
        web_search=CompanySearchFailureFake(),
    )

    with pytest.raises(RuntimeError, match="Company search unavailable"):
        await workflow.run(model.id)

    run = next(iter(research.runs.values()))
    assert run.status == "FAILED"
    assert "search_company_sources" in run.error
