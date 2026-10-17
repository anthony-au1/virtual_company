"""Opt-in PostgreSQL upsert verification in an isolated temporary schema."""

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateSchema, DropSchema

from virtual_company.config import DEFAULT_DATABASE_URL
from virtual_company.db import Base
from virtual_company.db.models import (
    Campaign,
    CampaignTarget,
    ResearchCompany,
    ResearchCompanyQualification,
    ResearchEvidence,
    ResearchRun,
)
from virtual_company.repositories.dtos import ResearchCompanyQualificationUpsert
from virtual_company.repositories.research_company_qualification import (
    ResearchCompanyQualificationRepository,
)
from virtual_company.services.research_results import ResearchResultsService


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("RUN_QUALIFICATION_DB_TESTS") != "true",
    reason="Opt-in local PostgreSQL test",
)
async def test_committed_snapshots_are_idempotent_and_run_scoped() -> None:
    schema = f"test_qualification_{uuid4().hex}"
    engine = create_async_engine(
        os.getenv("QUALIFICATION_TEST_DATABASE_URL", DEFAULT_DATABASE_URL)
    )
    scoped = engine.execution_options(schema_translate_map={None: schema})
    try:
        async with engine.begin() as connection:
            await connection.execute(CreateSchema(schema))
        async with scoped.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(scoped, expire_on_commit=False)
        campaign_id, company_a, company_b, run_a, run_b = (uuid4() for _ in range(5))
        async with sessions() as session:
            session.add(
                Campaign(
                    id=campaign_id,
                    name="Snapshot test",
                    target_count=2,
                    status="RUNNING",
                    keywords=[],
                )
            )
            session.add_all(
                [
                    ResearchCompany(id=company_a, name="A"),
                    ResearchCompany(id=company_b, name="B"),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    ResearchRun(
                        id=run_id,
                        campaign_id=campaign_id,
                        status="RUNNING",
                        companies_found=2,
                    )
                    for run_id in (run_a, run_b)
                ]
            )
            await session.flush()
            repository = ResearchCompanyQualificationRepository(session)
            payload = {
                "criteria": [
                    {
                        "criterion": "keyword",
                        "subject": "java",
                        "status": "MATCH",
                        "evidence_ids": [str(uuid4())],
                        "reason": "Supported",
                    }
                ]
            }
            data = ResearchCompanyQualificationUpsert(
                research_run_id=run_a,
                campaign_id=campaign_id,
                company_id=company_a,
                status="QUALIFIED",
                criteria_results=payload,
            )
            first = await repository.upsert(data)
            identity, timestamp = first.id, first.created_at
            for _ in range(2):
                repeated = await repository.upsert(data)
                assert (repeated.id, repeated.created_at) == (identity, timestamp)
            replacement = data.model_copy(
                update={
                    "status": "INSUFFICIENT_EVIDENCE",
                    "criteria_results": {"criteria": []},
                }
            )
            updated = await repository.upsert(replacement)
            assert (updated.id, updated.created_at) == (identity, timestamp)
            await repository.upsert(data.model_copy(update={"company_id": company_b}))
            await repository.upsert(data.model_copy(update={"research_run_id": run_b}))
            await session.commit()
        async with sessions() as session:
            rows = list(await session.scalars(select(ResearchCompanyQualification)))
            assert len(rows) == 3
            stored = next(row for row in rows if row.id == identity)
            assert stored.status == "INSUFFICIENT_EVIDENCE"
            assert stored.criteria_results == {"criteria": []}
            assert stored.created_at.tzinfo is not None
            assert all(
                row.criteria_results == payload for row in rows if row.id != identity
            )
            assert stored.status == "INSUFFICIENT_EVIDENCE"
            assert stored.criteria_results == {"criteria": []}
    finally:
        async with engine.begin() as connection:
            await connection.execute(DropSchema(schema, cascade=True, if_exists=True))
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("RUN_QUALIFICATION_DB_TESTS") != "true",
    reason="Opt-in local PostgreSQL test",
)
async def test_deleting_a_run_preserves_campaign_siblings_and_canonical_company() -> (
    None
):
    schema = f"test_run_delete_{uuid4().hex}"
    engine = create_async_engine(
        os.getenv("QUALIFICATION_TEST_DATABASE_URL", DEFAULT_DATABASE_URL)
    )
    scoped = engine.execution_options(schema_translate_map={None: schema})
    try:
        async with engine.begin() as connection:
            await connection.execute(CreateSchema(schema))
        async with scoped.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(scoped, expire_on_commit=False)
        campaign_id, company_id, run_to_delete, sibling_run = (
            uuid4() for _ in range(4)
        )
        sealed_at = datetime.now(UTC)
        async with sessions() as session:
            session.add(
                Campaign(
                    id=campaign_id,
                    name="Sealed campaign",
                    target_count=1,
                    status="COMPLETED",
                    keywords=[],
                    sealed_at=sealed_at,
                )
            )
            session.add(ResearchCompany(id=company_id, name="Canonical company"))
            await session.flush()
            session.add(CampaignTarget(campaign_id=campaign_id, company_id=company_id))
            session.add_all(
                [
                    ResearchRun(
                        id=run_id,
                        campaign_id=campaign_id,
                        status="COMPLETED",
                        companies_found=1,
                    )
                    for run_id in (run_to_delete, sibling_run)
                ]
            )
            await session.flush()
            for run_id in (run_to_delete, sibling_run):
                session.add(
                    ResearchEvidence(
                        company_id=company_id,
                        research_run_id=run_id,
                        claim="Run scoped claim",
                        evidence_text="Evidence for this execution",
                        source_url=f"https://example.test/{run_id}",
                    )
                )
                session.add(
                    ResearchCompanyQualification(
                        research_run_id=run_id,
                        campaign_id=campaign_id,
                        company_id=company_id,
                        status="QUALIFIED",
                        criteria_results={"criteria": []},
                    )
                )
            await session.commit()

        async with sessions() as session:
            assert await ResearchResultsService(session).delete_run(run_to_delete)

        async with sessions() as session:
            assert await session.get(Campaign, campaign_id) is not None
            assert await session.get(ResearchCompany, company_id) is not None
            assert await session.get(ResearchRun, run_to_delete) is None
            assert await session.get(ResearchRun, sibling_run) is not None
            assert (
                await session.get(CampaignTarget, (campaign_id, company_id)) is not None
            )
            assert (
                await session.scalar(
                    select(ResearchCompanyQualification).where(
                        ResearchCompanyQualification.research_run_id == sibling_run
                    )
                )
                is not None
            )
            assert (
                await session.scalar(
                    select(ResearchEvidence).where(
                        ResearchEvidence.research_run_id == sibling_run
                    )
                )
                is not None
            )
            assert (
                await session.scalar(
                    select(ResearchCompanyQualification).where(
                        ResearchCompanyQualification.research_run_id == run_to_delete
                    )
                )
                is None
            )
            assert (
                await session.scalar(
                    select(ResearchEvidence).where(
                        ResearchEvidence.research_run_id == run_to_delete
                    )
                )
                is None
            )
            campaign = await session.get(Campaign, campaign_id)
            assert campaign is not None and campaign.sealed_at == sealed_at
    finally:
        async with engine.begin() as connection:
            await connection.execute(DropSchema(schema, cascade=True, if_exists=True))
        await engine.dispose()
