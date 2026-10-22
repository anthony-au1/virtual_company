"""Workflow-owned raw structured output and extraction context models."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ExtractedExplorationEvidence(BaseModel):
    """Raw page-scoped LLM claim and supporting excerpt."""

    model_config = ConfigDict(extra="forbid")

    claim: str = Field(min_length=1)
    evidence_text: str = Field(min_length=1)


class ExtractedExplorationEvidenceItems(BaseModel):
    """Structured LLM result; an empty evidence list is a valid success."""

    model_config = ConfigDict(extra="forbid")

    evidence: list[ExtractedExplorationEvidence] = Field(default_factory=list)


class ExplorationEvidenceCompanyContext(BaseModel):
    """Selected Exploration company/profile context for evidence extraction."""

    model_config = ConfigDict(extra="forbid")

    exploration_run_id: UUID
    exploration_company_id: UUID
    company_id: UUID
    name: str = Field(min_length=1)
    website: str | None = None
    domain: str | None = None
    industry: str | None = None
    country: str | None = None
    state: str | None = None
    city: str | None = None


class ExplorationEvidenceObligationContext(BaseModel):
    """The Exploration obligation investigated by this extraction batch."""

    model_config = ConfigDict(extra="forbid")

    exploration_obligation_id: UUID
    description: str = Field(min_length=1)

