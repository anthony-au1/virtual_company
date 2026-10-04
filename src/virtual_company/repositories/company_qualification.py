"""Persistence of final company qualification snapshots and human review."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from virtual_company.db.models import Company, CompanyQualificationSnapshot
from virtual_company.domain.review import ReviewStatus
from virtual_company.repositories.dtos import CompanyQualificationUpsert


class CompanyQualificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(
        self, data: CompanyQualificationUpsert
    ) -> CompanyQualificationSnapshot:
        """Replace a run/company snapshot without changing its identity or timestamp."""
        statement = insert(CompanyQualificationSnapshot).values(**data.model_dump())
        statement = statement.on_conflict_do_update(
            constraint="uq_company_qualifications_run_company",
            set_={
                "status": statement.excluded.status,
                "criteria_results": statement.excluded.criteria_results,
            },
        ).returning(CompanyQualificationSnapshot)
        result = await self._session.scalars(
            statement, execution_options={"populate_existing": True}
        )
        return result.one()

    async def list_for_run(
        self, research_run_id: UUID
    ) -> list[tuple[CompanyQualificationSnapshot, Company]]:
        """Return terminal company results for a run in stable presentation order."""
        statement = (
            select(CompanyQualificationSnapshot, Company)
            .join(Company, Company.id == CompanyQualificationSnapshot.company_id)
            .where(
                CompanyQualificationSnapshot.research_run_id == research_run_id
            )
            .order_by(Company.name, Company.id)
        )
        rows = await self._session.execute(statement)
        return [(snapshot, company) for snapshot, company in rows.all()]

    async def update_review_status(
        self,
        *,
        research_run_id: UUID,
        company_id: UUID,
        review_status: ReviewStatus,
    ) -> CompanyQualificationSnapshot | None:
        """Set the current human decision for an exact run/company result."""
        statement = select(CompanyQualificationSnapshot).where(
            CompanyQualificationSnapshot.research_run_id == research_run_id,
            CompanyQualificationSnapshot.company_id == company_id,
        )
        snapshot = await self._session.scalar(statement)
        if snapshot is None:
            return None
        snapshot.review_status = review_status.value
        await self._session.flush()
        await self._session.refresh(snapshot)
        return snapshot
