"""Transient evidence-grounded qualification results."""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from virtual_company.domain.criteria import CriterionRequirement


class QualificationStatus(StrEnum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    UNKNOWN = "UNKNOWN"


class CompanyQualificationStatus(StrEnum):
    QUALIFIED = "QUALIFIED"
    NOT_QUALIFIED = "NOT_QUALIFIED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


@dataclass(frozen=True)
class CriterionQualification:
    criterion: str
    subject: str | None
    requirement: CriterionRequirement
    status: QualificationStatus
    evidence_ids: list[UUID]
    reason: str


@dataclass(frozen=True)
class CompanyQualification:
    company_id: UUID
    status: CompanyQualificationStatus
    criteria: list[CriterionQualification]
