"""Tests for deterministic campaign Evidence coverage."""

from types import SimpleNamespace
from uuid import UUID, uuid4

from virtual_company.services.coverage import assess_evidence_coverage
from virtual_company.workflows.research.models import (
    CampaignCriteria,
    CoverageStatus,
)


def make_campaign(*, technologies: list[str] | None = None) -> CampaignCriteria:
    return CampaignCriteria(
        id=uuid4(),
        name="Research",
        description=None,
        target_market="Australia",
        industry="fin tech",
        technologies=technologies or ["java", "spring", "spring boot", "kafka"],
        company_size_min=100,
        company_size_max=500,
        target_count=3,
    )


def item(
    company_id: UUID,
    run_id: UUID,
    criterion: str,
    subject: str | None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        company_id=company_id,
        research_run_id=run_id,
        criterion=criterion,
        subject=subject,
    )


def test_full_coverage_retains_matching_evidence_ids() -> None:
    company_id, run_id = uuid4(), uuid4()
    evidence = [
        item(company_id, run_id, "target_market", "Australia"),
        item(company_id, run_id, "industry", "fin tech"),
        item(company_id, run_id, "technology", "Java"),
        item(company_id, run_id, "technology", "Spring"),
        item(company_id, run_id, "technology", "SpringBoot"),
        item(company_id, run_id, "technology", "Apache Kafka"),
        item(company_id, run_id, "company_size", "2300+ employees"),
    ]
    coverage = assess_evidence_coverage(
        make_campaign(), evidence, company_id=company_id, research_run_id=run_id
    )
    assert len(coverage) == 7
    assert all(result.status is CoverageStatus.FOUND for result in coverage)
    assert all(result.evidence_ids for result in coverage)


def test_sparse_and_zero_evidence_are_missing_without_qualification() -> None:
    company_id, run_id = uuid4(), uuid4()
    evidence = [
        item(company_id, run_id, "target_market", "Australia"),
        item(company_id, run_id, "industry", "fin tech"),
        item(company_id, run_id, "company_size", "2300+ employees"),
    ]
    coverage = assess_evidence_coverage(
        make_campaign(), evidence, company_id=company_id, research_run_id=run_id
    )
    assert [result.subject for result in coverage if result.status is CoverageStatus.MISSING] == [
        "java",
        "spring",
        "spring boot",
        "kafka",
    ]
    assert coverage[-1].status is CoverageStatus.FOUND

    empty = assess_evidence_coverage(
        make_campaign(), [], company_id=company_id, research_run_id=run_id
    )
    assert len(empty) == 7
    assert all(result.status is CoverageStatus.MISSING for result in empty)


def test_criteria_are_dynamic_and_evidence_is_run_and_company_scoped() -> None:
    company_id, run_id = uuid4(), uuid4()
    campaign = make_campaign(technologies=["python", "django", "postgresql"])
    evidence = [
        item(company_id, uuid4(), "technology", "python"),
        item(uuid4(), run_id, "technology", "django"),
    ]
    coverage = assess_evidence_coverage(
        campaign, evidence, company_id=company_id, research_run_id=run_id
    )
    technologies = [result.subject for result in coverage if result.criterion == "technology"]
    assert technologies == ["python", "django", "postgresql"]
    assert all(
        result.status is CoverageStatus.MISSING
        for result in coverage
        if result.criterion == "technology"
    )
