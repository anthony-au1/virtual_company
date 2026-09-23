"""Opt-in PostgreSQL upsert verification in an isolated temporary schema."""

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
    Company,
    CompanyQualificationSnapshot,
    ResearchRun,
)
from virtual_company.repositories.company_qualification import (
    CompanyQualificationRepository,
)
from virtual_company.repositories.dtos import CompanyQualificationUpsert


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
                )
            )
            session.add_all(
                [Company(id=company_a, name="A"), Company(id=company_b, name="B")]
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
            repository = CompanyQualificationRepository(session)
            payload = {
                "criteria": [
                    {
                        "criterion": "technology",
                        "subject": "java",
                        "status": "MATCH",
                        "evidence_ids": [str(uuid4())],
                        "reason": "Supported",
                    }
                ]
            }
            data = CompanyQualificationUpsert(
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
            rows = list(await session.scalars(select(CompanyQualificationSnapshot)))
            assert len(rows) == 3
            stored = next(row for row in rows if row.id == identity)
            assert stored.status == "INSUFFICIENT_EVIDENCE"
            assert stored.criteria_results == {"criteria": []}
            assert stored.created_at.tzinfo is not None
            assert all(
                row.criteria_results == payload for row in rows if row.id != identity
            )
    finally:
        async with engine.begin() as connection:
            await connection.execute(DropSchema(schema, cascade=True, if_exists=True))
        await engine.dispose()
