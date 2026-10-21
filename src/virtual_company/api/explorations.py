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
    ExplorationRunResponse,
    ExplorationRunSummaryResponse,
    ExplorationRunStartRequest,
    ExplorationUpdateRequest,
)
from virtual_company.repositories.dtos import (
    ExplorationUpdate,
)
from virtual_company.services import ExplorationService
from virtual_company.services.exploration import (
    ExplorationCompanySelectionError,
    ExplorationStartConflictError,
    ExplorationStartNotFoundError,
    ExplorationLifecycleConflictError,
    ExplorationObligationGenerationError,
)

router = APIRouter(prefix="/api/v1/explorations", tags=["explorations"])
ExplorationServiceDependency = Annotated[
    ExplorationService, Depends(get_exploration_service)
]


@router.post(
    "/{exploration_id}/runs",
    response_model=ExplorationRunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def start_exploration_run(
    exploration_id: UUID,
    payload: ExplorationRunStartRequest,
    service: ExplorationServiceDependency,
) -> ExplorationRunResponse:
    try:
        started = await service.start_run(
            exploration_id, payload.research_run_id, payload.company_ids
        )
    except ExplorationStartNotFoundError as error:
        raise HTTPException(status_code=404, detail="ResearchRun not found") from error
    except ExplorationStartConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ExplorationCompanySelectionError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    if started is None:
        raise HTTPException(status_code=404, detail="Exploration not found")
    return ExplorationRunResponse(
        id=started.run.id,
        exploration_id=started.run.exploration_id,
        research_run_id=started.run.research_run_id,
        status=started.run.status,
        started_at=started.run.started_at,
        completed_at=started.run.completed_at,
        company_ids=started.company_ids,
    )


@router.get(
    "/{exploration_id}/runs",
    response_model=list[ExplorationRunSummaryResponse],
)
async def list_exploration_runs(
    exploration_id: UUID,
    service: ExplorationServiceDependency,
) -> list[ExplorationRunSummaryResponse]:
    runs = await service.list_runs(exploration_id)
    if runs is None:
        raise HTTPException(status_code=404, detail="Exploration not found")
    return [ExplorationRunSummaryResponse.model_validate(run) for run in runs]


@router.post(
    "", response_model=ExplorationResponse, status_code=status.HTTP_201_CREATED
)
async def create_exploration(
    payload: ExplorationCreateRequest, service: ExplorationServiceDependency
) -> ExplorationResponse:
    try:
        exploration = await service.create(
            payload.business_context, payload.max_obligations
        )
    except ExplorationObligationGenerationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Obligation generation failed",
        ) from error
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
    try:
        exploration = await service.update(
            exploration_id,
            ExplorationUpdate(**payload.model_dump(exclude_unset=True)),
        )
    except ExplorationLifecycleConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(error)
        ) from error
    except ExplorationObligationGenerationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Obligation generation failed",
        ) from error
    if exploration is None:
        raise HTTPException(status_code=404, detail="Exploration not found")
    return ExplorationResponse.model_validate(exploration)


@router.delete(
    "/{exploration_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Exploration not found"},
        status.HTTP_409_CONFLICT: {"description": "Exploration has already been run"},
    },
)
async def delete_exploration(
    exploration_id: UUID, service: ExplorationServiceDependency
) -> None:
    try:
        deleted = await service.delete(exploration_id)
    except ExplorationLifecycleConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(error)
        ) from error
    if not deleted:
        raise HTTPException(status_code=404, detail="Exploration not found")


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
