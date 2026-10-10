"""Pure deterministic qualification over validated semantic facts."""

from __future__ import annotations

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


def _fact_bounds(fact: EmployeeCountFact) -> tuple[int | None, int | None] | None:
    match fact.relation:
        case "exact":
            return fact.value, fact.value
        case "greater_than":
            return fact.value + 1, None
        case "greater_than_or_equal":
            return fact.value, None
        case "less_than":
            return None, fact.value - 1
        case "less_than_or_equal":
            return None, fact.value
        case "approximately":
            return None


def _fact_proves_size_predicate(
    criterion: CampaignCriterion, fact: EmployeeCountFact
) -> QualificationStatus | None:
    threshold = criterion.size_value
    if threshold is None:
        raise ValueError("Company-size criterion needs a threshold")
    bounds = _fact_bounds(fact)
    if bounds is None:
        return None
    lower, upper = bounds
    if criterion.size_bound == "min":
        if lower is not None and lower >= threshold:
            return QualificationStatus.MATCH
        if fact.scope != "regional" and upper is not None and upper < threshold:
            return QualificationStatus.MISMATCH
        return None
    if lower is not None and lower > threshold:
        return QualificationStatus.MISMATCH
    if fact.scope != "regional" and upper is not None and upper <= threshold:
        return QualificationStatus.MATCH
    return None


def _qualify_size(
    criterion: CampaignCriterion,
    facts: QualificationFacts | None,
    as_of_year: int,
) -> CriterionQualification:
    employee_facts = facts.employee_counts if facts is not None else []
    eligible_facts = [
        fact
        for fact in employee_facts
        if fact.year is None or fact.year <= as_of_year
    ]
    proven = [
        (fact, result)
        for fact in eligible_facts
        if (result := _fact_proves_size_predicate(criterion, fact)) is not None
    ]
    preferred_status = (
        QualificationStatus.MATCH
        if criterion.size_bound == "min"
        else QualificationStatus.MISMATCH
    )
    decisive = [item for item in proven if item[1] is preferred_status]
    if not decisive:
        decisive = proven
    status = decisive[0][1] if decisive else QualificationStatus.UNKNOWN
    ids = sorted(
        {
            evidence_id
            for fact, _ in decisive
            for evidence_id in fact.evidence_ids
        },
        key=str,
    )
    if status is QualificationStatus.UNKNOWN:
        reason = (
            "No validated company-size evidence establishes whether the company "
            "satisfies the campaign size constraint."
        )
    elif status is QualificationStatus.MATCH:
        reason = "Validated employee-count evidence establishes the campaign size constraint."
    else:
        reason = "Validated employee-count evidence violates the campaign size constraint."
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
