"""Real PostgreSQL lifecycle and ownership checks for Research Taskiq runs."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateSchema, DropSchema

from virtual_company.config import Settings
from virtual_company.db import Base
from virtual_company.db.models import (
    Campaign,
    ResearchCompany,
    ResearchCompanyQualification,
    ResearchEvidence,
    ResearchRun,
    WorkflowExecution,
)
from virtual_company.domain.research.discovery import DiscoveredCompany
from virtual_company.domain.research.qualification import (
    ResearchCompanyQualification as DomainResearchQualification,
)
from virtual_company.domain.research.qualification import (
    ResearchCompanyQualificationStatus,
)
from virtual_company.repositories.dtos import ResearchEvidenceCreate
from virtual_company.repositories.research_evidence import ResearchEvidenceRepository
from virtual_company.repositories.workflow_execution import (
    ExecutionOwnershipLostError,
    WorkflowExecutionRepository,
)
from virtual_company.services.research import ResearchService
from virtual_company.task_queue.reconciliation import reconcile_taskiq_runs_once

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.getenv("RUN_TASKIQ_POSTGRES_TESTS") != "true",
        reason="Requires an isolated TASKIQ_TEST_DATABASE_URL PostgreSQL database",
    ),
]


async def _wait_for_execution_lock_wait(sessions) -> None:
    deadline = asyncio.get_running_loop().time() + 8
    while asyncio.get_running_loop().time() < deadline:
        async with sessions() as session:
            waiting = await session.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE wait_event_type = 'Lock' "
                    "AND query ILIKE '%workflow_execution%'"
                )
            )
        if waiting:
            return
        await asyncio.sleep(0.05)
    raise AssertionError("PostgreSQL transaction did not wait on execution ownership")


async def test_research_queue_claim_and_stale_evidence_fencing() -> None:
    database_url = os.getenv("TASKIQ_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TASKIQ_TEST_DATABASE_URL is not configured")
    if "test" not in database_url.rsplit("/", 1)[-1].lower():
        pytest.fail("Refusing to use a PostgreSQL database without 'test' in its name")

    schema = f"research_taskiq_{uuid4().hex}"
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
                name="PostgreSQL Research Taskiq test",
                keywords=[],
                target_count=1,
                max_companies_to_research=1,
                status="DRAFT",
            )
            company = ResearchCompany(name="Fence Test Company", domain="fence.test")
            session.add_all([campaign, company])
            await session.flush()
            campaign_id, company_id = campaign.id, company.id

        async with sessions() as session:
            run = await ResearchService(session).prepare_queued_run(campaign_id)
            run_id = run.id

        async with sessions.begin() as session:
            claim = await WorkflowExecutionRepository(session).claim("research", run_id)
            execution_id = claim.execution_id
            assert execution_id is not None

        first = ResearchEvidenceCreate(
            company_id=company_id,
            research_run_id=run_id,
            criterion="keyword",
            subject="PostgreSQL",
            claim="The company uses PostgreSQL.",
            evidence_text="PostgreSQL is listed in the engineering stack.",
            source_url="https://fence.test/engineering",
        )
        async with sessions() as session:
            await ResearchService(session).persist_research_evidence(
                research_run_id=run_id, evidence=[first], execution_id=execution_id
            )

        async with sessions.begin() as session:
            assert await WorkflowExecutionRepository(session).transition(
                execution_id, "FAILED"
            )

        second = first.model_copy(
            update={
                "subject": "Python",
                "claim": "The company uses Python.",
                "evidence_text": "Python is listed in the engineering stack.",
            }
        )
        async with sessions() as session:
            with pytest.raises(ExecutionOwnershipLostError):
                await ResearchService(session).persist_research_evidence(
                    research_run_id=run_id, evidence=[second], execution_id=execution_id
                )

        stale_company = DiscoveredCompany(
            name="Stale Candidate",
            domain="stale-candidate.test",
            discovery_reason="Ownership fencing test",
            supporting_urls=[],
        )
        async with sessions() as session:
            with pytest.raises(ExecutionOwnershipLostError):
                await ResearchService(session).persist_companies(
                    campaign_id=campaign_id,
                    companies=[stale_company],
                    research_run_id=run_id,
                    execution_id=execution_id,
                )

        async with sessions() as session:
            with pytest.raises(ExecutionOwnershipLostError):
                await ResearchService(session).persist_research_company_qualifications(
                    campaign_id=campaign_id,
                    research_run_id=run_id,
                    qualifications=[
                        DomainResearchQualification(
                            company_id=company_id,
                            status=ResearchCompanyQualificationStatus.QUALIFIED,
                            criteria=[],
                        )
                    ],
                    execution_id=execution_id,
                )

        async with sessions() as session:
            assert await session.scalar(
                select(ResearchRun.status).where(ResearchRun.id == run_id)
            ) == "FAILED"
            assert await session.scalar(
                select(WorkflowExecution.status).where(
                    WorkflowExecution.run_id == run_id
                )
            ) == "FAILED"
            assert await session.scalar(
                select(func.count(ResearchEvidence.id)).where(
                    ResearchEvidence.research_run_id == run_id
                )
            ) == 1
            assert await session.scalar(
                select(func.count(ResearchCompany.id)).where(
                    ResearchCompany.domain == "stale-candidate.test"
                )
            ) == 0
            assert await session.scalar(
                select(func.count(ResearchCompanyQualification.id)).where(
                    ResearchCompanyQualification.research_run_id == run_id
                )
            ) == 0
    finally:
        async with engine.begin() as connection:
            await connection.execute(DropSchema(schema, cascade=True))
        await engine.dispose()


async def test_research_persistence_and_reconciliation_lock_orderings() -> None:
    database_url = os.getenv("TASKIQ_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TASKIQ_TEST_DATABASE_URL is not configured")
    if "test" not in database_url.rsplit("/", 1)[-1].lower():
        pytest.fail("Refusing to use a PostgreSQL database without 'test' in its name")

    schema = f"research_taskiq_race_{uuid4().hex}"
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
                name="Research ownership race test",
                keywords=[],
                target_count=1,
                max_companies_to_research=1,
                status="DRAFT",
            )
            company = ResearchCompany(name="Race Test Company", domain="race.test")
            session.add_all([campaign, company])
            await session.flush()
            campaign_id, company_id = campaign.id, company.id

        async with sessions() as session:
            first_run = await ResearchService(session).prepare_queued_run(campaign_id)
            first_run_id = first_run.id
        async with sessions.begin() as session:
            first_claim = await WorkflowExecutionRepository(session).claim(
                "research", first_run_id
            )
        first_execution_id = first_claim.execution_id
        assert first_execution_id is not None

        persistence_locked = asyncio.Event()
        release_persistence = asyncio.Event()

        async def persist_and_hold() -> None:
            async with sessions() as session, session.begin():
                await WorkflowExecutionRepository(session).lock_running_ownership(
                    workflow_type="research",
                    run_id=first_run_id,
                    execution_id=first_execution_id,
                )
                await ResearchEvidenceRepository(session).create(
                    ResearchEvidenceCreate(
                        company_id=company_id,
                        research_run_id=first_run_id,
                        criterion="keyword",
                        subject="race",
                        claim="First transaction owns this write.",
                        evidence_text="Evidence committed before reconciliation.",
                        source_url="https://race.test/source",
                    )
                )
                persistence_locked.set()
                await release_persistence.wait()

        persistence_task = asyncio.create_task(persist_and_hold())
        await asyncio.wait_for(persistence_locked.wait(), timeout=5)
        future = datetime.now(UTC) + timedelta(seconds=10)
        reconciliation_task = asyncio.create_task(
            reconcile_taskiq_runs_once(
                sessions,
                Settings(
                    taskiq_running_stale_after_seconds=3,
                    taskiq_heartbeat_interval_seconds=1,
                    taskiq_queued_stale_after_seconds=30,
                    taskiq_reconciliation_interval_seconds=1,
                ),
                now=future,
            )
        )
        await _wait_for_execution_lock_wait(sessions)
        assert not reconciliation_task.done()
        release_persistence.set()
        await persistence_task
        first_reconciliation = await reconciliation_task
        assert first_reconciliation.running_failed == 1
        async with sessions() as session:
            assert await session.scalar(
                select(ResearchRun.status).where(ResearchRun.id == first_run_id)
            ) == "FAILED"
            assert await session.scalar(
                select(func.count(ResearchEvidence.id)).where(
                    ResearchEvidence.research_run_id == first_run_id
                )
            ) == 1

        async with sessions() as session:
            second_run = await ResearchService(session).prepare_queued_run(campaign_id)
            second_run_id = second_run.id
        async with sessions.begin() as session:
            second_claim = await WorkflowExecutionRepository(session).claim(
                "research", second_run_id
            )
        second_execution_id = second_claim.execution_id
        assert second_execution_id is not None

        reconciliation_locked = asyncio.Event()
        release_reconciliation = asyncio.Event()

        async def reconcile_and_hold() -> None:
            async with sessions() as session, session.begin():
                counts = await WorkflowExecutionRepository(session).fail_stale(
                    queued_before=future,
                    running_before=future,
                )
                assert counts[1] == 1
                reconciliation_locked.set()
                await release_reconciliation.wait()

        reconciliation_owner_task = asyncio.create_task(reconcile_and_hold())
        await asyncio.wait_for(reconciliation_locked.wait(), timeout=5)
        stale_write = ResearchEvidenceCreate(
            company_id=company_id,
            research_run_id=second_run_id,
            criterion="keyword",
            subject="race",
            claim="Stale transaction must not commit.",
            evidence_text="This write follows reconciliation ownership.",
            source_url="https://race.test/stale",
        )

        async def try_stale_write() -> None:
            async with sessions() as session:
                await ResearchService(session).persist_research_evidence(
                    research_run_id=second_run_id,
                    evidence=[stale_write],
                    execution_id=second_execution_id,
                )

        persistence_task = asyncio.create_task(try_stale_write())
        await _wait_for_execution_lock_wait(sessions)
        assert not persistence_task.done()
        release_reconciliation.set()
        await reconciliation_owner_task
        with pytest.raises(ExecutionOwnershipLostError):
            await persistence_task
        async with sessions() as session:
            assert await session.scalar(
                select(ResearchRun.status).where(ResearchRun.id == second_run_id)
            ) == "FAILED"
            assert await session.scalar(
                select(func.count(ResearchEvidence.id)).where(
                    ResearchEvidence.research_run_id == second_run_id
                )
            ) == 0
    finally:
        async with engine.begin() as connection:
            await connection.execute(DropSchema(schema, cascade=True))
        await engine.dispose()
