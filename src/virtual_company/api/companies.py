"""Company HTTP endpoints."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from virtual_company.api.dependencies import get_company_service, get_evidence_service
from virtual_company.api.models import CompanyResponse, EvidenceResponse
from virtual_company.services import CompanyService, EvidenceService

router = APIRouter(prefix="/api/v1/companies", tags=["companies"])
CompanyServiceDependency = Annotated[CompanyService, Depends(get_company_service)]
EvidenceServiceDependency = Annotated[EvidenceService, Depends(get_evidence_service)]


@router.get("/{company_id}", response_model=CompanyResponse)
async def get_company(company_id: UUID, service: CompanyServiceDependency) -> CompanyResponse:
    """Retrieve one company."""
    company = await service.get_by_id(company_id)
    if company is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
    return CompanyResponse.model_validate(company)


@router.get("/{company_id}/evidence", response_model=list[EvidenceResponse])
async def list_company_evidence(
    company_id: UUID, service: EvidenceServiceDependency
) -> list[EvidenceResponse]:
    """List evidence for a company."""
    evidence = await service.list_for_company(company_id)
    if evidence is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
    return [EvidenceResponse.model_validate(item) for item in evidence]
