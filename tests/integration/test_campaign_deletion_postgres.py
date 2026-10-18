"""Opt-in PostgreSQL coverage for Campaign deletion ownership and rollback."""

import os
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
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
from virtual_company.services.campaign import (
    CampaignLifecycleConflictError,
    CampaignService,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.getenv("RUN_CAMPAIGN_DELETE_DB_TESTS") != "true",
        reason="Opt-in local PostgreSQL Campaign deletion test",
    ),
]


def new_campaign() -> Campaign:
    return Campaign(
        name="Test Campaign",
        keywords=[],
        target_count=1,
        max_companies_to_research=1,
        status="DRAFT",
    )


async def postgres_context() -> tuple[
    str, AsyncEngine, AsyncEngine, async_sessionmaker[AsyncSession]
]:
    schema = f"test_campaign_delete_{uuid4().hex}"
    engine = create_async_engine(
        os.getenv("CAMPAIGN_DELETE_TEST_DATABASE_URL", DEFAULT_DATABASE_URL)
    )
    scoped = engine.execution_options(schema_translate_map={None: schema})
    async with engine.begin() as connection:
        await connection.execute(CreateSchema(schema))
    async with scoped.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return schema, engine, scoped, async_sessionmaker(scoped, expire_on_commit=False)


async def cleanup(schema: str, engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.execute(DropSchema(schema, cascade=True))
    await engine.dispose()


async def test_pre_run_delete_removes_campaign_target_but_keeps_shared_company():
    schema, engine, _, sessions = await postgres_context()
    try:
        async with sessions() as session:
            campaign = new_campaign()
            company = ResearchCompany(name="Shared Company")
            session.add_all([campaign, company])
            await session.flush()
            target = CampaignTarget(
                campaign_id=campaign.id,
                company_id=company.id,
            )
            campaign_id, company_id = campaign.id, company.id
            session.add(target)
            await session.commit()

            assert await CampaignService(session).delete(campaign_id)

            assert await session.get(Campaign, campaign_id) is None
            assert await session.get(CampaignTarget, (campaign_id, company_id)) is None
            assert await session.get(ResearchCompany, company_id) is not None
    finally:
        await cleanup(schema, engine)


async def test_any_run_blocks_delete_and_preserves_persisted_research_history():
    schema, engine, _, sessions = await postgres_context()
    try:
        async with sessions() as session:
            campaign = new_campaign()
            company = ResearchCompany(name="Research Subject")
            session.add_all([campaign, company])
            await session.flush()
            run = ResearchRun(
                campaign_id=campaign.id,
                status="FAILED",
                companies_found=1,
            )
            session.add(run)
            await session.flush()
            evidence = ResearchEvidence(
                company_id=company.id,
                research_run_id=run.id,
                claim="Persisted claim",
                evidence_text="Evidence detail",
                source_url="https://example.com/source",
            )
            qualification = ResearchCompanyQualification(
                research_run_id=run.id,
                campaign_id=campaign.id,
                company_id=company.id,
                status="QUALIFIED",
                criteria_results={},
            )
            session.add_all([evidence, qualification])
            campaign_id, run_id = campaign.id, run.id
            evidence_id, qualification_id = evidence.id, qualification.id
            await session.commit()

            with pytest.raises(CampaignLifecycleConflictError):
                await CampaignService(session).delete(campaign_id)

            assert await session.get(Campaign, campaign_id) is not None
            assert await session.get(ResearchRun, run_id) is not None
            assert await session.get(ResearchEvidence, evidence_id) is not None
            assert (
                await session.get(ResearchCompanyQualification, qualification_id)
                is not None
            )
    finally:
        await cleanup(schema, engine)


async def test_persistence_failure_rolls_back_target_cleanup():
    schema, engine, _, sessions = await postgres_context()
    try:
        async with sessions() as session:
            campaign = new_campaign()
            company = ResearchCompany(name="Shared Company")
            session.add_all([campaign, company])
            await session.flush()
            target = CampaignTarget(
                campaign_id=campaign.id,
                company_id=company.id,
            )
            campaign_id, company_id = campaign.id, company.id
            session.add(target)
            await session.commit()

            service = CampaignService(session)

            async def fail_delete(_: Campaign) -> None:
                raise RuntimeError("simulated Campaign delete failure")

            service._campaigns.delete = fail_delete
            with pytest.raises(RuntimeError, match="simulated Campaign delete failure"):
                await service.delete(campaign_id)

        async with sessions() as verify_session:
            assert await verify_session.get(Campaign, campaign_id) is not None
            assert (
                await verify_session.get(CampaignTarget, (campaign_id, company_id))
                is not None
            )
    finally:
        await cleanup(schema, engine)
