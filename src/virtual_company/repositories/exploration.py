"""Persistence operations for Explorations."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from virtual_company.db.models import Exploration, ExplorationObligation, ExplorationRun
from virtual_company.repositories._helpers import apply_updates, create_values
from virtual_company.repositories.dtos import ExplorationCreate, ExplorationUpdate


class ExplorationRepository:
    """Provide asynchronous persistence operations for Explorations."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, data: ExplorationCreate) -> Exploration:
        exploration = Exploration(**create_values(data))
        self._session.add(exploration)
        await self._session.flush()
        await self._session.refresh(exploration)
        return exploration

    async def get_by_id(self, exploration_id: UUID) -> Exploration | None:
        return await self._session.get(Exploration, exploration_id)

    async def list(self) -> list[Exploration]:
        return list(await self._session.scalars(select(Exploration)))

    async def update(
        self, exploration_id: UUID, data: ExplorationUpdate
    ) -> Exploration | None:
        exploration = await self.get_by_id(exploration_id)
        if exploration is None:
            return None
        apply_updates(exploration, data)
        await self._session.flush()
        await self._session.refresh(exploration)
        return exploration

    async def list_obligations(
        self, exploration_id: UUID
    ) -> list[ExplorationObligation]:
        statement = select(ExplorationObligation).where(
            ExplorationObligation.exploration_id == exploration_id
        )
        return list(await self._session.scalars(statement))

    async def list_runs(self, exploration_id: UUID) -> list[ExplorationRun]:
        statement = select(ExplorationRun).where(
            ExplorationRun.exploration_id == exploration_id
        )
        return list(await self._session.scalars(statement))
