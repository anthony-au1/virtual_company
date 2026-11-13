"""Persistence operations for Exploration runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import exists, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from virtual_company.db.models import (
    Campaign,
    ExplorationCompany,
    ExplorationRun,
    ResearchRun,
)
from virtual_company.domain.exploration.run import ExplorationRunStatus
from virtual_company.repositories._helpers import apply_updates, create_values
from virtual_company.repositories.dtos import ExplorationRunCreate, ExplorationRunUpdate


class ExplorationRunClaimOutcome(StrEnum):
    CLAIMED = "CLAIMED"
    NOT_FOUND = "NOT_FOUND"
    NOT_READY = "NOT_READY"


@dataclass(frozen=True)
class ExplorationRunClaimResult:
    outcome: ExplorationRunClaimOutcome
    run: ExplorationRun | None = None


class InvalidExplorationRunTransitionError(ValueError):
    """Raised when a run cannot make the requested lifecycle transition."""


_ALLOWED_PREVIOUS_STATUSES: dict[ExplorationRunStatus, tuple[ExplorationRunStatus, ...]] = {
    ExplorationRunStatus.RUNNING: (ExplorationRunStatus.QUEUED,),
    ExplorationRunStatus.COMPLETED: (ExplorationRunStatus.RUNNING,),
    ExplorationRunStatus.PARTIAL: (ExplorationRunStatus.RUNNING,),
    ExplorationRunStatus.FAILED: (
        ExplorationRunStatus.QUEUED,
        ExplorationRunStatus.RUNNING,
    ),
    ExplorationRunStatus.CANCELLED: (ExplorationRunStatus.RUNNING,),
}


class ExplorationRunRepository:
    """Provide asynchronous persistence operations for Exploration runs."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def exists_for_exploration(self, exploration_id: UUID) -> bool:
        statement = select(
            exists().where(ExplorationRun.exploration_id == exploration_id)
        )
        return bool(await self._session.scalar(statement))

    async def exists_for_research_run(self, research_run_id: UUID) -> bool:
        statement = select(
            exists().where(ExplorationRun.research_run_id == research_run_id)
        )
        return bool(await self._session.scalar(statement))

    async def create(self, data: ExplorationRunCreate) -> ExplorationRun:
        run = ExplorationRun(**create_values(data))
        self._session.add(run)
        await self._session.flush()
        await self._session.refresh(run)
        return run

    async def get_by_id(self, run_id: UUID) -> ExplorationRun | None:
        return await self._session.get(ExplorationRun, run_id)

    async def update(
        self, run_id: UUID, data: ExplorationRunUpdate
    ) -> ExplorationRun | None:
        if "status" in data.model_fields_set or "completed_at" in data.model_fields_set:
            raise ValueError(
                "Exploration run lifecycle fields must use guarded transitions"
            )
        run = await self.get_by_id(run_id)
        if run is None:
            return None
        apply_updates(run, data)
        await self._session.flush()
        await self._session.refresh(run)
        return run

    async def claim_for_execution(self, run_id: UUID) -> ExplorationRunClaimResult:
        """Atomically move one READY run to QUEUED."""
        statement = (
            update(ExplorationRun)
            .where(
                ExplorationRun.id == run_id,
                ExplorationRun.status == ExplorationRunStatus.READY.value,
            )
            .values(
                status=ExplorationRunStatus.QUEUED.value,
                completed_at=None,
            )
            .returning(ExplorationRun)
            .execution_options(synchronize_session="fetch")
        )
        run = (await self._session.execute(statement)).scalar_one_or_none()
        if run is not None:
            return ExplorationRunClaimResult(ExplorationRunClaimOutcome.CLAIMED, run)

        exists = await self._session.scalar(
            select(ExplorationRun.id).where(ExplorationRun.id == run_id)
        )
        outcome = (
            ExplorationRunClaimOutcome.NOT_READY
            if exists is not None
            else ExplorationRunClaimOutcome.NOT_FOUND
        )
        return ExplorationRunClaimResult(outcome)

    async def transition(
        self, run_id: UUID, target: ExplorationRunStatus
    ) -> ExplorationRun | None:
        """Apply one allowed status transition atomically; return None if missing."""
        try:
            target_status = ExplorationRunStatus(target)
        except (TypeError, ValueError) as error:
            raise InvalidExplorationRunTransitionError(
                f"Unsupported ExplorationRun status: {target!r}"
            ) from error

        previous_statuses = _ALLOWED_PREVIOUS_STATUSES.get(target_status)
        if previous_statuses is None:
            raise InvalidExplorationRunTransitionError(
                f"No guarded transition is defined for {target_status.value}"
            )

        values: dict[str, object] = {"status": target_status.value}
        if target_status is ExplorationRunStatus.RUNNING:
            values["started_at"] = datetime.now(UTC)
            values["completed_at"] = None
        if target_status in {
            ExplorationRunStatus.COMPLETED,
            ExplorationRunStatus.PARTIAL,
            ExplorationRunStatus.FAILED,
            ExplorationRunStatus.CANCELLED,
        }:
            values["completed_at"] = datetime.now(UTC)

        statement = (
            update(ExplorationRun)
            .where(
                ExplorationRun.id == run_id,
                ExplorationRun.status.in_(
                    [status.value for status in previous_statuses]
                ),
            )
            .values(**values)
            .returning(ExplorationRun)
            .execution_options(synchronize_session="fetch")
        )
        run = (await self._session.execute(statement)).scalar_one_or_none()
        if run is not None:
            return run

        current_status = await self._session.scalar(
            select(ExplorationRun.status).where(ExplorationRun.id == run_id)
        )
        if current_status is None:
            return None
        raise InvalidExplorationRunTransitionError(
            f"Cannot transition ExplorationRun from {current_status} "
            f"to {target_status.value}"
        )

    async def list_companies(self, run_id: UUID) -> list[ExplorationCompany]:
        statement = (
            select(ExplorationCompany)
            .where(ExplorationCompany.exploration_run_id == run_id)
            .order_by(ExplorationCompany.id.asc())
        )
        return list(await self._session.scalars(statement))

    async def list_with_summary(
        self, exploration_id: UUID
    ) -> list[tuple[ExplorationRun, str, int]]:
        """Load run provenance and selected-company counts in one query."""
        statement = (
            select(
                ExplorationRun,
                Campaign.name,
                func.count(ExplorationCompany.id).label("selected_company_count"),
            )
            .join(ResearchRun, ResearchRun.id == ExplorationRun.research_run_id)
            .join(Campaign, Campaign.id == ResearchRun.campaign_id)
            .outerjoin(
                ExplorationCompany,
                ExplorationCompany.exploration_run_id == ExplorationRun.id,
            )
            .where(ExplorationRun.exploration_id == exploration_id)
            .group_by(ExplorationRun.id, Campaign.id)
            .order_by(ExplorationRun.started_at.desc())
        )
        rows = (await self._session.execute(statement)).all()
        return [(run, campaign_name, count) for run, campaign_name, count in rows]
