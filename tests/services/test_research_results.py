"""Product-facing research result projection tests."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from virtual_company.db.models import (
    Campaign,
    Company,
    CompanyQualificationSnapshot,
    Evidence,
    ResearchRun,
)
from virtual_company.domain.review import ReviewStatus
from virtual_company.services.research_results import (
    ResearchCompanyNotFoundError,
    ResearchResultsService,
)


def build_service() -> tuple[ResearchResultsService, MagicMock]:
    session = MagicMock(spec=AsyncSession)
    session.commit = AsyncMock()
    service = ResearchResultsService(session)
    service._runs.get_by_id_with_campaign = AsyncMock()
    service._runs.get_by_id = AsyncMock()
    service._qualifications.list_for_run = AsyncMock()
    service._qualifications.update_review_status = AsyncMock()
    service._evidence.list_by_research_run_id = AsyncMock()
    return service, session


@pytest.mark.asyncio
async def test_builds_complete_deterministic_results_and_scopes_evidence() -> None:
    service, _ = build_service()
    now = datetime.now(UTC)
    campaign = Campaign(
        id=uuid4(),
        name="Australian Fintech Java Research",
        description="",
        target_market="Australia",
        industry="fin tech",
        technologies=["java", "spring", "spring boot", "kafka"],
        company_size={"min": {"value": 500}},
        target_count=5,
        max_companies_to_research=10,
        status="COMPLETED",
        created_at=now,
        updated_at=now,
    )
    run = ResearchRun(
        id=uuid4(),
        campaign_id=campaign.id,
        campaign=campaign,
        status="COMPLETED",
        started_at=now,
        completed_at=now,
        companies_found=3,
        created_at=now,
    )
    company_a = Company(
        id=uuid4(), name="Alpha", website="https://alpha.example"
    )
    company_b = Company(id=uuid4(), name="Beta")
    java_evidence = Evidence(
        id=uuid4(),
        company_id=company_a.id,
        research_run_id=run.id,
        claim="Uses Java",
        evidence_text="Java appears on the engineering page.",
        source_url="https://alpha.example/engineering",
        source_title="Engineering",
        source_type="careers",
        observed_at=now,
        created_at=now,
    )
    unrelated = Evidence(
        id=uuid4(),
        company_id=company_b.id,
        research_run_id=run.id,
        claim="Uses Spring",
        evidence_text="Spring appears on another company's page.",
        source_url="https://beta.example/engineering",
        observed_at=now,
        created_at=now,
    )
    snapshot_a = CompanyQualificationSnapshot(
        id=uuid4(),
        research_run_id=run.id,
        campaign_id=campaign.id,
        company_id=company_a.id,
        status="INSUFFICIENT_EVIDENCE",
        review_status="UNREVIEWED",
        criteria_results={
            "criteria": [
                {
                    "criterion": "technology",
                    "subject": "java",
                    "status": "MATCH",
                    "reason": "Supported",
                    "evidence_ids": [str(java_evidence.id), str(unrelated.id)],
                },
                {
                    "criterion": "technology",
                    "subject": "spring",
                    "status": "UNKNOWN",
                    "reason": "Not established",
                    "evidence_ids": [],
                },
                {
                    "criterion": "technology",
                    "subject": "kafka",
                    "status": "MISMATCH",
                    "reason": "Contradicted",
                    "evidence_ids": [],
                },
            ]
        },
        created_at=now,
    )
    snapshot_b = CompanyQualificationSnapshot(
        id=uuid4(),
        research_run_id=run.id,
        campaign_id=campaign.id,
        company_id=company_b.id,
        status="QUALIFIED",
        review_status="ACCEPTED",
        criteria_results={"criteria": []},
        created_at=now,
    )
    service._runs.get_by_id_with_campaign.return_value = run
    service._qualifications.list_for_run.return_value = [
        (snapshot_a, company_a),
        (snapshot_b, company_b),
    ]
    service._evidence.list_by_research_run_id.return_value = [
        java_evidence,
        unrelated,
    ]

    result = await service.get_results(run.id)

    assert result.campaign.name == campaign.name
    assert result.campaign.description == ""
    assert result.campaign.target_count == 5
    assert result.campaign.max_companies_to_research == 10
    assert result.campaign.criteria.target_market == "Australia"
    assert result.campaign.criteria.industry == "fin tech"
    assert result.campaign.criteria.technologies == campaign.technologies
    assert result.campaign.criteria.company_size.model_dump() == {
        **campaign.company_size,
        "max": None,
    }
    assert result.summary.researched == 2
    assert result.summary.qualified == 1
    assert result.summary.not_qualified == 0
    assert result.summary.insufficient_evidence == 1
    assert result.companies[0].summary.matched == 1
    assert result.companies[0].summary.unknown == 1
    assert result.companies[0].summary.mismatched == 1
    assert [item.id for item in result.companies[0].criteria[0].evidence] == [
        java_evidence.id
    ]
    assert result.companies[0].criteria[1].evidence == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("initial", "updated"),
    [
        (ReviewStatus.UNREVIEWED, ReviewStatus.ACCEPTED),
        (ReviewStatus.UNREVIEWED, ReviewStatus.REJECTED),
        (ReviewStatus.ACCEPTED, ReviewStatus.REJECTED),
        (ReviewStatus.ACCEPTED, ReviewStatus.UNREVIEWED),
        (ReviewStatus.REJECTED, ReviewStatus.ACCEPTED),
        (ReviewStatus.REJECTED, ReviewStatus.UNREVIEWED),
    ],
)
async def test_all_review_transitions_are_simple_independent_updates(
    initial: ReviewStatus, updated: ReviewStatus
) -> None:
    service, session = build_service()
    run_id, campaign_id, company_id = (uuid4() for _ in range(3))
    snapshot = CompanyQualificationSnapshot(
        id=uuid4(),
        research_run_id=run_id,
        campaign_id=campaign_id,
        company_id=company_id,
        status="NOT_QUALIFIED",
        review_status=initial.value,
        criteria_results={"criteria": [{"unchanged": True}]},
    )
    original_status = snapshot.status
    original_criteria = snapshot.criteria_results
    service._runs.get_by_id.return_value = object()

    async def update(**kwargs: object) -> CompanyQualificationSnapshot:
        snapshot.review_status = str(kwargs["review_status"])
        return snapshot

    service._qualifications.update_review_status.side_effect = update

    result = await service.update_review(
        research_run_id=run_id,
        company_id=company_id,
        review_status=updated,
    )

    assert result.review_status is updated
    assert snapshot.status == original_status
    assert snapshot.criteria_results is original_criteria
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_cross_run_company_review_is_rejected() -> None:
    service, session = build_service()
    service._runs.get_by_id.return_value = object()
    service._qualifications.update_review_status.return_value = None

    with pytest.raises(ResearchCompanyNotFoundError):
        await service.update_review(
            research_run_id=uuid4(),
            company_id=uuid4(),
            review_status=ReviewStatus.ACCEPTED,
        )

    session.commit.assert_not_awaited()


@pytest.mark.parametrize(
    "qualification_status",
    ["INSUFFICIENT_EVIDENCE", "NOT_QUALIFIED"],
)
@pytest.mark.asyncio
async def test_non_qualified_company_can_be_accepted(
    qualification_status: str,
) -> None:
    service, _ = build_service()
    snapshot = CompanyQualificationSnapshot(
        id=uuid4(),
        research_run_id=uuid4(),
        campaign_id=uuid4(),
        company_id=uuid4(),
        status=qualification_status,
        review_status="ACCEPTED",
        criteria_results={"criteria": []},
    )
    service._runs.get_by_id.return_value = object()
    service._qualifications.update_review_status.return_value = snapshot

    result = await service.update_review(
        research_run_id=snapshot.research_run_id,
        company_id=snapshot.company_id,
        review_status=ReviewStatus.ACCEPTED,
    )

    assert result.review_status is ReviewStatus.ACCEPTED
    assert snapshot.status == qualification_status
