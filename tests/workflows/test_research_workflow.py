"""Tests for staged company discovery."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from virtual_company.config import Settings
from virtual_company.db.models import Campaign
from virtual_company.research.models import DiscoveredCompany, SearchResult
from virtual_company.workflows.research.graph import ResearchWorkflow
from virtual_company.workflows.research.models import (
    AggregatedCompanyCandidate,
    CampaignCriteria,
    DiscoveredCompanies,
    ExtractedCompanyCandidate,
    ExtractedCompanyIdentities,
    ExtractedCompanyIdentity,
    GeneratedCompanySearchQueries,
    GeneratedSearchQueries,
)
from virtual_company.workflows.research.nodes import (
    CampaignNotFoundError,
    ResearchNodes,
)
from virtual_company.workflows.research.prompts import (
    EXTRACT_COMPANY_CANDIDATES_PROMPT,
    RANK_COMPANY_CANDIDATES_PROMPT,
    extract_company_candidates_system_prompt,
    rank_company_candidates_system_prompt,
)


class CampaignServiceFake:
    def __init__(self, value: Campaign | None) -> None:
        self.value = value

    async def get_by_id(self, _: UUID) -> Campaign | None:
        return self.value


class ResearchServiceFake:
    def __init__(self) -> None:
        self.runs: dict[UUID, SimpleNamespace] = {}
        self.targets: list[str] = []

    async def create_run(self, campaign_id: UUID) -> SimpleNamespace:
        run = SimpleNamespace(id=uuid4(), campaign_id=campaign_id, status="RUNNING")
        self.runs[run.id] = run
        return run

    async def persist_companies(
        self, *, campaign_id: UUID, companies: list[DiscoveredCompany]
    ) -> SimpleNamespace:
        self.targets = [c.name for c in companies]
        return SimpleNamespace(
            companies_found=len(companies),
            companies=[
                SimpleNamespace(
                    id=uuid4(), name=c.name, website=c.website, domain=c.domain
                )
                for c in companies
            ],
        )

    async def complete_run(self, run_id: UUID, companies_found: int) -> None:
        self.runs[run_id].status = "COMPLETED"

    async def fail_run(self, run_id: UUID, error: str) -> None:
        self.runs[run_id].status = "FAILED"


class SearchFake:
    def __init__(self, results: list[SearchResult]) -> None:
        self.results = results
        self.calls: list[tuple[str, int]] = []

    async def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        self.calls.append((query, limit))
        return self.results


class ExtractionFake:
    def __init__(self, values: dict[str, list[ExtractedCompanyIdentity]]) -> None:
        self.values = values
        self.prompts: list[str] = []
        self.active = 0
        self.max_active = 0

    async def generate_structured(self, **kwargs: object) -> ExtractedCompanyIdentities:
        prompt = str(kwargs["user_prompt"])
        self.prompts.append(prompt)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(0)
            return ExtractedCompanyIdentities(
                companies=next(v for url, v in self.values.items() if url in prompt)
            )
        finally:
            self.active -= 1


class ResearchFake:
    def __init__(self, ranked: list[DiscoveredCompany]) -> None:
        self.ranked = ranked
        self.prompts: list[str] = []
        self.models: list[type[object]] = []

    async def generate_structured(self, **kwargs: object) -> object:
        self.prompts.append(str(kwargs["user_prompt"]))
        model = kwargs["response_model"]
        self.models.append(model)
        if model is GeneratedSearchQueries:
            return GeneratedSearchQueries(queries=["Australian fintech companies"])
        if model is GeneratedCompanySearchQueries:
            return GeneratedCompanySearchQueries(queries=["company evidence"])
        return DiscoveredCompanies(companies=self.ranked)


def campaign() -> Campaign:
    return Campaign(
        id=uuid4(),
        name="Australian fintech",
        description=None,
        target_market="Australia",
        industry="Fintech",
        technologies=["Java", "Spring Boot", "Kafka"],
        company_size_min=None,
        company_size_max=None,
        target_count=3,
        status="DRAFT",
    )


def found(name: str, urls: list[str]) -> DiscoveredCompany:
    return DiscoveredCompany(
        name=name, discovery_reason="Relevant supplied evidence.", supporting_urls=urls
    )


def make_nodes(
    extraction: ExtractionFake, research: ResearchFake, model: Campaign
) -> ResearchNodes:
    return ResearchNodes(
        campaigns=CampaignServiceFake(model),
        research=ResearchServiceFake(),
        research_llm=research,
        extraction_llm=extraction,
        web_search=SearchFake([]),
        web_search_concurrency=2,
    )


def test_staged_prompt_semantics() -> None:
    extraction, ranking = (
        extract_company_candidates_system_prompt().lower(),
        rank_company_candidates_system_prompt().lower(),
    )
    assert (
        EXTRACT_COMPANY_CANDIDATES_PROMPT.version == "v1"
        and RANK_COMPANY_CANDIDATES_PROMPT.version == "v1"
    )
    assert (
        "optimizes for recall" in extraction and "do not rank companies" in extraction
    )
    assert (
        "technology criteria and exact employee count are not required" in extraction
        and "article publishers" in extraction
    )
    assert (
        "do not discover additional companies" in ranking
        and "unstated knowledge" in ranking
    )


@pytest.mark.asyncio
async def test_extraction_recall_has_no_limit_and_provenance_is_assigned() -> None:
    model = campaign()
    results = [
        SearchResult(
            title=n,
            url=f"https://source.example/{n.lower()}",
            snippet="Australian fintech",
        )
        for n in ["Airwallex", "Prospa", "Zai", "Openpay", "Tyro"]
    ]
    extraction = ExtractionFake(
        {r.url: [ExtractedCompanyIdentity(name=r.title)] for r in results}
    )
    output = await make_nodes(
        extraction, ResearchFake([]), model
    ).extract_company_candidates(
        {"campaign": CampaignCriteria.model_validate(model), "search_results": results}
    )  # type: ignore[arg-type]
    candidates = output["extracted_company_candidates"]
    assert [c.name for c in candidates] == [r.title for r in results]
    assert [c.source_url for c in candidates] == [r.url for r in results]
    assert extraction.max_active == 2


@pytest.mark.asyncio
async def test_aggregation_merges_variants_and_keeps_single_mention() -> None:
    model = campaign()
    candidates = [
        ExtractedCompanyCandidate(name=n, source_url=url)
        for n, url in [
            ("Airwallex", "https://a.example"),
            ("Airwallex Pty Ltd", "https://b.example"),
            ("AIRWALLEX", "https://c.example"),
            ("Moula", "https://d.example"),
        ]
    ]
    output = await make_nodes(
        ExtractionFake({}), ResearchFake([]), model
    ).aggregate_company_candidates({"extracted_company_candidates": candidates})  # type: ignore[arg-type]
    aggregate = output["aggregated_company_candidates"]
    assert [(c.name, c.mention_count) for c in aggregate] == [
        ("Airwallex", 3),
        ("Moula", 1),
    ]
    assert aggregate[0].supporting_urls == [
        "https://a.example",
        "https://b.example",
        "https://c.example",
    ]


@pytest.mark.asyncio
async def test_ranking_receives_aggregates_limits_results_and_validates_urls() -> None:
    model = campaign()
    aggregate = [
        AggregatedCompanyCandidate(
            name=f"Candidate {i}",
            mention_count=1,
            supporting_urls=[f"https://{i}.example"],
            supporting_results=[SearchResult(title=str(i), url=f"https://{i}.example")],
        )
        for i in range(10)
    ]
    research = ResearchFake(
        [
            found(f"Candidate {i}", [f"https://{i}.example", "https://wrong.example"])
            for i in range(10)
        ]
    )
    output = await make_nodes(
        ExtractionFake({}), research, model
    ).rank_company_candidates(
        {
            "campaign": CampaignCriteria.model_validate(model),
            "aggregated_company_candidates": aggregate,
        }
    )  # type: ignore[arg-type]
    assert len(output["discovered_companies"]) == 9
    assert output["discovered_companies"][0].supporting_urls == ["https://0.example"]
    assert (
        "Aggregated company candidates" in research.prompts[0]
        and "Search results:" not in research.prompts[0]
    )


@pytest.mark.asyncio
async def test_workflow_investigates_only_ranked_companies() -> None:
    model = campaign()
    results = [
        SearchResult(title=f"Candidate {i}", url=f"https://source-{i}.example")
        for i in range(10)
    ]
    extraction = ExtractionFake(
        {r.url: [ExtractedCompanyIdentity(name=r.title)] for r in results}
    )
    research = ResearchFake(
        [found(f"Candidate {i}", [f"https://source-{i}.example"]) for i in range(9)]
    )
    service = ResearchServiceFake()
    workflow = ResearchWorkflow(
        campaigns=CampaignServiceFake(model),
        research=service,
        research_llm=research,
        extraction_llm=extraction,
        web_search=SearchFake(results),
        settings=Settings(),
    )
    await workflow.run(model.id)
    assert service.targets == [f"Candidate {i}" for i in range(9)]
    assert research.models.count(GeneratedCompanySearchQueries) == 9


@pytest.mark.asyncio
async def test_unknown_campaign_does_not_create_run() -> None:
    service = ResearchServiceFake()
    with pytest.raises(CampaignNotFoundError):
        await ResearchWorkflow(
            campaigns=CampaignServiceFake(None),
            research=service,
            research_llm=ResearchFake([]),
            extraction_llm=ExtractionFake({}),
            web_search=SearchFake([]),
        ).run(uuid4())
    assert service.runs == {}
