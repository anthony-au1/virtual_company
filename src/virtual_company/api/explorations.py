"""Exploration HTTP endpoints."""

from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from virtual_company.api.dependencies import get_exploration_service
from virtual_company.api.exploration_execution import (
    execute_exploration_run,
    fail_if_still_queued,
)
from virtual_company.api.models import (
    ExplorationCompanyResultResponse,
    ExplorationCreateRequest,
    ExplorationEvidenceResponse,
    ExplorationFactResponse,
    ExplorationHypothesisResponse,
    ExplorationObligationResponse,
    ExplorationResponse,
    ExplorationRunExecutionResponse,
    ExplorationRunResponse,
    ExplorationRunStartRequest,
    ExplorationRunStatusResponse,
    ExplorationRunSummaryResponse,
    ExplorationUpdateRequest,
)
from virtual_company.db.models import ExplorationFact, ExplorationHypothesis
from virtual_company.repositories.dtos import (
    ExplorationUpdate,
)
from virtual_company.repositories.exploration_run import ExplorationRunClaimOutcome
from virtual_company.services import ExplorationService
from virtual_company.services.exploration import (
    ExplorationCompanySelectionError,
    ExplorationLifecycleConflictError,
    ExplorationObligationGenerationError,
    ExplorationStartConflictError,
    ExplorationStartNotFoundError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/explorations", tags=["explorations"])
ExplorationServiceDependency = Annotated[
    ExplorationService, Depends(get_exploration_service)
]


@router.post(
    "/{exploration_id}/runs/{run_id}/execute",
    response_model=ExplorationRunExecutionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def execute_run(
    exploration_id: UUID,
    run_id: UUID,
    background_tasks: BackgroundTasks,
    service: ExplorationServiceDependency,
) -> ExplorationRunExecutionResponse:
    try:
        claim = await service.claim_run_for_execution(exploration_id, run_id)
    except Exception as error:
        logger.error(
            "exploration_run_claim_failed",
            extra={
                "context": {
                    "exploration_run_id": str(run_id),
                    "error_type": type(error).__name__,
                }
            },
        )
        raise HTTPException(
            status_code=500, detail="Execution could not be scheduled"
        ) from error
    if claim is None or claim.outcome is ExplorationRunClaimOutcome.NOT_FOUND:
        raise HTTPException(status_code=404, detail="Exploration run not found")
    if claim.outcome is ExplorationRunClaimOutcome.NOT_READY:
        raise HTTPException(status_code=409, detail="Exploration run is not READY")
    try:
        background_tasks.add_task(execute_exploration_run, run_id)
    except Exception as error:
        await fail_if_still_queued(run_id)
        logger.error(
            "exploration_run_scheduling_failed",
            extra={
                "context": {
                    "exploration_run_id": str(run_id),
                    "error_type": type(error).__name__,
                }
            },
        )
        raise HTTPException(
            status_code=500, detail="Execution could not be scheduled"
        ) from error
    return ExplorationRunExecutionResponse(exploration_run_id=run_id, status="QUEUED")


@router.get(
    "/{exploration_id}/runs/{run_id}",
    response_model=ExplorationRunStatusResponse,
)
async def get_exploration_run(
    exploration_id: UUID,
    run_id: UUID,
    service: ExplorationServiceDependency,
) -> ExplorationRunStatusResponse:
    run = await service.get_run(exploration_id, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Exploration run not found")
    return ExplorationRunStatusResponse(
        id=run.id,
        exploration_id=run.exploration_id,
        status=run.status,
        started_at=run.started_at,
        completed_at=run.completed_at,
    )


@router.get(
    "/{exploration_id}/runs/{run_id}/companies",
    response_model=list[ExplorationCompanyResultResponse],
)
async def list_exploration_run_companies(
    exploration_id: UUID,
    run_id: UUID,
    service: ExplorationServiceDependency,
) -> list[ExplorationCompanyResultResponse]:
    companies = await service.list_run_companies(exploration_id, run_id)
    if companies is None:
        raise HTTPException(status_code=404, detail="Exploration run not found")
    return [
        ExplorationCompanyResultResponse(
            id=item.id,
            company_id=item.company_id,
            name=item.company.name,
            website=item.company.website,
            domain=item.company.domain,
        )
        for item in companies
    ]


@router.get(
    "/{exploration_id}/companies/{company_link_id}/evidence",
    response_model=list[ExplorationEvidenceResponse],
)
async def list_exploration_company_evidence(
    exploration_id: UUID,
    company_link_id: UUID,
    service: ExplorationServiceDependency,
) -> list[ExplorationEvidenceResponse]:
    records = await service.list_company_evidence(exploration_id, company_link_id)
    if records is None:
        raise HTTPException(status_code=404, detail="Exploration company not found")
    return [ExplorationEvidenceResponse.model_validate(item) for item in records]


@router.get(
    "/{exploration_id}/companies/{company_link_id}/facts",
    response_model=list[ExplorationFactResponse],
)
async def list_exploration_company_facts(
    exploration_id: UUID,
    company_link_id: UUID,
    service: ExplorationServiceDependency,
) -> list[ExplorationFactResponse]:
    records = await service.list_company_facts(exploration_id, company_link_id)
    if records is None:
        raise HTTPException(status_code=404, detail="Exploration company not found")
    return [_fact_response(item) for item in records]


@router.get(
    "/{exploration_id}/companies/{company_link_id}/hypotheses",
    response_model=list[ExplorationHypothesisResponse],
)
async def list_exploration_company_hypotheses(
    exploration_id: UUID,
    company_link_id: UUID,
    service: ExplorationServiceDependency,
) -> list[ExplorationHypothesisResponse]:
    records = await service.list_company_hypotheses(exploration_id, company_link_id)
    if records is None:
        raise HTTPException(status_code=404, detail="Exploration company not found")
    return [_hypothesis_response(item) for item in records]


def _fact_response(item: ExplorationFact) -> ExplorationFactResponse:
    return ExplorationFactResponse(
        id=item.id,
        exploration_company_id=item.exploration_company_id,
        statement=item.statement,
        created_at=item.created_at,
        evidence_ids=sorted(
            (
                evidence.id
                for evidence in item.evidence
                if evidence.exploration_company_id == item.exploration_company_id
            ),
            key=str,
        ),
    )


def _hypothesis_response(
    item: ExplorationHypothesis,
) -> ExplorationHypothesisResponse:
    return ExplorationHypothesisResponse(
        id=item.id,
        exploration_company_id=item.exploration_company_id,
        statement=item.statement,
        created_at=item.created_at,
        fact_ids=sorted(
            (
                fact.id
                for fact in item.facts
                if fact.exploration_company_id == item.exploration_company_id
            ),
            key=str,
        ),
    )


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
