"""Product-facing research result projection tests."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from virtual_company.db.models import (
    Campaign,
    ResearchCompany,
    ResearchCompanyQualification,
    ResearchEvidence,
    ResearchRun,
)
from virtual_company.services.research_results import (
    ReferencedResearchRunError,
    ResearchResultsService,
)


def build_service() -> tuple[ResearchResultsService, MagicMock]:
    session = MagicMock(spec=AsyncSession)
    session.commit = AsyncMock()
    service = ResearchResultsService(session)
    service._runs.get_by_id_with_campaign = AsyncMock()
    service._runs.get_by_id = AsyncMock()
    service._runs.get_by_id_for_update = AsyncMock()
    service._qualifications.list_for_run = AsyncMock()
    service._evidence.list_by_research_run_id = AsyncMock()
    service._evidence.delete_by_research_run_id = AsyncMock()
    service._qualifications.delete_by_research_run_id = AsyncMock()
    service._runs.delete = AsyncMock()
    service._exploration_runs.exists_for_research_run = AsyncMock(return_value=False)
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
        keywords=["java", "spring", "spring boot", "kafka"],
        company_size={"min": 500},
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
    company_a = ResearchCompany(
        id=uuid4(), name="Alpha", website="https://alpha.example"
    )
    company_b = ResearchCompany(id=uuid4(), name="Beta")
    java_evidence = ResearchEvidence(
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
    unrelated = ResearchEvidence(
        id=uuid4(),
        company_id=company_b.id,
        research_run_id=run.id,
        claim="Uses Spring",
        evidence_text="Spring appears on another company's page.",
        source_url="https://beta.example/engineering",
        observed_at=now,
        created_at=now,
    )
    snapshot_a = ResearchCompanyQualification(
        id=uuid4(),
        research_run_id=run.id,
        campaign_id=campaign.id,
        company_id=company_a.id,
        status="INSUFFICIENT_EVIDENCE",
        criteria_results={
            "criteria": [
                {
                    "criterion": "keyword",
                    "subject": "java",
                    "status": "MATCH",
                    "reason": "Supported",
                    "evidence_ids": [str(java_evidence.id), str(unrelated.id)],
                },
                {
                    "criterion": "keyword",
                    "subject": "spring",
                    "status": "UNKNOWN",
                    "reason": "Not established",
                    "evidence_ids": [],
                },
                {
                    "criterion": "keyword",
                    "subject": "kafka",
                    "status": "MISMATCH",
                    "reason": "Contradicted",
                    "evidence_ids": [],
                },
            ]
        },
        created_at=now,
    )
    snapshot_b = ResearchCompanyQualification(
        id=uuid4(),
        research_run_id=run.id,
        campaign_id=campaign.id,
        company_id=company_b.id,
        status="QUALIFIED",
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
    assert result.campaign.criteria.keywords == campaign.keywords
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
@pytest.mark.parametrize("status", ["COMPLETED", "FAILED"])
async def test_deleting_one_terminal_run_removes_only_its_owned_data(
    status: str,
) -> None:
    service, session = build_service()
    run_id = uuid4()
    sealed_at = datetime.now(UTC)
    campaign = Campaign(
        id=uuid4(),
        name="Sealed campaign",
        target_count=1,
        max_companies_to_research=10,
        status="COMPLETED",
        keywords=[],
        sealed_at=sealed_at,
    )
    run = ResearchRun(
        id=run_id,
        campaign_id=campaign.id,
        campaign=campaign,
        status=status,
    )
    service._runs.get_by_id_for_update.return_value = run

    assert await service.delete_run(run_id)

    service._evidence.delete_by_research_run_id.assert_awaited_once_with(run_id)
    service._qualifications.delete_by_research_run_id.assert_awaited_once_with(run_id)
    service._runs.delete.assert_awaited_once_with(run)
    session.commit.assert_awaited_once()
    assert campaign.sealed_at == sealed_at


@pytest.mark.asyncio
async def test_deleting_run_rejects_non_terminal_and_unknown_runs() -> None:
    service, session = build_service()
    for status in ("RUNNING", "PENDING"):
        service._runs.get_by_id_for_update.return_value = ResearchRun(
            id=uuid4(), campaign_id=uuid4(), status=status
        )
        with pytest.raises(ValueError, match="non-terminal research run"):
            await service.delete_run(uuid4())
    service._evidence.delete_by_research_run_id.assert_not_awaited()
    service._qualifications.delete_by_research_run_id.assert_not_awaited()
    session.commit.assert_not_awaited()

    service._runs.get_by_id_for_update.return_value = None
    assert not await service.delete_run(uuid4())


@pytest.mark.asyncio
async def test_deleting_run_rejects_exploration_provenance() -> None:
    service, session = build_service()
    run_id = uuid4()
    service._runs.get_by_id_for_update.return_value = ResearchRun(
        id=run_id, campaign_id=uuid4(), status="COMPLETED"
    )
    service._exploration_runs.exists_for_research_run.return_value = True

    with pytest.raises(ReferencedResearchRunError, match="referenced by an Exploration"):
        await service.delete_run(run_id)

    service._exploration_runs.exists_for_research_run.assert_awaited_once_with(run_id)
    service._evidence.delete_by_research_run_id.assert_not_awaited()
    service._qualifications.delete_by_research_run_id.assert_not_awaited()
    service._runs.delete.assert_not_awaited()
    session.commit.assert_not_awaited()
