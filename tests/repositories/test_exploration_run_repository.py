"""ExplorationRun creation DTO validation."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from virtual_company.domain.exploration.run import ExplorationRunStatus
from virtual_company.repositories.dtos import ExplorationRunCreate, ExplorationRunUpdate
from virtual_company.repositories.exploration_run import (
    ExplorationRunClaimOutcome,
    ExplorationRunRepository,
    InvalidExplorationRunTransitionError,
)


def test_exploration_run_create_requires_research_run_id() -> None:
    with pytest.raises(ValidationError, match="research_run_id"):
        ExplorationRunCreate(exploration_id=uuid4(), status="RUNNING")


def test_exploration_run_create_accepts_research_run_id() -> None:
    exploration_id = uuid4()
    research_run_id = uuid4()

    run = ExplorationRunCreate(
        exploration_id=exploration_id,
        research_run_id=research_run_id,
        status="RUNNING",
    )

    assert run.exploration_id == exploration_id
    assert run.research_run_id == research_run_id


@pytest.mark.asyncio
async def test_summary_query_counts_companies_and_joins_research_campaign():
    exploration_id = uuid4()
    run = SimpleNamespace(
        id=uuid4(),
        exploration_id=exploration_id,
        research_run_id=uuid4(),
        status="RUNNING",
        started_at=datetime.now(UTC),
        completed_at=None,
    )
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock(
        return_value=SimpleNamespace(all=lambda: [(run, "Campaign name", 2)])
    )

    result = await ExplorationRunRepository(session).list_with_summary(exploration_id)

    assert result == [(run, "Campaign name", 2)]
    statement = session.execute.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "JOIN research_run" in sql
    assert "JOIN campaign" in sql
    assert "LEFT OUTER JOIN exploration_company" in sql
    assert "count(exploration_company.id)" in sql


def _session_with_execute_result(value):
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock(
        return_value=SimpleNamespace(scalar_one_or_none=lambda: value)
    )
    session.scalar = AsyncMock(return_value=None)
    return session


@pytest.mark.asyncio
async def test_claim_is_conditional_update_and_returns_claimed_run():
    run = SimpleNamespace(id=uuid4(), status="QUEUED")
    session = _session_with_execute_result(run)

    result = await ExplorationRunRepository(session).claim_for_execution(run.id)

    assert result.outcome is ExplorationRunClaimOutcome.CLAIMED
    assert result.run is run
    statement = session.execute.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "UPDATE exploration_run" in sql
    assert "exploration_run.status = %(status_1)s" in sql
    assert "RETURNING exploration_run" in sql
    assert session.commit.await_count == 0
    assert session.rollback.await_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("existing_id", "expected"),
    [
        (None, ExplorationRunClaimOutcome.NOT_FOUND),
        (uuid4(), ExplorationRunClaimOutcome.NOT_READY),
    ],
)
async def test_claim_failure_distinguishes_missing_and_not_ready(existing_id, expected):
    run_id = uuid4()
    session = _session_with_execute_result(None)
    session.scalar = AsyncMock(return_value=existing_id)

    result = await ExplorationRunRepository(session).claim_for_execution(run_id)

    assert result.outcome is expected
    assert result.run is None


@pytest.mark.asyncio
async def test_transition_updates_status_and_execution_timestamp():
    run_id = uuid4()
    run = SimpleNamespace(id=run_id, status="RUNNING")
    session = _session_with_execute_result(run)

    result = await ExplorationRunRepository(session).transition(
        run_id, ExplorationRunStatus.RUNNING
    )

    assert result is run
    statement = session.execute.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "UPDATE exploration_run" in sql
    assert "started_at" in sql
    assert "queued" in repr(compiled.params).lower()
    assert session.commit.await_count == 0
    assert session.rollback.await_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("target", "allowed"),
    [
        (ExplorationRunStatus.RUNNING, ("QUEUED",)),
        (ExplorationRunStatus.COMPLETED, ("RUNNING",)),
        (ExplorationRunStatus.PARTIAL, ("RUNNING",)),
        (ExplorationRunStatus.FAILED, ("QUEUED", "RUNNING")),
        (ExplorationRunStatus.CANCELLED, ("RUNNING",)),
    ],
)
async def test_transition_has_only_expected_predecessors(target, allowed):
    run_id = uuid4()
    run = SimpleNamespace(id=run_id, status=target.value)
    session = _session_with_execute_result(run)

    await ExplorationRunRepository(session).transition(run_id, target)

    compiled = session.execute.await_args.args[0].compile(
        dialect=postgresql.dialect()
    )
    for status in allowed:
        assert status.lower() in repr(compiled.params).lower()


@pytest.mark.asyncio
async def test_invalid_transition_raises_and_does_not_update():
    run_id = uuid4()
    session = _session_with_execute_result(None)
    session.scalar = AsyncMock(return_value="COMPLETED")

    with pytest.raises(InvalidExplorationRunTransitionError):
        await ExplorationRunRepository(session).transition(
            run_id, ExplorationRunStatus.RUNNING
        )

    sql = str(session.execute.await_args.args[0].compile(dialect=postgresql.dialect()))
    assert "completed" in sql


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("current_status", "target"),
    [
        ("QUEUED", ExplorationRunStatus.COMPLETED),
        ("COMPLETED", ExplorationRunStatus.COMPLETED),
        ("PARTIAL", ExplorationRunStatus.RUNNING),
        ("FAILED", ExplorationRunStatus.RUNNING),
        ("CANCELLED", ExplorationRunStatus.RUNNING),
    ],
)
async def test_disallowed_and_repeated_terminal_transitions_raise(
    current_status, target
):
    run_id = uuid4()
    session = _session_with_execute_result(None)
    session.scalar = AsyncMock(return_value=current_status)

    with pytest.raises(InvalidExplorationRunTransitionError):
        await ExplorationRunRepository(session).transition(run_id, target)


@pytest.mark.asyncio
async def test_generic_update_rejects_lifecycle_fields():
    repository = ExplorationRunRepository(MagicMock(spec=AsyncSession))

    with pytest.raises(ValueError, match="guarded transitions"):
        await repository.update(uuid4(), ExplorationRunUpdate(status="RUNNING"))

    with pytest.raises(ValueError, match="guarded transitions"):
        await repository.update(
            uuid4(), ExplorationRunUpdate(completed_at=datetime.now(UTC))
        )
