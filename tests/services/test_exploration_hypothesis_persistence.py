"""Persistence contracts for final validated Exploration Hypotheses."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from virtual_company.db.models import ExplorationHypothesis as PersistedHypothesis
from virtual_company.domain.exploration.hypotheses import ExplorationHypothesis
from virtual_company.repositories.dtos import ExplorationHypothesisCreate
from virtual_company.services.exploration_hypothesis_generator import (
    ExplorationHypothesisGenerationResult,
)
from virtual_company.services.exploration_hypothesis_persistence import (
    ExplorationHypothesisPersistenceService,
)
from virtual_company.workflows.exploration.models import (
    ExplorationHypothesisGenerationFailureCategory as FailureCategory,
)
from virtual_company.workflows.exploration.models import (
    ExplorationHypothesisGenerationOutcome as Outcome,
)


class RepositoryStub:
    def __init__(self, *, fail_at: int | None = None) -> None:
        self.calls: list[ExplorationHypothesisCreate] = []
        self.created: list[PersistedHypothesis] = []
        self.fail_at = fail_at

    async def create(
        self, data: ExplorationHypothesisCreate
    ) -> PersistedHypothesis:
        self.calls.append(data)
        if self.fail_at == len(self.calls):
            raise ValueError("private repository validation message")
        saved = PersistedHypothesis(
            id=uuid4(),
            exploration_company_id=data.exploration_company_id,
            statement=data.statement,
        )
        self.created.append(saved)
        return saved


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


def hypothesis(
    company_id=None, statement: str = "May benefit from a local partner.", fact_ids=None
):
    return ExplorationHypothesis(
        exploration_company_id=company_id or uuid4(),
        statement=statement,
        fact_ids=tuple(fact_ids or (uuid4(),)),
    )


def batch(*hypotheses: ExplorationHypothesis, outcome=Outcome.SUCCEEDED):
    return ExplorationHypothesisGenerationResult(
        outcome=outcome,
        hypotheses=tuple(hypotheses),
        failure_category=(
            FailureCategory.TIMEOUT if outcome is Outcome.FAILED else None
        ),
    )


def service(repository: RepositoryStub | None = None):
    session = MagicMock(spec=AsyncSession)
    telemetry = ObservabilityStub()
    instance = ExplorationHypothesisPersistenceService(
        cast(AsyncSession, session), observability=cast(object, telemetry)
    )
    stub = repository or RepositoryStub()
    instance._hypotheses = stub
    return instance, stub, session, telemetry


@pytest.mark.asyncio
async def test_persists_one_hypothesis_with_one_fact_and_returns_entity() -> None:
    company_id, fact_id = uuid4(), uuid4()
    item = hypothesis(company_id, "First interpretation.", (fact_id,))
    instance, repository, _, telemetry = service()

    result = await instance.persist(batch(item))

    assert repository.calls == [
        ExplorationHypothesisCreate(
            exploration_company_id=company_id,
            statement="First interpretation.",
            fact_ids=[fact_id],
        )
    ]
    assert result.input_count == result.persisted_count == 1
    assert result.hypotheses == tuple(repository.created)
    assert result.hypotheses[0].statement == item.statement
    assert result.generation_outcome is Outcome.SUCCEEDED
    assert result.failure_category is None
    completed = next(
        data for name, data in telemetry.events
        if name == "exploration_hypothesis_persistence_completed"
    )
    assert completed["capability"] == "exploration_hypothesis_persistence"
    assert completed["input_hypothesis_count"] == 1
    assert completed["persisted_count"] == 1
    assert completed["outcome"] == Outcome.SUCCEEDED.value
    assert isinstance(completed["duration_ms"], int)


@pytest.mark.asyncio
async def test_persists_all_fact_ids_and_multiple_hypotheses_in_input_order() -> None:
    company_id = uuid4()
    first = hypothesis(company_id, "First.", (uuid4(), uuid4()))
    second = hypothesis(company_id, "Second.", (uuid4(),))
    instance, repository, _, _ = service()

    result = await instance.persist(batch(first, second))

    assert [call.statement for call in repository.calls] == ["First.", "Second."]
    assert repository.calls[0].fact_ids == list(first.fact_ids)
    assert repository.calls[1].fact_ids == list(second.fact_ids)
    assert [saved.statement for saved in result.hypotheses] == ["First.", "Second."]
    assert result.input_count == result.persisted_count == 2


@pytest.mark.asyncio
async def test_successful_empty_generation_is_a_noop() -> None:
    instance, repository, session, telemetry = service()

    result = await instance.persist(batch())

    assert result.input_count == result.persisted_count == 0
    assert result.hypotheses == ()
    assert repository.calls == []
    assert result.generation_outcome is Outcome.SUCCEEDED
    assert [name for name, _ in telemetry.events] == [
        "exploration_hypothesis_persistence_started",
        "exploration_hypothesis_persistence_completed",
    ]
    session.commit.assert_not_called()
    session.rollback.assert_not_called()


@pytest.mark.asyncio
async def test_failed_generation_never_persists_partial_hypotheses() -> None:
    partial = hypothesis(statement="Must not be written.")
    instance, repository, _, telemetry = service()

    result = await instance.persist(batch(partial, outcome=Outcome.FAILED))

    assert result.input_count == 1
    assert result.persisted_count == 0
    assert result.hypotheses == ()
    assert result.generation_outcome is Outcome.FAILED
    assert result.failure_category is FailureCategory.TIMEOUT
    assert repository.calls == []
    assert "exploration_hypothesis_persistence_failed" in str(telemetry.events)


@pytest.mark.asyncio
async def test_failed_generation_with_no_hypotheses_is_not_reported_as_success():
    instance, repository, _, telemetry = service()

    result = await instance.persist(batch(outcome=Outcome.FAILED))

    assert result.input_count == result.persisted_count == 0
    assert result.hypotheses == ()
    assert result.generation_outcome is Outcome.FAILED
    assert result.failure_category is FailureCategory.TIMEOUT
    assert repository.calls == []
    failed = next(
        data for name, data in telemetry.events
        if name == "exploration_hypothesis_persistence_failed"
    )
    assert failed["outcome"] == Outcome.FAILED.value
    assert failed["persisted_count"] == 0


@pytest.mark.asyncio
async def test_repository_validation_exception_propagates_without_transaction_control():
    instance, repository, session, telemetry = service(RepositoryStub(fail_at=1))
    private_statement = "Sensitive hypothesis statement."

    with pytest.raises(ValueError, match="private repository validation message"):
        await instance.persist(batch(hypothesis(statement=private_statement)))

    assert len(repository.calls) == 1
    session.commit.assert_not_called()
    session.rollback.assert_not_called()
    logged = str(telemetry.events)
    assert "exploration_hypothesis_persistence_failed" in logged
    assert "repository_error" in logged
    assert "private repository validation message" not in logged
    assert private_statement not in logged


@pytest.mark.asyncio
async def test_failure_after_prior_repository_success_propagates_without_partial_result():
    repository = RepositoryStub(fail_at=2)
    instance, _, session, telemetry = service(repository)
    supplied = batch(
        hypothesis(statement="First persisted inside caller transaction."),
        hypothesis(statement="Second call fails."),
    )

    with pytest.raises(ValueError):
        await instance.persist(supplied)

    assert len(repository.calls) == 2
    assert len(repository.created) == 1
    assert session.commit.call_count == 0
    assert session.rollback.call_count == 0
    failed_event = next(
        data for name, data in telemetry.events
        if name == "exploration_hypothesis_persistence_failed"
    )
    assert failed_event["persisted_count"] == 1


def test_service_has_no_generator_llm_or_direct_association_write_dependencies() -> None:
    source = (
        Path(__file__).parents[2]
        / "src/virtual_company/services/exploration_hypothesis_persistence.py"
    ).read_text()
    assert "ExplorationHypothesisGenerator(" not in source
    assert "generate_structured" not in source
    assert "ExplorationHypothesisRepository" in source
    assert "exploration_hypothesis_fact" not in source
    assert "select(" not in source
    assert "ExplorationFactRepository" not in source
    assert "commit(" not in source
    assert "rollback(" not in source
    assert "virtual_company.research" not in source
    assert "workflows.research" not in source
