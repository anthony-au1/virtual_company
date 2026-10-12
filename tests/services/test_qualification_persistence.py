"""Final-result serialization without recomputing qualification."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from virtual_company.domain.qualification import (
    CriterionQualification,
    QualificationStatus,
    ResearchCompanyQualification,
    ResearchCompanyQualificationStatus,
)
from virtual_company.services.research import ResearchService


@pytest.mark.asyncio
@pytest.mark.parametrize("status", list(ResearchCompanyQualificationStatus))
async def test_serializes_existing_results_without_committing(
    status: ResearchCompanyQualificationStatus,
) -> None:
    session = MagicMock(spec=AsyncSession)
    service = ResearchService(session)
    service._qualifications.upsert = AsyncMock()
    company_id, run_id, campaign_id, evidence_id = (uuid4() for _ in range(4))
    criteria = [
        CriterionQualification(
            "technology",
            "java",
            QualificationStatus.MATCH,
            [evidence_id],
            "Explicit support",
        ),
        CriterionQualification(
            "company_size",
            "employees >= 100",
            QualificationStatus.UNKNOWN,
            [],
            "Missing size",
        ),
    ]
    result = ResearchCompanyQualification(company_id, status, criteria)
    await service.persist_research_company_qualifications(
        campaign_id=campaign_id, research_run_id=run_id, qualifications=[result]
    )
    data = service._qualifications.upsert.await_args.args[0]
    assert (data.company_id, data.research_run_id, data.campaign_id, data.status) == (
        company_id,
        run_id,
        campaign_id,
        status.value,
    )
    assert data.criteria_results == {
        "criteria": [
            {
                "criterion": "technology",
                "subject": "java",
                "status": "MATCH",
                "evidence_ids": [str(evidence_id)],
                "reason": "Explicit support",
            },
            {
                "criterion": "company_size",
                "subject": "employees >= 100",
                "status": "UNKNOWN",
                "evidence_ids": [],
                "reason": "Missing size",
            },
        ]
    }
    session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_run_creation_and_terminal_transitions_populate_lifecycle_timestamps() -> (
    None
):
    session = MagicMock(spec=AsyncSession)
    session.commit = AsyncMock()
    service = ResearchService(session)
    service._campaigns.seal_for_research = AsyncMock(return_value=object())
    created_run = MagicMock()
    service._runs.create = AsyncMock(return_value=created_run)

    await service.create_run(uuid4())

    create_data = service._runs.create.await_args.args[0]
    assert create_data.status == "RUNNING"
    assert create_data.created_at is not None
    assert create_data.started_at == create_data.created_at
    assert create_data.completed_at is None
    session.commit.assert_awaited_once()

    completed_run = MagicMock()
    service._runs.update = AsyncMock(return_value=completed_run)
    await service.complete_run(uuid4(), 4)
    completion = service._runs.update.await_args.args[1]
    assert completion.status == "COMPLETED"
    assert completion.completed_at is not None

    service._runs.update = AsyncMock(return_value=completed_run)
    await service.fail_run(uuid4(), "failure")
    failure = service._runs.update.await_args.args[1]
    assert failure.status == "FAILED"
    assert failure.completed_at is not None
    assert failure.error == "failure"
