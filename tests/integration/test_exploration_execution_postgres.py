"""Opt-in PostgreSQL verification for Phase 3 execution claims."""

import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateSchema, DropSchema

from virtual_company.config import DEFAULT_DATABASE_URL
from virtual_company.db import Base
from virtual_company.db.models import (
    Campaign,
    Exploration,
    ExplorationRun,
    ResearchRun,
)
from virtual_company.domain.exploration.run import ExplorationRunStatus
from virtual_company.repositories.exploration_run import (
    ExplorationRunClaimOutcome,
    ExplorationRunRepository,
)


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("RUN_EXPLORATION_DB_TESTS") != "true",
    reason="Opt-in local PostgreSQL Exploration execution test",
)
async def test_concurrent_execution_claims_are_atomic_and_committed() -> None:
    schema = f"test_exploration_execution_{uuid4().hex}"
    engine = create_async_engine(
        os.getenv("EXPLORATION_TEST_DATABASE_URL", DEFAULT_DATABASE_URL)
    )
    scoped_engine = engine.execution_options(schema_translate_map={None: schema})
    try:
        async with engine.begin() as connection:
            await connection.execute(CreateSchema(schema))
        async with scoped_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(scoped_engine, expire_on_commit=False)

        async with sessions.begin() as session:
            campaign = Campaign(
                name="Execution claim test",
                keywords=[],
                target_count=1,
                max_companies_to_research=1,
                status="COMPLETED",
            )
            session.add(campaign)
            await session.flush()
            research_run = ResearchRun(
                campaign_id=campaign.id, status="COMPLETED", companies_found=1
            )
            session.add(research_run)
            exploration = Exploration(
                business_context="Execution claim test",
                max_obligations=1,
                status="DRAFT",
            )
            session.add(exploration)
            await session.flush()
            run = ExplorationRun(
                exploration_id=exploration.id,
                research_run_id=research_run.id,
                status=ExplorationRunStatus.READY.value,
            )
            session.add(run)
            await session.flush()
            run_id = run.id

        async def claim_once():
            async with sessions() as session, session.begin():
                return await ExplorationRunRepository(session).claim_for_execution(
                    run_id
                )

        claims = await asyncio.gather(claim_once(), claim_once())
        assert (
            sum(claim.outcome is ExplorationRunClaimOutcome.CLAIMED for claim in claims)
            == 1
        )
        assert (
            sum(
                claim.outcome is ExplorationRunClaimOutcome.NOT_READY
                for claim in claims
            )
            == 1
        )

        async with sessions() as session:
            persisted_status = await session.scalar(
                select(ExplorationRun.status).where(ExplorationRun.id == run_id)
            )
        assert persisted_status == ExplorationRunStatus.QUEUED.value
    finally:
        async with engine.begin() as connection:
            await connection.execute(DropSchema(schema, cascade=True))
        await engine.dispose()
