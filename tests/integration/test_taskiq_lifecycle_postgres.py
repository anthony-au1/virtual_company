"""Opt-in real PostgreSQL checks for shared execution ownership."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateSchema, DropSchema

from virtual_company.config import Settings
from virtual_company.db import Base
from virtual_company.db.models import (
    Campaign,
    Exploration,
    ExplorationRun,
    ResearchRun,
    WorkflowExecution,
)
from virtual_company.repositories.workflow_execution import (
    WorkflowExecutionClaimOutcome,
    WorkflowExecutionRepository,
)
from virtual_company.task_queue.dispatcher import WorkflowType
from virtual_company.task_queue.lifecycle import (
    ExecutionHeartbeat,
    claim_workflow_run,
    heartbeat_workflow_run,
    run_with_heartbeat,
    transition_workflow_run,
)
from virtual_company.task_queue.reconciliation import reconcile_taskiq_runs_once


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("RUN_TASKIQ_POSTGRES_TESTS") != "true",
    reason="Requires an explicitly configured isolated Taskiq test database",
)
async def test_shared_execution_claim_fencing_and_reconciliation() -> None:
    database_url = os.environ.get("TASKIQ_TEST_DATABASE_URL")
    if not database_url:
        pytest.fail("TASKIQ_TEST_DATABASE_URL is required for this opt-in test")
    database_name = make_url(database_url).database or ""
    if "test" not in database_name.lower():
        pytest.fail("Refusing to run against a database without 'test' in its name")

    schema = f"taskiq_lifecycle_{uuid4().hex}"
    engine = create_async_engine(database_url)
    scoped_engine = engine.execution_options(schema_translate_map={None: schema})
    try:
        async with engine.begin() as connection:
            await connection.execute(CreateSchema(schema))
        async with scoped_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(scoped_engine, expire_on_commit=False)

        async with sessions.begin() as session:
            campaign = Campaign(
                name="Taskiq lifecycle integration",
                keywords=[],
                target_count=1,
                max_companies_to_research=1,
                status="COMPLETED",
            )
            session.add(campaign)
            await session.flush()
            research_run = ResearchRun(
                campaign_id=campaign.id, status="QUEUED", companies_found=0
            )
            legacy_research_run = ResearchRun(
                campaign_id=campaign.id, status="RUNNING", companies_found=0
            )
            stale_research_run = ResearchRun(
                campaign_id=campaign.id, status="RUNNING", companies_found=0
            )
            session.add_all([research_run, legacy_research_run, stale_research_run])
            exploration = Exploration(
                business_context="Taskiq lifecycle test",
                max_obligations=1,
                status="DRAFT",
            )
            session.add(exploration)
            await session.flush()
            exploration_run = ExplorationRun(
                exploration_id=exploration.id,
                research_run_id=research_run.id,
                status="QUEUED",
            )
            legacy_exploration_run = ExplorationRun(
                exploration_id=exploration.id,
                research_run_id=research_run.id,
                status="QUEUED",
            )
            stale_queued_run = ExplorationRun(
                exploration_id=exploration.id,
                research_run_id=research_run.id,
                status="QUEUED",
            )
            session.add_all([exploration_run, legacy_exploration_run, stale_queued_run])
            await session.flush()
            execution = WorkflowExecution(
                workflow_type="exploration",
                run_id=exploration_run.id,
                status="QUEUED",
                queued_at=datetime.now(UTC),
            )
            stale_queued_execution = WorkflowExecution(
                workflow_type="exploration",
                run_id=stale_queued_run.id,
                status="QUEUED",
                queued_at=datetime.now(UTC) - timedelta(hours=2),
            )
            stale_research_execution = WorkflowExecution(
                workflow_type="research",
                run_id=stale_research_run.id,
                status="RUNNING",
                queued_at=datetime.now(UTC) - timedelta(hours=2),
                started_at=datetime.now(UTC) - timedelta(hours=2),
                heartbeat_at=datetime.now(UTC) - timedelta(hours=2),
            )
            session.add_all(
                [execution, stale_queued_execution, stale_research_execution]
            )
            await session.flush()
            legacy_research_id = legacy_research_run.id
            stale_research_id = stale_research_run.id
            exploration_id = exploration_run.id
            legacy_exploration_id = legacy_exploration_run.id
            stale_queued_id = stale_queued_run.id
            execution_id = execution.id
            stale_research_execution_id = stale_research_execution.id

        async with sessions.begin() as session:
            repository = WorkflowExecutionRepository(session)
            with pytest.raises(ValueError, match="Unsupported workflow type"):
                await repository.create_queued("unknown", uuid4())
            with pytest.raises(ValueError, match="does not exist or is not QUEUED"):
                await repository.create_queued("research", uuid4())

        claims = await asyncio.gather(
            claim_workflow_run(sessions, WorkflowType.EXPLORATION, exploration_id),
            claim_workflow_run(sessions, WorkflowType.EXPLORATION, exploration_id),
        )
        assert sum(c.outcome is WorkflowExecutionClaimOutcome.CLAIMED for c in claims) == 1
        assert sum(c.outcome is WorkflowExecutionClaimOutcome.NOT_CLAIMABLE for c in claims) == 1
        assert claims[0].execution_id == execution_id or claims[1].execution_id == execution_id
        assert await heartbeat_workflow_run(
            sessions, WorkflowType.EXPLORATION, exploration_id, execution_id
        )
        await run_with_heartbeat(
            ExecutionHeartbeat(
                session_factory=sessions,
                workflow_type=WorkflowType.EXPLORATION,
                run_id=exploration_id,
                execution_id=execution_id,
                interval_seconds=0.02,
            ),
            asyncio.sleep(0.08),
        )
        async with sessions() as session:
            heartbeat = await session.scalar(
                select(WorkflowExecution.heartbeat_at).where(
                    WorkflowExecution.id == execution_id
                )
            )
            assert heartbeat is not None

        with pytest.raises(RuntimeError, match="rollback coordination"):
            async with sessions.begin() as session:
                await WorkflowExecutionRepository(session).transition(
                    execution_id, "COMPLETED"
                )
                raise RuntimeError("rollback coordination")
        async with sessions() as session:
            assert await session.scalar(
                select(WorkflowExecution.status).where(
                    WorkflowExecution.id == execution_id
                )
            ) == "RUNNING"
            assert await session.scalar(
                select(ExplorationRun.status).where(ExplorationRun.id == exploration_id)
            ) == "RUNNING"

        assert await transition_workflow_run(
            sessions, WorkflowType.EXPLORATION, exploration_id, execution_id, "COMPLETED"
        )
        assert not await heartbeat_workflow_run(
            sessions, WorkflowType.EXPLORATION, exploration_id, execution_id
        )
        assert not await transition_workflow_run(
            sessions, WorkflowType.EXPLORATION, exploration_id, execution_id, "FAILED"
        )

        with pytest.raises(IntegrityError):
            async with sessions.begin() as session:
                session.add(
                    WorkflowExecution(
                        workflow_type="exploration",
                        run_id=exploration_id,
                        status="QUEUED",
                    )
                )
                await session.flush()

        settings = Settings(
            taskiq_heartbeat_interval_seconds=1,
            taskiq_running_stale_after_seconds=3,
            taskiq_queued_stale_after_seconds=60,
            taskiq_reconciliation_interval_seconds=1,
        )
        result = await reconcile_taskiq_runs_once(
            sessions, settings, now=datetime.now(UTC) + timedelta(hours=3)
        )
        assert result.queued_failed == 1
        assert result.running_failed == 1
        assert not await heartbeat_workflow_run(
            sessions, WorkflowType.RESEARCH, stale_research_id, stale_research_execution_id
        )
        assert not await transition_workflow_run(
            sessions, WorkflowType.RESEARCH, stale_research_id,
            stale_research_execution_id, "COMPLETED"
        )

        async with sessions() as session:
            statuses = {
                run_id: await session.scalar(
                    select(ExplorationRun.status).where(ExplorationRun.id == run_id)
                )
                for run_id in (exploration_id, legacy_exploration_id, stale_queued_id)
            }
            assert await session.scalar(
                select(ResearchRun.status).where(ResearchRun.id == legacy_research_id)
            ) == "RUNNING"
            assert await session.scalar(
                select(ResearchRun.status).where(ResearchRun.id == stale_research_id)
            ) == "FAILED"
        assert statuses[exploration_id] == "COMPLETED"
        assert statuses[legacy_exploration_id] == "QUEUED"
        assert statuses[stale_queued_id] == "FAILED"
    finally:
        async with engine.begin() as connection:
            await connection.execute(DropSchema(schema, cascade=True))
        await engine.dispose()
