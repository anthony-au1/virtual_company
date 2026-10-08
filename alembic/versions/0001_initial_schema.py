"""Create the complete campaign research schema.

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
        sa.Column("technologies", postgresql.JSONB(), nullable=False),
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
    )
    op.create_check_constraint(
        "ck_campaign_max_companies_to_research_ge_target_count",
        "campaign",
        "max_companies_to_research >= target_count",
    )
    op.create_table(
        "company",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
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
        "campaign_targets",
        sa.Column(
            "campaign_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("campaign.id"),
            primary_key=True,
        ),
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("company.id"),
            primary_key=True,
        ),
        sa.Column("score", sa.Numeric()),
        sa.Column("status", sa.String()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_table(
        "evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("company.id"),
            nullable=False,
        ),
        sa.Column(
            "research_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("research_run.id"),
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
    )
    op.create_index("ix_evidence_research_run_id", "evidence", ["research_run_id"])
    op.create_table(
        "company_qualifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "research_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("research_run.id"),
            nullable=False,
        ),
        sa.Column(
            "campaign_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("campaign.id"),
            nullable=False,
        ),
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("company.id"),
            nullable=False,
        ),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column(
            "review_status",
            sa.String(30),
            server_default="UNREVIEWED",
            nullable=False,
        ),
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
            name="uq_company_qualifications_run_company",
        ),
    )


def downgrade() -> None:
    op.drop_table("company_qualifications")
    op.drop_index("ix_evidence_research_run_id", table_name="evidence")
    op.drop_table("evidence")
    op.drop_table("campaign_targets")
    op.drop_table("research_run")
    op.drop_table("company")
    op.drop_table("campaign")
