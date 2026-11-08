"""Stable ordering for data consumed by Exploration generation stages."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from virtual_company.repositories.exploration_company import (
    ExplorationCompanyRepository,
)
from virtual_company.repositories.exploration_evidence import (
    ExplorationEvidenceRepository,
)
from virtual_company.repositories.exploration_fact import ExplorationFactRepository
from virtual_company.repositories.exploration_hypothesis import (
    ExplorationHypothesisRepository,
)
from virtual_company.repositories.exploration_obligation import (
    ExplorationObligationRepository,
)


def _session_with_rows(rows):
    session = MagicMock(spec=AsyncSession)
    session.scalars = AsyncMock(return_value=rows)
    return session


@pytest.mark.asyncio
async def test_company_links_are_ordered_by_id():
    session = _session_with_rows([])

    assert await ExplorationCompanyRepository(session).list_by_run_id(uuid4()) == []

    sql = str(session.scalars.await_args.args[0].compile(dialect=postgresql.dialect()))
    assert "ORDER BY exploration_company.id ASC" in sql


@pytest.mark.asyncio
async def test_obligations_are_ordered_by_creation_then_id():
    session = _session_with_rows([])

    result = await ExplorationObligationRepository(session).list_by_exploration_id(
        uuid4()
    )

    assert result == []
    sql = str(session.scalars.await_args.args[0].compile(dialect=postgresql.dialect()))
    assert "ORDER BY exploration_obligation.created_at ASC, exploration_obligation.id ASC" in sql


@pytest.mark.asyncio
async def test_company_evidence_includes_all_obligations_in_stable_order():
    company_link_id = uuid4()
    evidence = [
        SimpleNamespace(exploration_obligation_id=uuid4()),
        SimpleNamespace(exploration_obligation_id=uuid4()),
    ]
    session = _session_with_rows(evidence)

    result = await ExplorationEvidenceRepository(
        session
    ).list_by_exploration_company_id(company_link_id)

    assert result == evidence
    sql = str(session.scalars.await_args.args[0].compile(dialect=postgresql.dialect()))
    assert "exploration_evidence.exploration_company_id =" in sql
    assert "exploration_obligation_id" not in sql.split("WHERE", 1)[-1]
    assert "ORDER BY exploration_evidence.created_at ASC, exploration_evidence.id ASC" in sql


@pytest.mark.asyncio
async def test_facts_are_company_scoped_and_ordered_by_creation_then_id():
    company_link_id = uuid4()
    facts = [SimpleNamespace(id=uuid4(), statement="Fact")]
    session = _session_with_rows(facts)

    result = await ExplorationFactRepository(
        session
    ).list_by_exploration_company_id(company_link_id)

    assert result == facts
    sql = str(session.scalars.await_args.args[0].compile(dialect=postgresql.dialect()))
    assert "exploration_fact.exploration_company_id =" in sql
    assert "ORDER BY exploration_fact.created_at ASC, exploration_fact.id ASC" in sql


@pytest.mark.asyncio
async def test_fact_result_query_eager_loads_evidence_relationships():
    session = _session_with_rows([])

    await ExplorationFactRepository(session).list_by_exploration_company_id(uuid4())

    statement = session.scalars.await_args.args[0]
    assert any("ExplorationFact.evidence" in str(option.path) for option in statement._with_options)


@pytest.mark.asyncio
async def test_hypothesis_result_query_eager_loads_fact_relationships():
    session = _session_with_rows([])

    await ExplorationHypothesisRepository(session).list_by_exploration_company_id(
        uuid4()
    )

    statement = session.scalars.await_args.args[0]
    assert any(
        "ExplorationHypothesis.facts" in str(option.path)
        for option in statement._with_options
    )
