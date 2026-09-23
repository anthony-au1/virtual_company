"""Pure qualification using validated, persisted Evidence only."""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
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
from virtual_company.research.models import CompanySizeNormalization, EmployeeCountFact


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
_SIZE_VALUE = (
    rf"(?P<operator>{_OPERATOR})?\s*(?P<prefix_plus>\+)?"
    rf"(?P<count>{_NUMBER})(?P<plus>\+)?"
)
_COUNT = re.compile(
    rf"(?<![\w.,+−-]){_SIZE_VALUE}\s+(?:global\s+)?(?:employees|staff|people)\b",
    re.IGNORECASE,
)
_TEAM_COUNT = re.compile(
    rf"\b(?:team|workforce)\s+of\s+{_SIZE_VALUE}(?![\w,+%−-]|\.\d)",
    re.IGNORECASE,
)
_UNSUPPORTED_SIZE = re.compile(
    r"\b(about|around(?=\s+\+?\d)|approximately|roughly|between|nearly|"
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
            # A detached plus must not fall through to an exact-count match.
            if text[: match.start()].rstrip().endswith("+"):
                continue
            count = int(match["count"].replace(",", ""))
            operator = (match["operator"] or "").lower()
            if operator in {"over", "more than"}:
                values.append(EmployeeCountBounds(count + 1, None))
            elif operator == "at least" or match["plus"] or match["prefix_plus"]:
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


# Routing guards, not another employee-count parser. Strip recognized counts so
# an exact count such as "2000 employees" is not mistaken for a calendar year.
_YEAR = re.compile(r"\b(?:19|20|21)\d{2}\b")
_APPROXIMATE_SIZE = re.compile(r"\b(?:close to|almost|circa)\s+\+?\d", re.IGNORECASE)


def size_requires_semantic_interpretation(item: EvidenceForQualification) -> bool:
    """Dates and approximation must not be lost through regex fallback."""
    for text in (item.claim, item.evidence_text):
        normalized = " ".join(text.split())
        if _APPROXIMATE_SIZE.search(normalized):
            return True
        without_counts = _TEAM_COUNT.sub("", _COUNT.sub("", normalized))
        if _YEAR.search(without_counts):
            return True
    return False


def needs_size_normalization(item: EvidenceForQualification) -> bool:
    return item.criterion == "company_size" and (
        size_requires_semantic_interpretation(item) or _size_bounds(item) is None
    )


def _regex_size_facts(item: EvidenceForQualification) -> list[EmployeeCountFact]:
    if size_requires_semantic_interpretation(item):
        return []
    bounds = _size_bounds(item)
    if bounds is None:
        return []
    if bounds.lower == bounds.upper and bounds.lower is not None:
        return [EmployeeCountFact(value=bounds.lower, relation="exact")]
    facts: list[EmployeeCountFact] = []
    if bounds.lower is not None:
        facts.append(
            EmployeeCountFact(value=bounds.lower, relation="greater_than_or_equal")
        )
    if bounds.upper is not None:
        # A negative upper bound cannot describe a nonnegative headcount.
        if bounds.upper < 0:
            return []
        facts.append(
            EmployeeCountFact(value=bounds.upper, relation="less_than_or_equal")
        )
    return facts


def _fact_bounds(fact: EmployeeCountFact) -> EmployeeCountBounds | None:
    match fact.relation:
        case "exact":
            return EmployeeCountBounds(fact.value, fact.value)
        case "greater_than":
            return EmployeeCountBounds(fact.value + 1, None)
        case "greater_than_or_equal":
            return EmployeeCountBounds(fact.value, None)
        case "less_than":
            return EmployeeCountBounds(None, fact.value - 1)
        case "less_than_or_equal":
            return EmployeeCountBounds(None, fact.value)
        case "approximately":
            return None


def _select_size_facts(
    facts: Sequence[EmployeeCountFact], as_of_year: int
) -> tuple[list[EmployeeCountFact], str]:
    scopes = {fact.scope for fact in facts}
    if len(scopes) != 1 or "regional" in scopes:
        return [], "Company-size facts have incomparable or regional scopes."
    if any(fact.year is not None and fact.year > as_of_year for fact in facts):
        return [], "Company-size facts include future-year observations."
    latest = max((fact.year for fact in facts if fact.year is not None), default=None)
    selected = [fact for fact in facts if fact.year is None or fact.year == latest]
    note = ""
    if latest is not None:
        note = (
            f" Using the latest dated observations ({latest}) and any undated evidence."
        )
        if len(selected) < len(facts):
            note += " Older dated observations were superseded."
    return selected, note


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
    campaign: CampaignForQualification,
    evidence: Sequence[EvidenceForQualification],
    normalizations: Mapping[UUID, CompanySizeNormalization | None],
    as_of_year: int,
) -> CriterionQualification:
    ids = sorted({item.id for item in evidence}, key=str)
    status = QualificationStatus.UNKNOWN
    reason = "Available company-size evidence does not establish whether the company satisfies the campaign size constraint."
    records: list[list[EmployeeCountFact]] = []
    for item in evidence:
        normalized = normalizations.get(item.id)
        records.append(
            normalized.counts
            if normalized and normalized.counts
            else _regex_size_facts(item)
        )
    if not evidence:
        reason = "No validated company-size evidence is available."
    elif all(records):
        selected, note = _select_size_facts(
            [fact for facts in records for fact in facts], as_of_year
        )
        if not selected:
            reason = note
        else:
            parsed = [_fact_bounds(fact) for fact in selected]
            bounds = _intersect_bounds([value for value in parsed if value is not None])
            if _contradictory(bounds):
                reason = (
                    "Available evidence contains conflicting company-size information."
                )
            elif all(value is not None for value in parsed):
                status, reason = _evaluate_size(campaign, bounds)
            reason += note
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
    campaign: CampaignForQualification,
    evidence: Sequence[EvidenceForQualification],
    *,
    size_normalizations: Mapping[UUID, CompanySizeNormalization | None] | None = None,
    as_of_year: int | None = None,
) -> list[CriterionQualification]:
    """Evaluate one company's persisted evidence; callers enforce company scope."""
    results: list[CriterionQualification] = []
    for criterion, subject in campaign_criteria(campaign):
        relevant = [item for item in evidence if item.criterion == criterion]
        results.append(
            _qualify_size(
                campaign,
                relevant,
                size_normalizations or {},
                as_of_year if as_of_year is not None else datetime.now(UTC).year,
            )
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
