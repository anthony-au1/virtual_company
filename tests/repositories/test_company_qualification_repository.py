"""Atomic snapshot upsert contract."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from virtual_company.db.models import CompanyQualificationSnapshot
from virtual_company.domain.review import ReviewStatus
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


@pytest.mark.asyncio
async def test_update_review_status_changes_only_human_decision() -> None:
    session = MagicMock(spec=AsyncSession)
    session.scalar = AsyncMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    snapshot = CompanyQualificationSnapshot(
        research_run_id=uuid4(),
        campaign_id=uuid4(),
        company_id=uuid4(),
        status="INSUFFICIENT_EVIDENCE",
        review_status="UNREVIEWED",
        criteria_results={"criteria": []},
    )
    session.scalar.return_value = snapshot
    repository = CompanyQualificationRepository(session)

    result = await repository.update_review_status(
        research_run_id=snapshot.research_run_id,
        company_id=snapshot.company_id,
        review_status=ReviewStatus.ACCEPTED,
    )

    assert result is snapshot
    assert snapshot.review_status == "ACCEPTED"
    assert snapshot.status == "INSUFFICIENT_EVIDENCE"
    assert snapshot.criteria_results == {"criteria": []}
    session.flush.assert_awaited_once()
    session.refresh.assert_awaited_once_with(snapshot)
    session.commit.assert_not_called()


def test_review_status_has_unreviewed_application_and_database_defaults() -> None:
    column = CompanyQualificationSnapshot.__table__.c.review_status
    assert column.default.arg == "UNREVIEWED"
    assert column.server_default.arg == "UNREVIEWED"
