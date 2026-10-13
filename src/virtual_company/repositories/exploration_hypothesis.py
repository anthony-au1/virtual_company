"""Persistence operations for Exploration hypotheses."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from virtual_company.db.models import ExplorationFact, ExplorationHypothesis
from virtual_company.repositories._helpers import apply_updates
from virtual_company.repositories.dtos import (
    ExplorationHypothesisCreate,
    ExplorationHypothesisUpdate,
)


class ExplorationHypothesisRepository:
    """Provide asynchronous persistence operations for hypotheses."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, data: ExplorationHypothesisCreate) -> ExplorationHypothesis:
        hypothesis = ExplorationHypothesis(statement=data.statement)
        if data.fact_ids:
            facts = list(
                await self._session.scalars(
                    select(ExplorationFact).where(ExplorationFact.id.in_(data.fact_ids))
                )
            )
            if len(facts) != len(set(data.fact_ids)):
                raise ValueError("One or more Exploration facts do not exist")
            hypothesis.facts = facts
        self._session.add(hypothesis)
        await self._session.flush()
        await self._session.refresh(hypothesis)
        return hypothesis

    async def get_by_id(self, hypothesis_id: UUID) -> ExplorationHypothesis | None:
        return await self._session.get(ExplorationHypothesis, hypothesis_id)

    async def get_by_id_with_facts(
        self, hypothesis_id: UUID
    ) -> ExplorationHypothesis | None:
        statement = (
            select(ExplorationHypothesis)
            .options(selectinload(ExplorationHypothesis.facts))
            .where(ExplorationHypothesis.id == hypothesis_id)
        )
        return await self._session.scalar(statement)

    async def update(
        self, hypothesis_id: UUID, data: ExplorationHypothesisUpdate
    ) -> ExplorationHypothesis | None:
        hypothesis = await self.get_by_id(hypothesis_id)
        if hypothesis is None:
            return None
        apply_updates(hypothesis, data)
        await self._session.flush()
        await self._session.refresh(hypothesis)
        return hypothesis
