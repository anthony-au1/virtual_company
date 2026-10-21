"""ExplorationRun creation DTO validation."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from virtual_company.repositories.dtos import ExplorationRunCreate
from virtual_company.repositories.exploration_run import ExplorationRunRepository


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
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "JOIN research_run" in sql
    assert "JOIN campaign" in sql
    assert "LEFT OUTER JOIN exploration_company" in sql
    assert "count(exploration_company.id)" in sql
