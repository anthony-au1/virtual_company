"""Tests for mapping final validated Facts into repository creates."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from virtual_company.db.models import ExplorationFact as PersistedFact
from virtual_company.domain.exploration.facts import ExplorationFact
from virtual_company.repositories.dtos import ExplorationFactCreate
from virtual_company.services.exploration_fact_persistence import (
    ExplorationFactPersistenceService,
)
from virtual_company.workflows.exploration.models import (
    ExplorationFactExtractionBatchResult,
    ExplorationFactExtractionChunkResult,
    ExplorationFactExtractionFailureCategory,
    ExplorationFactExtractionOutcome,
)


class RepositoryStub:
    def __init__(self, *, fail_at: int | None = None) -> None:
        self.calls: list[ExplorationFactCreate] = []
        self.created: list[PersistedFact] = []
        self.fail_at = fail_at

    async def create(self, data: ExplorationFactCreate) -> PersistedFact:
        self.calls.append(data)
        if self.fail_at == len(self.calls):
            raise RuntimeError("private database error")
        result = PersistedFact(
            id=uuid4(),
            exploration_company_id=data.exploration_company_id,
            statement=data.statement,
        )
        self.created.append(result)
        return result


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


def fact(statement: str = "Acme offers payments.", *, evidence_ids=None):
    return ExplorationFact(
        exploration_company_id=uuid4(),
        statement=statement,
        evidence_ids=tuple(evidence_ids or [uuid4()]),
    )


def batch(*facts: ExplorationFact, outcomes=None):
    return ExplorationFactExtractionBatchResult(
        exploration_company_id=uuid4(),
        provider="test-provider",
        model="test-model",
        outcomes=list(outcomes or []),
        facts=list(facts),
    )


def service(repository: RepositoryStub | None = None):
    session = MagicMock(spec=AsyncSession)
    observability = ObservabilityStub()
    instance = ExplorationFactPersistenceService(
        cast(AsyncSession, session), observability=cast(object, observability)
    )
    stub = repository or RepositoryStub()
    instance._facts = stub
    return instance, stub, session, observability


@pytest.mark.asyncio
async def test_persists_domain_facts_in_order_with_all_evidence_ids() -> None:
    support_one, support_two, support_three = uuid4(), uuid4(), uuid4()
    first = fact("First statement.", evidence_ids=[support_one, support_two])
    second = fact("Second statement.", evidence_ids=[support_three])
    instance, repository, _, _ = service()

    result = await instance.persist(batch(first, second))

    assert [call.statement for call in repository.calls] == [
        "First statement.",
        "Second statement.",
    ]
    assert [call.exploration_company_id for call in repository.calls] == [
        first.exploration_company_id,
        second.exploration_company_id,
    ]
    assert repository.calls[0].evidence_ids == [support_one, support_two]
    assert repository.calls[1].evidence_ids == [support_three]
    assert result.input_count == result.persisted_count == 2
    assert result.facts == tuple(repository.created)
    assert [saved.statement for saved in result.facts] == [
        "First statement.",
        "Second statement.",
    ]


@pytest.mark.asyncio
async def test_uses_final_batch_facts_and_ignores_failed_chunk_outcomes() -> None:
    final_fact = fact("Successful chunk fact.")
    chunk_only_fact = fact("Must not be separately persisted.")
    outcomes = [
        ExplorationFactExtractionChunkResult(
            chunk_index=0, evidence_count=1,
            outcome=ExplorationFactExtractionOutcome.SUCCEEDED,
            facts=[final_fact],
        ),
        ExplorationFactExtractionChunkResult(
            chunk_index=1, evidence_count=1,
            outcome=ExplorationFactExtractionOutcome.FAILED,
            facts=[chunk_only_fact],
            failure_category=ExplorationFactExtractionFailureCategory.TIMEOUT,
        ),
    ]
    instance, repository, _, _ = service()

    await instance.persist(batch(final_fact, outcomes=outcomes))

    assert [call.statement for call in repository.calls] == [
        "Successful chunk fact."
    ]


@pytest.mark.asyncio
async def test_empty_batch_returns_zero_counts_without_repository_call() -> None:
    instance, repository, session, _ = service()

    result = await instance.persist(batch())

    assert (result.input_count, result.persisted_count, result.facts) == (0, 0, ())
    assert repository.calls == []
    session.commit.assert_not_called()
    session.rollback.assert_not_called()


@pytest.mark.asyncio
async def test_duplicate_facts_are_created_without_deduplication_or_input_mutation() -> None:
    duplicate = fact("Repeated statement.")
    supplied = batch(duplicate, duplicate)
    original_facts = list(supplied.facts)
    instance, repository, _, _ = service()

    result = await instance.persist(supplied)

    assert len(repository.calls) == result.persisted_count == 2
    assert repository.calls[0] == repository.calls[1]
    assert supplied.facts == original_facts


@pytest.mark.asyncio
async def test_separate_calls_create_new_fact_rows() -> None:
    instance, repository, _, _ = service()
    supplied = batch(fact("Repeated across calls."))

    first = await instance.persist(supplied)
    second = await instance.persist(supplied)

    assert len(repository.calls) == 2
    assert first.facts[0].id != second.facts[0].id


@pytest.mark.asyncio
async def test_repository_failure_propagates_without_retry_or_transaction_control() -> None:
    instance, repository, session, _ = service(RepositoryStub(fail_at=2))

    with pytest.raises(RuntimeError, match="private database error"):
        await instance.persist(batch(fact("First."), fact("Second.")))

    assert len(repository.calls) == 2
    session.commit.assert_not_called()
    session.rollback.assert_not_called()


@pytest.mark.asyncio
async def test_observability_contains_counts_but_no_fact_or_exception_text() -> None:
    sensitive_statement = "Secret acquisition revenue is 42 million."
    instance, _, _, observability = service(RepositoryStub(fail_at=1))

    with pytest.raises(RuntimeError):
        await instance.persist(batch(fact(sensitive_statement)))

    logged = str(observability.events)
    assert "exploration_fact_persistence_started" in logged
    assert "exploration_fact_persistence_failed" in logged
    assert sensitive_statement not in logged
    assert "private database error" not in logged
    assert "input_fact_count" in logged
    assert "supporting_evidence_reference_count" in logged


def test_service_has_no_research_hypothesis_or_orchestration_dependencies() -> None:
    source = (
        Path(__file__).parents[2]
        / "src/virtual_company/services/exploration_fact_persistence.py"
    ).read_text()
    assert "virtual_company.research" not in source
    assert "workflows.research" not in source
    assert "Hypothesis" not in source
    assert "ExplorationFactExtractor" not in source
    assert "ExplorationFactRepository" in source
