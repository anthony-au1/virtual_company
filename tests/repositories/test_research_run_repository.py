"""Compact run-list query contract."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from virtual_company.db.models import Campaign, ResearchRun
from virtual_company.repositories.research_run import ResearchRunRepository


@pytest.mark.asyncio
async def test_list_with_summary_uses_one_grouped_query() -> None:
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock()
    run = ResearchRun(
        id=uuid4(),
        campaign_id=uuid4(),
        status="COMPLETED",
        companies_found=1,
        created_at=datetime.now(UTC),
    )
    campaign = Campaign(
        id=run.campaign_id,
        name="Australian Fintech",
        target_count=5,
        status="COMPLETED",
        technologies=[],
    )
    result_proxy = MagicMock()
    result_proxy.all.return_value = [(run, campaign, 1, 1, 0, 0, 1, 0, 0)]
    session.execute.return_value = result_proxy

    result = await ResearchRunRepository(session).list_with_summary()

    assert result == [
        (
            run,
            campaign,
            {
                "researched": 1,
                "qualified": 1,
                "not_qualified": 0,
                "insufficient_evidence": 0,
                "accepted": 1,
                "rejected": 0,
                "unreviewed": 0,
            },
        )
    ]
    session.execute.assert_awaited_once()
    statement = session.execute.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect())).lower()
    assert "group by research_run.id, campaign.id" in sql
    assert "left outer join company_qualifications" in sql
