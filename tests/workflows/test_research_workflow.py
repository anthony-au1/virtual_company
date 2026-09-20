"""Tests for staged company discovery."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from virtual_company.config import Settings
from virtual_company.db.models import Campaign
from virtual_company.repositories.dtos import EvidenceCreate
from virtual_company.research.models import (
    DiscoveredCompany,
    EvidenceCriterion,
    ExtractedEvidence,
    ExtractedEvidenceItems,
    SearchResult,
    WebPage,
)
from virtual_company.services.research import ResearchService
from virtual_company.tools.web_fetch import WebFetchError
from virtual_company.workflows.research.graph import ResearchWorkflow
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
    ExtractedCompanyIdentity,
    GeneratedCompanySearchQueries,
    GeneratedSearchQueries,
    InvestigationStopReason,
    ResearchCompany,
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
        self.evidence: list[SimpleNamespace] = []

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

    async def persist_evidence(self, *, research_run_id: UUID, evidence: list[object]) -> SimpleNamespace:
        created_by_company: dict[UUID, int] = {}
        for item in evidence:
            stored = SimpleNamespace(id=uuid4(), **item.model_dump())
            self.evidence.append(stored)
            created_by_company[item.company_id] = created_by_company.get(item.company_id, 0) + 1
        return SimpleNamespace(
            created_count=len(evidence),
            skipped_count=0,
            created_by_company=created_by_company,
        )

    async def list_evidence_for_run(self, run_id: UUID) -> list[SimpleNamespace]:
        return [item for item in self.evidence if item.research_run_id == run_id]

    async def fail_run(self, run_id: UUID, error: str) -> None:
        self.runs[run_id].status = "FAILED"


class SearchFake:
    def __init__(self, results: list[SearchResult]) -> None:
        self.results = results
        self.calls: list[tuple[str, int]] = []

    async def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        self.calls.append((query, limit))
        return self.results


class FetchFake:
    def __init__(self, pages: dict[str, WebPage | Exception]) -> None:
        self.pages = pages
        self.calls: list[str] = []

    async def fetch(self, url: str) -> WebPage:
        self.calls.append(url)
        value = self.pages.get(url, WebPage(url=url, content="Fetched page"))
        if isinstance(value, Exception):
            raise value
        return value


class ExtractionFake:
    def __init__(self, values: dict[str, list[ExtractedCompanyIdentity]]) -> None:
        self.values = values
        self.prompts: list[str] = []
        self.active = 0
        self.max_active = 0

    async def generate_structured(self, **kwargs: object) -> object:
        prompt = str(kwargs["user_prompt"])
        self.prompts.append(prompt)
        model = kwargs["response_model"]
        if model is CompanyPageAttribution:
            return CompanyPageAttribution(attributable=True, reason="The page concerns the company.")
        if model is ExtractedEvidenceItems:
            return ExtractedEvidenceItems(evidence=[])
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(0)
            return ExtractedCompanyIdentities(
                companies=next(v for url, v in self.values.items() if url in prompt)
            )
        finally:
            self.active -= 1


class EvidenceExtractionFake:
    def __init__(self, values: dict[str, list[ExtractedEvidence] | Exception]) -> None:
        self.values = values
        self.prompts: list[str] = []

    async def generate_structured(self, **kwargs: object) -> ExtractedEvidenceItems:
        prompt = str(kwargs["user_prompt"])
        self.prompts.append(prompt)
        value = next(v for url, v in self.values.items() if url in prompt)
        if isinstance(value, Exception):
            raise value
        return ExtractedEvidenceItems(evidence=value)


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
        web_fetch=FetchFake({}),
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
        web_fetch=FetchFake({}),
        settings=Settings(company_research_max_investigation_rounds=0),
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
            web_fetch=FetchFake({}),
        ).run(uuid4())
    assert service.runs == {}


@pytest.mark.asyncio
async def test_source_selection_deduplicates_and_prefers_first_party_pages() -> None:
    model = campaign()
    company = ResearchCompany(id=uuid4(), name="Acme", website=None, domain="acme.example")
    sources = [
        SearchResult(title="Profile", url="https://directory.example/acme", snippet="Company profile"),
        SearchResult(title="Acme", url="https://acme.example/", snippet=None),
        SearchResult(title="Backend jobs", url="https://acme.example/careers/backend", snippet="Java"),
        SearchResult(title="Duplicate", url="https://acme.example/careers/backend?utm_source=search"),
        SearchResult(title="Engineering", url="https://acme.example/blog/engineering", snippet="Platform"),
        SearchResult(title="Independent", url="https://news.example/acme", snippet="Funding"),
    ]
    nodes = make_nodes(ExtractionFake({}), ResearchFake([]), model)
    nodes._company_research_max_fetches_per_company = 3
    output = await nodes.select_company_sources(
        {
            "research_companies": [company],
            "company_search_results": {company.id: sources},
        }
    )  # type: ignore[arg-type]
    selected = output["selected_company_sources"][company.id]
    assert [source.url for source in selected][:2] == [
        "https://acme.example/careers/backend",
        "https://acme.example/blog/engineering",
    ]
    assert len(selected) == 3
    assert all("utm_source" not in source.url for source in selected)


@pytest.mark.asyncio
async def test_fetch_sources_retains_partial_successes() -> None:
    model = campaign()
    company_a = SimpleNamespace(id=uuid4(), name="A", website=None, domain="a.example")
    company_b = SimpleNamespace(id=uuid4(), name="B", website=None, domain="b.example")
    sources = {
        company_a.id: [
            SearchResult(title="A one", url="https://a.example/one"),
            SearchResult(title="A two", url="https://a.example/two"),
        ],
        company_b.id: [SearchResult(title="B", url="https://b.example")],
    }
    fetch = FetchFake(
        {
            "https://a.example/one": WebPage(url="https://a.example/one", content="A"),
            "https://a.example/two": WebFetchError("timeout"),
            "https://b.example": WebPage(url="https://b.example", content="B"),
        }
    )
    nodes = make_nodes(ExtractionFake({}), ResearchFake([]), model)
    nodes._web_fetch = fetch
    output = await nodes.fetch_company_sources(
        {"research_companies": [company_a, company_b], "selected_company_sources": sources}
    )  # type: ignore[arg-type]
    assert [page.content for page in output["company_web_pages"][company_a.id]] == ["A"]
    assert [page.content for page in output["company_web_pages"][company_b.id]] == ["B"]
    assert fetch.calls == [
        "https://a.example/one",
        "https://a.example/two",
        "https://b.example",
    ]


@pytest.mark.asyncio
async def test_evidence_extraction_validates_provenance_whitespace_and_duplicates() -> None:
    model = campaign()
    company = ResearchCompany(id=uuid4(), name="Acme", website=None, domain="acme.example")
    page = WebPage(
        url="https://acme.example/jobs/backend",
        title="Backend Engineer",
        content="We use Java\nand Spring Boot for backend services.",
    )
    extracted = ExtractedEvidence(
        criterion=EvidenceCriterion.TECHNOLOGY,
        subject="Java",
        claim="Acme uses Java for backend services.",
        evidence_text="We use Java and Spring Boot for backend services.",
    )
    fake = EvidenceExtractionFake({page.url: [extracted, extracted]})
    nodes = make_nodes(ExtractionFake({}), ResearchFake([]), model)
    nodes._extraction_llm = fake
    run_id = uuid4()
    output = await nodes.extract_company_evidence(
        {
            "campaign": CampaignCriteria.model_validate(model),
            "research_run_id": run_id,
            "research_companies": [company],
            "company_web_pages": {company.id: [page]},
        }
    )  # type: ignore[arg-type]
    evidence = output["validated_evidence"]
    assert len(evidence) == 1
    assert evidence[0].source_url == page.url
    assert evidence[0].source_title == page.title
    assert evidence[0].subject == "Java"
    assert "\"technologies\":[\"Java\",\"Spring Boot\",\"Kafka\"]" in fake.prompts[0]


@pytest.mark.asyncio
async def test_evidence_extraction_rejects_absent_excerpt_and_continues_after_failure() -> None:
    model = campaign()
    company = ResearchCompany(id=uuid4(), name="Acme", website=None, domain="acme.example")
    valid_page = WebPage(url="https://acme.example/one", content="We use Java for backend services.")
    failed_page = WebPage(url="https://acme.example/two", content="Unused")
    invalid = ExtractedEvidence(
        criterion=EvidenceCriterion.TECHNOLOGY,
        subject="Kafka",
        claim="Acme uses Kafka.",
        evidence_text="Our platform is built with Java and Kafka.",
    )
    fake = EvidenceExtractionFake({valid_page.url: [invalid], failed_page.url: RuntimeError("timeout")})
    nodes = make_nodes(ExtractionFake({}), ResearchFake([]), model)
    nodes._extraction_llm = fake
    output = await nodes.extract_company_evidence(
        {
            "campaign": CampaignCriteria.model_validate(model),
            "research_run_id": uuid4(),
            "research_companies": [company],
            "company_web_pages": {company.id: [valid_page, failed_page]},
        }
    )  # type: ignore[arg-type]
    assert output["validated_evidence"] == []


@pytest.mark.asyncio
async def test_evidence_extraction_preserves_explicit_size_and_geography_precision() -> None:
    model = campaign()
    model.company_size_min = 100
    model.company_size_max = 500
    company = ResearchCompany(id=uuid4(), name="Acme", website=None, domain="acme.example")
    page = WebPage(
        url="https://acme.example/careers",
        content="Join our Melbourne engineering team. Our global team has more than 300 employees.",
    )
    fake = EvidenceExtractionFake(
        {
            page.url: [
                ExtractedEvidence(
                    criterion=EvidenceCriterion.TARGET_MARKET,
                    subject="Australia",
                    claim="Acme has an engineering presence in Melbourne.",
                    evidence_text="Join our Melbourne engineering team.",
                ),
                ExtractedEvidence(
                    criterion=EvidenceCriterion.COMPANY_SIZE,
                    subject="more than 300 employees",
                    claim="Acme reports a global team of more than 300 employees.",
                    evidence_text="Our global team has more than 300 employees.",
                ),
            ]
        }
    )
    nodes = make_nodes(ExtractionFake({}), ResearchFake([]), model)
    nodes._extraction_llm = fake
    output = await nodes.extract_company_evidence(
        {
            "campaign": CampaignCriteria.model_validate(model),
            "research_run_id": uuid4(),
            "research_companies": [company],
            "company_web_pages": {company.id: [page]},
            "selected_company_sources": {company.id: [SearchResult(title="Careers", url=page.url)]},
        }
    )  # type: ignore[arg-type]
    assert [(item.criterion, item.subject) for item in output["validated_evidence"]] == [
        (EvidenceCriterion.TARGET_MARKET, "Australia"),
        (EvidenceCriterion.COMPANY_SIZE, "more than 300 employees"),
    ]


@pytest.mark.asyncio
async def test_evidence_persistence_is_idempotent_within_one_research_run() -> None:
    class EvidenceRepositoryFake:
        def __init__(self) -> None:
            self.items: list[EvidenceCreate] = []

        async def list_by_research_run_id(self, _: UUID) -> list[EvidenceCreate]:
            return self.items

        async def create(self, item: EvidenceCreate) -> EvidenceCreate:
            self.items.append(item)
            return item

    repository = EvidenceRepositoryFake()
    service = object.__new__(ResearchService)
    service._evidence = repository
    run_id = uuid4()
    item = EvidenceCreate(
        company_id=uuid4(),
        research_run_id=run_id,
        criterion="technology",
        subject="Java",
        claim="Acme uses Java.",
        evidence_text="We use Java.",
        source_url="https://acme.example/engineering",
    )
    first = await service.persist_evidence(research_run_id=run_id, evidence=[item, item])
    second = await service.persist_evidence(research_run_id=run_id, evidence=[item])
    assert (first.created_count, first.skipped_count) == (1, 1)
    assert (second.created_count, second.skipped_count) == (0, 1)
    assert repository.items == [item]


@pytest.mark.asyncio
async def test_followup_queries_contain_only_missing_criteria() -> None:
    model = campaign()
    company = ResearchCompany(id=uuid4(), name="Acme", domain="acme.example")
    research = ResearchFake([])
    nodes = make_nodes(ExtractionFake({}), research, model)
    coverage = [
        CriterionCoverage(
            criterion=EvidenceCriterion.TARGET_MARKET,
            subject="Australia",
            status=CoverageStatus.FOUND,
            evidence_ids=[uuid4()],
        ),
        CriterionCoverage(
            criterion=EvidenceCriterion.TECHNOLOGY,
            subject="Kafka",
            status=CoverageStatus.MISSING,
        ),
    ]
    output = await nodes.generate_followup_queries(
        {
            "campaign": CampaignCriteria.model_validate(model),
            "research_companies": [company],
            "active_company_ids": [company.id],
            "investigations": {
                company.id: CompanyInvestigationState(
                    company_id=company.id, coverage=coverage
                )
            },
        }
    )  # type: ignore[arg-type]
    prompt = research.prompts[-1]
    missing_section = prompt.split("Missing criteria:", 1)[1]
    assert "Kafka" in missing_section
    assert "Australia" not in missing_section
    assert output["investigations"][company.id].round == 1


@pytest.mark.asyncio
async def test_attempted_urls_are_not_selected_or_fetched_again() -> None:
    model = campaign()
    company = ResearchCompany(id=uuid4(), name="Acme", domain="acme.example")
    old_url = "https://acme.example/jobs/123"
    new_url = "https://acme.example/jobs/456"
    nodes = make_nodes(ExtractionFake({}), ResearchFake([]), model)
    output = await nodes.select_company_sources(
        {
            "research_companies": [company],
            "active_company_ids": [company.id],
            "adaptive_mode": True,
            "company_search_results": {
                company.id: [
                    SearchResult(title="Old", url=old_url),
                    SearchResult(title="New", url=new_url),
                ]
            },
            "investigations": {
                company.id: CompanyInvestigationState(
                    company_id=company.id, attempted_urls={old_url}
                )
            },
        }
    )  # type: ignore[arg-type]
    assert [item.url for item in output["selected_company_sources"][company.id]] == [new_url]
    assert output["investigations"][company.id].attempted_urls == {old_url, new_url}


@pytest.mark.asyncio
async def test_coverage_stops_companies_independently() -> None:
    model = campaign()
    model.target_market = None
    model.industry = None
    model.technologies = ["Kafka"]
    complete = ResearchCompany(id=uuid4(), name="Complete")
    stalled = ResearchCompany(id=uuid4(), name="Stalled")
    progressing = ResearchCompany(id=uuid4(), name="Progressing")
    run_id = uuid4()
    service = ResearchServiceFake()
    service.evidence = [
        SimpleNamespace(
            id=uuid4(), company_id=complete.id, research_run_id=run_id,
            criterion="technology", subject="Kafka"
        )
    ]
    nodes = ResearchNodes(
        campaigns=CampaignServiceFake(model),
        research=service,
        research_llm=ResearchFake([]),
        extraction_llm=ExtractionFake({}),
        web_search=SearchFake([]),
        web_fetch=FetchFake({}),
        company_research_max_investigation_rounds=2,
    )
    output = await nodes.check_evidence_coverage(
        {
            "campaign": CampaignCriteria.model_validate(model),
            "research_run_id": run_id,
            "research_companies": [complete, stalled, progressing],
            "investigations": {
                complete.id: CompanyInvestigationState(company_id=complete.id),
                stalled.id: CompanyInvestigationState(
                    company_id=stalled.id, round=1, missing_before=1,
                    new_evidence_count=0
                ),
                progressing.id: CompanyInvestigationState(
                    company_id=progressing.id, round=1, missing_before=2,
                    new_evidence_count=1
                ),
            },
        }
    )  # type: ignore[arg-type]
    states = output["investigations"]
    assert states[complete.id].stop_reason is InvestigationStopReason.COVERAGE_COMPLETE
    assert states[stalled.id].stop_reason is InvestigationStopReason.NO_PROGRESS
    assert states[progressing.id].stop_reason is None
    assert output["active_company_ids"] == [progressing.id]


@pytest.mark.asyncio
async def test_coverage_stops_at_maximum_adaptive_rounds() -> None:
    model = campaign()
    model.target_market = None
    model.industry = None
    model.technologies = ["Kafka"]
    company = ResearchCompany(id=uuid4(), name="Acme")
    run_id = uuid4()
    service = ResearchServiceFake()
    nodes = ResearchNodes(
        campaigns=CampaignServiceFake(model),
        research=service,
        research_llm=ResearchFake([]),
        extraction_llm=ExtractionFake({}),
        web_search=SearchFake([]),
        web_fetch=FetchFake({}),
        company_research_max_investigation_rounds=2,
    )
    output = await nodes.check_evidence_coverage(
        {
            "campaign": CampaignCriteria.model_validate(model),
            "research_run_id": run_id,
            "research_companies": [company],
            "investigations": {
                company.id: CompanyInvestigationState(
                    company_id=company.id,
                    round=2,
                    missing_before=2,
                    new_evidence_count=1,
                )
            },
        }
    )  # type: ignore[arg-type]
    investigation = output["investigations"][company.id]
    assert investigation.stop_reason is InvestigationStopReason.MAX_ROUNDS
    assert output["active_company_ids"] == []


@pytest.mark.asyncio
async def test_adaptive_pages_must_pass_attribution() -> None:
    class AttributionFake:
        async def generate_structured(self, **kwargs: object) -> CompanyPageAttribution:
            return CompanyPageAttribution(
                attributable=False, reason="The page belongs to another company."
            )

    model = campaign()
    company = ResearchCompany(id=uuid4(), name="Acme")
    page = WebPage(url="https://other.example/kafka", content="Other uses Kafka")
    nodes = make_nodes(ExtractionFake({}), ResearchFake([]), model)
    nodes._extraction_llm = AttributionFake()
    output = await nodes.validate_company_page_attribution(
        {
            "research_companies": [company],
            "active_company_ids": [company.id],
            "company_web_pages": {company.id: [page]},
        }
    )  # type: ignore[arg-type]
    assert output["attributable_company_web_pages"][company.id] == []
