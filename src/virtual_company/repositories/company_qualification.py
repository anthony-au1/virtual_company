"""Atomic persistence of final company qualification snapshots."""

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from virtual_company.db.models import CompanyQualificationSnapshot
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
