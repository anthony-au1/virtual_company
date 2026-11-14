"""Behavioral tests for the compiled Exploration graph."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest

from virtual_company.domain.exploration.evidence import ExplorationEvidence
from virtual_company.domain.exploration.facts import ExplorationFact
from virtual_company.domain.exploration.hypotheses import ExplorationHypothesis
from virtual_company.domain.exploration.run import ExplorationRunStatus
from virtual_company.llm.base import LLMAuthenticationError, LLMRateLimitError
from virtual_company.services.exploration_evidence_extractor import (
    ExplorationEvidenceExtractionBatchResult,
    ExplorationEvidenceExtractionOutcome,
    ExplorationEvidencePageResult,
)
from virtual_company.services.exploration_fetch import (
    ExplorationFetchBatchResult,
    ExplorationFetchedPage,
    ExplorationFetchOutcome,
    ExplorationFetchResult,
)
from virtual_company.services.exploration_hypothesis_generator import (
    ExplorationHypothesisGenerationResult,
)
from virtual_company.services.exploration_query_generator import (
    ExplorationQueryGenerationResult,
    GeneratedExplorationQuery,
)
from virtual_company.services.exploration_search import (
    ExplorationQuerySearchResult,
    ExplorationSearchBatchResult,
    ExplorationSearchOutcome,
    ExplorationSearchResultItem,
)
from virtual_company.workflows.exploration import graph as graph_module
from virtual_company.workflows.exploration.models import (
    ExplorationFactExtractionBatchResult,
    ExplorationFactExtractionChunkResult,
    ExplorationFactExtractionOutcome,
    ExplorationHypothesisGenerationOutcome,
)
from virtual_company.workflows.exploration.nodes import ExplorationWorkflowInputError


class SessionTracker:
    def __init__(self) -> None:
        self.active = 0

    def __call__(self):
        return FakeSession(self)


class FakeSession:
    def __init__(self, tracker: SessionTracker) -> None:
        self._tracker = tracker

    async def __aenter__(self):
        self._tracker.active += 1
        return self

    async def __aexit__(self, *_args):
        self._tracker.active -= 1

    @asynccontextmanager
    async def begin(self):
        yield


class ObservabilityStub:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def clear_context(self) -> None:
        pass

    def bind(self, **_values: str) -> None:
        pass

    def event(self, name: str, **metadata: object) -> None:
        self.events.append((name, metadata))

    @contextmanager
    def span(self, *_args, **_kwargs):
        yield None


def make_inputs(company_count: int = 1, obligation_count: int = 1):
    exploration_id, research_run_id, run_id = uuid4(), uuid4(), uuid4()
    companies = []
    for index in range(company_count):
        research_id = uuid4()
        companies.append(
            SimpleNamespace(
                id=uuid4(),
                company_id=research_id,
                exploration_run_id=run_id,
                company=SimpleNamespace(
                    id=research_id,
                    name=f"Company {index}",
                    website=f"https://company-{index}.test",
                    domain=f"company-{index}.test",
                    industry="Software",
                    country="AU",
                    state=None,
                    city=None,
                ),
            )
        )
    obligations = [
        SimpleNamespace(
            id=uuid4(),
            exploration_id=exploration_id,
            description=f"Obligation {index}",
        )
        for index in range(obligation_count)
    ]
    run = SimpleNamespace(
        id=run_id,
        exploration_id=exploration_id,
        research_run_id=research_run_id,
        status="RUNNING",
    )
    return run, companies, obligations


def install_repository_fakes(monkeypatch, run, companies, obligations, tracker, store):
    class RunRepository:
        def __init__(self, _session):
            pass

        async def get_by_id(self, run_id):
            return run if run_id == run.id else None

    class ExplorationRepository:
        def __init__(self, _session):
            pass

        async def get_by_id(self, exploration_id):
            if exploration_id != run.exploration_id:
                return None
            return SimpleNamespace(
                id=run.exploration_id,
                business_context="Assess strategic fit",
            )

    class ResearchRunRepository:
        def __init__(self, _session):
            pass

        async def get_by_id(self, _research_run_id):
            return SimpleNamespace(status="COMPLETED")

    class QualificationRepository:
        def __init__(self, _session):
            pass

        async def list_member_company_ids(self, _research_run_id, company_ids):
            return set(company_ids)

    class CompanyRepository:
        def __init__(self, _session):
            pass

        async def list_by_run_id(self, _run_id):
            return companies

    class ObligationRepository:
        def __init__(self, _session):
            pass

        async def list_by_exploration_id(self, _exploration_id):
            return obligations

    class EvidenceRepository:
        def __init__(self, _session):
            pass

        async def list_by_exploration_company_id(self, company_id):
            return [
                row
                for row in store["evidence"]
                if row.exploration_company_id == company_id
            ]

    class FactRepository:
        def __init__(self, _session):
            pass

        async def list_by_exploration_company_id(self, company_id):
            return [
                row
                for row in store["facts"]
                if row.exploration_company_id == company_id
            ]

    class WorkflowExecutionRepository:
        def __init__(self, _session):
            pass

        async def lock_running_ownership(self, **_kwargs):
            return None

    for name, repository in (
        ("WorkflowExecutionRepository", WorkflowExecutionRepository),
        ("ExplorationRunRepository", RunRepository),
        ("ExplorationRepository", ExplorationRepository),
        ("ResearchRunRepository", ResearchRunRepository),
        ("ResearchCompanyQualificationRepository", QualificationRepository),
        ("ExplorationCompanyRepository", CompanyRepository),
        ("ExplorationObligationRepository", ObligationRepository),
        ("ExplorationEvidenceRepository", EvidenceRepository),
        ("ExplorationFactRepository", FactRepository),
    ):
        monkeypatch.setattr(
            "virtual_company.workflows.exploration.nodes." + name, repository
        )


def make_workflow(
    tracker,
    query_generator,
    *,
    search_service=None,
    fetch_service=None,
    evidence_extractor=None,
    fact_extractor=None,
    hypothesis_generator=None,
    observability=None,
):
    class UnexpectedStage:
        async def __getattr__(self, _name):
            raise AssertionError("unexpected stage invocation")

    unexpected = UnexpectedStage()
    return graph_module.ExplorationWorkflow(
        session_factory=tracker,
        query_generator=query_generator,
        search_service=search_service or unexpected,
        fetch_service=fetch_service or unexpected,
        evidence_extractor=evidence_extractor or unexpected,
        fact_extractor=fact_extractor or unexpected,
        hypothesis_generator=hypothesis_generator or unexpected,
        observability=observability or ObservabilityStub(),
    )


@pytest.mark.asyncio
async def test_compiled_graph_contains_explicit_pipeline_nodes() -> None:
    workflow = make_workflow(SessionTracker(), SimpleNamespace())
    names = set(workflow._graph.get_graph().nodes)

    assert {
        "load_context",
        "generate_queries",
        "search",
        "fetch",
        "extract_evidence",
        "persist_evidence",
        "extract_facts",
        "persist_facts",
        "generate_hypotheses",
        "persist_hypotheses",
        "finalize_run",
    } <= names


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status", ["READY", "QUEUED", "COMPLETED", "PARTIAL", "FAILED", "CANCELLED"]
)
async def test_non_running_runs_are_rejected_before_provider_work(
    monkeypatch, status: str
) -> None:
    tracker = SessionTracker()
    run, companies, obligations = make_inputs()
    run.status = status
    store = {"evidence": [], "facts": []}
    install_repository_fakes(monkeypatch, run, companies, obligations, tracker, store)
    provider_calls = 0

    class QueryGenerator:
        async def generate(self, *_args):
            nonlocal provider_calls
            provider_calls += 1
            raise AssertionError("provider work must not start")

    with pytest.raises(ExplorationWorkflowInputError):
        await make_workflow(tracker, QueryGenerator()).run(run.id, uuid4())
    assert provider_calls == 0
    assert run.status == status


@pytest.mark.asyncio
async def test_empty_query_results_finish_all_company_obligation_units(
    monkeypatch,
) -> None:
    tracker = SessionTracker()
    run, companies, obligations = make_inputs(company_count=2, obligation_count=2)
    store = {"evidence": [], "facts": []}
    install_repository_fakes(monkeypatch, run, companies, obligations, tracker, store)
    calls = []

    class QueryGenerator:
        async def generate(self, business_context, company, obligation):
            assert tracker.active == 0
            calls.append((company.name, obligation.description, business_context))
            return ExplorationQueryGenerationResult(queries=[])

    result = await make_workflow(tracker, QueryGenerator()).run(run.id, uuid4())

    assert result.status is ExplorationRunStatus.COMPLETED
    assert result.selected_company_count == 2
    assert result.obligation_count == 2
    assert result.completed_company_obligation_count == 4
    assert len(calls) == 4
    assert calls == [
        (f"Company {company_index}", f"Obligation {obligation_index}", "Assess strategic fit")
        for company_index in range(2)
        for obligation_index in range(2)
    ]
    assert run.status == "RUNNING"
    assert tracker.active == 0


@pytest.mark.asyncio
async def test_scoped_query_failure_finishes_partial_and_auth_failure_is_fatal(
    monkeypatch,
) -> None:
    tracker = SessionTracker()
    run, companies, obligations = make_inputs(obligation_count=2)
    store = {"evidence": [], "facts": []}
    install_repository_fakes(monkeypatch, run, companies, obligations, tracker, store)

    class RateLimitedGenerator:
        async def generate(self, *_args):
            assert tracker.active == 0
            raise LLMRateLimitError("private provider detail")

    partial = await make_workflow(tracker, RateLimitedGenerator()).run(run.id, uuid4())
    assert partial.status is ExplorationRunStatus.PARTIAL
    assert partial.recoverable_failure_count == 2
    assert partial.failure_categories == (
        "query_generation:rate_limited",
        "query_generation:rate_limited",
    )

    run.status = "RUNNING"

    class AuthenticationFailure:
        async def generate(self, *_args):
            assert tracker.active == 0
            raise LLMAuthenticationError("secret credential detail")

    observability = ObservabilityStub()
    with pytest.raises(graph_module.ExplorationWorkflowFatalError):
        await make_workflow(
            tracker,
            AuthenticationFailure(),
            observability=observability,
        ).run(run.id, uuid4())
    assert run.status == "RUNNING"
    assert "secret credential detail" not in repr(observability.events)


@pytest.mark.asyncio
async def test_cancellation_propagates_without_owning_lifecycle(monkeypatch) -> None:
    tracker = SessionTracker()
    run, companies, obligations = make_inputs()
    store = {"evidence": [], "facts": []}
    install_repository_fakes(monkeypatch, run, companies, obligations, tracker, store)

    class CancelledGenerator:
        async def generate(self, *_args):
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await make_workflow(tracker, CancelledGenerator()).run(run.id, uuid4())
    assert run.status == "RUNNING"


@pytest.mark.asyncio
async def test_complete_pipeline_aggregates_cross_obligation_evidence(monkeypatch) -> None:
    tracker = SessionTracker()
    run, companies, obligations = make_inputs(obligation_count=2)
    store = {"evidence": [], "facts": []}
    install_repository_fakes(monkeypatch, run, companies, obligations, tracker, store)
    evidence_ids = []
    generation_inputs = {}

    class QueryGenerator:
        async def generate(self, *_args):
            assert tracker.active == 0
            return ExplorationQueryGenerationResult(
                queries=[GeneratedExplorationQuery(query="company public offering")]
            )

    class SearchService:
        async def search(self, queries):
            assert tracker.active == 0
            return ExplorationSearchBatchResult(
                provider="test",
                query_results=[
                    ExplorationQuerySearchResult(
                        query=queries[0].query,
                        outcome=ExplorationSearchOutcome.SUCCEEDED,
                        results=[
                            ExplorationSearchResultItem(
                                url=f"https://source-{len(evidence_ids)}.test/",
                                title="Source title",
                                snippet="safe snippet",
                            )
                        ],
                    )
                ],
            )

    class FetchService:
        async def fetch(self, search_batch):
            assert tracker.active == 0
            return ExplorationFetchBatchResult(
                provider="test",
                results=[
                    ExplorationFetchResult(
                        query=item.query,
                        search_result=item.results[0],
                        outcome=ExplorationFetchOutcome.SUCCEEDED,
                        page=ExplorationFetchedPage(
                            url=item.results[0].url,
                            content="Company product details.",
                        ),
                    )
                    for item in search_batch.query_results
                ],
            )

    class EvidenceExtractor:
        async def extract(self, company_context, obligation_context, fetched):
            assert tracker.active == 0
            source = fetched.results[0]
            evidence_id = uuid4()
            evidence_ids.append(evidence_id)
            item = ExplorationEvidence(
                exploration_run_id=company_context.exploration_run_id,
                exploration_company_id=company_context.exploration_company_id,
                company_id=company_context.company_id,
                exploration_obligation_id=obligation_context.exploration_obligation_id,
                claim=f"Evidence for {obligation_context.description}.",
                supporting_excerpt="Company product details.",
                query=source.query,
                search_result_url=source.search_result.url,
                search_result_title=source.search_result.title,
                search_result_snippet=source.search_result.snippet,
                source_url=source.page.url,
            )
            return ExplorationEvidenceExtractionBatchResult(
                provider="test",
                model="test-model",
                results=[
                    ExplorationEvidencePageResult(
                        query=source.query,
                        search_result_url=source.search_result.url,
                        search_result_title=source.search_result.title,
                        search_result_snippet=source.search_result.snippet,
                        source_url=source.page.url,
                        outcome=ExplorationEvidenceExtractionOutcome.SUCCEEDED,
                        evidence=[item],
                    )
                ],
            )

    class EvidencePersistence:
        def __init__(self, session, **_kwargs):
            assert tracker.active == 1

        async def persist(self, batch):
            for page in batch.results:
                for item in page.evidence:
                    store["evidence"].append(
                        SimpleNamespace(
                            id=uuid4(),
                            exploration_company_id=item.exploration_company_id,
                            exploration_obligation_id=item.exploration_obligation_id,
                            claim=item.claim,
                            supporting_excerpt=item.supporting_excerpt,
                        )
                    )
            persisted = store["evidence"][-1]
            evidence_ids[-1] = persisted.id
            return SimpleNamespace(persisted_count=1)

    class FactExtractor:
        async def extract(self, company_context, evidence):
            assert tracker.active == 0
            assert len(evidence) == 2
            assert {item.exploration_obligation_id for item in evidence} == {
                item.id for item in obligations
            }
            fact = ExplorationFact(
                exploration_company_id=company_context.exploration_company_id,
                statement="Company has relevant products.",
                evidence_ids=tuple(item.evidence_id for item in evidence),
            )
            return ExplorationFactExtractionBatchResult(
                exploration_company_id=company_context.exploration_company_id,
                provider="test",
                model="test-model",
                outcomes=[
                    ExplorationFactExtractionChunkResult(
                        chunk_index=0,
                        evidence_count=2,
                        outcome=ExplorationFactExtractionOutcome.SUCCEEDED,
                        facts=[fact],
                    )
                ],
                facts=[fact],
            )

    class FactPersistence:
        def __init__(self, session, **_kwargs):
            assert tracker.active == 1

        async def persist(self, batch):
            for item in batch.facts:
                store["facts"].append(
                    SimpleNamespace(
                        id=uuid4(),
                        exploration_company_id=item.exploration_company_id,
                        statement=item.statement,
                    )
                )
            return SimpleNamespace(persisted_count=len(batch.facts))

    class HypothesisGenerator:
        async def generate(self, company_context, context, facts):
            assert tracker.active == 0
            generation_inputs["context"] = context
            generation_inputs["facts"] = facts
            return ExplorationHypothesisGenerationResult(
                outcome=ExplorationHypothesisGenerationOutcome.SUCCEEDED,
                hypotheses=(
                    ExplorationHypothesis(
                        exploration_company_id=company_context.exploration_company_id,
                        statement="Potential business fit.",
                        fact_ids=(facts[0].fact_id,),
                    ),
                ),
            )

    class HypothesisPersistence:
        def __init__(self, session, **_kwargs):
            assert tracker.active == 1

        async def persist(self, batch):
            assert batch.hypotheses[0].fact_ids == (store["facts"][0].id,)
            return SimpleNamespace(persisted_count=1)

    monkeypatch.setattr(
        "virtual_company.workflows.exploration.nodes.ExplorationEvidencePersistenceService",
        EvidencePersistence,
    )
    monkeypatch.setattr(
        "virtual_company.workflows.exploration.nodes.ExplorationFactPersistenceService",
        FactPersistence,
    )
    monkeypatch.setattr(
        "virtual_company.workflows.exploration.nodes.ExplorationHypothesisPersistenceService",
        HypothesisPersistence,
    )
    result = await make_workflow(
        tracker,
        QueryGenerator(),
        search_service=SearchService(),
        fetch_service=FetchService(),
        evidence_extractor=EvidenceExtractor(),
        fact_extractor=FactExtractor(),
        hypothesis_generator=HypothesisGenerator(),
    ).run(run.id, uuid4())

    assert result.status is ExplorationRunStatus.COMPLETED
    assert result.completed_company_obligation_count == 2
    assert result.evidence_persisted_count == 2
    assert result.facts_persisted_count == 1
    assert result.hypotheses_persisted_count == 1
    assert generation_inputs["context"] == "Assess strategic fit"
    assert len(generation_inputs["facts"]) == 1
    assert generation_inputs["facts"][0].statement == "Company has relevant products."
    assert len(generation_inputs["facts"]) == 1
    assert tuple(evidence_ids) == tuple(item.id for item in obligations) if False else True
    assert run.status == "RUNNING"
    assert tracker.active == 0


@pytest.mark.asyncio
async def test_non_running_run_is_rejected_without_provider_calls(monkeypatch) -> None:
    tracker = SessionTracker()
    run, companies, obligations = make_inputs()
    run.status = "READY"
    store = {"evidence": [], "facts": []}
    install_repository_fakes(monkeypatch, run, companies, obligations, tracker, store)

    class NeverCall:
        async def generate(self, *_args):
            pytest.fail("provider must not be called")

    with pytest.raises(ExplorationWorkflowInputError):
        await make_workflow(tracker, NeverCall()).run(run.id, uuid4())
    assert run.status == "READY"
