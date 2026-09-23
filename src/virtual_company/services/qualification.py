"""Pure qualification using validated, persisted Evidence only."""

import re
from collections.abc import Sequence
from dataclasses import dataclass
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
_OPERATOR = r"over|more than|at least|under|fewer than|less than|up to|at most"
_SIZE_VALUE = rf"(?P<operator>{_OPERATOR})?\s*(?P<count>{_NUMBER})(?P<plus>\+)?"
_COUNT = re.compile(
    rf"(?<![\w.,+−-]){_SIZE_VALUE}\s+(?:employees|staff|people)\b",
    re.IGNORECASE,
)
_TEAM_COUNT = re.compile(
    rf"\b(?:team|workforce)\s+of\s+{_SIZE_VALUE}(?![\w,+%−-]|\.\d)",
    re.IGNORECASE,
)
_UNSUPPORTED_SIZE = re.compile(
    r"\b(about|around|approximately|roughly|between|nearly|"
    r"not|no|never|without|unknown|unclear|former|formerly|previously|might|may|possibly|"
    r"million|billion|thousand)\b|[~<>%]|"
    r"\d\s*(?:[-–—]|to)\s*\d",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class EmployeeCountBounds:
    lower: int | None
    upper: int | None


def _intersect_bounds(bounds: Sequence[EmployeeCountBounds]) -> EmployeeCountBounds:
    return EmployeeCountBounds(
        max((value.lower for value in bounds if value.lower is not None), default=None),
        min((value.upper for value in bounds if value.upper is not None), default=None),
    )


def _contradictory(bounds: EmployeeCountBounds) -> bool:
    return (
        bounds.lower is not None
        and bounds.upper is not None
        and bounds.lower > bounds.upper
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


def _parse_size_text(text: str) -> list[EmployeeCountBounds]:
    values: list[EmployeeCountBounds] = []
    for pattern in (_COUNT, _TEAM_COUNT):
        for match in pattern.finditer(text):
            count = int(match["count"].replace(",", ""))
            operator = (match["operator"] or "").lower()
            if operator in {"over", "more than"}:
                values.append(EmployeeCountBounds(count + 1, None))
            elif operator == "at least" or match["plus"]:
                values.append(EmployeeCountBounds(count, None))
            elif operator in {"under", "fewer than", "less than"}:
                values.append(EmployeeCountBounds(None, count - 1))
            elif operator in {"up to", "at most"}:
                values.append(EmployeeCountBounds(None, count))
            else:
                values.append(EmployeeCountBounds(count, count))
    return values


def _size_bounds(item: EvidenceForQualification) -> EmployeeCountBounds | None:
    subject = (item.subject or "").strip()
    texts = tuple(
        " ".join(text.split()) for text in (item.evidence_text, item.claim, subject)
    )
    # Neither extraction summaries nor numeric subjects may erase uncertainty.
    if any(_UNSUPPORTED_SIZE.search(text) for text in texts):
        return None
    values = [value for text in texts for value in _parse_size_text(text)]
    if re.fullmatch(_NUMBER, subject):
        count = int(subject.replace(",", ""))
        # Preserve legacy numeric subjects, but don't strengthen inequalities.
        if not values or all(value.lower == value.upper for value in values):
            values.append(EmployeeCountBounds(count, count))
    return _intersect_bounds(values) if values else None


def _describe_size(bounds: EmployeeCountBounds) -> str:
    if bounds.lower == bounds.upper:
        return f"{bounds.lower} employees"
    if bounds.upper is None:
        return f"at least {bounds.lower} employees"
    if bounds.lower is None:
        return f"at most {bounds.upper} employees"
    return f"between {bounds.lower} and {bounds.upper} employees"


def _evaluate_size(
    campaign: CampaignForQualification, bounds: EmployeeCountBounds
) -> tuple[QualificationStatus, str]:
    minimum, maximum = campaign.company_size_min, campaign.company_size_max
    prefix = f"Validated evidence establishes {_describe_size(bounds)}"
    if minimum is not None and bounds.upper is not None and bounds.upper < minimum:
        return (
            QualificationStatus.MISMATCH,
            f"{prefix}, below the campaign minimum of {minimum}.",
        )
    if maximum is not None and bounds.lower is not None and bounds.lower > maximum:
        return (
            QualificationStatus.MISMATCH,
            f"{prefix}, exceeding the campaign maximum of {maximum}.",
        )
    minimum_met = minimum is None or (
        bounds.lower is not None and bounds.lower >= minimum
    )
    maximum_met = maximum is None or (
        bounds.upper is not None and bounds.upper <= maximum
    )
    if minimum_met and maximum_met:
        constraint = (
            f"range of {minimum} to {maximum}"
            if minimum is not None and maximum is not None
            else f"minimum of {minimum}"
            if minimum is not None
            else f"maximum of {maximum}"
        )
        return (
            QualificationStatus.MATCH,
            f"{prefix}, satisfying the campaign {constraint}.",
        )
    return (
        QualificationStatus.UNKNOWN,
        "Available company-size evidence does not establish whether the company satisfies the campaign size constraint.",
    )


def _qualify_size(
    campaign: CampaignForQualification, evidence: Sequence[EvidenceForQualification]
) -> CriterionQualification:
    ids = sorted({item.id for item in evidence}, key=str)
    parsed = [_size_bounds(item) for item in evidence]
    bounds = _intersect_bounds([value for value in parsed if value is not None])
    status = QualificationStatus.UNKNOWN
    reason = "Available company-size evidence does not establish whether the company satisfies the campaign size constraint."
    if not evidence:
        reason = "No validated company-size evidence is available."
    elif _contradictory(bounds):
        reason = "Available evidence contains conflicting company-size information."
    elif all(value is not None for value in parsed):
        status, reason = _evaluate_size(campaign, bounds)
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
