"""Opt-in verification that the initial migration creates the current schema."""

import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
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
async def test_initial_migration_creates_current_schema() -> None:
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
                    "exploration",
                    "exploration_obligation",
                    "exploration_run",
                    "exploration_company",
                    "exploration_evidence",
                    "exploration_fact",
                    "exploration_fact_evidence",
                    "exploration_hypothesis",
                    "exploration_hypothesis_fact",
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
                    "exploration": "exploration_pkey",
                    "exploration_obligation": "exploration_obligation_pkey",
                    "exploration_run": "exploration_run_pkey",
                    "exploration_company": "exploration_company_pkey",
                    "exploration_evidence": "exploration_evidence_pkey",
                    "exploration_fact": "exploration_fact_pkey",
                    "exploration_fact_evidence": "exploration_fact_evidence_pkey",
                    "exploration_hypothesis": "exploration_hypothesis_pkey",
                    "exploration_hypothesis_fact": "exploration_hypothesis_fact_pkey",
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

                expected_exploration_foreign_keys = {
                    "exploration_obligation": {
                        "exploration_obligation_exploration_id_fkey": "exploration"
                    },
                    "exploration_run": {
                        "exploration_run_exploration_id_fkey": "exploration",
                        "exploration_run_research_run_id_fkey": "research_run",
                    },
                    "exploration_company": {
                        "exploration_company_exploration_run_id_fkey": "exploration_run",
                        "exploration_company_company_id_fkey": "research_company",
                    },
                    "exploration_evidence": {
                        "exploration_evidence_exploration_company_id_fkey": "exploration_company",
                        "exploration_evidence_exploration_obligation_id_fkey": "exploration_obligation",
                    },
                    "exploration_fact_evidence": {
                        "exploration_fact_evidence_fact_id_fkey": "exploration_fact",
                        "exploration_fact_evidence_evidence_id_fkey": "exploration_evidence",
                    },
                    "exploration_hypothesis_fact": {
                        "exploration_hypothesis_fact_hypothesis_id_fkey": "exploration_hypothesis",
                        "exploration_hypothesis_fact_fact_id_fkey": "exploration_fact",
                    },
                }
                for table, expected in expected_exploration_foreign_keys.items():
                    foreign_keys = inspector.get_foreign_keys(table, schema=schema)
                    references = {
                        foreign_key["name"]: foreign_key["referred_table"]
                        for foreign_key in foreign_keys
                    }
                    for constraint_name, referred_table in expected.items():
                        assert references[constraint_name] == referred_table

                exploration_company_uniques = inspector.get_unique_constraints(
                    "exploration_company", schema=schema
                )
                assert any(
                    constraint["name"] == "uq_exploration_company_run_company"
                    and constraint["column_names"]
                    == ["exploration_run_id", "company_id"]
                    for constraint in exploration_company_uniques
                )
                for table, expected_index in (
                    (
                        "exploration_fact_evidence",
                        "ix_exploration_fact_evidence_exploration_evidence_id",
                    ),
                    (
                        "exploration_hypothesis_fact",
                        "ix_exploration_hypothesis_fact_exploration_fact_id",
                    ),
                ):
                    assert any(
                        index["name"] == expected_index
                        for index in inspector.get_indexes(table, schema=schema)
                    )
                expected_exploration_indexes = (
                    (
                        "exploration_obligation",
                        "ix_exploration_obligation_exploration_id",
                    ),
                    ("exploration_run", "ix_exploration_run_exploration_id"),
                    ("exploration_run", "ix_exploration_run_research_run_id"),
                    ("exploration_company", "ix_exploration_company_company_id"),
                    (
                        "exploration_evidence",
                        "ix_exploration_evidence_exploration_company_id",
                    ),
                    (
                        "exploration_evidence",
                        "ix_exploration_evidence_exploration_obligation_id",
                    ),
                )
                for table, expected_index in expected_exploration_indexes:
                    assert any(
                        index["name"] == expected_index
                        for index in inspector.get_indexes(table, schema=schema)
                    )

                expected_exploration_columns = {
                    "exploration": {
                        "id",
                        "business_context",
                        "max_obligations",
                        "status",
                        "created_at",
                        "updated_at",
                    },
                    "exploration_obligation": {
                        "id",
                        "exploration_id",
                        "description",
                        "created_at",
                    },
                    "exploration_run": {
                        "id",
                        "exploration_id",
                        "research_run_id",
                        "status",
                        "started_at",
                        "completed_at",
                    },
                    "exploration_company": {
                        "id",
                        "exploration_run_id",
                        "company_id",
                    },
                    "exploration_evidence": {
                        "id",
                        "exploration_company_id",
                        "exploration_obligation_id",
                        "source_url",
                        "source_type",
                        "content",
                        "created_at",
                    },
                    "exploration_fact": {"id", "statement", "created_at"},
                    "exploration_fact_evidence": {
                        "exploration_fact_id",
                        "exploration_evidence_id",
                    },
                    "exploration_hypothesis": {"id", "statement", "created_at"},
                    "exploration_hypothesis_fact": {
                        "exploration_hypothesis_id",
                        "exploration_fact_id",
                    },
                }
                for table, expected_columns in expected_exploration_columns.items():
                    columns = {
                        column["name"]
                        for column in inspector.get_columns(table, schema=schema)
                    }
                    assert columns == expected_columns

                expected_not_null_columns = {
                    "exploration": {
                        "id",
                        "business_context",
                        "max_obligations",
                        "status",
                        "created_at",
                        "updated_at",
                    },
                    "exploration_obligation": {
                        "id",
                        "exploration_id",
                        "description",
                        "created_at",
                    },
                    "exploration_run": {
                        "id", "exploration_id", "research_run_id", "status", "started_at"
                    },
                    "exploration_company": {
                        "id",
                        "exploration_run_id",
                        "company_id",
                    },
                    "exploration_evidence": {
                        "id",
                        "exploration_company_id",
                        "exploration_obligation_id",
                        "created_at",
                    },
                    "exploration_fact": {"id", "statement", "created_at"},
                    "exploration_fact_evidence": {
                        "exploration_fact_id",
                        "exploration_evidence_id",
                    },
                    "exploration_hypothesis": {"id", "statement", "created_at"},
                    "exploration_hypothesis_fact": {
                        "exploration_hypothesis_id",
                        "exploration_fact_id",
                    },
                }
                for table, not_null_columns in expected_not_null_columns.items():
                    columns = {
                        column["name"]: column
                        for column in inspector.get_columns(table, schema=schema)
                    }
                    assert {
                        name
                        for name, column in columns.items()
                        if not column["nullable"]
                    } == not_null_columns

                exploration_columns = {
                    column["name"]: column
                    for column in inspector.get_columns("exploration", schema=schema)
                }
                assert str(exploration_columns["max_obligations"]["default"]) in {
                    "10",
                    "10::integer",
                }
                assert any(
                    constraint["name"] == "ck_exploration_max_obligations_range"
                    for constraint in inspector.get_check_constraints(
                        "exploration", schema=schema
                    )
                )

                assert inspector.get_pk_constraint(
                    "exploration_fact_evidence", schema=schema
                )["constrained_columns"] == [
                    "exploration_fact_id",
                    "exploration_evidence_id",
                ]
                assert inspector.get_pk_constraint(
                    "exploration_hypothesis_fact", schema=schema
                )["constrained_columns"] == [
                    "exploration_hypothesis_id",
                    "exploration_fact_id",
                ]

                campaign_columns = {
                    column["name"]: column
                    for column in inspector.get_columns("campaign", schema=schema)
                }
                assert campaign_columns["keywords"]["nullable"] is False
                assert "technologies" not in campaign_columns
                assert "target_count" in campaign_columns
                assert "industry" in campaign_columns
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
            migration_dir = Path(__file__).resolve().parents[2] / "alembic" / "versions"
            assert sorted(path.name for path in migration_dir.glob("*.py")) == [
                "0001_initial_schema.py"
            ]
            assert ScriptDirectory.from_config(config).get_heads() == [
                "0001_initial_schema"
            ]
            await connection.rollback()
    finally:
        async with engine.begin() as connection:
            await connection.execute(DropSchema(schema, cascade=True, if_exists=True))
        await engine.dispose()
