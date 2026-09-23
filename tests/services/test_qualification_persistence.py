"""Final-result serialization without recomputing qualification."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from virtual_company.domain.qualification import (
    CompanyQualification,
    CompanyQualificationStatus,
    CriterionQualification,
    QualificationStatus,
)
from virtual_company.services.research import ResearchService


@pytest.mark.asyncio
@pytest.mark.parametrize("status", list(CompanyQualificationStatus))
async def test_serializes_existing_results_without_committing(
    status: CompanyQualificationStatus,
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
            "company_size", None, QualificationStatus.UNKNOWN, [], "Missing size"
        ),
    ]
    result = CompanyQualification(company_id, status, criteria)
    await service.persist_company_qualifications(
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
                "subject": None,
                "status": "UNKNOWN",
                "evidence_ids": [],
                "reason": "Missing size",
            },
        ]
    }
    session.commit.assert_not_called()
