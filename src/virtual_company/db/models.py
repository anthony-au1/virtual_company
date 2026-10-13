"""SQLAlchemy models for the research persistence schema."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from virtual_company.db.base import Base

exploration_fact_evidence = Table(
    "exploration_fact_evidence",
    Base.metadata,
    Column(
        "exploration_fact_id",
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "exploration_fact.id", name="exploration_fact_evidence_fact_id_fkey"
        ),
        primary_key=True,
    ),
    Column(
        "exploration_evidence_id",
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "exploration_evidence.id",
            name="exploration_fact_evidence_evidence_id_fkey",
        ),
        primary_key=True,
    ),
    Index(
        "ix_exploration_fact_evidence_exploration_evidence_id",
        "exploration_evidence_id",
    ),
)

exploration_hypothesis_fact = Table(
    "exploration_hypothesis_fact",
    Base.metadata,
    Column(
        "exploration_hypothesis_id",
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "exploration_hypothesis.id",
            name="exploration_hypothesis_fact_hypothesis_id_fkey",
        ),
        primary_key=True,
    ),
    Column(
        "exploration_fact_id",
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "exploration_fact.id", name="exploration_hypothesis_fact_fact_id_fkey"
        ),
        primary_key=True,
    ),
    Index("ix_exploration_hypothesis_fact_exploration_fact_id", "exploration_fact_id"),
)


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
    exploration_links: Mapped[list[ExplorationCompany]] = relationship(
        back_populates="company"
    )


class CampaignTarget(Base):
    """A candidate company within a campaign, pending future qualification."""

    __tablename__ = "campaign_target"

    campaign_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("campaign.id", name="campaign_target_campaign_id_fkey"),
        primary_key=True,
    )
    company_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "research_company.id",
            name="campaign_target_research_company_id_fkey",
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

    __tablename__ = "research_company_qualification"
    __table_args__ = (
        UniqueConstraint(
            "research_run_id",
            "company_id",
            name="uq_research_company_qualification_run_company",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    research_run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "research_run.id",
            name="research_company_qualification_research_run_id_fkey",
        ),
        nullable=False,
    )
    campaign_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "campaign.id",
            name="research_company_qualification_campaign_id_fkey",
        ),
        nullable=False,
    )
    company_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "research_company.id",
            name="research_company_qualification_research_company_id_fkey",
        ),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    criteria_results: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Exploration(Base):
    """An Exploration definition and its business context."""

    __tablename__ = "exploration"

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    business_context: Mapped[str] = mapped_column(Text, nullable=False)
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

    obligations: Mapped[list[ExplorationObligation]] = relationship(
        back_populates="exploration"
    )
    runs: Mapped[list[ExplorationRun]] = relationship(back_populates="exploration")


class ExplorationObligation(Base):
    """A requirement or question guiding an Exploration."""

    __tablename__ = "exploration_obligation"
    __table_args__ = (
        Index("ix_exploration_obligation_exploration_id", "exploration_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    exploration_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("exploration.id", name="exploration_obligation_exploration_id_fkey"),
        nullable=False,
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    exploration: Mapped[Exploration] = relationship(back_populates="obligations")
    evidence: Mapped[list[ExplorationEvidence]] = relationship(
        back_populates="obligation"
    )


class ExplorationRun(Base):
    """One execution of an Exploration."""

    __tablename__ = "exploration_run"
    __table_args__ = (Index("ix_exploration_run_exploration_id", "exploration_id"),)

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    exploration_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("exploration.id", name="exploration_run_exploration_id_fkey"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    exploration: Mapped[Exploration] = relationship(back_populates="runs")
    companies: Mapped[list[ExplorationCompany]] = relationship(back_populates="run")


class ExplorationCompany(Base):
    """A research company in the context of an Exploration run."""

    __tablename__ = "exploration_company"
    __table_args__ = (
        UniqueConstraint(
            "exploration_run_id",
            "company_id",
            name="uq_exploration_company_run_company",
        ),
        Index("ix_exploration_company_company_id", "company_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    exploration_run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "exploration_run.id", name="exploration_company_exploration_run_id_fkey"
        ),
        nullable=False,
    )
    company_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("research_company.id", name="exploration_company_company_id_fkey"),
        nullable=False,
    )

    run: Mapped[ExplorationRun] = relationship(back_populates="companies")
    company: Mapped[ResearchCompany] = relationship(back_populates="exploration_links")
    evidence: Mapped[list[ExplorationEvidence]] = relationship(
        back_populates="exploration_company"
    )


class ExplorationEvidence(Base):
    """External supporting material collected for an obligation and company."""

    __tablename__ = "exploration_evidence"
    __table_args__ = (
        Index(
            "ix_exploration_evidence_exploration_company_id",
            "exploration_company_id",
        ),
        Index(
            "ix_exploration_evidence_exploration_obligation_id",
            "exploration_obligation_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    exploration_company_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "exploration_company.id",
            name="exploration_evidence_exploration_company_id_fkey",
        ),
        nullable=False,
    )
    exploration_obligation_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "exploration_obligation.id",
            name="exploration_evidence_exploration_obligation_id_fkey",
        ),
        nullable=False,
    )
    source_url: Mapped[str | None] = mapped_column(Text)
    source_type: Mapped[str | None] = mapped_column(String(50))
    content: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    exploration_company: Mapped[ExplorationCompany] = relationship(
        back_populates="evidence"
    )
    obligation: Mapped[ExplorationObligation] = relationship(back_populates="evidence")
    facts: Mapped[list[ExplorationFact]] = relationship(
        secondary=exploration_fact_evidence, back_populates="evidence"
    )


class ExplorationFact(Base):
    """A factual statement derived from supporting Evidence."""

    __tablename__ = "exploration_fact"

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    evidence: Mapped[list[ExplorationEvidence]] = relationship(
        secondary=exploration_fact_evidence, back_populates="facts"
    )
    hypotheses: Mapped[list[ExplorationHypothesis]] = relationship(
        secondary=exploration_hypothesis_fact, back_populates="facts"
    )


class ExplorationHypothesis(Base):
    """A higher-level inference derived from Facts."""

    __tablename__ = "exploration_hypothesis"

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    facts: Mapped[list[ExplorationFact]] = relationship(
        secondary=exploration_hypothesis_fact, back_populates="hypotheses"
    )
