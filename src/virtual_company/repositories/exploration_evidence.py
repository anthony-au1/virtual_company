"""Persistence operations for Exploration evidence."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from virtual_company.db.models import (
    ExplorationCompany,
    ExplorationEvidence,
    ExplorationObligation,
    ExplorationRun,
)
from virtual_company.repositories._helpers import create_values
from virtual_company.repositories.dtos import ExplorationEvidenceCreate


class ExplorationEvidenceRepository:
    """Provide asynchronous persistence operations for evidence."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, data: ExplorationEvidenceCreate) -> ExplorationEvidence:
        company_exploration_id = await self._session.scalar(
            select(ExplorationRun.exploration_id)
            .join(
                ExplorationCompany,
                ExplorationCompany.exploration_run_id == ExplorationRun.id,
            )
            .where(ExplorationCompany.id == data.exploration_company_id)
        )
        if company_exploration_id is None:
            raise ValueError("Exploration company does not exist")

        obligation = await self._session.get(
            ExplorationObligation, data.exploration_obligation_id
        )
        if obligation is None:
            raise ValueError("Exploration obligation does not exist")
        if obligation.exploration_id != company_exploration_id:
            raise ValueError(
                "Evidence company and obligation must belong to the same Exploration"
            )

        evidence = ExplorationEvidence(**create_values(data))
        self._session.add(evidence)
        await self._session.flush()
        await self._session.refresh(evidence)
        return evidence

    async def get_by_id(self, evidence_id: UUID) -> ExplorationEvidence | None:
        return await self._session.get(ExplorationEvidence, evidence_id)

    async def get_by_id_with_facts(
        self, evidence_id: UUID
    ) -> ExplorationEvidence | None:
        statement = (
            select(ExplorationEvidence)
            .options(selectinload(ExplorationEvidence.facts))
            .where(ExplorationEvidence.id == evidence_id)
        )
        return await self._session.scalar(statement)

    async def list_by_exploration_company_id(
        self, exploration_company_id: UUID
    ) -> list[ExplorationEvidence]:
        statement = select(ExplorationEvidence).where(
            ExplorationEvidence.exploration_company_id == exploration_company_id
        )
        return list(await self._session.scalars(statement))

    async def list_by_obligation_id(
        self, obligation_id: UUID
    ) -> list[ExplorationEvidence]:
        statement = select(ExplorationEvidence).where(
            ExplorationEvidence.exploration_obligation_id == obligation_id
        )
        return list(await self._session.scalars(statement))
