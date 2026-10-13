"""Persistence operations for Exploration facts."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from virtual_company.db.models import ExplorationEvidence, ExplorationFact
from virtual_company.repositories._helpers import apply_updates
from virtual_company.repositories.dtos import (
    ExplorationFactCreate,
    ExplorationFactUpdate,
)


class ExplorationFactRepository:
    """Provide asynchronous persistence operations for facts."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, data: ExplorationFactCreate) -> ExplorationFact:
        fact = ExplorationFact(statement=data.statement)
        if data.evidence_ids:
            evidence = list(
                await self._session.scalars(
                    select(ExplorationEvidence).where(
                        ExplorationEvidence.id.in_(data.evidence_ids)
                    )
                )
            )
            if len(evidence) != len(set(data.evidence_ids)):
                raise ValueError(
                    "One or more Exploration evidence records do not exist"
                )
            fact.evidence = evidence
        self._session.add(fact)
        await self._session.flush()
        await self._session.refresh(fact)
        return fact

    async def get_by_id(self, fact_id: UUID) -> ExplorationFact | None:
        return await self._session.get(ExplorationFact, fact_id)

    async def get_by_id_with_evidence(self, fact_id: UUID) -> ExplorationFact | None:
        statement = (
            select(ExplorationFact)
            .options(selectinload(ExplorationFact.evidence))
            .where(ExplorationFact.id == fact_id)
        )
        return await self._session.scalar(statement)

    async def update(
        self, fact_id: UUID, data: ExplorationFactUpdate
    ) -> ExplorationFact | None:
        fact = await self.get_by_id(fact_id)
        if fact is None:
            return None
        apply_updates(fact, data)
        await self._session.flush()
        await self._session.refresh(fact)
        return fact
