"""Persistence operations for shared workflow execution ownership."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import ClassVar
from uuid import UUID, uuid4

from sqlalchemy import exists, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from virtual_company.db.models import ExplorationRun, ResearchRun, WorkflowExecution


class WorkflowExecutionStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class WorkflowExecutionClaimOutcome(StrEnum):
    CLAIMED = "CLAIMED"
    NOT_FOUND = "NOT_FOUND"
    NOT_CLAIMABLE = "NOT_CLAIMABLE"


@dataclass(frozen=True)
class WorkflowExecutionClaimResult:
    outcome: WorkflowExecutionClaimOutcome
    execution_id: UUID | None = None


class ExecutionOwnershipLostError(RuntimeError):
    """A graph stage attempted persistence after execution ownership was lost."""


class WorkflowExecutionRepository:
    """Own execution persistence and transactionally coordinate business status."""

    _workflow_tables: ClassVar[dict[str, type[ResearchRun | ExplorationRun]]] = {
        "research": ResearchRun,
        "exploration": ExplorationRun,
    }

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @classmethod
    def _run_model(cls, workflow_type: str):
        try:
            return cls._workflow_tables[workflow_type]
        except KeyError as error:
            raise ValueError(f"Unsupported workflow type: {workflow_type}") from error

    async def create_queued(
        self, workflow_type: str, run_id: UUID, *, queued_at: datetime | None = None
    ) -> WorkflowExecution:
        model = self._run_model(workflow_type)
        if not await self._session.scalar(
            select(
                exists().where(model.id == run_id, model.status == "QUEUED")
            )
        ):
            raise ValueError("Business workflow run does not exist or is not QUEUED")
        execution = WorkflowExecution(
            id=uuid4(),
            workflow_type=workflow_type,
            run_id=run_id,
            status=WorkflowExecutionStatus.QUEUED.value,
            queued_at=queued_at or func.now(),
        )
        self._session.add(execution)
        await self._session.flush()
        return execution

    async def get_by_id(self, execution_id: UUID) -> WorkflowExecution | None:
        return await self._session.get(WorkflowExecution, execution_id)

    async def claim(
        self, workflow_type: str, run_id: UUID
    ) -> WorkflowExecutionClaimResult:
        self._run_model(workflow_type)
        execution = await self._session.scalar(
            update(WorkflowExecution)
            .where(
                WorkflowExecution.workflow_type == workflow_type,
                WorkflowExecution.run_id == run_id,
                WorkflowExecution.status == WorkflowExecutionStatus.QUEUED.value,
            )
            .values(
                status=WorkflowExecutionStatus.RUNNING.value,
                started_at=func.now(),
                heartbeat_at=func.now(),
            )
            .returning(WorkflowExecution)
        )
        if execution is None:
            exists = await self._session.scalar(
                select(WorkflowExecution.id).where(
                    WorkflowExecution.workflow_type == workflow_type,
                    WorkflowExecution.run_id == run_id,
                )
            )
            return WorkflowExecutionClaimResult(
                WorkflowExecutionClaimOutcome.NOT_CLAIMABLE
                if exists is not None
                else WorkflowExecutionClaimOutcome.NOT_FOUND
            )

        model = self._run_model(execution.workflow_type)
        business = await self._session.scalar(
            update(model)
            .where(model.id == execution.run_id, model.status == "QUEUED")
            .values(status="RUNNING", started_at=func.now(), completed_at=None)
            .returning(model.id)
        )
        if business is None:
            await self._session.execute(
                update(WorkflowExecution)
                .where(WorkflowExecution.id == execution.id)
                .values(
                    status=WorkflowExecutionStatus.QUEUED.value,
                    started_at=None,
                    heartbeat_at=None,
                )
            )
            return WorkflowExecutionClaimResult(
                WorkflowExecutionClaimOutcome.NOT_CLAIMABLE
            )
        return WorkflowExecutionClaimResult(
            WorkflowExecutionClaimOutcome.CLAIMED, execution.id
        )

    async def owns(self, execution_id: UUID) -> bool:
        return bool(
            await self._session.scalar(
                select(exists().where(
                    WorkflowExecution.id == execution_id,
                    WorkflowExecution.status == WorkflowExecutionStatus.RUNNING.value,
                ))
            )
        )

    async def lock_running_ownership(
        self, *, workflow_type: str, run_id: UUID, execution_id: UUID
    ) -> None:
        """Lock the live execution row until the caller's persistence commits."""
        owner_id = await self._session.scalar(
            select(WorkflowExecution.id)
            .where(
                WorkflowExecution.id == execution_id,
                WorkflowExecution.workflow_type == workflow_type,
                WorkflowExecution.run_id == run_id,
                WorkflowExecution.status == WorkflowExecutionStatus.RUNNING.value,
            )
            .with_for_update()
        )
        if owner_id is None:
            raise ExecutionOwnershipLostError("Execution ownership is no longer valid")

    async def heartbeat(self, execution_id: UUID) -> bool:
        return await self._session.scalar(
            update(WorkflowExecution)
            .where(
                WorkflowExecution.id == execution_id,
                WorkflowExecution.status == WorkflowExecutionStatus.RUNNING.value,
            )
            .values(heartbeat_at=func.now())
            .returning(WorkflowExecution.id)
        ) is not None

    async def transition(
        self, execution_id: UUID, target: WorkflowExecutionStatus | str
    ) -> bool:
        try:
            status = WorkflowExecutionStatus(target)
        except ValueError as error:
            raise ValueError(f"Unsupported execution status: {target}") from error
        if status in {WorkflowExecutionStatus.QUEUED, WorkflowExecutionStatus.RUNNING}:
            raise ValueError("Terminal transition requires a terminal status")
        execution = await self._session.scalar(
            update(WorkflowExecution)
            .where(
                WorkflowExecution.id == execution_id,
                WorkflowExecution.status == WorkflowExecutionStatus.RUNNING.value,
            )
            .values(status=status.value, completed_at=func.now())
            .returning(WorkflowExecution)
        )
        if execution is None:
            return False
        model = self._run_model(execution.workflow_type)
        allowed_terminal = (
            {"COMPLETED", "FAILED"}
            if execution.workflow_type == "research"
            else {"COMPLETED", "PARTIAL", "FAILED", "CANCELLED"}
        )
        if status.value not in allowed_terminal:
            raise ValueError(
                f"{status.value} is not valid for {execution.workflow_type}"
            )
        business = await self._session.scalar(
            update(model)
            .where(model.id == execution.run_id, model.status == "RUNNING")
            .values(status=status.value, completed_at=func.now())
            .returning(model.id)
        )
        if business is None:
            raise ValueError("Business run is missing or no longer RUNNING")
        return True

    async def fail_queued(self, workflow_type: str, run_id: UUID) -> bool:
        """Fail a definitely unpublished queued execution and its business run."""
        model = self._run_model(workflow_type)
        execution_id = await self._session.scalar(
            update(WorkflowExecution)
            .where(
                WorkflowExecution.workflow_type == workflow_type,
                WorkflowExecution.run_id == run_id,
                WorkflowExecution.status == WorkflowExecutionStatus.QUEUED.value,
            )
            .values(status=WorkflowExecutionStatus.FAILED.value, completed_at=func.now())
            .returning(WorkflowExecution.id)
        )
        if execution_id is None:
            return False
        run_id_updated = await self._session.scalar(
            update(model)
            .where(model.id == run_id, model.status == "QUEUED")
            .values(status="FAILED", completed_at=func.now())
            .returning(model.id)
        )
        if run_id_updated is None:
            raise RuntimeError("Queued business run changed before publish failure")
        return True

    async def fail_stale(
        self, *, queued_before: datetime, running_before: datetime
    ) -> tuple[int, int]:
        queued_rows = await self._session.execute(
            update(WorkflowExecution)
            .where(
                WorkflowExecution.status == WorkflowExecutionStatus.QUEUED.value,
                WorkflowExecution.queued_at < queued_before,
            )
            .values(status=WorkflowExecutionStatus.FAILED.value, completed_at=func.now())
            .returning(WorkflowExecution.workflow_type, WorkflowExecution.run_id)
        )
        running_rows = await self._session.execute(
            update(WorkflowExecution)
            .where(
                WorkflowExecution.status == WorkflowExecutionStatus.RUNNING.value,
                WorkflowExecution.heartbeat_at < running_before,
            )
            .values(status=WorkflowExecutionStatus.FAILED.value, completed_at=func.now())
            .returning(WorkflowExecution.workflow_type, WorkflowExecution.run_id)
        )
        queued = queued_rows.all()
        running = running_rows.all()
        for workflow_type, run_id in (*queued, *running):
            model = self._run_model(workflow_type)
            await self._session.execute(
                update(model)
                .where(
                    model.id == run_id,
                    model.status.not_in(("COMPLETED", "PARTIAL", "FAILED", "CANCELLED")),
                )
                .values(status="FAILED", completed_at=func.now())
            )
        return len(queued), len(running)
