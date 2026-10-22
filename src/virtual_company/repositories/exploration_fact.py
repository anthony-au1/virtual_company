"""Persistence operations for Exploration facts."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from virtual_company.db.models import (
    ExplorationCompany,
    ExplorationEvidence,
    ExplorationFact,
)
from virtual_company.repositories.dtos import ExplorationFactCreate


class ExplorationFactRepository:
    """Provide asynchronous persistence operations for facts."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, data: ExplorationFactCreate) -> ExplorationFact:
        company = await self._session.get(
            ExplorationCompany, data.exploration_company_id
        )
        if company is None:
            raise ValueError("Exploration company does not exist")

        evidence = list(
            await self._session.scalars(
                select(ExplorationEvidence).where(
                    ExplorationEvidence.id.in_(data.evidence_ids)
                )
            )
        )
        if len(evidence) != len(set(data.evidence_ids)):
            raise ValueError("One or more Exploration evidence records do not exist")
        if any(
            item.exploration_company_id != data.exploration_company_id
            for item in evidence
        ):
            raise ValueError(
                "All Evidence supporting a Fact must belong to its company"
            )

        fact = ExplorationFact(
            exploration_company_id=data.exploration_company_id,
            statement=data.statement,
            evidence=evidence,
        )
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
