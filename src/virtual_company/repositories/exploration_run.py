"""Persistence operations for Exploration runs."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from virtual_company.db.models import (
    Campaign,
    ExplorationCompany,
    ExplorationRun,
    ResearchRun,
)
from virtual_company.repositories._helpers import apply_updates, create_values
from virtual_company.repositories.dtos import ExplorationRunCreate, ExplorationRunUpdate


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
        run = await self.get_by_id(run_id)
        if run is None:
            return None
        apply_updates(run, data)
        await self._session.flush()
        await self._session.refresh(run)
        return run

    async def list_companies(self, run_id: UUID) -> list[ExplorationCompany]:
        statement = select(ExplorationCompany).where(
            ExplorationCompany.exploration_run_id == run_id
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
