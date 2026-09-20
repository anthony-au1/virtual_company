"""Deterministic campaign-criterion coverage derived from structured Evidence."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

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


def normalize_coverage_subject(value: str | None) -> str:
      return "".join(
          character
          for character in (value or "").casefold()
          if character.isalnum()
      )


def campaign_technologies(campaign: CampaignCriteria) -> list[str]:
    """Return the campaign's configured technology labels in stable order."""
    raw = campaign.technologies
    values = raw.values() if isinstance(raw, dict) else raw or []
    technologies: list[str] = []
    seen: set[str] = set()
    for value in values:
        label = str(value).strip()
        key = normalize_coverage_subject(label)
        if label and key and key not in seen:
            seen.add(key)
            technologies.append(label)
    return technologies


def assess_evidence_coverage(
    campaign: CampaignCriteria,
    evidence: Sequence[EvidenceForCoverage],
    *,
    company_id: UUID,
    research_run_id: UUID,
) -> list[CriterionCoverage]:
    """Match current-run evidence to every configured campaign criterion."""
    expected: list[tuple[EvidenceCriterion, str | None]] = []
    if campaign.target_market:
        expected.append((EvidenceCriterion.TARGET_MARKET, campaign.target_market))
    if campaign.industry:
        expected.append((EvidenceCriterion.INDUSTRY, campaign.industry))
    expected.extend(
        (EvidenceCriterion.TECHNOLOGY, technology)
        for technology in campaign_technologies(campaign)
    )
    if campaign.company_size_min is not None or campaign.company_size_max is not None:
        expected.append((EvidenceCriterion.COMPANY_SIZE, None))

    matches: dict[tuple[str, str], list[UUID]] = defaultdict(list)
    for item in evidence:
        if item.company_id != company_id or item.research_run_id != research_run_id:
            continue
        criterion = str(item.criterion or "")
        subject_key = (
            "" if criterion == EvidenceCriterion.COMPANY_SIZE.value
            else normalize_coverage_subject(item.subject)
        )
        matches[(criterion, subject_key)].append(item.id)

    coverage: list[CriterionCoverage] = []
    for criterion, subject in expected:
        key = (
            criterion.value,
            "" if criterion is EvidenceCriterion.COMPANY_SIZE else normalize_coverage_subject(subject),
        )
        evidence_ids = matches.get(key, [])
        coverage.append(
            CriterionCoverage(
                criterion=criterion,
                subject=subject,
                status=CoverageStatus.FOUND if evidence_ids else CoverageStatus.MISSING,
                evidence_ids=evidence_ids,
            )
        )
    return coverage
