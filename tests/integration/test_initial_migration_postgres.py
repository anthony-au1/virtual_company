"""Opt-in verification that the initial migration creates the current schema."""

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
async def test_initial_migration_creates_current_research_schema() -> None:
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
                tables = set(inspector.get_table_names(schema=schema))
                assert tables == {
                    "alembic_version",
                    "campaign",
                    "research_company",
                    "research_run",
                    "campaign_target",
                    "research_evidence",
                    "research_company_qualification",
                }
                assert {
                    "company",
                    "evidence",
                    "company_qualifications",
                    "campaign_targets",
                    "research_company_qualifications",
                }.isdisjoint(tables)

                expected_primary_keys = {
                    "campaign": "campaign_pkey",
                    "research_company": "research_company_pkey",
                    "research_run": "research_run_pkey",
                    "campaign_target": "campaign_target_pkey",
                    "research_evidence": "research_evidence_pkey",
                    "research_company_qualification": "research_company_qualification_pkey",
                }
                for table, expected_name in expected_primary_keys.items():
                    assert (
                        inspector.get_pk_constraint(table, schema=schema)["name"]
                        == expected_name
                    )
                assert inspector.get_pk_constraint("campaign_target", schema=schema)[
                    "constrained_columns"
                ] == ["campaign_id", "company_id"]
                assert inspector.get_pk_constraint(
                    "research_company_qualification", schema=schema
                )["constrained_columns"] == ["id"]

                expected_foreign_keys = {
                    "research_run": {
                        "research_run_campaign_id_fkey": "campaign",
                    },
                    "campaign_target": {
                        "campaign_target_campaign_id_fkey": "campaign",
                        "campaign_target_research_company_id_fkey": (
                            "research_company"
                        ),
                    },
                    "research_evidence": {
                        "research_evidence_research_company_id_fkey": (
                            "research_company"
                        ),
                        "research_evidence_research_run_id_fkey": "research_run",
                    },
                    "research_company_qualification": {
                        "research_company_qualification_research_run_id_fkey": (
                            "research_run"
                        ),
                        "research_company_qualification_campaign_id_fkey": ("campaign"),
                        "research_company_qualification_research_company_id_fkey": (
                            "research_company"
                        ),
                    },
                }
                for table, expected in expected_foreign_keys.items():
                    foreign_keys = inspector.get_foreign_keys(table, schema=schema)
                    references = {
                        foreign_key["name"]: foreign_key["referred_table"]
                        for foreign_key in foreign_keys
                    }
                    for constraint_name, referred_table in expected.items():
                        assert references[constraint_name] == referred_table

                unique_constraints = inspector.get_unique_constraints(
                    "research_company_qualification", schema=schema
                )
                assert any(
                    constraint["name"]
                    == "uq_research_company_qualification_run_company"
                    and constraint["column_names"] == ["research_run_id", "company_id"]
                    for constraint in unique_constraints
                )
                indexes = inspector.get_indexes("research_evidence", schema=schema)
                assert any(
                    index["name"] == "ix_research_evidence_research_run_id"
                    and index["column_names"] == ["research_run_id"]
                    for index in indexes
                )

                campaign_columns = {
                    column["name"]: column
                    for column in inspector.get_columns("campaign", schema=schema)
                }
                assert campaign_columns["technologies"]["nullable"] is False
                assert "company_size" in campaign_columns
                assert (
                    campaign_columns["max_companies_to_research"]["nullable"] is False
                )
                assert "sealed_at" in campaign_columns

                qualification_columns = {
                    column["name"]: column
                    for column in inspector.get_columns(
                        "research_company_qualification", schema=schema
                    )
                }
                assert "criteria_results" in qualification_columns
                assert "review_status" not in qualification_columns

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
