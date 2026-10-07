"""Pydantic data-transfer models for the research workflow."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SearchResult(BaseModel):
    """One result returned by a web search provider."""

    title: str
    url: str
    snippet: str | None = None


class WebPage(BaseModel):
    """Downloaded web-page content for later analysis."""

    url: str
    final_url: str | None = None
    title: str | None = None
    content: str
    content_type: str | None = None
    truncated: bool = False


class DiscoveredCompany(BaseModel):
    """A company found during research before persistence."""

    name: str
    website: str | None = None
    domain: str | None = None
    discovery_reason: str = Field(min_length=1)
    supporting_urls: list[str] = Field(max_length=3)


class EvidenceCriterion(StrEnum):
    """Campaign criteria which can be supported by extracted evidence."""

    TARGET_MARKET = "target_market"
    INDUSTRY = "industry"
    TECHNOLOGY = "technology"
    COMPANY_SIZE = "company_size"


class ExtractedEvidence(BaseModel):
    """LLM-provided evidence content, without authoritative source identity."""

    criterion: EvidenceCriterion
    subject: str | None = None
    claim: str = Field(min_length=1)
    evidence_text: str = Field(min_length=1)


class ExtractedEvidenceItems(BaseModel):
    """Structured output from one page-scoped evidence extraction call."""

    evidence: list[ExtractedEvidence] = Field(default_factory=list)


class EmployeeCountFact(BaseModel):
    """One supported employee-count observation, never a qualification decision."""

    model_config = ConfigDict(extra="forbid")

    value: int = Field(ge=0, strict=True)
    relation: Literal[
        "exact",
        "greater_than",
        "greater_than_or_equal",
        "less_than",
        "less_than_or_equal",
        "approximately",
    ]
    year: int | None = Field(default=None, gt=0, strict=True)
    scope: Literal["global", "regional", "unknown"] = "unknown"


class CategoricalEvidenceFact(BaseModel):
    """Evidence-grounded semantic support for one configured criterion."""

    model_config = ConfigDict(extra="forbid")

    criterion_id: str = Field(min_length=1)
    state: Literal["supported", "unknown", "conflicting"]
    evidence_ids: list[UUID] = Field(default_factory=list)


class EmployeeCountEvidenceFact(EmployeeCountFact):
    """One employee-count observation linked to its source Evidence records."""

    evidence_ids: list[UUID] = Field(min_length=1)


class QualificationFacts(BaseModel):
    """Strict semantic facts extracted for deterministic qualification."""

    model_config = ConfigDict(extra="forbid")

    categorical: list[CategoricalEvidenceFact] = Field(default_factory=list)
    employee_counts: list[EmployeeCountEvidenceFact] = Field(default_factory=list)


class QualificationFactsCacheStatus(StrEnum):
    SUCCESS = "success"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_EXHAUSTED = "failed_exhausted"


class QualificationFactsCacheEntry(BaseModel):
    """Transient facts and the exact Evidence set from which they were extracted."""

    model_config = ConfigDict(extra="forbid")

    evidence_ids: list[UUID]
    facts: QualificationFacts | None
    status: QualificationFactsCacheStatus = QualificationFactsCacheStatus.SUCCESS
    attempt_count: int = Field(default=1, ge=0, le=2)

    @model_validator(mode="after")
    def validate_status(self) -> QualificationFactsCacheEntry:
        if self.status is QualificationFactsCacheStatus.SUCCESS and self.facts is None:
            raise ValueError("Successful fact extraction requires facts")
        if self.status is not QualificationFactsCacheStatus.SUCCESS and self.facts is not None:
            raise ValueError("Failed fact extraction cannot contain facts")
        if self.status is QualificationFactsCacheStatus.FAILED_RETRYABLE and self.attempt_count != 1:
            raise ValueError("Retryable extraction failures require one attempt")
        if self.status is QualificationFactsCacheStatus.FAILED_EXHAUSTED and self.attempt_count != 2:
            raise ValueError("Exhausted extraction failures require two attempts")
        if self.status is QualificationFactsCacheStatus.SUCCESS and self.evidence_ids and self.attempt_count == 0:
            raise ValueError("Successful extraction of Evidence requires an attempt")
        return self
