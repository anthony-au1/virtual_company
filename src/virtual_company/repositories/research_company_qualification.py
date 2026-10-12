"""Persistence of final company qualification snapshots."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from virtual_company.db.models import ResearchCompany, ResearchCompanyQualification
from virtual_company.repositories.dtos import ResearchCompanyQualificationUpsert


class ResearchCompanyQualificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(
        self, data: ResearchCompanyQualificationUpsert
    ) -> ResearchCompanyQualification:
        """Replace a run/company snapshot without changing its identity or timestamp."""
        statement = insert(ResearchCompanyQualification).values(**data.model_dump())
        statement = statement.on_conflict_do_update(
            constraint="uq_research_company_qualifications_run_company",
            set_={
                "status": statement.excluded.status,
                "criteria_results": statement.excluded.criteria_results,
            },
        ).returning(ResearchCompanyQualification)
        result = await self._session.scalars(
            statement, execution_options={"populate_existing": True}
        )
        return result.one()

    async def list_for_run(
        self, research_run_id: UUID
    ) -> list[tuple[ResearchCompanyQualification, ResearchCompany]]:
        """Return terminal company results for a run in stable presentation order."""
        statement = (
            select(ResearchCompanyQualification, ResearchCompany)
            .join(
                ResearchCompany,
                ResearchCompany.id == ResearchCompanyQualification.company_id,
            )
            .where(ResearchCompanyQualification.research_run_id == research_run_id)
            .order_by(ResearchCompany.name, ResearchCompany.id)
        )
        rows = await self._session.execute(statement)
        return [(snapshot, company) for snapshot, company in rows.all()]

    async def delete_by_research_run_id(self, research_run_id: UUID) -> None:
        statement = select(ResearchCompanyQualification).where(
            ResearchCompanyQualification.research_run_id == research_run_id
        )
        for snapshot in await self._session.scalars(statement):
            await self._session.delete(snapshot)
        await self._session.flush()
