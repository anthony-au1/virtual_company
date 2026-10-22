"""Transient results for evidence-grounded Research qualification."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class QualificationStatus(StrEnum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    UNKNOWN = "UNKNOWN"


class ResearchCompanyQualificationStatus(StrEnum):
    QUALIFIED = "QUALIFIED"
    NOT_QUALIFIED = "NOT_QUALIFIED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


@dataclass(frozen=True)
class CriterionQualification:
    criterion: str
    subject: str | None
    status: QualificationStatus
    evidence_ids: list[UUID]
    reason: str


@dataclass(frozen=True)
class ResearchCompanyQualification:
    company_id: UUID
    status: ResearchCompanyQualificationStatus
    criteria: list[CriterionQualification]
    provenance: dict[str, object] | None = None
