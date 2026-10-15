"""Application service for Exploration definitions and their Obligations."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from virtual_company.db.models import Exploration, ExplorationObligation
from virtual_company.repositories.dtos import (
    ExplorationCreate,
    ExplorationObligationCreate,
    ExplorationObligationUpdate,
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

    async def create_obligation(
        self, exploration_id: UUID, description: str
    ) -> ExplorationObligation | None:
        async with self._session.begin():
            if await self._explorations.get_by_id(exploration_id) is None:
                return None
            return await self._obligations.create(
                ExplorationObligationCreate(
                    exploration_id=exploration_id, description=description
                )
            )

    async def list_obligations(
        self, exploration_id: UUID
    ) -> list[ExplorationObligation] | None:
        if await self._explorations.get_by_id(exploration_id) is None:
            return None
        return await self._obligations.list_by_exploration_id(exploration_id)

    async def update_obligation(
        self,
        exploration_id: UUID,
        obligation_id: UUID,
        data: ExplorationObligationUpdate,
    ) -> ExplorationObligation | None:
        async with self._session.begin():
            if await self._explorations.get_by_id(exploration_id) is None:
                return None
            obligation = await self._obligations.get_by_id(obligation_id)
            if obligation is None or obligation.exploration_id != exploration_id:
                return None
            return await self._obligations.update(obligation_id, data)

    async def delete_obligation(
        self, exploration_id: UUID, obligation_id: UUID
    ) -> bool:
        async with self._session.begin():
            if await self._explorations.get_by_id(exploration_id) is None:
                return False
            obligation = await self._obligations.get_by_id(obligation_id)
            if obligation is None or obligation.exploration_id != exploration_id:
                return False
            await self._obligations.delete(obligation)
            return True
