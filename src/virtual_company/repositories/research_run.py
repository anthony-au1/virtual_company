"""Persistence operations for research runs."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from virtual_company.db.models import (
    Campaign,
    CompanyQualificationSnapshot,
    ResearchRun,
)
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

    async def get_by_id_with_campaign(
        self, research_run_id: UUID
    ) -> ResearchRun | None:
        statement = (
            select(ResearchRun)
            .options(selectinload(ResearchRun.campaign))
            .where(ResearchRun.id == research_run_id)
        )
        return await self._session.scalar(statement)

    async def list(self) -> list[ResearchRun]:
        return list(await self._session.scalars(select(ResearchRun)))

    async def list_with_summary(
        self,
    ) -> list[tuple[ResearchRun, Campaign, dict[str, int]]]:
        """Load runs, campaigns, and grouped qualification/review counts in one query."""
        snapshot = CompanyQualificationSnapshot
        statement = (
            select(
                ResearchRun,
                Campaign,
                func.count(snapshot.id).label("researched"),
                func.count(case((snapshot.status == "QUALIFIED", 1))).label(
                    "qualified"
                ),
                func.count(case((snapshot.status == "NOT_QUALIFIED", 1))).label(
                    "not_qualified"
                ),
                func.count(case((snapshot.status == "INSUFFICIENT_EVIDENCE", 1))).label(
                    "insufficient_evidence"
                ),
                func.count(case((snapshot.review_status == "ACCEPTED", 1))).label(
                    "accepted"
                ),
                func.count(case((snapshot.review_status == "REJECTED", 1))).label(
                    "rejected"
                ),
                func.count(case((snapshot.review_status == "UNREVIEWED", 1))).label(
                    "unreviewed"
                ),
            )
            .join(Campaign, Campaign.id == ResearchRun.campaign_id)
            .outerjoin(snapshot, snapshot.research_run_id == ResearchRun.id)
            .group_by(ResearchRun.id, Campaign.id)
            .order_by(ResearchRun.created_at.desc())
        )
        rows = (await self._session.execute(statement)).all()
        return [
            (
                run,
                campaign,
                {
                    "researched": researched,
                    "qualified": qualified,
                    "not_qualified": not_qualified,
                    "insufficient_evidence": insufficient_evidence,
                    "accepted": accepted,
                    "rejected": rejected,
                    "unreviewed": unreviewed,
                },
            )
            for run, campaign, researched, qualified, not_qualified, insufficient_evidence, accepted, rejected, unreviewed in rows
        ]

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
