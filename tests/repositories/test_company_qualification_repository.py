"""Atomic snapshot upsert contract."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from virtual_company.repositories.company_qualification import (
    CompanyQualificationRepository,
)
from virtual_company.repositories.dtos import CompanyQualificationUpsert


@pytest.mark.asyncio
async def test_upsert_updates_only_snapshot_payload() -> None:
    session = MagicMock(spec=AsyncSession)
    session.scalars = AsyncMock(return_value=MagicMock())
    data = CompanyQualificationUpsert(
        research_run_id=uuid4(),
        campaign_id=uuid4(),
        company_id=uuid4(),
        status="QUALIFIED",
        criteria_results={"criteria": []},
    )
    result = await CompanyQualificationRepository(session).upsert(data)
    assert result is session.scalars.return_value.one.return_value
    statement = session.scalars.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert (
        "ON CONFLICT ON CONSTRAINT uq_company_qualifications_run_company DO UPDATE SET status = excluded.status, criteria_results = excluded.criteria_results"
        in sql
    )
    assert "RETURNING company_qualifications.id" in sql
    session.commit.assert_not_called()
