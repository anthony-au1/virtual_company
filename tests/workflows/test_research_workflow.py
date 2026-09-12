"""Tests for the first LangGraph campaign research workflow."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from virtual_company.db.models import Campaign
from virtual_company.research.models import DiscoveredCompany, SearchResult
from virtual_company.workflows.research.graph import ResearchWorkflow
from virtual_company.workflows.research.models import (
    DiscoveredCompanies,
    GeneratedSearchQueries,
)
from virtual_company.workflows.research.nodes import CampaignNotFoundError


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
    ) -> int:
        created_targets = 0
        for company in companies:
            domain = (company.domain or company.website or company.name).lower()
            company_id = self.companies_by_domain.setdefault(domain, uuid4())
            target = (campaign_id, company_id)
            if target not in self.targets:
                self.targets.add(target)
                created_targets += 1
        return created_targets

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
        companies: list[DiscoveredCompany] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.queries = queries or ["Australian fintech companies"]
        self.companies = companies or []
        self.error = error
        self.response_models: list[type[object]] = []

    async def generate_structured(self, **kwargs: object) -> object:
        self.response_models.append(kwargs["response_model"])
        if self.error is not None:
            raise self.error
        if kwargs["response_model"] is GeneratedSearchQueries:
            return GeneratedSearchQueries(queries=self.queries)
        return DiscoveredCompanies(companies=self.companies)


class WebSearchFake:
    """In-memory web search fake."""

    def __init__(
        self, results: list[SearchResult] | None = None, error: Exception | None = None
    ) -> None:
        self.results = results or []
        self.error = error
        self.queries: list[str] = []

    async def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        self.queries.append(query)
        assert limit == 10
        if self.error is not None:
            raise self.error
        return self.results


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
    assert search.queries == ["Australian fintech companies"]
    assert llm.response_models == [GeneratedSearchQueries, DiscoveredCompanies]


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
