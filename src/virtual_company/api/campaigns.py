"""Campaign HTTP endpoints."""

from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from redis.exceptions import ResponseError
from taskiq import SendTaskError

from virtual_company.api.dependencies import get_campaign_service, get_research_service
from virtual_company.api.models import (
    CampaignCreateRequest,
    CampaignResponse,
    CampaignUpdateRequest,
    CompanyResponse,
    ResearchRunExecutionResponse,
)
from virtual_company.services import CampaignService, ResearchService
from virtual_company.services.campaign import (
    CampaignLifecycleConflictError,
    CampaignLimitValidationError,
    CampaignSealedError,
)
from virtual_company.task_queue.tasks import execute_workflow

router = APIRouter(prefix="/api/v1/campaigns", tags=["campaigns"])
CampaignServiceDependency = Annotated[CampaignService, Depends(get_campaign_service)]
ResearchServiceDependency = Annotated[ResearchService, Depends(get_research_service)]
logger = logging.getLogger(__name__)


@router.post("", response_model=CampaignResponse, status_code=status.HTTP_201_CREATED)
async def create_campaign(
    payload: CampaignCreateRequest, service: CampaignServiceDependency
) -> CampaignResponse:
    """Create a campaign."""
    campaign = await service.create(payload)
    return CampaignResponse.model_validate(campaign)


@router.get("", response_model=list[CampaignResponse])
async def list_campaigns(service: CampaignServiceDependency) -> list[CampaignResponse]:
    """List campaigns."""
    return [
        CampaignResponse.model_validate(campaign) for campaign in await service.list()
    ]


@router.get("/{campaign_id}", response_model=CampaignResponse)
async def get_campaign(
    campaign_id: UUID, service: CampaignServiceDependency
) -> CampaignResponse:
    """Retrieve one campaign."""
    campaign = await service.get_by_id(campaign_id)
    if campaign is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found"
        )
    return CampaignResponse.model_validate(campaign)


@router.patch("/{campaign_id}", response_model=CampaignResponse)
async def update_campaign(
    campaign_id: UUID,
    payload: CampaignUpdateRequest,
    service: CampaignServiceDependency,
) -> CampaignResponse:
    """Partially update a campaign."""
    try:
        campaign = await service.update(campaign_id, payload)
    except CampaignLimitValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from error
    except CampaignSealedError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(error)
        ) from error
    if campaign is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found"
        )
    return CampaignResponse.model_validate(campaign)


@router.delete(
    "/{campaign_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Campaign not found"},
        status.HTTP_409_CONFLICT: {
            "description": "Campaign has Research execution history"
        },
    },
)
async def delete_campaign(
    campaign_id: UUID, service: CampaignServiceDependency
) -> None:
    """Delete a Campaign before it has been used for research."""
    try:
        deleted = await service.delete(campaign_id)
    except CampaignLifecycleConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(error)
        ) from error
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found"
        )


@router.get("/{campaign_id}/companies", response_model=list[CompanyResponse])
async def list_campaign_companies(
    campaign_id: UUID, service: CampaignServiceDependency
) -> list[CompanyResponse]:
    """List companies associated with a campaign."""
    companies = await service.list_research_companies(campaign_id)
    if companies is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found"
        )
    return [CompanyResponse.model_validate(company) for company in companies]


@router.post(
    "/{campaign_id}/research",
    response_model=ResearchRunExecutionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def research_campaign(
    campaign_id: UUID, service: ResearchServiceDependency
) -> ResearchRunExecutionResponse:
    """Queue campaign research for execution by a Taskiq worker."""
    try:
        run = await service.prepare_queued_run(campaign_id)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(error)
        ) from error

    try:
        await execute_workflow.kiq("research", str(run.id))
    except SendTaskError as error:
        definitive = isinstance(error.__cause__, ResponseError)
        if definitive:
            try:
                await service.fail_queued_execution(run.id)
            except Exception as transition_error:  # noqa: BLE001 - retain publish failure as primary
                logger.error(
                    "research_enqueue_compensation_failed",
                    extra={"context": {"error_type": type(transition_error).__name__}},
                )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Execution could not be scheduled"
                if definitive
                else "Execution publish outcome is unknown"
            ),
        ) from error
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Execution publish outcome is unknown",
        ) from error
    return ResearchRunExecutionResponse(research_run_id=run.id, status="QUEUED")
