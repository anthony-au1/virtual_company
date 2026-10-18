"""Persistence operations for Exploration obligations."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from virtual_company.db.models import ExplorationObligation
from virtual_company.repositories._helpers import apply_updates, create_values
from virtual_company.repositories.dtos import (
    ExplorationObligationCreate,
    ExplorationObligationUpdate,
)


class ExplorationObligationRepository:
    """Provide asynchronous persistence operations for obligations."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, data: ExplorationObligationCreate) -> ExplorationObligation:
        obligation = ExplorationObligation(**create_values(data))
        self._session.add(obligation)
        await self._session.flush()
        await self._session.refresh(obligation)
        return obligation

    async def create_many(
        self, exploration_id: UUID, descriptions: list[str]
    ) -> list[ExplorationObligation]:
        obligations = [
            ExplorationObligation(
                exploration_id=exploration_id,
                description=description,
            )
            for description in descriptions
        ]
        self._session.add_all(obligations)
        await self._session.flush()
        return obligations

    async def get_by_id(self, obligation_id: UUID) -> ExplorationObligation | None:
        return await self._session.get(ExplorationObligation, obligation_id)

    async def list_by_exploration_id(
        self, exploration_id: UUID
    ) -> list[ExplorationObligation]:
        statement = select(ExplorationObligation).where(
            ExplorationObligation.exploration_id == exploration_id
        )
        return list(await self._session.scalars(statement))

    async def replace_for_exploration(
        self, exploration_id: UUID, descriptions: list[str]
    ) -> list[ExplorationObligation]:
        """Replace all obligations for an Exploration within the caller's transaction."""
        await self._session.execute(
            delete(ExplorationObligation).where(
                ExplorationObligation.exploration_id == exploration_id
            )
        )
        obligations = [
            ExplorationObligation(
                exploration_id=exploration_id,
                description=description,
            )
            for description in descriptions
        ]
        self._session.add_all(obligations)
        await self._session.flush()
        return obligations

    async def update(
        self, obligation_id: UUID, data: ExplorationObligationUpdate
    ) -> ExplorationObligation | None:
        obligation = await self.get_by_id(obligation_id)
        if obligation is None:
            return None
        apply_updates(obligation, data)
        await self._session.flush()
        await self._session.refresh(obligation)
        return obligation

    async def delete(self, obligation: ExplorationObligation) -> None:
        await self._session.delete(obligation)
        await self._session.flush()
