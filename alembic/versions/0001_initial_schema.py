"""Create the complete Research and Exploration schema.

Revision ID: 0001_initial_schema
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "campaign",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("target_market", sa.String(255)),
        sa.Column("industry", sa.String(255)),
        sa.Column("keywords", postgresql.JSONB(), nullable=False),
        sa.Column("company_size", postgresql.JSONB()),
        sa.Column("target_count", sa.Integer(), nullable=False),
        sa.Column(
            "max_companies_to_research",
            sa.Integer(),
            server_default="15",
            nullable=False,
        ),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("sealed_at", sa.DateTime(timezone=True)),
    )
    op.create_check_constraint(
        "ck_campaign_max_companies_to_research_ge_target_count",
        "campaign",
        "max_companies_to_research >= target_count",
    )
    op.create_table(
        "research_company",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("website", sa.String(1000)),
        sa.Column("domain", sa.String(255)),
        sa.Column("industry", sa.String(255)),
        sa.Column("country", sa.String(100)),
        sa.Column("state", sa.String(255)),
        sa.Column("city", sa.String(255)),
        sa.Column("employee_number", sa.Integer()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="research_company_pkey"),
    )
    op.create_table(
        "research_run",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "campaign_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("campaign.id"),
            nullable=False,
        ),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("error", sa.Text()),
        sa.Column("companies_found", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_table(
        "campaign_target",
        sa.Column(
            "campaign_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("campaign.id", name="campaign_target_campaign_id_fkey"),
            nullable=False,
        ),
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "research_company.id",
                name="campaign_target_research_company_id_fkey",
            ),
            nullable=False,
        ),
        sa.Column("score", sa.Numeric()),
        sa.Column("status", sa.String()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "campaign_id", "company_id", name="campaign_target_pkey"
        ),
    )
    op.create_table(
        "research_evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "research_company.id",
                name="research_evidence_research_company_id_fkey",
            ),
            nullable=False,
        ),
        sa.Column(
            "research_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "research_run.id", name="research_evidence_research_run_id_fkey"
            ),
        ),
        sa.Column("criterion", sa.String(50)),
        sa.Column("subject", sa.String(500)),
        sa.Column("claim", sa.Text(), nullable=False),
        sa.Column("evidence_text", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_title", sa.String(500)),
        sa.Column("source_type", sa.String(50)),
        sa.Column("confidence", sa.Numeric(4, 3)),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="research_evidence_pkey"),
    )
    op.create_index(
        "ix_research_evidence_research_run_id",
        "research_evidence",
        ["research_run_id"],
    )
    op.create_table(
        "research_company_qualification",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "research_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "research_run.id",
                name="research_company_qualification_research_run_id_fkey",
            ),
            nullable=False,
        ),
        sa.Column(
            "campaign_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "campaign.id",
                name="research_company_qualification_campaign_id_fkey",
            ),
            nullable=False,
        ),
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "research_company.id",
                name="research_company_qualification_research_company_id_fkey",
            ),
            nullable=False,
        ),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("criteria_results", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "research_run_id",
            "company_id",
            name="uq_research_company_qualification_run_company",
        ),
        sa.PrimaryKeyConstraint("id", name="research_company_qualification_pkey"),
    )
    op.create_table(
        "exploration",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_context", sa.Text(), nullable=False),
        sa.Column("max_obligations", sa.Integer(), server_default="10", nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="exploration_pkey"),
        sa.CheckConstraint(
            "max_obligations >= 1 AND max_obligations <= 20",
            name="ck_exploration_max_obligations_range",
        ),
    )
    op.create_table(
        "exploration_obligation",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("exploration_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["exploration_id"],
            ["exploration.id"],
            name="exploration_obligation_exploration_id_fkey",
        ),
        sa.PrimaryKeyConstraint("id", name="exploration_obligation_pkey"),
    )
    op.create_index(
        "ix_exploration_obligation_exploration_id",
        "exploration_obligation",
        ["exploration_id"],
    )
    op.create_table(
        "exploration_run",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("exploration_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("research_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["exploration_id"],
            ["exploration.id"],
            name="exploration_run_exploration_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["research_run_id"],
            ["research_run.id"],
            name="exploration_run_research_run_id_fkey",
        ),
        sa.PrimaryKeyConstraint("id", name="exploration_run_pkey"),
    )
    op.create_index(
        "ix_exploration_run_exploration_id", "exploration_run", ["exploration_id"]
    )
    op.create_index(
        "ix_exploration_run_research_run_id", "exploration_run", ["research_run_id"]
    )
    op.create_table(
        "exploration_company",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("exploration_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["exploration_run_id"],
            ["exploration_run.id"],
            name="exploration_company_exploration_run_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["research_company.id"],
            name="exploration_company_company_id_fkey",
        ),
        sa.PrimaryKeyConstraint("id", name="exploration_company_pkey"),
        sa.UniqueConstraint(
            "exploration_run_id",
            "company_id",
            name="uq_exploration_company_run_company",
        ),
    )
    op.create_index(
        "ix_exploration_company_company_id", "exploration_company", ["company_id"]
    )
    op.create_table(
        "exploration_evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "exploration_company_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column(
            "exploration_obligation_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("source_url", sa.Text()),
        sa.Column("source_type", sa.String(50)),
        sa.Column("content", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["exploration_company_id"],
            ["exploration_company.id"],
            name="exploration_evidence_exploration_company_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["exploration_obligation_id"],
            ["exploration_obligation.id"],
            name="exploration_evidence_exploration_obligation_id_fkey",
        ),
        sa.PrimaryKeyConstraint("id", name="exploration_evidence_pkey"),
    )
    op.create_index(
        "ix_exploration_evidence_exploration_company_id",
        "exploration_evidence",
        ["exploration_company_id"],
    )
    op.create_index(
        "ix_exploration_evidence_exploration_obligation_id",
        "exploration_evidence",
        ["exploration_obligation_id"],
    )
    op.create_table(
        "exploration_fact",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="exploration_fact_pkey"),
    )
    op.create_table(
        "exploration_hypothesis",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="exploration_hypothesis_pkey"),
    )
    op.create_table(
        "exploration_fact_evidence",
        sa.Column("exploration_fact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "exploration_evidence_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["exploration_fact_id"],
            ["exploration_fact.id"],
            name="exploration_fact_evidence_fact_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["exploration_evidence_id"],
            ["exploration_evidence.id"],
            name="exploration_fact_evidence_evidence_id_fkey",
        ),
        sa.PrimaryKeyConstraint(
            "exploration_fact_id",
            "exploration_evidence_id",
            name="exploration_fact_evidence_pkey",
        ),
    )
    op.create_index(
        "ix_exploration_fact_evidence_exploration_evidence_id",
        "exploration_fact_evidence",
        ["exploration_evidence_id"],
    )
    op.create_table(
        "exploration_hypothesis_fact",
        sa.Column(
            "exploration_hypothesis_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("exploration_fact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["exploration_hypothesis_id"],
            ["exploration_hypothesis.id"],
            name="exploration_hypothesis_fact_hypothesis_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["exploration_fact_id"],
            ["exploration_fact.id"],
            name="exploration_hypothesis_fact_fact_id_fkey",
        ),
        sa.PrimaryKeyConstraint(
            "exploration_hypothesis_id",
            "exploration_fact_id",
            name="exploration_hypothesis_fact_pkey",
        ),
    )
    op.create_index(
        "ix_exploration_hypothesis_fact_exploration_fact_id",
        "exploration_hypothesis_fact",
        ["exploration_fact_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_exploration_hypothesis_fact_exploration_fact_id",
        table_name="exploration_hypothesis_fact",
    )
    op.drop_table("exploration_hypothesis_fact")
    op.drop_index(
        "ix_exploration_fact_evidence_exploration_evidence_id",
        table_name="exploration_fact_evidence",
    )
    op.drop_table("exploration_fact_evidence")
    op.drop_table("exploration_hypothesis")
    op.drop_table("exploration_fact")
    op.drop_index(
        "ix_exploration_evidence_exploration_obligation_id",
        table_name="exploration_evidence",
    )
    op.drop_index(
        "ix_exploration_evidence_exploration_company_id",
        table_name="exploration_evidence",
    )
    op.drop_table("exploration_evidence")
    op.drop_index("ix_exploration_company_company_id", table_name="exploration_company")
    op.drop_table("exploration_company")
    op.drop_index("ix_exploration_run_exploration_id", table_name="exploration_run")
    op.drop_index("ix_exploration_run_research_run_id", table_name="exploration_run")
    op.drop_table("exploration_run")
    op.drop_index(
        "ix_exploration_obligation_exploration_id",
        table_name="exploration_obligation",
    )
    op.drop_table("exploration_obligation")
    op.drop_table("exploration")
    op.drop_table("research_company_qualification")
    op.drop_index(
        "ix_research_evidence_research_run_id", table_name="research_evidence"
    )
    op.drop_table("research_evidence")
    op.drop_table("campaign_target")
    op.drop_table("research_run")
    op.drop_table("research_company")
    op.drop_table("campaign")
