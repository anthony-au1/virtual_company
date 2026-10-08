"""Research result and human review HTTP endpoints."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from virtual_company.api.dependencies import get_research_results_service
from virtual_company.api.models import (
    ResearchResultsResponse,
    ResearchRunListCampaignResponse,
    ResearchRunListItemResponse,
    ResearchRunListSummaryResponse,
    ReviewResponse,
    ReviewUpdateRequest,
)
from virtual_company.services import (
    ResearchCompanyNotFoundError,
    ResearchResultsService,
    ResearchRunNotFoundError,
)

router = APIRouter(prefix="/api/v1/research-runs", tags=["research-runs"])
ResearchResultsServiceDependency = Annotated[
    ResearchResultsService, Depends(get_research_results_service)
]


@router.get("/{run_id}/results", response_model=ResearchResultsResponse)
async def get_research_results(
    run_id: UUID, service: ResearchResultsServiceDependency
) -> ResearchResultsResponse:
    """Return the complete persisted presentation of one research run."""
    try:
        result = await service.get_results(run_id)
    except ResearchRunNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(error)
        ) from error
    return ResearchResultsResponse.model_validate(result)


@router.get("", response_model=list[ResearchRunListItemResponse])
async def list_research_runs(
    service: ResearchResultsServiceDependency,
) -> list[ResearchRunListItemResponse]:
    """Return compact summaries for every persisted research run."""
    return [
        ResearchRunListItemResponse(
            run_id=item.run_id,
            status=item.status,
            created_at=item.created_at,
            started_at=item.started_at,
            completed_at=item.completed_at,
            campaign=ResearchRunListCampaignResponse(
                id=item.campaign_id,
                name=item.campaign_name,
                target_count=item.target_count,
                max_companies_to_research=item.max_companies_to_research,
            ),
            summary=ResearchRunListSummaryResponse.model_validate(item.summary),
        )
        for item in await service.list_runs()
    ]


@router.patch("/{run_id}/companies/{company_id}/review", response_model=ReviewResponse)
async def update_company_review(
    run_id: UUID,
    company_id: UUID,
    payload: ReviewUpdateRequest,
    service: ResearchResultsServiceDependency,
) -> ReviewResponse:
    """Replace the user's current decision for a company in one run."""
    try:
        result = await service.update_review(
            research_run_id=run_id,
            company_id=company_id,
            review_status=payload.status,
        )
    except ResearchRunNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(error)
        ) from error
    except ResearchCompanyNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(error)
        ) from error
    return ReviewResponse.model_validate(result)
