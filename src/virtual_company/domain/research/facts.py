"""Evidence-grounded facts used by Research qualification."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

CategoricalEvidenceState = Literal["supported", "unknown", "conflicting"]


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
    state: CategoricalEvidenceState
    evidence_ids: list[UUID] = Field(default_factory=list)
    reason: str

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_reason(cls, value: object) -> str:
        if not isinstance(value, str):
            raise TypeError("Qualification fact reason must be text")
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("Qualification fact reason must not be empty")
        return normalized


class EmployeeCountEvidenceFact(EmployeeCountFact):
    """An employee-count observation linked to its source Evidence records."""

    evidence_ids: list[UUID] = Field(min_length=1)


class QualificationFacts(BaseModel):
    """Strict semantic facts extracted for deterministic Research qualification."""

    model_config = ConfigDict(extra="forbid")

    categorical: list[CategoricalEvidenceFact] = Field(default_factory=list)
    employee_counts: list[EmployeeCountEvidenceFact] = Field(default_factory=list)
