"""Workflow-owned raw structured output and extraction context models."""

from __future__ import annotations

import unicodedata
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from virtual_company.domain.exploration.facts import ExplorationFact


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


class ExplorationFactCompanyContext(BaseModel):
    """Minimal selected-company context for factual normalization."""

    model_config = ConfigDict(extra="forbid")

    exploration_company_id: UUID
    company_name: str = Field(min_length=1)

    @field_validator("company_name")
    @classmethod
    def normalize_company_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("company_name must not be blank")
        return value


class ExplorationFactEvidenceInput(BaseModel):
    """Persisted Evidence fields explicitly supplied to fact extraction."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: UUID
    exploration_company_id: UUID
    exploration_obligation_id: UUID
    claim: str = Field(min_length=1)
    supporting_excerpt: str = Field(min_length=1)


class ExtractedExplorationFact(BaseModel):
    """Raw structured statement and chunk-local Evidence labels."""

    model_config = ConfigDict(extra="forbid")

    statement: str
    evidence_refs: list[str]


class ExtractedExplorationFacts(BaseModel):
    """Strict structured result; an empty facts list is valid."""

    model_config = ConfigDict(extra="forbid")

    facts: list[ExtractedExplorationFact]


class ExplorationFactExtractionOutcome(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class ExplorationFactExtractionFailureCategory(StrEnum):
    CONFIGURATION = "configuration"
    TIMEOUT = "timeout"
    PROVIDER_ERROR = "provider_error"
    MALFORMED_OUTPUT = "malformed_output"
    INPUT_LIMIT = "input_limit"
    UNEXPECTED_ERROR = "unexpected_error"


class ExplorationFactExtractionChunkResult(BaseModel):
    """One deterministic outcome for an ordered Evidence chunk."""

    model_config = ConfigDict(extra="forbid")

    chunk_index: int = Field(ge=0)
    evidence_count: int = Field(ge=1)
    outcome: ExplorationFactExtractionOutcome
    facts: list[ExplorationFact] = Field(default_factory=list)
    failure_category: ExplorationFactExtractionFailureCategory | None = None
    rejected_fact_count: int = Field(default=0, ge=0)


class ExplorationFactExtractionBatchResult(BaseModel):
    """Ordered chunk outcomes and exact-deduplicated validated Facts."""

    model_config = ConfigDict(extra="forbid")

    exploration_company_id: UUID
    provider: str
    model: str
    outcomes: list[ExplorationFactExtractionChunkResult]
    facts: list[ExplorationFact]


class ExplorationHypothesisCompanyContext(BaseModel):
    """Minimal company identity supplied to Hypothesis Generation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    exploration_company_id: UUID
    company_name: str = Field(min_length=1)

    @field_validator("company_name")
    @classmethod
    def normalize_company_name(cls, value: str) -> str:
        normalized = " ".join(unicodedata.normalize("NFKC", value).split())
        if not normalized:
            raise ValueError("company_name must not be blank")
        return normalized


class ExplorationHypothesisFactInput(BaseModel):
    """One persisted same-company Fact supplied without its ORM entity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fact_id: UUID
    exploration_company_id: UUID
    statement: str = Field(min_length=1, max_length=2_000)

    @field_validator("statement")
    @classmethod
    def normalize_statement(cls, value: str) -> str:
        normalized = " ".join(unicodedata.normalize("NFKC", value).split())
        if not normalized:
            raise ValueError("statement must not be blank")
        return normalized


class ExtractedExplorationHypothesis(BaseModel):
    """One raw model hypothesis and its call-local Fact references."""

    model_config = ConfigDict(extra="forbid")

    statement: str = Field(strict=True)
    fact_refs: list[str] = Field(strict=True)


class ExtractedExplorationHypotheses(BaseModel):
    """Strict structured result; no hypotheses is a valid response."""

    model_config = ConfigDict(extra="forbid")

    hypotheses: list[ExtractedExplorationHypothesis] = Field(strict=True)


class ExplorationHypothesisGenerationOutcome(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class ExplorationHypothesisGenerationFailureCategory(StrEnum):
    CONFIGURATION = "configuration"
    INPUT_LIMIT = "input_limit"
    PROVIDER_ERROR = "provider_error"
    TIMEOUT = "timeout"
    MALFORMED_OUTPUT = "malformed_output"
    UNEXPECTED_ERROR = "unexpected_error"
