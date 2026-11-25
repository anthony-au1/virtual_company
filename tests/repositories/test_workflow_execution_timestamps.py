"""Workflow execution updates maintain the standard update timestamp."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from virtual_company.repositories.workflow_execution import (
    WorkflowExecutionRepository,
    WorkflowExecutionStatus,
)


def _sql(statement: object) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))


@pytest.mark.asyncio
async def test_heartbeat_updates_both_liveness_and_standard_timestamp() -> None:
    execution_id = uuid4()
    session = MagicMock(spec=AsyncSession)
    session.scalar = AsyncMock(return_value=execution_id)

    updated = await WorkflowExecutionRepository(session).heartbeat(execution_id)

    assert updated is True
    sql = _sql(session.scalar.await_args.args[0])
    assert "heartbeat_at=now()" in sql
    assert "updated_at=now()" in sql


@pytest.mark.asyncio
async def test_claim_updates_execution_and_business_run_timestamps() -> None:
    run_id = uuid4()
    execution = SimpleNamespace(
        id=uuid4(), workflow_type="research", run_id=run_id, status="RUNNING"
    )
    session = MagicMock(spec=AsyncSession)
    session.scalar = AsyncMock(side_effect=[execution, run_id])

    await WorkflowExecutionRepository(session).claim("research", run_id)

    statements = [call.args[0] for call in session.scalar.await_args_list]
    assert len(statements) == 2
    assert all("updated_at=now()" in _sql(statement) for statement in statements)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [
        WorkflowExecutionStatus.COMPLETED,
        WorkflowExecutionStatus.PARTIAL,
        WorkflowExecutionStatus.FAILED,
        WorkflowExecutionStatus.CANCELLED,
    ],
)
async def test_terminal_transition_updates_execution_and_business_run_timestamps(
    status: WorkflowExecutionStatus,
) -> None:
    execution_id = uuid4()
    run_id = uuid4()
    execution = SimpleNamespace(
        id=execution_id,
        workflow_type="exploration",
        run_id=run_id,
        status="RUNNING",
    )
    session = MagicMock(spec=AsyncSession)
    session.scalar = AsyncMock(side_effect=[execution, run_id])

    updated = await WorkflowExecutionRepository(session).transition(
        execution_id, status
    )

    assert updated is True
    statements = [call.args[0] for call in session.scalar.await_args_list]
    assert len(statements) == 2
    assert all("updated_at=now()" in _sql(statement) for statement in statements)
