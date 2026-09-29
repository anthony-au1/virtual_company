"""Pydantic data-transfer models for the research workflow."""

from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


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


class QualificationFactsCacheEntry(BaseModel):
    """Transient facts and the exact Evidence set from which they were extracted."""

    model_config = ConfigDict(extra="forbid")

    evidence_ids: list[UUID]
    facts: QualificationFacts | None
