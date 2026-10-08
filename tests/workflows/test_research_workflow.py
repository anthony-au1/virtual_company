"""Tests for staged company discovery."""

from __future__ import annotations

import asyncio
import json
import re
from contextlib import nullcontext
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from virtual_company.config import Settings
from virtual_company.db.models import Campaign
from virtual_company.domain.qualification import (
    CompanyQualification,
    CompanyQualificationStatus,
    CriterionQualification,
    QualificationStatus,
)
from virtual_company.repositories.dtos import EvidenceCreate
from virtual_company.research.models import (
    CategoricalEvidenceFact,
    DiscoveredCompany,
    EmployeeCountEvidenceFact,
    EvidenceCriterion,
    ExtractedEvidence,
    ExtractedEvidenceItems,
    QualificationFacts,
    QualificationFactsCacheEntry,
    QualificationFactsCacheStatus,
    SearchResult,
    WebPage,
)
from virtual_company.services.research import ResearchService
from virtual_company.tools.web_fetch import (
    WebFetchHttpError,
    WebFetchTimeoutError,
)
from virtual_company.workflows.research.graph import (
    ResearchWorkflow,
    _research_run_stop_reason,
    route_candidate_pool,
)
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
        self.company_ids: dict[str, UUID] = {}
        self.persist_company_calls: list[list[str]] = []
        self.qualifications: dict = {}
        self.evidence: list[SimpleNamespace] = []

    async def create_run(self, campaign_id: UUID) -> SimpleNamespace:
        run = SimpleNamespace(id=uuid4(), campaign_id=campaign_id, status="RUNNING")
        self.runs[run.id] = run
        return run

    async def persist_companies(
        self, *, campaign_id: UUID, companies: list[DiscoveredCompany]
    ) -> SimpleNamespace:
        self.persist_company_calls.append([company.name for company in companies])
        created = 0
        for company in companies:
            if company.name not in self.company_ids:
                self.company_ids[company.name] = uuid4()
                self.targets.append(company.name)
                created += 1
        persisted = [
            SimpleNamespace(
                id=self.company_ids[c.name],
                name=c.name,
                website=c.website,
                domain=c.domain,
            )
            for c in companies
        ]
        return SimpleNamespace(
            companies_found=created,
            companies=persisted,
            discovered_by_company_id={
                company.id: discovered
                for company, discovered in zip(persisted, companies, strict=True)
            },
        )

    async def persist_company_qualifications(
        self, *, campaign_id: UUID, research_run_id: UUID, qualifications: list
    ) -> None:
        for result in qualifications:
            self.qualifications[(research_run_id, result.company_id)] = result

    async def complete_run(self, run_id: UUID, companies_found: int) -> None:
        self.runs[run_id].status = "COMPLETED"

    async def persist_evidence(
        self, *, research_run_id: UUID, evidence: list[object]
    ) -> SimpleNamespace:
        created_by_company: dict[UUID, int] = {}
        for item in evidence:
            stored = SimpleNamespace(id=uuid4(), **item.model_dump())
            self.evidence.append(stored)
            created_by_company[item.company_id] = (
                created_by_company.get(item.company_id, 0) + 1
            )
        return SimpleNamespace(
            created_count=len(evidence),
            skipped_count=0,
            created_by_company=created_by_company,
        )

    async def list_evidence_for_run(self, run_id: UUID) -> list[SimpleNamespace]:
        return [item for item in self.evidence if item.research_run_id == run_id]

    async def list_evidence_for_company(
        self, company_id: UUID
    ) -> list[SimpleNamespace]:
        return [item for item in self.evidence if item.company_id == company_id]

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


class FetchSequenceFake:
    def __init__(self, values: dict[str, list[WebPage | Exception]]) -> None:
        self.values = {url: list(items) for url, items in values.items()}
        self.calls: list[str] = []

    async def fetch(self, url: str) -> WebPage:
        self.calls.append(url)
        value = self.values[url].pop(0)
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
            return CompanyPageAttribution(
                attributable=True, reason="The page concerns the company."
            )
        if model is ExtractedEvidenceItems:
            return ExtractedEvidenceItems(evidence=[])
        if model is QualificationFacts:
            return qualification_facts_from_prompt(prompt)
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


def qualification_facts_from_prompt(prompt: str) -> QualificationFacts:
    payload = json.loads(prompt)
    evidence_items = payload["evidence"]
    categorical: list[CategoricalEvidenceFact] = []
    for configured in payload["categorical_criteria"]:
        matches = []
        for item in evidence_items:
            if item["criterion"] != configured["criterion"]:
                continue
            if configured["criterion"] == "technology":
                actual = " ".join((item["subject"] or "").casefold().split())
                expected = " ".join((configured["subject"] or "").casefold().split())
                if actual != expected and not (
                    actual == "spring boot" and expected == "spring"
                ):
                    continue
            matches.append(item["id"])
        if matches:
            categorical.append(
                CategoricalEvidenceFact(
                    criterion_id=configured["criterion_id"],
                    state="supported",
                    evidence_ids=matches,
                )
            )
    counts: list[EmployeeCountEvidenceFact] = []
    for item in evidence_items:
        if item["criterion"] != "company_size":
            continue
        text = f"{item['claim']} {item['evidence_text']}"
        match = re.search(r"(?<!\d)(\d{1,3}(?:,\d{3})+|\d+)(?!\d)", text)
        if match:
            value = int(match.group(1).replace(",", ""))
            relation = "exact"
            if "approximately" in text.casefold() or "close to" in text.casefold():
                relation = "approximately"
            elif "more than" in text.casefold() or "over " in text.casefold():
                relation = "greater_than"
            counts.append(
                EmployeeCountEvidenceFact(
                    value=value,
                    relation=relation,
                    evidence_ids=[item["id"]],
                )
            )
    return QualificationFacts(categorical=categorical, employee_counts=counts)


class ResearchFake:
    def __init__(
        self,
        ranked: list[DiscoveredCompany],
        *,
        company_queries: list[str] | None = None,
    ) -> None:
        self.ranked = ranked
        self.company_queries = company_queries or ["company evidence"]
        self.prompts: list[str] = []
        self.models: list[type[object]] = []

    async def generate_structured(self, **kwargs: object) -> object:
        self.prompts.append(str(kwargs["user_prompt"]))
        model = kwargs["response_model"]
        self.models.append(model)
        if model is GeneratedSearchQueries:
            return GeneratedSearchQueries(queries=["Australian fintech companies"])
        if model is GeneratedCompanySearchQueries:
            return GeneratedCompanySearchQueries(queries=self.company_queries)
        return DiscoveredCompanies(companies=self.ranked)


class ObservabilityFake:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def context(self, **_: object):
        return nullcontext()

    def span(self, *_: object, **__: object):
        return nullcontext()

    def event(self, name: str, **context: object) -> None:
        self.events.append((name, context))

    def record(self, *_: object, **__: object) -> None:
        pass


def campaign() -> Campaign:
    return Campaign(
        id=uuid4(),
        name="Australian fintech",
        description=None,
        target_market="Australia",
        industry="Fintech",
        technologies=["Java", "Spring Boot", "Kafka"],
        company_size=None,
        target_count=3,
        max_companies_to_research=15,
        status="DRAFT",
    )


def found(name: str, urls: list[str]) -> DiscoveredCompany:
    return DiscoveredCompany(
        name=name, discovery_reason="Relevant supplied evidence.", supporting_urls=urls
    )


def make_nodes(
    extraction: ExtractionFake,
    research: ResearchFake,
    model: Campaign,
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


@pytest.mark.asyncio
async def test_search_result_caps_fairly_retain_later_query_groups() -> None:
    queries = [f"query {index}" for index in range(5)]
    groups = {
        query: [SearchResult(title=query, url=f"https://source-{index}.example/page")]
        for index, query in enumerate(queries)
    }

    class QuerySearchFake:
        async def search(self, query: str, limit: int = 10) -> list[SearchResult]:
            return groups[query]

    model = campaign()
    company = ResearchCompany(id=uuid4(), name="Acme")
    nodes = ResearchNodes(
        campaigns=CampaignServiceFake(model),
        research=ResearchServiceFake(),
        research_llm=ResearchFake([]),
        extraction_llm=ExtractionFake({}),
        web_search=QuerySearchFake(),  # type: ignore[arg-type]
        web_fetch=FetchFake({}),
        web_search_max_total_results=5,
        company_research_max_results_per_company=5,
    )
    discovery = await nodes.search_web({"queries": queries})  # type: ignore[arg-type]
    assert [item.title for item in discovery["search_results"]] == queries

    company_results = await nodes.search_company_sources(
        {
            "research_companies": [company],
            "active_company_ids": [company.id],
            "company_research_queries": {company.id: queries},
            "investigations": {
                company.id: CompanyInvestigationState(company_id=company.id)
            },
        }
    )  # type: ignore[arg-type]
    assert [
        item.title for item in company_results["company_search_results"][company.id]
    ] == queries


def test_fair_result_merge_deduplicates_overlapping_urls() -> None:
    groups = [
        [
            SearchResult(title="A", url="https://example.com/a"),
            SearchResult(title="B", url="https://example.com/b"),
        ],
        [
            SearchResult(title="A duplicate", url="https://example.com/a"),
            SearchResult(title="C", url="https://example.com/c"),
        ],
        [
            SearchResult(title="D", url="https://example.com/d"),
            SearchResult(title="E", url="https://example.com/e"),
        ],
    ]
    results, contributions = ResearchNodes._fair_merge_search_results(
        groups, 4, lambda value: value
    )
    assert [item.title for item in results] == ["A", "C", "D", "B"]
    assert len({item.url for item in results}) == len(results)
    assert contributions == [2, 1, 1]


@pytest.mark.asyncio
async def test_source_selection_reserves_available_sources_for_unknown_criteria() -> None:
    model = campaign()
    model.target_market = None
    model.industry = None
    model.technologies = ["Java", "Spring Boot", ]
    company = ResearchCompany(id=uuid4(), name="Acme", domain="acme.example")
    nodes = make_nodes(ExtractionFake({}), ResearchFake([]), model)
    nodes._company_research_followup_max_fetches_per_company = 2
    output = await nodes.select_company_sources(
        {
            "research_companies": [company],
            "active_company_ids": [company.id],
            "adaptive_mode": True,
            "company_search_results": {
                company.id: [
                    SearchResult(
                        title="Engineering careers technology",
                        url="https://acme.example/careers/engineering/technology",
                    ),
                    SearchResult(
                        title="Java systems",
                        snippet="Java services are used by Acme",
                        url="https://third-party.example/acme-java",
                    ),
                    SearchResult(
                        title="Spring Boot architecture",
                        snippet="Acme uses Spring Boot",
                        url="https://third-party.example/acme-spring",
                    ),
                ]
            },
            "criterion_qualifications": {
                company.id: [
                    CriterionQualification(
                        "technology", subject,
                        QualificationStatus.UNKNOWN, [], "Missing"
                    )
                    for subject in ("Java", "Spring Boot")
                ]
            },
            "investigations": {
                company.id: CompanyInvestigationState(company_id=company.id)
            },
        }
    )  # type: ignore[arg-type]
    urls = {
        item.url
        for item in output["selected_company_sources"][company.id]
    }
    assert "https://third-party.example/acme-java" in urls
    assert "https://third-party.example/acme-spring" in urls


def test_staged_prompt_semantics() -> None:
    extraction, ranking = (
        extract_company_candidates_system_prompt().lower(),
        rank_company_candidates_system_prompt().lower(),
    )
    assert (
        EXTRACT_COMPANY_CANDIDATES_PROMPT.version == "v1"
        and RANK_COMPANY_CANDIDATES_PROMPT.version == "v4"
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
        and "at most the supplied discovery candidate limit" in ranking
        and "target_count" in ranking
        and "discovery candidate limit controls that number exclusively" in ranking
        and "exactly the discovery candidate limit" in ranking
        and "prioritization, not qualification" in ranking
        and "absence of evidence is unknown" in ranking
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
async def test_ranking_bounds_pool_preserves_order_and_validates_urls() -> None:
    model = campaign()
    aggregate = [
        AggregatedCompanyCandidate(
            name=f"Candidate {i}",
            mention_count=1,
            supporting_urls=[f"https://{i}.example"],
            supporting_results=[SearchResult(title=str(i), url=f"https://{i}.example")],
        )
        for i in range(50)
    ]
    research = ResearchFake(
        [
            found(f"Candidate {i}", [f"https://{i}.example", "https://wrong.example"])
            for i in range(50)
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
    assert len(output["discovered_companies"]) == 15
    assert [item.name for item in output["discovered_companies"]] == [
        f"Candidate {i}" for i in range(15)
    ]
    assert output["discovered_companies"][0].supporting_urls == ["https://0.example"]
    assert (
        "Aggregated company candidates" in research.prompts[0]
        and "Discovery candidate limit: 15" in research.prompts[0]
        and "Search results:" not in research.prompts[0]
    )


def test_ranked_validation_preserves_airwallex_selected_representation() -> None:
    candidates = [
        AggregatedCompanyCandidate(
            name="Airwallex Pty Ltd",
            mention_count=1,
            supporting_urls=[
                "https://imarc.example/airwallex",
                "https://builtin.example/melbourne/airwallex",
                "https://mordor.example/airwallex",
            ],
        ),
        AggregatedCompanyCandidate(
            name="Airwallex",
            domain="airwallex.com",
            mention_count=1,
            supporting_urls=["https://ieu.example/article/airwallex"],
        ),
    ]
    chosen_urls = candidates[0].supporting_urls

    validated = ResearchNodes._validated_ranked_companies(
        [found("Airwallex Pty Ltd", chosen_urls)], candidates, 2
    )

    assert len(validated) == 1
    assert validated[0].name == "Airwallex Pty Ltd"
    assert validated[0].supporting_urls == chosen_urls
    assert "https://ieu.example/article/airwallex" not in validated[0].supporting_urls


def test_ranked_validation_prefers_exact_name_for_normalized_collision() -> None:
    candidates = [
        AggregatedCompanyCandidate(
            name="Foo Pty Ltd",
            mention_count=1,
            supporting_urls=["https://pty.example"],
        ),
        AggregatedCompanyCandidate(
            name="Foo",
            mention_count=1,
            supporting_urls=["https://plain.example"],
        ),
    ]

    validated = ResearchNodes._validated_ranked_companies(
        [found("Foo Pty Ltd", ["https://pty.example"])], candidates, 2
    )

    assert [item.supporting_urls for item in validated] == [["https://pty.example"]]


def test_ranked_validation_keeps_unique_normalized_name_fallback() -> None:
    candidate = AggregatedCompanyCandidate(
        name="Foo Pty Ltd",
        mention_count=1,
        supporting_urls=["https://foo.example"],
    )

    validated = ResearchNodes._validated_ranked_companies(
        [found("FOO", ["https://foo.example"])], [candidate], 1
    )

    assert len(validated) == 1
    assert validated[0].name == "Foo Pty Ltd"
    assert validated[0].supporting_urls == ["https://foo.example"]


def test_ranked_validation_skips_ambiguous_normalized_collision() -> None:
    candidates = [
        AggregatedCompanyCandidate(
            name="Foo Pty Ltd",
            mention_count=1,
            supporting_urls=["https://pty.example"],
        ),
        AggregatedCompanyCandidate(
            name="Foo",
            mention_count=1,
            supporting_urls=["https://plain.example"],
        ),
    ]

    validated = ResearchNodes._validated_ranked_companies(
        [found("FOO LTD", ["https://unknown.example"])], candidates, 2
    )

    assert validated == []


def test_ranked_validation_rejects_url_outside_candidate_provenance() -> None:
    candidate = AggregatedCompanyCandidate(
        name="Foo",
        mention_count=1,
        supporting_urls=["https://foo.example"],
    )

    validated = ResearchNodes._validated_ranked_companies(
        [found("Foo", ["https://invented.example"])], [candidate], 1
    )

    assert len(validated) == 1
    assert validated[0].supporting_urls == []


@pytest.mark.asyncio
async def test_validated_airwallex_sources_reach_discovery_source_reuse() -> None:
    model = campaign()
    candidates = [
        AggregatedCompanyCandidate(
            name="Airwallex Pty Ltd",
            mention_count=1,
            supporting_urls=["https://imarc.example/airwallex"],
            supporting_results=[
                SearchResult(
                    title="IMARC Airwallex profile",
                    url="https://imarc.example/airwallex",
                )
            ],
        ),
        AggregatedCompanyCandidate(
            name="Airwallex",
            domain="airwallex.com",
            mention_count=1,
            supporting_urls=["https://ieu.example/article/airwallex"],
            supporting_results=[
                SearchResult(
                    title="IE University article",
                    url="https://ieu.example/article/airwallex",
                )
            ],
        ),
    ]
    validated = ResearchNodes._validated_ranked_companies(
        [found("Airwallex Pty Ltd", ["https://imarc.example/airwallex"])],
        candidates,
        2,
    )
    company = ResearchCompany(id=uuid4(), name="Airwallex Pty Ltd")
    nodes = make_nodes(ExtractionFake({}), ResearchFake([]), model)

    reused = await nodes.reuse_discovery_sources(
        {
            "research_companies": [company],
            "active_company_ids": [company.id],
            "discovered_companies_by_id": {company.id: validated[0]},
            "aggregated_company_candidates": candidates,
        }
    )  # type: ignore[arg-type]

    assert [item.url for item in reused["company_search_results"][company.id]] == [
        "https://imarc.example/airwallex"
    ]


@pytest.mark.parametrize(
    ("aggregated_count", "expected_ranked_count", "expected_activation_count"),
    [(20, 10, 5), (7, 7, 5), (3, 3, 3)],
)
@pytest.mark.asyncio
async def test_ranked_pool_limit_is_separate_from_initial_activation(
    aggregated_count: int,
    expected_ranked_count: int,
    expected_activation_count: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import virtual_company.workflows.research.nodes as research_nodes_module

    model = campaign()
    model.target_count = 5
    model.max_companies_to_research = 10
    observability = ObservabilityFake()
    monkeypatch.setattr(
        research_nodes_module, "get_observability", lambda: observability
    )
    aggregate = [
        AggregatedCompanyCandidate(
            name=f"Candidate {index}",
            mention_count=1,
            supporting_urls=[f"https://{index}.example"],
            supporting_results=[
                SearchResult(title=str(index), url=f"https://{index}.example")
            ],
        )
        for index in range(aggregated_count)
    ]
    research = ResearchFake(
        [
            found(candidate.name, candidate.supporting_urls)
            for candidate in aggregate
        ]
    )
    nodes = make_nodes(
        ExtractionFake({}), research, model
    )

    ranking = await nodes.rank_company_candidates(
        {
            "campaign": CampaignCriteria.model_validate(model),
            "aggregated_company_candidates": aggregate,
        }
    )  # type: ignore[arg-type]
    ranked = ranking["discovered_companies"]

    assert len(ranked) == expected_ranked_count
    assert f"Discovery candidate limit: {min(aggregated_count, 10)}" in research.prompts[0]

    state = {
        "campaign_id": model.id,
        "campaign": CampaignCriteria.model_validate(model),
        "discovered_companies": ranked,
        "companies_found": 0,
        "research_companies": [],
        "discovered_companies_by_id": {},
        "investigations": {},
        "company_qualifications": {},
    }
    state.update(await nodes.persist_companies(state))  # type: ignore[arg-type]

    assert len(state["research_companies"]) == expected_activation_count
    assert len(nodes._pending_ranked_companies(state)) == (
        expected_ranked_count - expected_activation_count
    )
    assert len(state["discovered_companies"]) == expected_ranked_count
    activation_event = next(
        context
        for name, context in observability.events
        if name == "company_candidates_activated"
    )
    assert activation_event["ranked_pool_count"] == expected_ranked_count
    assert activation_event["initial_activation_count"] == expected_activation_count
    assert activation_event["remaining_candidate_count"] == (
        expected_ranked_count - expected_activation_count
    )


@pytest.mark.asyncio
async def test_short_ranking_response_is_distinguishable_in_observability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import virtual_company.workflows.research.nodes as research_nodes_module

    model = campaign()
    model.target_count = 5
    model.max_companies_to_research = 10
    aggregate = [
        AggregatedCompanyCandidate(
            name=f"Candidate {index}",
            mention_count=1,
            supporting_urls=[f"https://{index}.example"],
            supporting_results=[
                SearchResult(title=str(index), url=f"https://{index}.example")
            ],
        )
        for index in range(20)
    ]
    observability = ObservabilityFake()
    monkeypatch.setattr(
        research_nodes_module, "get_observability", lambda: observability
    )
    research = ResearchFake(
        [
            found(candidate.name, candidate.supporting_urls)
            for candidate in aggregate[:5]
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

    ranked_event = next(
        context
        for name, context in observability.events
        if name == "company_candidates_ranked"
    )
    assert len(output["discovered_companies"]) == 5
    assert ranked_event["aggregated_candidate_count"] == 20
    assert ranked_event["candidate_pool_limit"] == 10
    assert ranked_event["target_count"] == 5
    assert ranked_event["llm_returned_candidate_count"] == 5
    assert ranked_event["ranked_pool_count"] == 5


@pytest.mark.asyncio
async def test_workflow_refills_ranked_companies_without_reranking() -> None:
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
    assert service.persist_company_calls == [
        [f"Candidate {i}" for i in range(3)],
        [f"Candidate {i}" for i in range(3, 6)],
        [f"Candidate {i}" for i in range(6, 9)],
    ]
    assert research.models.count(DiscoveredCompanies) == 1
    assert research.models.count(GeneratedCompanySearchQueries) == 0
    assert len(workflow._nodes._web_fetch.calls) == 9
    assert workflow._nodes._web_fetch.calls == [
        f"https://source-{i}.example" for i in range(9)
    ]


@pytest.mark.asyncio
async def test_workflow_completes_after_investigating_a_small_ranked_pool() -> None:
    model = campaign()
    model.target_count = 5
    results = [
        SearchResult(title=f"Candidate {i}", url=f"https://source-{i}.example")
        for i in range(3)
    ]
    service = ResearchServiceFake()
    research = ResearchFake(
        [found(result.title, [result.url]) for result in results]
    )
    workflow = ResearchWorkflow(
        campaigns=CampaignServiceFake(model),
        research=service,
        research_llm=research,
        extraction_llm=ExtractionFake(
            {
                result.url: [ExtractedCompanyIdentity(name=result.title)]
                for result in results
            }
        ),
        web_search=SearchFake(results),
        web_fetch=FetchFake({}),
        settings=Settings(
            company_research_max_investigation_rounds=0,
        ),
    )

    outcome = await workflow.run(model.id)

    assert outcome.status == "COMPLETED"
    assert service.targets == [f"Candidate {i}" for i in range(3)]
    assert service.persist_company_calls == [
        [f"Candidate {i}" for i in range(3)]
    ]
    assert research.models.count(DiscoveredCompanies) == 1
    assert len(service.qualifications) == 3


@pytest.mark.asyncio
async def test_activation_refills_only_the_qualification_shortfall() -> None:
    model = campaign()
    model.target_count = 5
    nodes = make_nodes(ExtractionFake({}), ResearchFake([]), model)
    ranked = [found(f"Candidate {i}", []) for i in range(1, 16)]
    state = {
        "campaign_id": model.id,
        "campaign": CampaignCriteria.model_validate(model),
        "discovered_companies": ranked,
        "companies_found": 0,
        "research_companies": [],
        "discovered_companies_by_id": {},
        "investigations": {},
        "company_qualifications": {},
    }

    state.update(await nodes.persist_companies(state))  # type: ignore[arg-type]
    assert [company.name for company in state["research_companies"]] == [
        f"Candidate {i}" for i in range(1, 6)
    ]
    assert len(state["active_company_ids"]) == 5

    first_ids = [company.id for company in state["research_companies"]]
    state["company_qualifications"] = {
        company_id: CompanyQualification(
            company_id=company_id,
            status=(
                CompanyQualificationStatus.QUALIFIED
                if index < 2
                else CompanyQualificationStatus.INSUFFICIENT_EVIDENCE
            ),
            criteria=[],
        )
        for index, company_id in enumerate(first_ids)
    }
    state.update(await nodes.persist_companies(state))  # type: ignore[arg-type]
    assert [company.name for company in state["research_companies"][-3:]] == [
        "Candidate 6",
        "Candidate 7",
        "Candidate 8",
    ]
    assert len(state["active_company_ids"]) == 3

    refill_ids = [company.id for company in state["research_companies"][-3:]]
    state["company_qualifications"].update(
        {
            refill_ids[0]: CompanyQualification(
                refill_ids[0], CompanyQualificationStatus.QUALIFIED, []
            ),
            refill_ids[1]: CompanyQualification(
                refill_ids[1], CompanyQualificationStatus.QUALIFIED, []
            ),
            refill_ids[2]: CompanyQualification(
                refill_ids[2],
                CompanyQualificationStatus.INSUFFICIENT_EVIDENCE,
                [],
            ),
        }
    )
    state.update(await nodes.persist_companies(state))  # type: ignore[arg-type]
    assert [
        company.name
        for company in state["research_companies"]
        if company.id in state["active_company_ids"]
    ] == ["Candidate 9"]
    assert len({company.id for company in state["research_companies"]}) == 9
    assert nodes._research.persist_company_calls == [
        [f"Candidate {i}" for i in range(1, 6)],
        ["Candidate 6", "Candidate 7", "Candidate 8"],
        ["Candidate 9"],
    ]

    candidate_nine_id = state["active_company_ids"][0]
    state["company_qualifications"][candidate_nine_id] = CompanyQualification(
        candidate_nine_id, CompanyQualificationStatus.QUALIFIED, []
    )
    assert route_candidate_pool(state) == "complete"  # type: ignore[arg-type]


async def _run_activation_scenario(
    model: Campaign,
    candidate_names: list[str],
    statuses: dict[str, CompanyQualificationStatus],
) -> dict[str, object]:
    nodes = make_nodes(
        ExtractionFake({}),
        ResearchFake([found(name, []) for name in candidate_names]),
        model,
    )
    state: dict[str, object] = {
        "campaign_id": model.id,
        "campaign": CampaignCriteria.model_validate(model),
        "discovered_companies": [found(name, []) for name in candidate_names],
        "companies_found": 0,
        "research_companies": [],
        "discovered_companies_by_id": {},
        "investigations": {},
        "company_qualifications": {},
    }
    for _ in range(len(candidate_names) + 1):
        previous_ids = {item.id for item in state["research_companies"]}  # type: ignore[union-attr]
        state.update(await nodes.persist_companies(state))  # type: ignore[arg-type]
        for company in state["research_companies"]:  # type: ignore[union-attr]
            if company.id not in previous_ids:
                state["company_qualifications"][company.id] = CompanyQualification(  # type: ignore[index]
                    company.id, statuses[company.name], []
                )
        if route_candidate_pool(state) == "complete":  # type: ignore[arg-type]
            break
    else:
        raise AssertionError("Candidate activation did not reach a stop condition")
    return state


@pytest.mark.asyncio
async def test_candidate_activation_stops_after_target_with_no_extra_company() -> None:
    model = campaign()
    model.target_count = 2
    model.max_companies_to_research = 10
    state = await _run_activation_scenario(
        model,
        ["A", "B", "C", "D"],
        {
            "A": CompanyQualificationStatus.QUALIFIED,
            "B": CompanyQualificationStatus.INSUFFICIENT_EVIDENCE,
            "C": CompanyQualificationStatus.QUALIFIED,
            "D": CompanyQualificationStatus.INSUFFICIENT_EVIDENCE,
        },
    )

    assert [company.name for company in state["research_companies"]] == [
        "A",
        "B",
        "C",
    ]
    assert sum(
        result.status is CompanyQualificationStatus.QUALIFIED
        for result in state["company_qualifications"].values()
    ) == 2


@pytest.mark.asyncio
async def test_candidate_activation_stops_at_campaign_research_limit() -> None:
    model = campaign()
    model.target_count = 5
    model.max_companies_to_research = 3
    names = ["A", "B", "C", "D"]
    state = await _run_activation_scenario(
        model,
        names,
        {
            "A": CompanyQualificationStatus.QUALIFIED,
            "B": CompanyQualificationStatus.NOT_QUALIFIED,
            "C": CompanyQualificationStatus.INSUFFICIENT_EVIDENCE,
            "D": CompanyQualificationStatus.QUALIFIED,
        },
    )

    assert [company.name for company in state["research_companies"]] == names[:3]
    assert len(state["company_qualifications"]) == 3
    assert sum(
        result.status is CompanyQualificationStatus.QUALIFIED
        for result in state["company_qualifications"].values()
    ) == 1


@pytest.mark.asyncio
async def test_all_researched_results_remain_when_target_is_difficult() -> None:
    model = campaign()
    model.target_count = 5
    model.max_companies_to_research = 10
    names = [f"Candidate {index}" for index in range(10)]
    state = await _run_activation_scenario(
        model,
        names,
        {
            name: (
                CompanyQualificationStatus.QUALIFIED
                if index == 0
                else CompanyQualificationStatus.NOT_QUALIFIED
            )
            for index, name in enumerate(names)
        },
    )

    assert len(state["research_companies"]) == 10
    assert len(state["company_qualifications"]) == 10
    assert sum(
        result.status is CompanyQualificationStatus.QUALIFIED
        for result in state["company_qualifications"].values()
    ) == 1
    assert sum(
        result.status is CompanyQualificationStatus.NOT_QUALIFIED
        for result in state["company_qualifications"].values()
    ) == 9


def test_candidate_pool_route_completes_when_exhausted_below_target() -> None:
    model = campaign()
    model.target_count = 5
    ranked = [found(f"Candidate {i}", []) for i in range(1, 4)]
    ids = [uuid4() for _ in ranked]
    state = {
        "campaign": CampaignCriteria.model_validate(model),
        "discovered_companies": ranked,
        "discovered_companies_by_id": dict(zip(ids, ranked, strict=True)),
        "company_qualifications": {
            company_id: CompanyQualification(
                company_id,
                (
                    CompanyQualificationStatus.QUALIFIED
                    if index == 0
                    else CompanyQualificationStatus.INSUFFICIENT_EVIDENCE
                ),
                [],
            )
            for index, company_id in enumerate(ids)
        },
    }
    assert route_candidate_pool(state) == "complete"  # type: ignore[arg-type]


def test_candidate_pool_route_stops_at_campaign_research_limit() -> None:
    model = campaign()
    model.target_count = 5
    model.max_companies_to_research = 5
    ids = [uuid4() for _ in range(5)]
    state = {
        "campaign": CampaignCriteria.model_validate(model),
        "research_companies": [ResearchCompany(id=id_, name=f"Company {index}") for index, id_ in enumerate(ids)],
        "company_qualifications": {
            ids[0]: CompanyQualification(
                ids[0], CompanyQualificationStatus.QUALIFIED, []
            )
        },
        "discovered_companies": [found("Still ranked", [])],
    }

    assert route_candidate_pool(state) == "complete"  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("qualified", "researched", "expected"),
    [
        (2, 3, "TARGET_REACHED"),
        (1, 3, "RESEARCH_LIMIT_REACHED"),
        (1, 2, "CANDIDATE_POOL_EXHAUSTED"),
    ],
)
def test_research_run_stop_reason_distinguishes_campaign_stops(
    qualified: int, researched: int, expected: str
) -> None:
    assert (
        _research_run_stop_reason(
            qualified_count=qualified,
            companies_researched=researched,
            target_count=2,
            max_companies_to_research=3,
        )
        == expected
    )


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
    company = ResearchCompany(
        id=uuid4(), name="Acme", website=None, domain="acme.example"
    )
    sources = [
        SearchResult(
            title="Profile",
            url="https://directory.example/acme",
            snippet="Company profile",
        ),
        SearchResult(title="Acme", url="https://acme.example/", snippet=None),
        SearchResult(
            title="Backend jobs",
            url="https://acme.example/careers/backend",
            snippet="Java",
        ),
        SearchResult(
            title="Duplicate",
            url="https://acme.example/careers/backend?utm_source=search",
        ),
        SearchResult(
            title="Engineering",
            url="https://acme.example/blog/engineering",
            snippet="Platform",
        ),
        SearchResult(
            title="Independent", url="https://news.example/acme", snippet="Funding"
        ),
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
async def test_discovery_sources_are_reused_by_company_identity_not_position() -> None:
    model = campaign()
    first = found("Afterpay Limited", ["https://source.example/afterpay"])
    second = found("Perpetual", ["https://source.example/perpetual"])
    afterpay = ResearchCompany(id=uuid4(), name="Afterpay Limited")
    perpetual = ResearchCompany(id=uuid4(), name="Perpetual")
    aggregates = [
        AggregatedCompanyCandidate(
            name=company.name,
            mention_count=1,
            supporting_urls=discovered.supporting_urls,
            supporting_results=[
                SearchResult(title=company.name, url=discovered.supporting_urls[0])
            ],
        )
        for company, discovered in ((afterpay, first), (perpetual, second))
    ]
    nodes = make_nodes(ExtractionFake({}), ResearchFake([]), model)
    output = await nodes.reuse_discovery_sources(
        {
            "research_companies": [perpetual, afterpay],
            "active_company_ids": [afterpay.id],
            "discovered_companies_by_id": {
                afterpay.id: first,
                perpetual.id: second,
            },
            "aggregated_company_candidates": aggregates,
        }
    )  # type: ignore[arg-type]
    assert list(output["company_search_results"]) == [afterpay.id]
    assert output["company_search_results"][afterpay.id][0].url.endswith("afterpay")


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
            "https://a.example/two": WebFetchTimeoutError("timeout"),
            "https://b.example": WebPage(url="https://b.example", content="B"),
        }
    )
    nodes = make_nodes(ExtractionFake({}), ResearchFake([]), model)
    nodes._web_fetch = fetch
    output = await nodes.fetch_company_sources(
        {
            "research_companies": [company_a, company_b],
            "selected_company_sources": sources,
        }
    )  # type: ignore[arg-type]
    assert [page.content for page in output["company_web_pages"][company_a.id]] == ["A"]
    assert [page.content for page in output["company_web_pages"][company_b.id]] == ["B"]
    assert fetch.calls == [
        "https://a.example/one",
        "https://a.example/two",
        "https://b.example",
    ]


@pytest.mark.asyncio
async def test_evidence_extraction_validates_provenance_whitespace_and_duplicates() -> (
    None
):
    model = campaign()
    company = ResearchCompany(
        id=uuid4(), name="Acme", website=None, domain="acme.example"
    )
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
    assert (
        '"technologies":["Java","Spring Boot","Kafka"]'
        in fake.prompts[0]
    )


@pytest.mark.asyncio
async def test_evidence_extraction_rejects_absent_excerpt_and_continues_after_failure() -> (
    None
):
    model = campaign()
    company = ResearchCompany(
        id=uuid4(), name="Acme", website=None, domain="acme.example"
    )
    valid_page = WebPage(
        url="https://acme.example/one", content="We use Java for backend services."
    )
    failed_page = WebPage(url="https://acme.example/two", content="Unused")
    invalid = ExtractedEvidence(
        criterion=EvidenceCriterion.TECHNOLOGY,
        subject="Kafka",
        claim="Acme uses Kafka.",
        evidence_text="Our platform is built with Java and Kafka.",
    )
    fake = EvidenceExtractionFake(
        {valid_page.url: [invalid], failed_page.url: RuntimeError("timeout")}
    )
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
async def test_evidence_extraction_preserves_explicit_size_and_geography_precision() -> (
    None
):
    model = campaign()
    model.company_size = {
        "min": 100,
        "max": 500,
    }
    company = ResearchCompany(
        id=uuid4(), name="Acme", website=None, domain="acme.example"
    )
    page = WebPage(
        url="https://acme.example/careers",
        content=(
            "Join our Melbourne engineering team. The Java platform supports it. "
            "Acme is a fintech company. "
            "Our global team has more than 300 employees."
        ),
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
                    criterion=EvidenceCriterion.INDUSTRY,
                    subject="Fintech",
                    claim="Acme is a fintech company.",
                    evidence_text="Acme is a fintech company.",
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
            "selected_company_sources": {
                company.id: [SearchResult(title="Careers", url=page.url)]
            },
        }
    )  # type: ignore[arg-type]
    assert [
        (item.criterion, item.subject) for item in output["validated_evidence"]
    ] == [
        (EvidenceCriterion.TARGET_MARKET, "Australia"),
        (EvidenceCriterion.INDUSTRY, "Fintech"),
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
    first = await service.persist_evidence(
        research_run_id=run_id, evidence=[item, item]
    )
    second = await service.persist_evidence(research_run_id=run_id, evidence=[item])
    assert (first.created_count, first.skipped_count) == (1, 1)
    assert (second.created_count, second.skipped_count) == (0, 1)
    assert repository.items == [item]


@pytest.mark.asyncio
async def test_evidence_persistence_collapses_same_statement_across_sources() -> None:
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
    company_id = uuid4()
    first = EvidenceCreate(
        company_id=company_id,
        research_run_id=run_id,
        criterion="technology",
        subject="Java",
        claim="Acme uses Java.",
        evidence_text="Strong proficiency in Java.",
        source_url="https://acme.example/jobs/one",
    )
    duplicate = first.model_copy(
        update={
            "claim": "Java is used at Acme.",
            "source_url": "https://acme.example/jobs/two",
        }
    )
    outcome = await service.persist_evidence(
        research_run_id=run_id, evidence=[first, duplicate]
    )
    assert (outcome.created_count, outcome.skipped_count) == (1, 1)
    assert repository.items == [first]


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
            "criterion_qualifications": {
                company.id: [
                    CriterionQualification(
                        "technology",
                        "Kafka",
                        QualificationStatus.UNKNOWN,
                        [],
                        "Missing",
                    )
                ]
            },
            "investigations": {
                company.id: CompanyInvestigationState(
                    company_id=company.id,
                    coverage=coverage,
                    attempted_queries=["Acme fintech careers"],
                    attempted_strategy_focuses=["careers and job evidence"],
                )
            },
        }
    )  # type: ignore[arg-type]
    prompt = research.prompts[-1]
    missing_section = prompt.split("Unresolved criteria:", 1)[1]
    assert "Kafka" in missing_section
    assert "Australia" not in missing_section
    assert "Acme fintech careers" in prompt
    assert "careers and job evidence" in prompt
    assert output["investigations"][company.id].round == 1


@pytest.mark.asyncio
async def test_followup_filters_duplicates_and_resolved_criteria() -> None:
    model = campaign()
    model.target_market = None
    model.industry = None
    model.technologies = ["Java", "Spring Boot", ]
    company = ResearchCompany(id=uuid4(), name="Acme", domain="acme.example")
    prior_query = "Acme Java engineering"
    research = ResearchFake(
        [],
        company_queries=[
            " ACME   java ENGINEERING ",
            "Acme Spring Boot careers",
            " acme spring boot   CAREERS ",
            "Acme Java developer jobs",
        ],
    )
    nodes = make_nodes(ExtractionFake({}), research, model)
    output = await nodes.generate_followup_queries(
        {
            "campaign": CampaignCriteria.model_validate(model),
            "research_companies": [company],
            "active_company_ids": [company.id],
            "criterion_qualifications": {
                company.id: [
                    CriterionQualification(
                        "technology",
                        "Java",
                        QualificationStatus.MATCH,
                        [uuid4()],
                        "Matched",
                    ),
                    CriterionQualification(
                        "technology",
                        "Spring Boot",
                        QualificationStatus.UNKNOWN,
                        [],
                        "Missing",
                    ),
                ]
            },
            "investigations": {
                company.id: CompanyInvestigationState(
                    company_id=company.id,
                    round=1,
                    attempted_queries=[prior_query],
                )
            },
        }
    )  # type: ignore[arg-type]
    prompt = research.prompts[-1]
    queries = output["company_research_queries"][company.id]
    assert queries == ["Acme Spring Boot careers"]
    assert prior_query in prompt
    assert "Java engineering" in prompt
    assert output["investigations"][company.id].alternative_strategy_attempted
    await nodes.search_company_sources(
        {
            "research_companies": [company],
            "active_company_ids": [company.id],
            "company_research_queries": output["company_research_queries"],
            "investigations": output["investigations"],
        }
    )  # type: ignore[arg-type]
    assert nodes._web_search.calls == [("Acme Spring Boot careers", 5)]


@pytest.mark.asyncio
async def test_unresolved_criteria_receive_query_coverage_when_queries_exist() -> None:
    model = campaign()
    model.target_market = None
    model.industry = None
    model.technologies = ["Java", "Spring Boot", ]
    company = ResearchCompany(id=uuid4(), name="Acme")
    research = ResearchFake(
        [],
        company_queries=[
            "Acme Java engineering",
            "Acme Spring Boot architecture",
            "Acme Java careers",
        ],
    )
    nodes = make_nodes(ExtractionFake({}), research, model)
    qualifications = [
        CriterionQualification(
            "technology", subject,
            QualificationStatus.UNKNOWN, [], "Missing"
        )
        for subject in ("Java", "Spring Boot")
    ]
    output = await nodes.generate_followup_queries(
        {
            "campaign": CampaignCriteria.model_validate(model),
            "research_companies": [company],
            "active_company_ids": [company.id],
            "criterion_qualifications": {company.id: qualifications},
            "investigations": {
                company.id: CompanyInvestigationState(company_id=company.id)
            },
        }
    )  # type: ignore[arg-type]
    queries = output["company_research_queries"][company.id]
    assert any("Java" in query for query in queries)
    assert any("Spring Boot" in query for query in queries)


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
    assert [item.url for item in output["selected_company_sources"][company.id]] == [
        new_url
    ]
    assert output["investigations"][company.id].attempted_urls == {old_url}
    nodes._web_fetch = FetchFake(
        {new_url: WebPage(url=new_url, content="Source examined")}
    )
    fetched = await nodes.fetch_company_sources(
        {
            "research_companies": [company],
            "active_company_ids": [company.id],
            "selected_company_sources": output["selected_company_sources"],
            "investigations": output["investigations"],
        }
    )  # type: ignore[arg-type]
    assert fetched["investigations"][company.id].attempted_urls == {old_url, new_url}
    repeated = await nodes.select_company_sources(
        {
            "research_companies": [company],
            "active_company_ids": [company.id],
            "adaptive_mode": True,
            "company_search_results": {company.id: [SearchResult(title="New", url=new_url)]},
            "investigations": fetched["investigations"],
        }
    )  # type: ignore[arg-type]
    assert repeated["selected_company_sources"][company.id] == []


@pytest.mark.asyncio
async def test_transient_fetch_failure_remains_available_for_one_later_retry() -> None:
    model = campaign()
    company = ResearchCompany(id=uuid4(), name="Acme", domain="acme.example")
    url = "https://acme.example/java"
    result = SearchResult(title="Java engineering", url=url)
    nodes = make_nodes(ExtractionFake({}), ResearchFake([]), model)
    nodes._web_fetch = FetchSequenceFake(
        {url: [WebFetchTimeoutError("timeout"), WebPage(url=url, content="Acme uses Java.")]}
    )
    investigation = CompanyInvestigationState(company_id=company.id)
    first_selection = await nodes.select_company_sources(
        {
            "research_companies": [company],
            "active_company_ids": [company.id],
            "company_search_results": {company.id: [result]},
            "investigations": {company.id: investigation},
        }
    )  # type: ignore[arg-type]
    assert first_selection["investigations"][company.id].attempted_urls == set()
    first_fetch = await nodes.fetch_company_sources(
        {
            "research_companies": [company],
            "active_company_ids": [company.id],
            "selected_company_sources": first_selection["selected_company_sources"],
            "investigations": first_selection["investigations"],
        }
    )  # type: ignore[arg-type]
    failed_state = first_fetch["investigations"][company.id]
    assert failed_state.transient_fetch_failures == {url: 1}
    assert url not in failed_state.attempted_urls

    second_selection = await nodes.select_company_sources(
        {
            "research_companies": [company],
            "active_company_ids": [company.id],
            "company_search_results": {company.id: [result]},
            "investigations": first_fetch["investigations"],
        }
    )  # type: ignore[arg-type]
    assert second_selection["selected_company_sources"][company.id] == [result]
    second_fetch = await nodes.fetch_company_sources(
        {
            "research_companies": [company],
            "active_company_ids": [company.id],
            "selected_company_sources": second_selection["selected_company_sources"],
            "investigations": second_selection["investigations"],
        }
    )  # type: ignore[arg-type]
    successful_state = second_fetch["investigations"][company.id]
    assert successful_state.transient_fetch_failures == {}
    assert url in successful_state.attempted_urls
    page = second_fetch["company_web_pages"][company.id][0]

    attributed = await nodes.validate_company_page_attribution(
        {
            "campaign": CampaignCriteria.model_validate(model),
            "research_companies": [company],
            "active_company_ids": [company.id],
            "company_web_pages": {company.id: [page]},
        }
    )  # type: ignore[arg-type]
    assert attributed["attributable_company_web_pages"][company.id] == [page]
    nodes._extraction_llm = EvidenceExtractionFake(
        {
            url: [
                ExtractedEvidence(
                    criterion=EvidenceCriterion.TECHNOLOGY,
                    subject="Java",
                    claim="Acme uses Java.",
                    evidence_text="Acme uses Java.",
                )
            ]
        }
    )
    extracted = await nodes.extract_company_evidence(
        {
            "campaign": CampaignCriteria.model_validate(model),
            "research_run_id": uuid4(),
            "research_companies": [company],
            "active_company_ids": [company.id],
            "company_web_pages": {company.id: [page]},
            "attributable_company_web_pages": attributed[
                "attributable_company_web_pages"
            ],
        }
    )  # type: ignore[arg-type]
    assert len(extracted["validated_evidence"]) == 1


@pytest.mark.asyncio
async def test_transient_fetch_retry_exhaustion_and_nonretryable_failure_are_terminal() -> None:
    model = campaign()
    company = ResearchCompany(id=uuid4(), name="Acme")
    url = "https://acme.example/page"
    result = SearchResult(title="Company page", url=url)
    nodes = make_nodes(ExtractionFake({}), ResearchFake([]), model)

    async def fetch_once(
        fetch: FetchSequenceFake,
        investigation: CompanyInvestigationState,
        source: SearchResult = result,
    ) -> CompanyInvestigationState:
        nodes._web_fetch = fetch
        return (
            await nodes.fetch_company_sources(
                {
                    "research_companies": [company],
                    "active_company_ids": [company.id],
                    "selected_company_sources": {company.id: [source]},
                    "investigations": {company.id: investigation},
                }
            )  # type: ignore[arg-type]
        )["investigations"][company.id]

    transient_fetch = FetchSequenceFake(
        {url: [WebFetchTimeoutError("first"), WebFetchTimeoutError("second")]}
    )
    first = await fetch_once(transient_fetch, CompanyInvestigationState(company_id=company.id))
    assert first.transient_fetch_failures[url] == 1
    second = await fetch_once(transient_fetch, first)
    assert url in second.attempted_urls
    assert second.transient_fetch_failures == {}
    assert len(transient_fetch.calls) == 2

    retry = await nodes.select_company_sources(
        {
            "research_companies": [company],
            "active_company_ids": [company.id],
            "company_search_results": {company.id: [result]},
            "investigations": {company.id: second},
        }
    )  # type: ignore[arg-type]
    assert retry["selected_company_sources"][company.id] == []

    missing_url = "https://acme.example/missing"
    missing = SearchResult(title="Missing", url=missing_url)
    permanent_fetch = FetchSequenceFake(
        {missing_url: [WebFetchHttpError(404)]}
    )
    permanent = await fetch_once(
        permanent_fetch,
        CompanyInvestigationState(company_id=company.id),
        missing,
    )
    assert missing_url in permanent.attempted_urls
    assert permanent.transient_fetch_failures == {}
    assert len(permanent_fetch.calls) == 1


def test_fact_cache_status_and_evidence_snapshot_control_freshness() -> None:
    evidence_id = uuid4()
    item = SimpleNamespace(id=evidence_id)
    retryable = QualificationFactsCacheEntry(
        evidence_ids=[evidence_id],
        facts=None,
        status=QualificationFactsCacheStatus.FAILED_RETRYABLE,
        attempt_count=1,
    )
    exhausted = QualificationFactsCacheEntry(
        evidence_ids=[evidence_id],
        facts=None,
        status=QualificationFactsCacheStatus.FAILED_EXHAUSTED,
        attempt_count=2,
    )
    semantic_unknown = QualificationFactsCacheEntry(
        evidence_ids=[evidence_id], facts=QualificationFacts()
    )
    assert ResearchNodes._facts_are_stale(retryable, [item])
    assert not ResearchNodes._facts_are_stale(exhausted, [item])
    assert not ResearchNodes._facts_are_stale(semantic_unknown, [item])
    assert ResearchNodes._facts_are_stale(exhausted, [SimpleNamespace(id=uuid4())])


@pytest.mark.asyncio
async def test_coverage_retries_failed_fact_extraction_but_caches_semantic_unknown() -> None:
    model = campaign()
    model.target_market = None
    model.industry = None
    model.technologies = ["Java", ]
    company = ResearchCompany(id=uuid4(), name="Acme")
    run_id = uuid4()
    item = SimpleNamespace(
        id=uuid4(),
        company_id=company.id,
        research_run_id=run_id,
        criterion="technology",
        subject="Java",
        claim="Uses Java.",
        evidence_text="Uses Java.",
    )
    service = ResearchServiceFake()
    service.evidence = [item]

    class FactProvider:
        def __init__(self) -> None:
            self.outputs: list[object] = [RuntimeError("temporary"), QualificationFacts()]
            self.calls = 0

        async def generate_structured(self, **_: object) -> object:
            self.calls += 1
            value = self.outputs.pop(0)
            if isinstance(value, Exception):
                raise value
            return value

    provider = FactProvider()
    nodes = ResearchNodes(
        campaigns=CampaignServiceFake(model),
        research=service,
        research_llm=provider,  # type: ignore[arg-type]
        extraction_llm=provider,  # type: ignore[arg-type]
        web_search=SearchFake([]),
        web_fetch=FetchFake({}),
        company_research_max_investigation_rounds=2,
    )
    state = {
        "campaign": CampaignCriteria.model_validate(model),
        "research_run_id": run_id,
        "research_companies": [company],
        "investigations": {
            company.id: CompanyInvestigationState(company_id=company.id)
        },
    }
    state.update(await nodes.check_evidence_coverage(state))  # type: ignore[arg-type]
    failed = state["qualification_facts"][company.id]
    assert failed.status is QualificationFactsCacheStatus.FAILED_RETRYABLE
    assert provider.calls == 1

    state.update(await nodes.check_evidence_coverage(state))  # type: ignore[arg-type]
    success = state["qualification_facts"][company.id]
    assert success.status is QualificationFactsCacheStatus.SUCCESS
    assert success.facts == QualificationFacts()
    assert state["criterion_qualifications"][company.id][0].status is QualificationStatus.UNKNOWN
    assert provider.calls == 2

    state.update(await nodes.check_evidence_coverage(state))  # type: ignore[arg-type]
    assert provider.calls == 2


def _qualification_evidence(
    company: ResearchCompany,
    run_id: UUID,
    criterion: str,
    subject: str | None,
    text: str,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        company_id=company.id,
        research_run_id=run_id,
        criterion=criterion,
        subject=subject,
        claim=text,
        evidence_text=text,
    )


class SemanticFactsProvider:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def generate_structured(self, **kwargs: object) -> object:
        prompt = str(kwargs["user_prompt"])
        self.prompts.append(prompt)
        return qualification_facts_from_prompt(prompt)


def _criteria_from_semantic_prompt(prompt: str) -> list[dict[str, object]]:
    return json.loads(prompt)["categorical_criteria"]


@pytest.mark.asyncio
async def test_airwallex_followup_only_extracts_unknown_and_preserves_matches() -> None:
    model = campaign()
    model.technologies = ["Java", "Spring", "Kafka"]
    model.company_size = {"min": 100}
    company = ResearchCompany(id=uuid4(), name="Airwallex Pty Ltd")
    run_id = uuid4()
    service = ResearchServiceFake()
    service.evidence = [
        _qualification_evidence(
            company, run_id, "target_market", "Australia", "Australia"
        ),
        _qualification_evidence(company, run_id, "industry", "Fintech", "Fintech"),
        _qualification_evidence(company, run_id, "technology", "Java", "Uses Java"),
        _qualification_evidence(company, run_id, "technology", "Spring", "Uses Spring"),
    ]
    provider = SemanticFactsProvider()
    nodes = ResearchNodes(
        campaigns=CampaignServiceFake(model),
        research=service,
        research_llm=provider,  # type: ignore[arg-type]
        extraction_llm=provider,  # type: ignore[arg-type]
        web_search=SearchFake([]),
        web_fetch=FetchFake({}),
    )
    state = {
        "campaign": CampaignCriteria.model_validate(model),
        "research_run_id": run_id,
        "research_companies": [company],
        "investigations": {
            company.id: CompanyInvestigationState(company_id=company.id)
        },
    }

    state.update(await nodes.check_evidence_coverage(state))  # type: ignore[arg-type]
    initial = state["criterion_qualifications"][company.id]
    assert [item.status for item in initial] == [
        QualificationStatus.MATCH,
        QualificationStatus.MATCH,
        QualificationStatus.MATCH,
        QualificationStatus.MATCH,
        QualificationStatus.UNKNOWN,
        QualificationStatus.UNKNOWN,
    ]
    service.evidence.append(
        _qualification_evidence(company, run_id, "technology", "Kafka", "Uses Kafka")
    )

    state.update(await nodes.check_evidence_coverage(state))  # type: ignore[arg-type]

    followup_targets = _criteria_from_semantic_prompt(provider.prompts[-1])
    assert [item["criterion_id"] for item in followup_targets] == ["criterion_4"]
    final_criteria = state["criterion_qualifications"][company.id]
    assert [item.status for item in final_criteria] == [
        QualificationStatus.MATCH,
        QualificationStatus.MATCH,
        QualificationStatus.MATCH,
        QualificationStatus.MATCH,
        QualificationStatus.MATCH,
        QualificationStatus.UNKNOWN,
    ]
    state["investigations"][company.id] = state["investigations"][
        company.id
    ].model_copy(update={"stopped": True})
    state["active_company_ids"] = []

    qualified = await nodes.qualify_companies(state)  # type: ignore[arg-type]

    assert qualified["company_qualifications"][company.id].status.value == "INSUFFICIENT_EVIDENCE"
    assert len(provider.prompts) == 2


@pytest.mark.asyncio
async def test_mismatch_does_not_block_unknown_followup_or_get_re_evaluated() -> None:
    model = campaign()
    model.target_market = None
    model.industry = None
    model.technologies = ["Kafka"]
    model.company_size = {"min": 100}
    company = ResearchCompany(id=uuid4(), name="Acme")
    run_id = uuid4()
    service = ResearchServiceFake()
    service.evidence = [
        _qualification_evidence(
            company, run_id, "company_size", None, "40 employees"
        )
    ]
    provider = SemanticFactsProvider()
    nodes = ResearchNodes(
        campaigns=CampaignServiceFake(model),
        research=service,
        research_llm=provider,  # type: ignore[arg-type]
        extraction_llm=provider,  # type: ignore[arg-type]
        web_search=SearchFake([]),
        web_fetch=FetchFake({}),
    )
    state = {
        "campaign": CampaignCriteria.model_validate(model),
        "research_run_id": run_id,
        "research_companies": [company],
        "investigations": {
            company.id: CompanyInvestigationState(company_id=company.id)
        },
    }
    state.update(await nodes.check_evidence_coverage(state))  # type: ignore[arg-type]
    assert state["criterion_qualifications"][company.id][1].status is (
        QualificationStatus.MISMATCH
    )
    assert state["active_company_ids"] == [company.id]
    assert state["investigations"][company.id].stop_reason is None
    service.evidence.append(
        _qualification_evidence(company, run_id, "technology", "Kafka", "Uses Kafka")
    )

    state.update(await nodes.check_evidence_coverage(state))  # type: ignore[arg-type]

    assert [item["criterion_id"] for item in _criteria_from_semantic_prompt(provider.prompts[-1])] == [
        "criterion_0"
    ]
    assert len(provider.prompts) == 2
    assert state["criterion_qualifications"][company.id][1].status is (
        QualificationStatus.MISMATCH
    )
    assert state["criterion_qualifications"][company.id][0].status is (
        QualificationStatus.MATCH
    )
    assert state["investigations"][company.id].stop_reason is (
        InvestigationStopReason.CRITERIA_RESOLVED
    )


@pytest.mark.asyncio
async def test_semantic_targets_shrink_as_criteria_resolve_across_rounds() -> None:
    model = campaign()
    model.target_market = None
    model.industry = None
    model.technologies = ["Java", "Spring", "Kafka"]
    company = ResearchCompany(id=uuid4(), name="Acme")
    run_id = uuid4()
    service = ResearchServiceFake()
    provider = SemanticFactsProvider()
    nodes = ResearchNodes(
        campaigns=CampaignServiceFake(model),
        research=service,
        research_llm=provider,  # type: ignore[arg-type]
        extraction_llm=provider,  # type: ignore[arg-type]
        web_search=SearchFake([]),
        web_fetch=FetchFake({}),
    )
    state = {
        "campaign": CampaignCriteria.model_validate(model),
        "research_run_id": run_id,
        "research_companies": [company],
        "investigations": {
            company.id: CompanyInvestigationState(company_id=company.id)
        },
    }
    state.update(await nodes.check_evidence_coverage(state))  # type: ignore[arg-type]
    service.evidence.extend(
        [
            _qualification_evidence(company, run_id, "technology", "Java", "Uses Java"),
            _qualification_evidence(company, run_id, "technology", "Spring", "Uses Spring"),
        ]
    )

    state.update(await nodes.check_evidence_coverage(state))  # type: ignore[arg-type]
    round_two = _criteria_from_semantic_prompt(provider.prompts[-1])
    assert [item["criterion_id"] for item in round_two] == [
        "criterion_0",
        "criterion_1",
        "criterion_2",
    ]
    service.evidence.append(
        _qualification_evidence(company, run_id, "technology", "Kafka", "Uses Kafka")
    )

    state.update(await nodes.check_evidence_coverage(state))  # type: ignore[arg-type]
    round_three = _criteria_from_semantic_prompt(provider.prompts[-1])
    assert [item["criterion_id"] for item in round_three] == ["criterion_2"]
    assert [item.status for item in state["criterion_qualifications"][company.id]] == [
        QualificationStatus.MATCH,
        QualificationStatus.MATCH,
        QualificationStatus.MATCH,
    ]
    assert len(provider.prompts) == 2


@pytest.mark.asyncio
async def test_coverage_stops_companies_independently() -> None:
    model = campaign()
    model.target_market = None
    model.industry = None
    model.technologies = ["Kafka", ]
    complete = ResearchCompany(id=uuid4(), name="Complete")
    stalled = ResearchCompany(id=uuid4(), name="Stalled")
    progressing = ResearchCompany(id=uuid4(), name="Progressing")
    exhausted = ResearchCompany(id=uuid4(), name="Exhausted")
    run_id = uuid4()
    service = ResearchServiceFake()
    service.evidence = [
        SimpleNamespace(
            id=uuid4(),
            company_id=complete.id,
            research_run_id=run_id,
            criterion="technology",
            subject="Kafka",
            claim="Uses Kafka.",
            evidence_text="Uses Kafka.",
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
            "research_companies": [complete, stalled, progressing, exhausted],
            "investigations": {
                complete.id: CompanyInvestigationState(company_id=complete.id),
                stalled.id: CompanyInvestigationState(
                    company_id=stalled.id,
                    round=1,
                    unresolved_before={"technology|kafka"},
                    new_evidence_count=3,
                ),
                progressing.id: CompanyInvestigationState(
                    company_id=progressing.id,
                    round=1,
                    new_evidence_count=1,
                ),
                exhausted.id: CompanyInvestigationState(
                    company_id=exhausted.id,
                    round=2,
                    unresolved_before={"technology|kafka"},
                    alternative_strategy_attempted=True,
                ),
            },
        }
    )  # type: ignore[arg-type]
    states = output["investigations"]
    assert states[complete.id].stop_reason is InvestigationStopReason.CRITERIA_RESOLVED
    assert states[stalled.id].stop_reason is None
    assert states[progressing.id].stop_reason is None
    assert states[exhausted.id].stop_reason is InvestigationStopReason.NO_PROGRESS
    assert output["active_company_ids"] == [stalled.id, progressing.id]


@pytest.mark.asyncio
async def test_coverage_stops_at_maximum_adaptive_rounds() -> None:
    model = campaign()
    model.target_market = None
    model.industry = None
    model.technologies = ["Kafka", ]
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

    coverage_state = {
        "campaign": CampaignCriteria.model_validate(model),
        "research_run_id": uuid4(),
        "research_companies": [company],
        "investigations": {
            company.id: CompanyInvestigationState(company_id=company.id)
        },
    }
    coverage_state.update(
        await nodes.check_evidence_coverage(coverage_state)  # type: ignore[arg-type]
    )
    assert coverage_state["active_company_ids"] == [company.id]
    queries = await nodes.generate_company_queries(coverage_state)  # type: ignore[arg-type]
    assert queries["company_research_queries"][company.id]


@pytest.mark.asyncio
async def test_qualification_reads_current_run_evidence_without_external_calls() -> (
    None
):
    from virtual_company.domain.qualification import CompanyQualificationStatus

    model = campaign()
    model.target_market = None
    model.industry = None
    model.technologies = ["spring", "spring boot", ]
    nodes = make_nodes(ExtractionFake({}), ResearchFake([]), model)
    company_id = uuid4()
    run_id = uuid4()
    old = SimpleNamespace(
        id=uuid4(),
        company_id=company_id,
        research_run_id=run_id,
        criterion="technology",
        subject="Spring Boot",
        claim="Uses Spring Boot.",
        evidence_text="Uses Spring Boot.",
    )
    nodes._research.evidence = [old]
    state = {
        "campaign": CampaignCriteria.model_validate(model),
        "research_companies": [ResearchCompany(id=company_id, name="Acme")],
        "investigations": {
            company_id: CompanyInvestigationState(company_id=company_id, stopped=True)
        },
        "active_company_ids": [],
        "validated_evidence": [],
        "research_run_id": run_id,
    }
    qualification_result = await nodes.qualify_companies(state)
    state.update(qualification_result)
    result = qualification_result["company_qualifications"][company_id]
    assert result.status is CompanyQualificationStatus.INSUFFICIENT_EVIDENCE
    assert [item.status for item in result.criteria] == [
        QualificationStatus.UNKNOWN,
        QualificationStatus.MATCH,
    ]
    assert [item.evidence_ids for item in result.criteria] == [[], [old.id]]
    assert not nodes._research_llm.prompts
    state["investigations"][company_id].stopped = False
    with pytest.raises(ValueError, match="terminal"):
        await nodes.qualify_companies(state)


@pytest.mark.asyncio
@pytest.mark.parametrize("rounds", [0, 2])
async def test_graph_qualifies_once_after_terminal_before_completion(
    monkeypatch: pytest.MonkeyPatch, rounds: int
) -> None:
    events = []
    original = ResearchNodes.qualify_companies
    original_persist = ResearchNodes.persist_company_qualifications

    async def qualify(nodes: ResearchNodes, state: dict) -> dict:
        assert not state["active_company_ids"]
        assert all(item.stopped for item in state["investigations"].values())
        events.append("qualify")
        result = await original(nodes, state)
        assert len(result["company_qualifications"]) == 1
        return result

    async def persist(nodes: ResearchNodes, state: dict) -> dict:
        events.append("persist")
        return await original_persist(nodes, state)

    async def complete(nodes: ResearchNodes, state: dict) -> dict:
        assert len(state["company_qualifications"]) == 1
        events.append("complete")
        return {"error": None}

    monkeypatch.setattr(ResearchNodes, "qualify_companies", qualify)
    monkeypatch.setattr(ResearchNodes, "persist_company_qualifications", persist)
    monkeypatch.setattr(ResearchNodes, "complete_research_run", complete)
    model = campaign()
    url = "https://acme.example"
    workflow = ResearchWorkflow(
        campaigns=CampaignServiceFake(model),
        research=ResearchServiceFake(),
        research_llm=ResearchFake([found("Acme", [url])]),
        extraction_llm=ExtractionFake({url: [ExtractedCompanyIdentity(name="Acme")]}),
        web_search=SearchFake([SearchResult(title="Acme", url=url)]),
        web_fetch=FetchFake({}),
        settings=Settings(company_research_max_investigation_rounds=rounds),
    )
    await workflow.run(model.id)
    assert events == ["qualify", "persist", "complete"]


@pytest.mark.asyncio
async def test_qualification_failure_marks_run_failed() -> None:
    from virtual_company.workflows.research.graph import _with_failure_handling

    service = ResearchServiceFake()
    run = await service.create_run(uuid4())

    async def failing_qualification(state: dict) -> dict:
        raise RuntimeError("Evidence read failed")

    wrapped = _with_failure_handling(
        failing_qualification, "qualify_companies", service
    )
    with pytest.raises(RuntimeError, match="Evidence read failed"):
        await wrapped({"research_run_id": run.id})
    assert run.status == "FAILED"


@pytest.mark.asyncio
async def test_workflow_node_events_bind_campaign_and_research_run_ids(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    from virtual_company.observability import get_observability
    from virtual_company.workflows.research.graph import _with_failure_handling

    observability = get_observability()
    observability.clear_context()
    service = ResearchServiceFake()

    async def node(_: dict) -> dict[str, object]:
        observability.event("test_operation")
        return {}

    wrapped = _with_failure_handling(node, "test_node", service)
    run_id, campaign_id = uuid4(), uuid4()
    with caplog.at_level(logging.INFO, logger="virtual_company.observability.runtime"):
        await wrapped({"campaign_id": campaign_id, "research_run_id": run_id})

    relevant = [
        record
        for record in caplog.records
        if record.getMessage() in {"workflow_node_started", "test_operation"}
    ]
    assert len(relevant) == 2
    assert all(record.context["campaign_id"] == str(campaign_id) for record in relevant)
    assert all(record.context["research_run_id"] == str(run_id) for record in relevant)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid", ["missing_result", "wrong_company", "active", "missing_run"]
)
async def test_persistence_rejects_incomplete_final_state(invalid: str) -> None:
    from unittest.mock import AsyncMock

    from virtual_company.domain.qualification import (
        CompanyQualification,
        CompanyQualificationStatus,
    )

    nodes = make_nodes(ExtractionFake({}), ResearchFake([]), campaign())
    nodes._research.persist_company_qualifications = AsyncMock()
    company_id = uuid4()
    result = CompanyQualification(company_id, CompanyQualificationStatus.QUALIFIED, [])
    state = {
        "campaign_id": uuid4(),
        "research_run_id": uuid4(),
        "research_companies": [ResearchCompany(id=company_id, name="Acme")],
        "active_company_ids": [],
        "investigations": {
            company_id: CompanyInvestigationState(company_id=company_id, stopped=True)
        },
        "company_qualifications": {company_id: result},
    }
    if invalid == "missing_result":
        state["company_qualifications"] = {}
    elif invalid == "wrong_company":
        state["company_qualifications"] = {uuid4(): result}
    elif invalid == "active":
        state["active_company_ids"] = [company_id]
    else:
        state["research_run_id"] = None
    with pytest.raises(ValueError):
        await nodes.persist_company_qualifications(state)
    nodes._research.persist_company_qualifications.assert_not_awaited()


@pytest.mark.asyncio
async def test_persistence_failure_prevents_run_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import AsyncMock

    model = campaign()
    service = ResearchServiceFake()
    service.persist_company_qualifications = AsyncMock(
        side_effect=RuntimeError("Snapshot write failed")
    )
    service.complete_run = AsyncMock()
    workflow = ResearchWorkflow(
        campaigns=CampaignServiceFake(model),
        research=service,
        research_llm=ResearchFake([]),
        extraction_llm=ExtractionFake({}),
        web_search=SearchFake([]),
        web_fetch=FetchFake({}),
        settings=Settings(company_research_max_investigation_rounds=0),
    )
    with pytest.raises(RuntimeError, match="Snapshot write failed"):
        await workflow.run(model.id)
    service.complete_run.assert_not_awaited()
    assert all(run.status == "FAILED" for run in service.runs.values())


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["facts", "failure", "invalid", "empty"])
async def test_final_qualification_normalizes_dated_size_without_campaign_failure(
    outcome: str,
) -> None:
    from unittest.mock import AsyncMock

    from virtual_company.domain.qualification import QualificationStatus

    model = campaign()
    model.target_market = None
    model.industry = None
    model.technologies = []
    model.company_size = {"min": 500}
    company_id = uuid4()
    run_id = uuid4()
    item = SimpleNamespace(
        id=uuid4(),
        company_id=company_id,
        research_run_id=run_id,
        criterion="company_size",
        subject=None,
        claim="Afterpay had approximately 714 employees in 2023.",
        evidence_text="from 714 employees in 2023 to 460 in 2026",
    )
    provider = SimpleNamespace(generate_structured=AsyncMock())
    if outcome == "failure":
        provider.generate_structured.side_effect = RuntimeError("unavailable")
    else:
        provider.generate_structured.return_value = (
            {"employee_counts": [{"value": "bad"}]}
            if outcome == "invalid"
            else QualificationFacts(
                employee_counts=[]
                if outcome == "empty"
                else [
                    EmployeeCountEvidenceFact(
                        value=714, relation="exact", year=2023, evidence_ids=[item.id]
                    ),
                    EmployeeCountEvidenceFact(
                        value=460, relation="exact", year=2026, evidence_ids=[item.id]
                    ),
                ]
            )
        )
    nodes = make_nodes(provider, ResearchFake([]), model)
    nodes._research.evidence = [item]
    state = {
        "campaign": CampaignCriteria.model_validate(model),
        "research_run_id": run_id,
        "research_companies": [ResearchCompany(id=company_id, name="Afterpay")],
        "investigations": {
            company_id: CompanyInvestigationState(company_id=company_id)
        },
        "active_company_ids": [],
    }
    state.update(await nodes.check_evidence_coverage(state))
    state["investigations"][company_id].stopped = True
    state["active_company_ids"] = []
    qualification_result = await nodes.qualify_companies(state)
    state.update(qualification_result)
    result = qualification_result["company_qualifications"][company_id]
    assert result.criteria[0].status is (
        QualificationStatus.MISMATCH
        if outcome == "facts"
        else QualificationStatus.UNKNOWN
    )
    assert result.criteria[0].evidence_ids == ([item.id] if outcome == "facts" else [])
    assert provider.generate_structured.await_count == (
        2 if outcome in {"failure", "invalid"} else 1
    )
    assert not nodes._research_llm.prompts
    assert not nodes._web_search.calls
    assert not nodes._web_fetch.calls

    provider.generate_structured.reset_mock()
    model.company_size = None
    state["campaign"] = CampaignCriteria.model_validate(model)
    state.update(await nodes.qualify_companies(state))
    provider.generate_structured.assert_not_awaited()


@pytest.mark.asyncio
async def test_discovery_size_mismatch_continues_unknown_criterion_research() -> None:
    class DiscoveryEvidenceFake(ExtractionFake):
        async def generate_structured(self, **kwargs: object) -> object:
            if kwargs["response_model"] is ExtractedEvidenceItems:
                return ExtractedEvidenceItems(
                    evidence=[
                        ExtractedEvidence(
                            criterion=EvidenceCriterion.COMPANY_SIZE,
                            claim="Candidate 0 has 47 employees.",
                            evidence_text="Candidate 0 has 47 employees.",
                        )
                    ]
                )
            return await super().generate_structured(**kwargs)

    model = campaign()
    model.company_size = {"min": 100}
    url = "https://candidate.example/about"
    search = SearchFake([SearchResult(title="Candidate 0", url=url)])
    research = ResearchFake([found("Candidate 0", [url])])
    service = ResearchServiceFake()
    workflow = ResearchWorkflow(
        campaigns=CampaignServiceFake(model),
        research=service,
        research_llm=research,
        extraction_llm=DiscoveryEvidenceFake(
            {url: [ExtractedCompanyIdentity(name="Candidate 0")]}
        ),
        web_search=search,
        web_fetch=FetchFake(
            {url: WebPage(url=url, content="Candidate 0 has 47 employees.")}
        ),
    )
    await workflow.run(model.id)
    assert len(search.calls) == 2  # discovery plus bounded company investigation
    assert GeneratedCompanySearchQueries in research.models
    result = next(iter(service.qualifications.values()))
    assert result.status.value == "NOT_QUALIFIED"
    assert any(
        item.subject == "employees >= 100"
        and item.status is QualificationStatus.MISMATCH
        for item in result.criteria
    )
    assert any(item.status is QualificationStatus.UNKNOWN for item in result.criteria)


@pytest.mark.asyncio
async def test_discovery_evidence_resolving_all_criteria_avoids_company_search() -> None:
    class DiscoveryEvidenceFake(ExtractionFake):
        async def generate_structured(self, **kwargs: object) -> object:
            if kwargs["response_model"] is ExtractedEvidenceItems:
                return ExtractedEvidenceItems(
                    evidence=[
                        ExtractedEvidence(
                            criterion=EvidenceCriterion.TARGET_MARKET,
                            claim="Operates in Australia.",
                            evidence_text="Operates in Australia.",
                        ),
                        ExtractedEvidence(
                            criterion=EvidenceCriterion.INDUSTRY,
                            claim="A fin tech company.",
                            evidence_text="A fin tech company.",
                        ),
                        ExtractedEvidence(
                            criterion=EvidenceCriterion.TECHNOLOGY,
                            subject="Java",
                            claim="Uses Java.",
                            evidence_text="Uses Java.",
                        ),
                        ExtractedEvidence(
                            criterion=EvidenceCriterion.COMPANY_SIZE,
                            claim="147 employees",
                            evidence_text="147 employees",
                        ),
                    ]
                )
            return await super().generate_structured(**kwargs)

    model = campaign()
    model.technologies = ["Java", ]
    model.company_size = {"min": 100}
    url = "https://candidate.example/about"
    search = SearchFake([SearchResult(title="Candidate 0", url=url)])
    research = ResearchFake([found("Candidate 0", [url])])
    service = ResearchServiceFake()
    workflow = ResearchWorkflow(
        campaigns=CampaignServiceFake(model),
        research=service,
        research_llm=research,
        extraction_llm=DiscoveryEvidenceFake(
            {url: [ExtractedCompanyIdentity(name="Candidate 0")]}
        ),
        web_search=search,
        web_fetch=FetchFake(
            {
                url: WebPage(
                    url=url,
                    content="Operates in Australia. A fin tech company. Uses Java. 147 employees",
                )
            }
        ),
    )
    await workflow.run(model.id)
    assert len(search.calls) == 1
    assert GeneratedCompanySearchQueries not in research.models
    assert next(iter(service.qualifications.values())).status.value == "QUALIFIED"


@pytest.mark.asyncio
async def test_all_unknown_criteria_are_targeted_for_followup() -> None:
    model = campaign()
    model.target_market = None
    model.industry = None
    model.technologies = ["Java", "Kafka"]
    company = ResearchCompany(id=uuid4(), name="Acme")
    research = ResearchFake([])
    nodes = make_nodes(ExtractionFake({}), research, model)
    state = {
        "campaign": CampaignCriteria.model_validate(model),
        "research_run_id": uuid4(),
        "research_companies": [company],
        "investigations": {
            company.id: CompanyInvestigationState(company_id=company.id)
        },
        "active_company_ids": [company.id],
    }
    state.update(await nodes.check_evidence_coverage(state))
    output = await nodes.generate_company_queries(state)
    targets = research.prompts[-1].split("Evidence targets:", 1)[1]
    assert "Java" in targets
    assert "Kafka" in targets
    assert output["investigations"][company.id].round == 1
    assert output["adaptive_mode"] is False


@pytest.mark.asyncio
async def test_all_unknown_criteria_are_scheduled_equally() -> None:
    model = campaign()
    model.target_market = None
    model.industry = None
    model.technologies = ["Java", "Spring", "Kafka"]
    complete = ResearchCompany(id=uuid4(), name="Complete")
    unresolved = ResearchCompany(id=uuid4(), name="Unresolved")
    run_id = uuid4()
    nodes = make_nodes(ExtractionFake({}), ResearchFake([]), model)
    nodes._research.evidence = [
        SimpleNamespace(
            id=uuid4(),
            company_id=complete.id,
            research_run_id=run_id,
            criterion="technology",
            subject=subject,
            claim=f"Uses {subject}.",
            evidence_text=f"Uses {subject}.",
        )
        for subject in ("Java", "Spring")
    ]
    state = {
        "campaign": CampaignCriteria.model_validate(model),
        "research_run_id": run_id,
        "research_companies": [complete, unresolved],
        "investigations": {
            complete.id: CompanyInvestigationState(company_id=complete.id),
            unresolved.id: CompanyInvestigationState(company_id=unresolved.id),
        },
    }
    output = await nodes.check_evidence_coverage(state)  # type: ignore[arg-type]
    assert output["active_company_ids"] == [complete.id, unresolved.id]
    assert output["investigations"][complete.id].stopped is False


@pytest.mark.asyncio
async def test_source_selection_scores_unresolved_qualification_not_raw_coverage() -> (
    None
):
    model = campaign()
    model.target_market = None
    model.industry = None
    model.technologies = ["Spring", ]
    company = ResearchCompany(id=uuid4(), name="Acme", domain="acme.example")
    generic = SearchResult(
        title="Careers", url="https://acme.example/careers", snippet="Open roles"
    )
    targeted = SearchResult(
        title="Engineering",
        url="https://acme.example/engineering",
        snippet="Spring platform roles",
    )
    nodes = make_nodes(ExtractionFake({}), ResearchFake([]), model)
    nodes._company_research_followup_max_fetches_per_company = 1
    output = await nodes.select_company_sources(
        {
            "research_companies": [company],
            "active_company_ids": [company.id],
            "adaptive_mode": True,
            "company_search_results": {company.id: [generic, targeted]},
            "criterion_qualifications": {
                company.id: [
                    CriterionQualification(
                        "technology",
                        "Spring",
                        QualificationStatus.UNKNOWN,
                        [uuid4()],
                        "Covered but inconclusive",
                    )
                ]
            },
            "investigations": {
                company.id: CompanyInvestigationState(
                    company_id=company.id,
                    coverage=[
                        CriterionCoverage(
                            criterion=EvidenceCriterion.TECHNOLOGY,
                            subject="Spring",
                            status=CoverageStatus.FOUND,
                            evidence_ids=[uuid4()],
                        )
                    ],
                )
            },
        }
    )  # type: ignore[arg-type]
    assert output["selected_company_sources"][company.id] == [targeted]


@pytest.mark.asyncio
async def test_source_selection_prioritizes_company_specific_unknown_subjects() -> (
    None
):
    model = campaign()
    model.target_market = None
    model.industry = None
    model.technologies = ["Java", "Spring", "Kafka"]
    company = ResearchCompany(id=uuid4(), name="Iress")
    generic = SearchResult(
        title="Iress careers", url="https://www.iress.com/careers", snippet="Join us"
    )
    unrelated = SearchResult(
        title="Java and Spring jobs",
        url="https://other.example/jobs",
        snippet="Java Spring engineering roles",
    )
    targeted = SearchResult(
        title="Iress Java engineer",
        url="https://jobs.example/iress-java",
        snippet="Iress Spring platform team",
    )
    unknown = [
        CriterionQualification(
            "technology",
            subject,
            QualificationStatus.UNKNOWN,
            [],
            "No evidence",
        )
        for subject in ("Java", "Spring")
    ]
    nodes = make_nodes(ExtractionFake({}), ResearchFake([]), model)
    nodes._company_research_followup_max_fetches_per_company = 1
    output = await nodes.select_company_sources(
        {
            "research_companies": [company],
            "active_company_ids": [company.id],
            "adaptive_mode": True,
            "company_search_results": {company.id: [generic, unrelated, targeted]},
            "criterion_qualifications": {company.id: unknown},
            "investigations": {
                company.id: CompanyInvestigationState(company_id=company.id)
            },
            "company_search_started": True,
        }
    )  # type: ignore[arg-type]
    assert output["selected_company_sources"][company.id] == [targeted]


@pytest.mark.asyncio
async def test_unknown_criteria_use_remaining_rounds_then_resolve() -> None:
    model = campaign()
    model.target_market = None
    model.industry = None
    model.technologies = ["Java", "Kafka"]
    company = ResearchCompany(id=uuid4(), name="Acme")
    run_id = uuid4()
    research = ResearchFake([])
    nodes = make_nodes(ExtractionFake({}), research, model)
    nodes._company_research_max_investigation_rounds = 1
    nodes._research.evidence = [
        SimpleNamespace(
            id=uuid4(),
            company_id=company.id,
            research_run_id=run_id,
            criterion="technology",
            subject="Java",
            claim="Uses Java.",
            evidence_text="Uses Java.",
        )
    ]
    state = {
        "campaign": CampaignCriteria.model_validate(model),
        "research_run_id": run_id,
        "research_companies": [company],
        "investigations": {
            company.id: CompanyInvestigationState(company_id=company.id)
        },
        "active_company_ids": [company.id],
    }
    state.update(await nodes.check_evidence_coverage(state))
    state.update(await nodes.generate_company_queries(state))
    assert "Kafka" in research.prompts[-1].split("Evidence targets:", 1)[1]
    assert state["investigations"][company.id].round == 1
    assert state["adaptive_mode"] is False
    state.update(await nodes.check_evidence_coverage(state))
    assert (
        state["investigations"][company.id].stop_reason
        is InvestigationStopReason.MAX_ROUNDS
    )
    result = (await nodes.qualify_companies(state))["company_qualifications"][
        company.id
    ]
    assert result.status.value == "INSUFFICIENT_EVIDENCE"
    assert result.criteria[-1].status is QualificationStatus.UNKNOWN


@pytest.mark.asyncio
async def test_size_mismatch_is_retained_after_all_criteria_resolve() -> None:
    model = campaign()
    model.target_market = None
    model.industry = None
    model.technologies = ["Java", ]
    model.company_size = {"max": 500}
    company = ResearchCompany(id=uuid4(), name="Acme")
    run_id = uuid4()
    nodes = make_nodes(ExtractionFake({}), ResearchFake([]), model)
    nodes._research.evidence = [
        SimpleNamespace(
            id=uuid4(),
            company_id=company.id,
            research_run_id=run_id,
            criterion="technology",
            subject="Java",
            claim="Uses Java.",
            evidence_text="Uses Java.",
        ),
        SimpleNamespace(
            id=uuid4(),
            company_id=company.id,
            research_run_id=run_id,
            criterion="company_size",
            subject=None,
            claim="2,300 employees",
            evidence_text="2,300 employees",
        ),
    ]
    state = {
        "campaign": CampaignCriteria.model_validate(model),
        "research_run_id": run_id,
        "research_companies": [company],
        "investigations": {
            company.id: CompanyInvestigationState(company_id=company.id)
        },
        "active_company_ids": [company.id],
    }
    state.update(await nodes.check_evidence_coverage(state))
    assert (
        state["investigations"][company.id].stop_reason
        is InvestigationStopReason.CRITERIA_RESOLVED
    )
    result = (await nodes.qualify_companies(state))["company_qualifications"][
        company.id
    ]
    assert result.status.value == "NOT_QUALIFIED"
    assert result.criteria[-1].status is QualificationStatus.MISMATCH


@pytest.mark.asyncio
async def test_multi_company_workflow_researches_all_unknown_criteria() -> None:
    discovery_complete = "https://complete.example/discovery"
    discovery_required = "https://required.example/discovery"
    required_page = "https://required.example/engineering"
    preferred_page = "https://complete.example/kafka"

    class CostResearchFake(ResearchFake):
        async def generate_structured(self, **kwargs: object) -> object:
            prompt = str(kwargs["user_prompt"])
            model_type = kwargs["response_model"]
            self.prompts.append(prompt)
            self.models.append(model_type)
            if model_type is GeneratedSearchQueries:
                return GeneratedSearchQueries(queries=["Australian fintech companies"])
            if model_type is GeneratedCompanySearchQueries:
                query = (
                    "RequiredCo Java Spring evidence"
                    if "RequiredCo" in prompt
                    else "CompleteCo Kafka evidence"
                )
                return GeneratedCompanySearchQueries(queries=[query])
            return DiscoveredCompanies(
                companies=[
                    found("CompleteCo", [discovery_complete]),
                    found("RequiredCo", [discovery_required]),
                ]
            )

    class CostSearchFake(SearchFake):
        async def search(self, query: str, limit: int = 10) -> list[SearchResult]:
            self.calls.append((query, limit))
            if query == "Australian fintech companies":
                return [
                    SearchResult(title="CompleteCo", url=discovery_complete),
                    SearchResult(title="RequiredCo", url=discovery_required),
                ]
            if query == "RequiredCo Java Spring evidence":
                return [SearchResult(title="Engineering", url=required_page)]
            if query == "CompleteCo Kafka evidence":
                return [SearchResult(title="Kafka", url=preferred_page)]
            raise AssertionError(f"Unexpected search query: {query}")

    class CostExtractionFake(ExtractionFake):
        async def generate_structured(self, **kwargs: object) -> object:
            prompt = str(kwargs["user_prompt"])
            model_type = kwargs["response_model"]
            if model_type is CompanyPageAttribution:
                return CompanyPageAttribution(attributable=True, reason="Matched")
            if model_type is ExtractedEvidenceItems:
                if discovery_complete in prompt:
                    return ExtractedEvidenceItems(
                        evidence=[
                            ExtractedEvidence(
                                criterion=EvidenceCriterion.TARGET_MARKET,
                                claim="Operates in Australia.",
                                evidence_text="Operates in Australia.",
                            ),
                            ExtractedEvidence(
                                criterion=EvidenceCriterion.INDUSTRY,
                                claim="A fintech company.",
                                evidence_text="A fintech company.",
                            ),
                            ExtractedEvidence(
                                criterion=EvidenceCriterion.TECHNOLOGY,
                                subject="Java",
                                claim="Uses Java.",
                                evidence_text="Uses Java.",
                            ),
                            ExtractedEvidence(
                                criterion=EvidenceCriterion.TECHNOLOGY,
                                subject="Spring",
                                claim="Uses Spring.",
                                evidence_text="Uses Spring.",
                            ),
                            ExtractedEvidence(
                                criterion=EvidenceCriterion.COMPANY_SIZE,
                                claim="700 employees.",
                                evidence_text="700 employees.",
                            ),
                        ]
                    )
                if discovery_required in prompt:
                    return ExtractedEvidenceItems(
                        evidence=[
                            ExtractedEvidence(
                                criterion=EvidenceCriterion.TARGET_MARKET,
                                claim="Operates in Australia.",
                                evidence_text="Operates in Australia.",
                            ),
                            ExtractedEvidence(
                                criterion=EvidenceCriterion.INDUSTRY,
                                claim="A fintech company.",
                                evidence_text="A fintech company.",
                            ),
                        ]
                    )
                if required_page in prompt:
                    return ExtractedEvidenceItems(
                        evidence=[
                            ExtractedEvidence(
                                criterion=EvidenceCriterion.TECHNOLOGY,
                                subject="Java",
                                claim="Uses Java.",
                                evidence_text="Uses Java.",
                            ),
                            ExtractedEvidence(
                                criterion=EvidenceCriterion.TECHNOLOGY,
                                subject="Spring",
                                claim="Uses Spring.",
                                evidence_text="Uses Spring.",
                            ),
                            ExtractedEvidence(
                                criterion=EvidenceCriterion.COMPANY_SIZE,
                                claim="230 employees.",
                                evidence_text="230 employees.",
                            ),
                        ]
                    )
                if preferred_page in prompt:
                    return ExtractedEvidenceItems(
                        evidence=[
                            ExtractedEvidence(
                                criterion=EvidenceCriterion.TECHNOLOGY,
                                subject="Kafka",
                                claim="Uses Kafka.",
                                evidence_text="Uses Kafka.",
                            )
                        ]
                    )
                return ExtractedEvidenceItems(evidence=[])
            if model_type is ExtractedCompanyIdentities:
                name = "CompleteCo" if discovery_complete in prompt else "RequiredCo"
                return ExtractedCompanyIdentities(
                    companies=[ExtractedCompanyIdentity(name=name)]
                )
            if model_type is QualificationFacts:
                return qualification_facts_from_prompt(prompt)
            raise AssertionError(f"Unexpected extraction model: {model_type}")

    model = campaign()
    model.technologies = ["Java", "Spring", "Kafka"]
    model.company_size = {"min": 500}
    search = CostSearchFake([])
    research = CostResearchFake([])
    service = ResearchServiceFake()
    pages = {
        discovery_complete: WebPage(
            url=discovery_complete,
            content=(
                "Operates in Australia. A fintech company. Uses Java. Uses Spring. "
                "700 employees."
            ),
        ),
        discovery_required: WebPage(
            url=discovery_required,
            content="Operates in Australia. A fintech company.",
        ),
        required_page: WebPage(
            url=required_page, content="Uses Java. Uses Spring. 230 employees."
        ),
        preferred_page: WebPage(url=preferred_page, content="Uses Kafka."),
    }
    workflow = ResearchWorkflow(
        campaigns=CampaignServiceFake(model),
        research=service,
        research_llm=research,
        extraction_llm=CostExtractionFake({}),
        web_search=search,
        web_fetch=FetchFake(pages),
        settings=Settings(company_research_max_investigation_rounds=2),
    )
    await workflow.run(model.id)
    assert [query for query, _ in search.calls] == [
        "Australian fintech companies",
        "CompleteCo Kafka evidence",
        "RequiredCo Java Spring evidence",
    ]
    statuses = {result.status.value for result in service.qualifications.values()}
    assert statuses == {"QUALIFIED", "NOT_QUALIFIED"}


@pytest.mark.asyncio
async def test_approximate_company_size_stays_unknown() -> None:
    from unittest.mock import AsyncMock

    model = campaign()
    model.target_market = None
    model.industry = None
    model.technologies = []
    model.company_size = {"min": 500}
    company = ResearchCompany(id=uuid4(), name="Acme")
    run_id = uuid4()
    item = SimpleNamespace(
        id=uuid4(),
        company_id=company.id,
        research_run_id=run_id,
        criterion="company_size",
        subject=None,
        claim="close to 600 employees",
        evidence_text="close to 600 employees",
    )
    provider = SimpleNamespace(
        generate_structured=AsyncMock(
            return_value=QualificationFacts(
                employee_counts=[
                    EmployeeCountEvidenceFact(
                        value=600,
                        relation="approximately",
                        evidence_ids=[item.id],
                    )
                ]
            )
        )
    )
    nodes = make_nodes(provider, ResearchFake([]), model)
    nodes._research.evidence = [item]
    state = {
        "campaign": CampaignCriteria.model_validate(model),
        "research_run_id": run_id,
        "research_companies": [company],
        "investigations": {
            company.id: CompanyInvestigationState(company_id=company.id)
        },
        "active_company_ids": [company.id],
    }
    state.update(await nodes.check_evidence_coverage(state))
    assert state["investigations"][company.id].stop_reason is None
    assert (
        state["criterion_qualifications"][company.id][0].status
        is QualificationStatus.UNKNOWN
    )
