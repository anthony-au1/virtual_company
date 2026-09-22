"""Pure qualification using validated, persisted Evidence only."""

import re
from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from virtual_company.domain.criteria import (
    CampaignForQualification,
    campaign_criteria,
    normalize_subject,
    technology_subjects,
)
from virtual_company.domain.qualification import (
    CompanyQualification,
    CompanyQualificationStatus,
    CriterionQualification,
    QualificationStatus,
)


class EvidenceForQualification(Protocol):
    id: UUID
    criterion: str | None
    subject: str | None
    claim: str
    evidence_text: str


_AMBIGUOUS = re.compile(
    r"\b(no|not|never|without|unknown|unclear|might|may|possibly|lacks?|formerly)\b|n't\b",
    re.IGNORECASE,
)
_NEGATIVES = {
    "technology": r"\bdoes not (?:use|require) (.+?)[.!]?$",
    "target_market": r"\bdoes not operate in (.+?)[.!]?$",
    "industry": r"\bis not (?:a|an) (.+?) company[.!]?$",
}
_NUMBER = r"(?:\d{1,3}(?:,\d{3})+|\d+)"
_COUNT = re.compile(rf"(?<![\w.,+−-])({_NUMBER})\s+employees\b", re.IGNORECASE)
_INEXACT_SIZE = re.compile(
    r"\b(about|around|approximately|roughly|over|under|more|less|than|at least|"
    r"at most|between|nearly|up to|not|no|former|previously)\b|[+~<>]|\d\s*[-–—]\s*\d",
    re.IGNORECASE,
)


def _polarity(item: EvidenceForQualification) -> QualificationStatus:
    """Trust structured positive extraction; narrowly recognize explicit negatives."""
    criterion = item.criterion or ""
    subject = normalize_subject(criterion, item.subject)
    signals: list[QualificationStatus] = []
    for text in (item.claim, item.evidence_text):
        match = re.search(_NEGATIVES[criterion], text.strip(), re.IGNORECASE)
        if match and normalize_subject(criterion, match[1]) == subject:
            signals.append(QualificationStatus.MISMATCH)
        elif _AMBIGUOUS.search(text):
            return QualificationStatus.UNKNOWN
        else:
            signals.append(QualificationStatus.MATCH)
    if len(set(signals)) != 1:
        return QualificationStatus.UNKNOWN
    return signals[0]


def _size_counts(item: EvidenceForQualification) -> set[int]:
    texts = (item.subject or "", item.claim, item.evidence_text)
    # A numeric subject must not strengthen an explicitly approximate source.
    if any(_INEXACT_SIZE.search(text) for text in texts):
        return set()
    counts: set[int] = set()
    subject = (item.subject or "").strip()
    if re.fullmatch(_NUMBER, subject):
        counts.add(int(subject.replace(",", "")))
    for text in texts:
        counts.update(int(match[1].replace(",", "")) for match in _COUNT.finditer(text))
    return counts


def _qualify_size(
    campaign: CampaignForQualification, evidence: Sequence[EvidenceForQualification]
) -> CriterionQualification:
    ids = sorted({item.id for item in evidence}, key=str)
    parsed = [_size_counts(item) for item in evidence]
    counts = {count for values in parsed for count in values}
    status = QualificationStatus.UNKNOWN
    reason = "No validated evidence establishes an exact company employee count."
    if len(counts) > 1:
        reason = "Available evidence contains conflicting company-size information."
    elif counts and all(parsed):
        count = next(iter(counts))
        inside = (
            campaign.company_size_min is None or count >= campaign.company_size_min
        ) and (campaign.company_size_max is None or count <= campaign.company_size_max)
        status = QualificationStatus.MATCH if inside else QualificationStatus.MISMATCH
        reason = f"Explicit employee count {count} is {'within' if inside else 'outside'} the configured bounds."
    return CriterionQualification("company_size", None, status, ids, reason)


def _qualify_category(
    criterion: str, subject: str | None, evidence: Sequence[EvidenceForQualification]
) -> CriterionQualification:
    key = normalize_subject(criterion, subject)
    signals: list[QualificationStatus] = []
    ids: list[UUID] = []
    implied = False
    for item in evidence:
        direct = normalize_subject(criterion, item.subject) == key
        implication = criterion == "technology" and key in technology_subjects(
            item.subject
        )
        if not direct and not implication:
            continue
        polarity = _polarity(item)
        # Implications apply only to explicit positive support, never negatives.
        if not direct and polarity is not QualificationStatus.MATCH:
            continue
        ids.append(item.id)
        signals.append(polarity)
        implied |= not direct
    status = QualificationStatus.UNKNOWN
    reason = "No validated evidence establishes whether the company satisfies this criterion."
    if signals:
        unique = set(signals)
        if len(unique) == 1 and QualificationStatus.UNKNOWN not in unique:
            status = signals[0]
            reason = (
                (
                    "Validated evidence supports this criterion through a technology implication."
                    if implied
                    else "Validated evidence explicitly supports this criterion."
                )
                if status is QualificationStatus.MATCH
                else "Validated evidence explicitly states that the company does not satisfy this criterion."
            )
        else:
            reason = "Available evidence contains conflicting or ambiguous information."
    return CriterionQualification(
        criterion, subject, status, sorted(set(ids), key=str), reason
    )


def qualify_company(
    campaign: CampaignForQualification, evidence: Sequence[EvidenceForQualification]
) -> list[CriterionQualification]:
    """Evaluate one company's persisted evidence; callers enforce company scope."""
    results: list[CriterionQualification] = []
    for criterion, subject in campaign_criteria(campaign):
        relevant = [item for item in evidence if item.criterion == criterion]
        results.append(
            _qualify_size(campaign, relevant)
            if criterion == "company_size"
            else _qualify_category(criterion, subject, relevant)
        )
    return results


def aggregate_qualification(
    company_id: UUID, criteria: list[CriterionQualification]
) -> CompanyQualification:
    statuses = {item.status for item in criteria}
    if QualificationStatus.MISMATCH in statuses:
        status = CompanyQualificationStatus.NOT_QUALIFIED
    elif QualificationStatus.UNKNOWN in statuses:
        status = CompanyQualificationStatus.INSUFFICIENT_EVIDENCE
    else:
        status = CompanyQualificationStatus.QUALIFIED
    return CompanyQualification(company_id, status, criteria)
