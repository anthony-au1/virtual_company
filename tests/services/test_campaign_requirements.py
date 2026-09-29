"""Campaign requirement validation and deterministic eligibility."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from virtual_company.api.models import CampaignCreateRequest
from virtual_company.domain.criteria import CriterionRequirement
from virtual_company.domain.qualification import (
    CompanyQualificationStatus,
    QualificationStatus,
)
from virtual_company.research.models import (
    CategoricalEvidenceFact,
    EmployeeCountEvidenceFact,
    QualificationFacts,
)
from virtual_company.services.coverage import assess_evidence_coverage
from virtual_company.services.qualification import (
    aggregate_qualification,
    qualify_company,
)
from virtual_company.workflows.research.models import CampaignCriteria, CoverageStatus


def request(**changes: object) -> CampaignCreateRequest:
    return CampaignCreateRequest.model_validate(
        {
            "name": "Australian Fintech Java Research",
            "target_count": 3,
            "status": "DRAFT",
            "description": "",
            "target_market": "Australia",
            "industry": "fin tech",
            "technologies": {
                "required": ["java"],
                "preferred": ["spring", "spring boot", "kafka"],
            },
            "company_size": {
                "min": {"value": 100, "requirement": "required"},
                "max": {"value": 500, "requirement": "preferred"},
            },
            **changes,
        }
    )


def evidence(criterion: str, subject: str | None, text: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        criterion=criterion,
        subject=subject,
        claim=text,
        evidence_text=text,
    )


def campaign() -> CampaignCriteria:
    payload = request().model_dump(mode="json")
    payload["id"] = str(uuid4())
    return CampaignCriteria.model_validate(payload)


def test_request_round_trip_and_independent_criteria() -> None:
    config = campaign()
    assert config.technologies.required == ["java"]
    assert config.technologies.preferred == ["spring", "spring boot", "kafka"]
    assert config.company_size is not None
    assert config.company_size.min.requirement is CriterionRequirement.REQUIRED
    assert config.company_size.max.requirement is CriterionRequirement.PREFERRED
    criteria = qualify_company(config, QualificationFacts())
    assert [(item.criterion, item.subject, item.requirement) for item in criteria] == [
        ("target_market", "Australia", CriterionRequirement.REQUIRED),
        ("industry", "fin tech", CriterionRequirement.REQUIRED),
        ("technology", "java", CriterionRequirement.REQUIRED),
        ("technology", "spring", CriterionRequirement.PREFERRED),
        ("technology", "spring boot", CriterionRequirement.PREFERRED),
        ("technology", "kafka", CriterionRequirement.PREFERRED),
        ("company_size", "employees >= 100", CriterionRequirement.REQUIRED),
        ("company_size", "employees <= 500", CriterionRequirement.PREFERRED),
    ]


@pytest.mark.parametrize(
    "technologies",
    [
        {"required": ["java", "kafka"], "preferred": ["kafka"]},
        {"required": ["SpringBoot"], "preferred": ["spring boot"]},
    ],
)
def test_normalized_technology_overlap_is_rejected(technologies: object) -> None:
    with pytest.raises(ValidationError):
        request(technologies=technologies)


@pytest.mark.parametrize(
    "size",
    [
        {"min": {"value": 100, "requirement": "required"}},
        {"max": {"value": 500, "requirement": "preferred"}},
        {
            "min": {"value": 100, "requirement": "preferred"},
            "max": {"value": 500, "requirement": "required"},
        },
        None,
    ],
)
def test_size_bounds_are_independent_or_absent(size: object) -> None:
    configured = request(company_size=size).company_size
    assert (
        configured is None
        if size is None
        else configured.model_dump(mode="json", exclude_none=True) == size
    )


@pytest.mark.parametrize(
    "size",
    [
        {
            "min": {"value": 501, "requirement": "required"},
            "max": {"value": 500, "requirement": "preferred"},
        },
        {"min": {"value": -1, "requirement": "required"}},
        {"min": {"value": 100}},
    ],
)
def test_invalid_size_is_rejected(size: object) -> None:
    with pytest.raises(ValidationError):
        request(company_size=size)


def test_required_only_aggregation_with_preferred_unknown_and_mismatch() -> None:
    config = campaign()
    evidence_ids = [uuid4() for _ in range(4)]
    facts = QualificationFacts(
        categorical=[
            CategoricalEvidenceFact(
                criterion_id=f"criterion_{index}",
                state="supported",
                evidence_ids=[evidence_ids[index]],
            )
            for index in range(3)
        ],
        employee_counts=[
            EmployeeCountEvidenceFact(
                value=2300, relation="exact", evidence_ids=[evidence_ids[3]]
            )
        ],
    )
    criteria = qualify_company(config, facts)
    assert criteria[-2].status is QualificationStatus.MATCH
    assert criteria[-1].status is QualificationStatus.MISMATCH
    assert criteria[5].status is QualificationStatus.UNKNOWN
    assert (
        aggregate_qualification(uuid4(), criteria).status
        is CompanyQualificationStatus.QUALIFIED
    )


def test_required_unknown_and_mismatch_have_distinct_outcomes() -> None:
    config = campaign()
    source_id = uuid4()
    facts = QualificationFacts(
        categorical=[
            CategoricalEvidenceFact(
                criterion_id=f"criterion_{index}",
                state="supported",
                evidence_ids=[uuid4()],
            )
            for index in range(2)
        ],
        employee_counts=[
            EmployeeCountEvidenceFact(
                value=47, relation="exact", evidence_ids=[source_id]
            )
        ],
    )
    criteria = qualify_company(config, facts)
    assert criteria[2].status is QualificationStatus.UNKNOWN
    assert criteria[-2].status is QualificationStatus.MISMATCH
    assert (
        aggregate_qualification(uuid4(), criteria).status
        is CompanyQualificationStatus.NOT_QUALIFIED
    )
    facts.employee_counts = [
        EmployeeCountEvidenceFact(value=147, relation="exact", evidence_ids=[source_id])
    ]
    criteria = qualify_company(config, facts)
    assert (
        aggregate_qualification(uuid4(), criteria).status
        is CompanyQualificationStatus.INSUFFICIENT_EVIDENCE
    )


def test_size_coverage_found_can_still_be_required_mismatch() -> None:
    config = campaign()
    company_id, run_id = uuid4(), uuid4()
    item = evidence("company_size", None, "47 employees")
    item.company_id = company_id
    item.research_run_id = run_id
    coverage = assess_evidence_coverage(
        config, [item], company_id=company_id, research_run_id=run_id
    )
    size_coverage = [entry for entry in coverage if entry.criterion == "company_size"]
    assert all(entry.status is CoverageStatus.FOUND for entry in size_coverage)
    size_results = [
        entry
        for entry in qualify_company(
            config,
            QualificationFacts(
                employee_counts=[
                    EmployeeCountEvidenceFact(
                        value=47, relation="exact", evidence_ids=[item.id]
                    )
                ]
            ),
        )
        if entry.criterion == "company_size"
    ]
    assert size_results[0].status is QualificationStatus.MISMATCH


def test_preferred_technology_evidence_matches_regardless_of_wording() -> None:
    config = campaign()
    config.technologies.preferred = ["kafka"]
    config.company_size = None
    criteria = qualify_company(
        config,
        QualificationFacts(
            categorical=[
                CategoricalEvidenceFact(
                    criterion_id=f"criterion_{index}",
                    state="supported",
                    evidence_ids=[uuid4()],
                )
                for index in range(4)
            ]
        ),
    )
    assert criteria[-1].status is QualificationStatus.MATCH
    assert (
        aggregate_qualification(uuid4(), criteria).status
        is CompanyQualificationStatus.QUALIFIED
    )
