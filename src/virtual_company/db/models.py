"""SQLAlchemy models for the research persistence schema."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from virtual_company.db.base import Base


class Campaign(Base):
    """A company-research campaign."""

    __tablename__ = "campaign"
    __table_args__ = (
        CheckConstraint(
            "max_companies_to_research >= target_count",
            name="ck_campaign_max_companies_to_research_ge_target_count",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    target_market: Mapped[str | None] = mapped_column(String(255))
    industry: Mapped[str | None] = mapped_column(String(255))
    technologies: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    company_size: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    target_count: Mapped[int] = mapped_column(Integer, nullable=False)
    max_companies_to_research: Mapped[int] = mapped_column(
        Integer, nullable=False, default=15, server_default="15"
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    sealed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    targets: Mapped[list[CampaignTarget]] = relationship(back_populates="campaign")
    research_runs: Mapped[list[ResearchRun]] = relationship(back_populates="campaign")


class ResearchCompany(Base):
    """A company discovered during research."""

    __tablename__ = "research_company"

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    website: Mapped[str | None] = mapped_column(String(1000))
    domain: Mapped[str | None] = mapped_column(String(255))
    industry: Mapped[str | None] = mapped_column(String(255))
    country: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(255))
    city: Mapped[str | None] = mapped_column(String(255))
    employee_number: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    campaign_targets: Mapped[list[CampaignTarget]] = relationship(
        back_populates="research_company"
    )
    research_evidence: Mapped[list[ResearchEvidence]] = relationship(
        back_populates="research_company"
    )


class CampaignTarget(Base):
    """A candidate company within a campaign, pending future qualification."""

    __tablename__ = "campaign_targets"

    campaign_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("campaign.id"), primary_key=True
    )
    company_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "research_company.id",
            name="campaign_targets_research_company_id_fkey",
        ),
        primary_key=True,
    )
    score: Mapped[Decimal | None] = mapped_column(Numeric)
    status: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    campaign: Mapped[Campaign] = relationship(back_populates="targets")
    research_company: Mapped[ResearchCompany] = relationship(
        back_populates="campaign_targets"
    )


class ResearchEvidence(Base):
    """A source-backed claim about a company."""

    __tablename__ = "research_evidence"
    __table_args__ = (Index("ix_research_evidence_research_run_id", "research_run_id"),)

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    company_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "research_company.id",
            name="research_evidence_research_company_id_fkey",
        ),
    )
    research_run_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("research_run.id", name="research_evidence_research_run_id_fkey"),
    )
    criterion: Mapped[str | None] = mapped_column(String(50))
    subject: Mapped[str | None] = mapped_column(String(500))
    claim: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_title: Mapped[str | None] = mapped_column(String(500))
    source_type: Mapped[str | None] = mapped_column(String(50))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    research_company: Mapped[ResearchCompany] = relationship(
        back_populates="research_evidence"
    )
    research_run: Mapped[ResearchRun | None] = relationship(
        back_populates="research_evidence"
    )


class ResearchRun(Base):
    """An execution of research for a campaign."""

    __tablename__ = "research_run"

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    campaign_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("campaign.id")
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    companies_found: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    campaign: Mapped[Campaign] = relationship(back_populates="research_runs")
    research_evidence: Mapped[list[ResearchEvidence]] = relationship(
        back_populates="research_run"
    )


class ResearchCompanyQualification(Base):
    """One final qualification result per company and research run."""

    __tablename__ = "research_company_qualifications"
    __table_args__ = (
        UniqueConstraint(
            "research_run_id",
            "company_id",
            name="uq_research_company_qualifications_run_company",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    research_run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "research_run.id",
            name="research_company_qualifications_research_run_id_fkey",
        ),
        nullable=False,
    )
    campaign_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "campaign.id",
            name="research_company_qualifications_campaign_id_fkey",
        ),
        nullable=False,
    )
    company_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "research_company.id",
            name="research_company_qualifications_research_company_id_fkey",
        ),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    criteria_results: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
