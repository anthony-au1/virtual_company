"""Tests for mapping validated Exploration Evidence into persistence records."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from virtual_company.db.models import ExplorationEvidence as PersistedEvidence
from virtual_company.domain.exploration.evidence import (
    ExplorationEvidence as DomainEvidence,
)
from virtual_company.repositories.dtos import ExplorationEvidenceCreate
from virtual_company.services.exploration_evidence_extractor import (
    ExplorationEvidenceExtractionBatchResult,
    ExplorationEvidenceExtractionOutcome,
    ExplorationEvidencePageResult,
)
from virtual_company.services.exploration_evidence_persistence import (
    ExplorationEvidencePersistenceService,
)


class RepositoryStub:
    def __init__(self, *, fail_at: int | None = None) -> None:
        self.calls: list[ExplorationEvidenceCreate] = []
        self.fail_at = fail_at

    async def create(self, data: ExplorationEvidenceCreate) -> PersistedEvidence:
        self.calls.append(data)
        if self.fail_at == len(self.calls):
            raise RuntimeError("private database error")
        return PersistedEvidence(**data.model_dump())


class ObservabilityStub:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []
        self.spans: list[str] = []

    def event(self, name: str, **metadata: object) -> None:
        self.events.append((name, metadata))

    @contextmanager
    def span(self, name: str, **_: object):
        self.spans.append(name)
        yield None


def evidence(
    *,
    company_id=None,
    obligation_id=None,
    claim: str = "The company offers payments.",
    excerpt: str = "It offers payments.",
    requested_url: str = "https://example.com/requested",
    final_url: str | None = "https://example.com/final",
    source_title: str | None = "Fetched title",
    query: str = "company payment services",
) -> DomainEvidence:
    return DomainEvidence(
        exploration_run_id=uuid4(),
        exploration_company_id=company_id or uuid4(),
        company_id=uuid4(),
        exploration_obligation_id=obligation_id or uuid4(),
        claim=claim,
        supporting_excerpt=excerpt,
        query=query,
        search_result_url="https://search.example/result",
        search_result_title="Search result title",
        search_result_snippet="Search snippet",
        source_url=requested_url,
        final_url=final_url,
        source_title=source_title,
    )


def page_result(
    *items: DomainEvidence,
    outcome: ExplorationEvidenceExtractionOutcome = (
        ExplorationEvidenceExtractionOutcome.SUCCEEDED
    ),
    query: str = "company payment services",
) -> ExplorationEvidencePageResult:
    return ExplorationEvidencePageResult(
        query=query,
        search_result_url="https://search.example/result",
        search_result_title="Search result title",
        search_result_snippet="Search snippet",
        source_url="https://example.com/requested",
        final_url="https://example.com/final",
        source_title="Fetched title",
        outcome=outcome,
        evidence=list(items),
    )


def batch(*results: ExplorationEvidencePageResult):
    return ExplorationEvidenceExtractionBatchResult(
        provider="test-provider", model="test-model", results=list(results)
    )


def service(repository: RepositoryStub | None = None):
    session = MagicMock(spec=AsyncSession)
    observability = ObservabilityStub()
    instance = ExplorationEvidencePersistenceService(
        cast(AsyncSession, session), observability=cast(object, observability)
    )
    stub = repository or RepositoryStub()
    instance._evidence = stub
    return instance, stub, session, observability


@pytest.mark.asyncio
async def test_persist_maps_only_durable_domain_fields_and_redirect_urls() -> None:
    item = evidence()
    original = item.model_dump()
    instance, repository, _, _ = service()

    result = await instance.persist(batch(page_result(item)))

    assert result.input_count == result.unique_count == result.persisted_count == 1
    assert len(result.evidence) == 1
    saved = repository.calls[0]
    assert saved.exploration_company_id == item.exploration_company_id
    assert saved.exploration_obligation_id == item.exploration_obligation_id
    assert saved.claim == item.claim
    assert saved.supporting_excerpt == item.supporting_excerpt
    assert saved.source_url == item.final_url
    assert saved.requested_url == item.source_url
    assert saved.source_title == item.source_title
    assert set(type(saved).model_fields) == {
        "exploration_company_id",
        "exploration_obligation_id",
        "claim",
        "supporting_excerpt",
        "source_url",
        "requested_url",
        "source_title",
    }
    assert item.model_dump() == original


@pytest.mark.asyncio
async def test_url_mapping_omits_same_requested_url_and_falls_back_without_final_url() -> (
    None
):
    equal_urls = evidence(
        requested_url="https://example.com/same",
        final_url="https://example.com/same",
    )
    fallback = evidence(
        requested_url="https://example.com/original",
        final_url=None,
        source_title=None,
    )
    instance, repository, _, _ = service()

    await instance.persist(batch(page_result(equal_urls), page_result(fallback)))

    assert repository.calls[0].source_url == "https://example.com/same"
    assert repository.calls[0].requested_url is None
    assert repository.calls[1].source_url == "https://example.com/original"
    assert repository.calls[1].requested_url is None
    assert repository.calls[1].source_title is None


@pytest.mark.asyncio
async def test_only_successful_outcomes_are_persisted() -> None:
    successful = evidence()
    should_not_persist = evidence(claim="Failed page evidence.")
    instance, repository, _, _ = service()

    result = await instance.persist(
        batch(
            page_result(successful),
            page_result(),
            page_result(
                should_not_persist,
                outcome=ExplorationEvidenceExtractionOutcome.FAILED,
            ),
        )
    )

    assert result.input_count == 2
    assert result.unique_count == result.persisted_count == 1
    assert len(repository.calls) == 1
    assert repository.calls[0].claim == successful.claim


@pytest.mark.asyncio
async def test_empty_successful_or_failed_batch_persists_nothing() -> None:
    instance, repository, _, _ = service()

    result = await instance.persist(
        batch(
            page_result(),
            page_result(outcome=ExplorationEvidenceExtractionOutcome.FAILED),
        )
    )

    assert result.input_count == result.unique_count == result.persisted_count == 0
    assert result.evidence == ()
    assert repository.calls == []


@pytest.mark.asyncio
async def test_query_fanout_and_exact_duplicates_persist_once_in_first_seen_order() -> (
    None
):
    first = evidence(claim="First claim", excerpt="First excerpt")
    duplicate = first.model_copy(
        update={
            "query": "another query",
            "claim": " First   claim ",
            "supporting_excerpt": "First\nexcerpt",
        }
    )
    second = evidence(claim="Second claim", excerpt="Second excerpt")
    instance, repository, _, _ = service()

    result = await instance.persist(
        batch(
            page_result(first, query="query A"),
            page_result(second, query="query B"),
            page_result(duplicate, query="query C"),
        )
    )

    assert result.input_count == 3
    assert result.unique_count == result.persisted_count == 2
    assert [item.claim for item in repository.calls] == ["First claim", "Second claim"]


@pytest.mark.parametrize(
    "update",
    [
        {"exploration_company_id": uuid4()},
        {"exploration_obligation_id": uuid4()},
        {"final_url": "https://different.example/source"},
        {"claim": "Different claim"},
        {"supporting_excerpt": "Different excerpt"},
    ],
    ids=["company", "obligation", "source", "claim", "excerpt"],
)
@pytest.mark.asyncio
async def test_different_semantic_identity_is_not_deduplicated(update) -> None:
    original = evidence()
    different = original.model_copy(update=update)
    instance, repository, _, _ = service()

    result = await instance.persist(
        batch(page_result(original), page_result(different))
    )

    assert result.unique_count == result.persisted_count == 2
    assert len(repository.calls) == 2


@pytest.mark.asyncio
async def test_repository_failure_propagates_without_retry_or_commit() -> None:
    instance, repository, session, _ = service(RepositoryStub(fail_at=1))

    with pytest.raises(RuntimeError, match="private database error"):
        await instance.persist(batch(page_result(evidence())))

    assert len(repository.calls) == 1
    session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_observability_excludes_claim_excerpt_query_and_raw_error() -> None:
    secret_claim = "Private claim content."
    secret_excerpt = "Private source excerpt."
    secret_query = "Private query term."
    item = evidence(claim=secret_claim, excerpt=secret_excerpt, query=secret_query)
    observability = ObservabilityStub()
    instance, _, _, _ = service()
    instance._observability = observability

    await instance.persist(batch(page_result(item, query=secret_query)))

    logged = str(observability.events)
    assert secret_claim not in logged
    assert secret_excerpt not in logged
    assert secret_query not in logged
    assert "exploration_evidence_persistence_completed" in logged


def test_persistence_and_extractor_dependency_boundaries_remain_separate() -> None:
    services_dir = Path(__file__).parents[2] / "src/virtual_company/services"
    persistence_source = (
        services_dir / "exploration_evidence_persistence.py"
    ).read_text()
    extractor_source = (services_dir / "exploration_evidence_extractor.py").read_text()

    assert "virtual_company.research." not in persistence_source
    assert "virtual_company.workflows.research" not in persistence_source
    assert "ExplorationEvidenceRepository" not in extractor_source
    assert "exploration_evidence_persistence" not in extractor_source
