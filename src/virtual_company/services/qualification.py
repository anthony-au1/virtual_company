"""Pure deterministic qualification over validated semantic facts."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from virtual_company.domain.criteria import (
    CampaignCriterion,
    CampaignForQualification,
    campaign_criteria,
)
from virtual_company.domain.qualification import (
    CompanyQualification,
    CompanyQualificationStatus,
    CriterionQualification,
    QualificationStatus,
)
from virtual_company.research.models import (
    CategoricalEvidenceFact,
    EmployeeCountFact,
    QualificationFacts,
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
    criterion: CampaignCriterion, bounds: EmployeeCountBounds
) -> tuple[QualificationStatus, str]:
    threshold = criterion.size_value
    if threshold is None:
        raise ValueError("Company-size criterion needs a threshold")
    prefix = f"Validated evidence establishes {_describe_size(bounds)}"
    if (
        criterion.size_bound == "min"
        and bounds.upper is not None
        and bounds.upper < threshold
    ):
        return (
            QualificationStatus.MISMATCH,
            f"{prefix}, below the campaign minimum of {threshold}.",
        )
    if (
        criterion.size_bound == "max"
        and bounds.lower is not None
        and bounds.lower > threshold
    ):
        return (
            QualificationStatus.MISMATCH,
            f"{prefix}, exceeding the campaign maximum of {threshold}.",
        )
    bound_met = (
        bounds.lower is not None and bounds.lower >= threshold
        if criterion.size_bound == "min"
        else bounds.upper is not None and bounds.upper <= threshold
    )
    if bound_met:
        constraint = f"{'minimum' if criterion.size_bound == 'min' else 'maximum'} of {threshold}"
        return (
            QualificationStatus.MATCH,
            f"{prefix}, satisfying the campaign {constraint}.",
        )
    return QualificationStatus.UNKNOWN, (
        "Available company-size evidence does not establish whether the company "
        "satisfies the campaign size constraint."
    )


def _qualify_size(
    criterion: CampaignCriterion,
    facts: QualificationFacts | None,
    as_of_year: int,
) -> CriterionQualification:
    employee_facts = facts.employee_counts if facts is not None else []
    ids = sorted(
        {evidence_id for fact in employee_facts for evidence_id in fact.evidence_ids},
        key=str,
    )
    status = QualificationStatus.UNKNOWN
    reason = "No validated company-size facts are available."
    if employee_facts:
        selected, note = _select_size_facts(employee_facts, as_of_year)
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
                status, reason = _evaluate_size(criterion, bounds)
            else:
                reason = (
                    "Available company-size evidence is approximate or otherwise "
                    "insufficient for the campaign constraint."
                )
            reason += note
    return CriterionQualification(
        "company_size", criterion.subject, status, ids, reason
    )


def _qualify_category(
    criterion: CampaignCriterion,
    fact: CategoricalEvidenceFact | None,
) -> CriterionQualification:
    ids = sorted(set(fact.evidence_ids), key=str) if fact else []
    if fact is not None and fact.state == "supported":
        status = QualificationStatus.MATCH
        reason = "Validated semantic facts support this criterion."
    elif fact is not None and fact.state == "conflicting":
        status = QualificationStatus.UNKNOWN
        reason = "Available evidence is conflicting for this criterion."
    else:
        status = QualificationStatus.UNKNOWN
        reason = "Available evidence does not establish this criterion."
    return CriterionQualification(
        criterion.criterion,
        criterion.subject,
        status,
        ids,
        reason,
    )


def qualify_company(
    campaign: CampaignForQualification,
    facts: QualificationFacts | None,
    *,
    as_of_year: int | None = None,
) -> list[CriterionQualification]:
    """Evaluate one company's already validated facts without any LLM call."""
    categorical = (
        {item.criterion_id: item for item in facts.categorical}
        if facts is not None
        else {}
    )
    results: list[CriterionQualification] = []
    for index, criterion in enumerate(campaign_criteria(campaign)):
        results.append(
            _qualify_size(
                criterion,
                facts,
                as_of_year if as_of_year is not None else datetime.now(UTC).year,
            )
            if criterion.criterion == "company_size"
            else _qualify_category(criterion, categorical.get(f"criterion_{index}"))
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
