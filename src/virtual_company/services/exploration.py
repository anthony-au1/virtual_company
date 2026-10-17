"""Application service for Exploration definitions and their Obligations."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from virtual_company.db.models import Exploration, ExplorationObligation
from virtual_company.repositories.dtos import (
    ExplorationCreate,
    ExplorationUpdate,
)
from virtual_company.repositories.exploration import ExplorationRepository
from virtual_company.repositories.exploration_obligation import (
    ExplorationObligationRepository,
)


class ExplorationService:
    """Coordinate application behavior for Explorations and Obligations."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._explorations = ExplorationRepository(session)
        self._obligations = ExplorationObligationRepository(session)

    async def create(self, business_context: str) -> Exploration:
        async with self._session.begin():
            return await self._explorations.create(
                ExplorationCreate(business_context=business_context, status="DRAFT")
            )

    async def get_by_id(self, exploration_id: UUID) -> Exploration | None:
        return await self._explorations.get_by_id(exploration_id)

    async def list(self) -> list[Exploration]:
        return await self._explorations.list()

    async def update(
        self, exploration_id: UUID, data: ExplorationUpdate
    ) -> Exploration | None:
        async with self._session.begin():
            return await self._explorations.update(exploration_id, data)

    async def list_obligations(
        self, exploration_id: UUID
    ) -> list[ExplorationObligation] | None:
        if await self._explorations.get_by_id(exploration_id) is None:
            return None
        return await self._obligations.list_by_exploration_id(exploration_id)
