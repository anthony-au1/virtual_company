"""Exploration HTTP endpoints."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from virtual_company.api.dependencies import get_exploration_service
from virtual_company.api.models import (
    ExplorationCreateRequest,
    ExplorationObligationResponse,
    ExplorationResponse,
    ExplorationUpdateRequest,
)
from virtual_company.repositories.dtos import (
    ExplorationUpdate,
)
from virtual_company.services import ExplorationService

router = APIRouter(prefix="/api/v1/explorations", tags=["explorations"])
ExplorationServiceDependency = Annotated[
    ExplorationService, Depends(get_exploration_service)
]


@router.post(
    "", response_model=ExplorationResponse, status_code=status.HTTP_201_CREATED
)
async def create_exploration(
    payload: ExplorationCreateRequest, service: ExplorationServiceDependency
) -> ExplorationResponse:
    exploration = await service.create(payload.business_context)
    return ExplorationResponse.model_validate(exploration)


@router.get("", response_model=list[ExplorationResponse])
async def list_explorations(
    service: ExplorationServiceDependency,
) -> list[ExplorationResponse]:
    return [ExplorationResponse.model_validate(item) for item in await service.list()]


@router.get("/{exploration_id}", response_model=ExplorationResponse)
async def get_exploration(
    exploration_id: UUID, service: ExplorationServiceDependency
) -> ExplorationResponse:
    exploration = await service.get_by_id(exploration_id)
    if exploration is None:
        raise HTTPException(status_code=404, detail="Exploration not found")
    return ExplorationResponse.model_validate(exploration)


@router.patch("/{exploration_id}", response_model=ExplorationResponse)
async def update_exploration(
    exploration_id: UUID,
    payload: ExplorationUpdateRequest,
    service: ExplorationServiceDependency,
) -> ExplorationResponse:
    exploration = await service.update(
        exploration_id,
        ExplorationUpdate(**payload.model_dump(exclude_unset=True)),
    )
    if exploration is None:
        raise HTTPException(status_code=404, detail="Exploration not found")
    return ExplorationResponse.model_validate(exploration)


@router.get(
    "/{exploration_id}/obligations",
    response_model=list[ExplorationObligationResponse],
)
async def list_obligations(
    exploration_id: UUID, service: ExplorationServiceDependency
) -> list[ExplorationObligationResponse]:
    obligations = await service.list_obligations(exploration_id)
    if obligations is None:
        raise HTTPException(status_code=404, detail="Exploration not found")
    return [ExplorationObligationResponse.model_validate(item) for item in obligations]
