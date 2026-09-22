"""Deterministic campaign-criterion coverage derived from structured Evidence."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from virtual_company.domain.criteria import (
    campaign_criteria,
    normalize_subject,
    technology_subjects,
)
from virtual_company.research.models import EvidenceCriterion
from virtual_company.workflows.research.models import (
    CampaignCriteria,
    CoverageStatus,
    CriterionCoverage,
)


class EvidenceForCoverage(Protocol):
    id: UUID
    company_id: UUID
    research_run_id: UUID | None
    criterion: str | None
    subject: str | None


def assess_evidence_coverage(
    campaign: CampaignCriteria,
    evidence: Sequence[EvidenceForCoverage],
    *,
    company_id: UUID,
    research_run_id: UUID,
) -> list[CriterionCoverage]:
    """Match current-run evidence to every configured campaign criterion."""
    expected = campaign_criteria(campaign)

    matches: dict[tuple[str, str], list[UUID]] = defaultdict(list)
    for item in evidence:
        if item.company_id != company_id or item.research_run_id != research_run_id:
            continue
        criterion = str(item.criterion or "")
        subjects = (
            {""}
            if criterion == "company_size"
            else technology_subjects(item.subject)
            if criterion == "technology"
            else {normalize_subject(criterion, item.subject)}
        )
        for subject_key in subjects:
            matches[(criterion, subject_key)].append(item.id)

    coverage: list[CriterionCoverage] = []
    for criterion, subject in expected:
        key = (
            criterion,
            ""
            if criterion == "company_size"
            else normalize_subject(criterion, subject),
        )
        evidence_ids = sorted(set(matches.get(key, [])), key=str)
        coverage.append(
            CriterionCoverage(
                criterion=EvidenceCriterion(criterion),
                subject=subject,
                status=CoverageStatus.FOUND if evidence_ids else CoverageStatus.MISSING,
                evidence_ids=evidence_ids,
            )
        )
    return coverage
