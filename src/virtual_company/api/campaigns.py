"""Campaign HTTP endpoints."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from virtual_company.api.dependencies import get_campaign_service, get_research_workflow
from virtual_company.api.models import (
    CampaignCreateRequest,
    CampaignResponse,
    CampaignUpdateRequest,
    CompanyResponse,
    ResearchWorkflowResponse,
)
from virtual_company.services import CampaignService
from virtual_company.tools import WebSearchConfigurationError
from virtual_company.workflows.research import ResearchWorkflow
from virtual_company.workflows.research.nodes import CampaignNotFoundError

router = APIRouter(prefix="/api/v1/campaigns", tags=["campaigns"])
CampaignServiceDependency = Annotated[CampaignService, Depends(get_campaign_service)]
ResearchWorkflowDependency = Annotated[ResearchWorkflow, Depends(get_research_workflow)]


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
    return [CampaignResponse.model_validate(campaign) for campaign in await service.list()]


@router.get("/{campaign_id}", response_model=CampaignResponse)
async def get_campaign(
    campaign_id: UUID, service: CampaignServiceDependency
) -> CampaignResponse:
    """Retrieve one campaign."""
    campaign = await service.get_by_id(campaign_id)
    if campaign is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")
    return CampaignResponse.model_validate(campaign)


@router.patch("/{campaign_id}", response_model=CampaignResponse)
async def update_campaign(
    campaign_id: UUID,
    payload: CampaignUpdateRequest,
    service: CampaignServiceDependency,
) -> CampaignResponse:
    """Partially update a campaign."""
    campaign = await service.update(campaign_id, payload)
    if campaign is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")
    return CampaignResponse.model_validate(campaign)


@router.get("/{campaign_id}/companies", response_model=list[CompanyResponse])
async def list_campaign_companies(
    campaign_id: UUID, service: CampaignServiceDependency
) -> list[CompanyResponse]:
    """List companies associated with a campaign."""
    companies = await service.list_companies(campaign_id)
    if companies is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")
    return [CompanyResponse.model_validate(company) for company in companies]


@router.post("/{campaign_id}/research", response_model=ResearchWorkflowResponse)
async def research_campaign(
    campaign_id: UUID, workflow: ResearchWorkflowDependency
) -> ResearchWorkflowResponse:
    """Run the first synchronous campaign research workflow."""
    try:
        result = await workflow.run(campaign_id)
    except CampaignNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except WebSearchConfigurationError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error
    return ResearchWorkflowResponse.model_validate(result.model_dump())
