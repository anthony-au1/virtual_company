"""Add run-scoped structured evidence fields.

Revision ID: 20260920_0002
Revises: 20260911_0001
Create Date: 2026-09-20 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260920_0002"
down_revision: str | None = "20260911_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add provenance and criterion fields without invalidating legacy evidence."""
    op.add_column(
        "evidence", sa.Column("research_run_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.add_column("evidence", sa.Column("criterion", sa.String(length=50), nullable=True))
    op.add_column("evidence", sa.Column("subject", sa.String(length=500), nullable=True))
    op.create_foreign_key(
        "fk_evidence_research_run_id_research_run",
        "evidence",
        "research_run",
        ["research_run_id"],
        ["id"],
    )
    op.create_index("ix_evidence_research_run_id", "evidence", ["research_run_id"])


def downgrade() -> None:
    """Remove the run-scoped evidence additions."""
    op.drop_index("ix_evidence_research_run_id", table_name="evidence")
    op.drop_constraint("fk_evidence_research_run_id_research_run", "evidence", type_="foreignkey")
    op.drop_column("evidence", "subject")
    op.drop_column("evidence", "criterion")
    op.drop_column("evidence", "research_run_id")
