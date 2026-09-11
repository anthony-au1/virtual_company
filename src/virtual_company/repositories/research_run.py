"""Persistence operations for research runs."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from virtual_company.db.models import ResearchRun
from virtual_company.repositories._helpers import apply_updates, create_values
from virtual_company.repositories.dtos import ResearchRunCreate, ResearchRunUpdate


class ResearchRunRepository:
    """Provide asynchronous persistence operations for research runs."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, data: ResearchRunCreate) -> ResearchRun:
        research_run = ResearchRun(**create_values(data))
        self._session.add(research_run)
        await self._session.flush()
        await self._session.refresh(research_run)
        return research_run

    async def get_by_id(self, research_run_id: UUID) -> ResearchRun | None:
        return await self._session.get(ResearchRun, research_run_id)

    async def list(self) -> list[ResearchRun]:
        return list(await self._session.scalars(select(ResearchRun)))

    async def update(
        self, research_run_id: UUID, data: ResearchRunUpdate
    ) -> ResearchRun | None:
        research_run = await self.get_by_id(research_run_id)
        if research_run is None:
            return None

        apply_updates(research_run, data)
        await self._session.flush()
        await self._session.refresh(research_run)
        return research_run
