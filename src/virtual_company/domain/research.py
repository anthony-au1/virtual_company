"""Research-specific company, evidence, and qualification contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DiscoveredCompany(BaseModel):
    """A company found by Research before persistence."""

    name: str
    website: str | None = None
    domain: str | None = None
    discovery_reason: str = Field(min_length=1)
    supporting_urls: list[str] = Field(max_length=3)


class EvidenceCriterion(StrEnum):
    """Campaign criteria which may be supported by Research evidence."""

    TARGET_MARKET = "target_market"
    INDUSTRY = "industry"
    KEYWORD = "keyword"
    COMPANY_SIZE = "company_size"


class ExtractedEvidence(BaseModel):
    """Research-extracted evidence content without authoritative source identity."""

    criterion: EvidenceCriterion
    subject: str | None = None
    claim: str = Field(min_length=1)
    evidence_text: str = Field(min_length=1)


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
    """Evidence-grounded support for one Research qualification criterion."""

    model_config = ConfigDict(extra="forbid")

    criterion_id: str = Field(min_length=1)
    state: Literal["supported", "unknown", "conflicting"]
    evidence_ids: list[UUID] = Field(default_factory=list)


class EmployeeCountEvidenceFact(EmployeeCountFact):
    """An employee-count observation linked to its source Evidence records."""

    evidence_ids: list[UUID] = Field(min_length=1)


class QualificationFacts(BaseModel):
    """Strict semantic facts extracted for deterministic Research qualification."""

    model_config = ConfigDict(extra="forbid")

    categorical: list[CategoricalEvidenceFact] = Field(default_factory=list)
    employee_counts: list[EmployeeCountEvidenceFact] = Field(default_factory=list)
