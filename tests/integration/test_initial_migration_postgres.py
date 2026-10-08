"""Opt-in verification of the clean initial migration in an empty PostgreSQL schema."""

import os
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import Connection, inspect, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.schema import CreateSchema, DropSchema

from alembic import command
from virtual_company.config import DEFAULT_DATABASE_URL


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("RUN_MIGRATION_DB_TESTS") != "true",
    reason="Opt-in local PostgreSQL migration test",
)
async def test_initial_migration_creates_complete_schema() -> None:
    schema = f"test_initial_{uuid4().hex}"
    engine = create_async_engine(
        os.getenv("MIGRATION_TEST_DATABASE_URL", DEFAULT_DATABASE_URL)
    )
    try:
        async with engine.begin() as connection:
            await connection.execute(CreateSchema(schema))
        async with engine.connect() as connection:
            await connection.execute(text(f'SET search_path TO "{schema}"'))
            config = Config("alembic.ini")

            def migrate(sync_connection: Connection) -> None:
                config.attributes["connection"] = sync_connection
                command.upgrade(config, "head")

            await connection.run_sync(migrate)

            def verify(sync_connection: Connection) -> None:
                inspector = inspect(sync_connection)
                assert set(inspector.get_table_names(schema=schema)) == {
                    "alembic_version",
                    "campaign",
                    "company",
                    "research_run",
                    "campaign_targets",
                    "evidence",
                    "company_qualifications",
                }
                campaign_columns = {
                    column["name"]: column
                    for column in inspector.get_columns("campaign", schema=schema)
                }
                assert campaign_columns["technologies"]["nullable"] is False
                assert "company_size" in campaign_columns
                assert campaign_columns["max_companies_to_research"]["nullable"] is False
                assert "company_size_min" not in campaign_columns
                assert "company_size_max" not in campaign_columns
                qualification_columns = {
                    column["name"]: column
                    for column in inspector.get_columns(
                        "company_qualifications", schema=schema
                    )
                }
                assert "criteria_results" in qualification_columns
                assert qualification_columns["review_status"]["nullable"] is False
                assert "UNREVIEWED" in str(
                    qualification_columns["review_status"]["default"]
                )

            await connection.run_sync(verify)
            revision = (
                await connection.execute(
                    text("SELECT version_num FROM alembic_version")
                )
            ).scalar_one()
            assert revision == "0001_initial_schema"
            await connection.rollback()
    finally:
        async with engine.begin() as connection:
            await connection.execute(DropSchema(schema, cascade=True, if_exists=True))
        await engine.dispose()
