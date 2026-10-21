"""Application service for Exploration definitions and their Obligations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from virtual_company.db.models import Exploration, ExplorationObligation, ExplorationRun
from virtual_company.repositories.dtos import (
    ExplorationCreate,
    ExplorationRunCreate,
    ExplorationUpdate,
)
from virtual_company.repositories.exploration_company import (
    ExplorationCompanyRepository,
)
from virtual_company.repositories.exploration import ExplorationRepository
from virtual_company.repositories.exploration_obligation import (
    ExplorationObligationRepository,
)
from virtual_company.repositories.exploration_run import ExplorationRunRepository
from virtual_company.repositories.research_company_qualification import (
    ResearchCompanyQualificationRepository,
)
from virtual_company.repositories.research_run import ResearchRunRepository
from virtual_company.services.obligation_generator import (
    ObligationGenerationResult,
    ObligationGenerator,
    create_configured_obligation_generator,
)


class ExplorationLifecycleConflictError(ValueError):
    """Raised when a lifecycle rule prevents changing an Exploration."""


# Preserve the existing service error name for callers while sharing the same
# lifecycle conflict type with DELETE.
ExplorationGenerationConflictError = ExplorationLifecycleConflictError


class ExplorationObligationGenerationError(RuntimeError):
    """Raised when obligation generation fails for technical reasons."""


class ExplorationStartNotFoundError(LookupError):
    """Raised when a source ResearchRun does not exist."""


class ExplorationStartConflictError(ValueError):
    """Raised when a source ResearchRun is not finalized."""


class ExplorationCompanySelectionError(ValueError):
    """Raised when one or more selected companies are outside the result set."""


@dataclass(frozen=True)
class StartedExplorationRun:
    run: ExplorationRun
    company_ids: list[UUID]


@dataclass(frozen=True)
class ExplorationRunSummary:
    id: UUID
    research_run_id: UUID
    status: str
    started_at: datetime
    completed_at: datetime | None
    campaign_name: str
    selected_company_count: int


class ExplorationService:
    """Coordinate application behavior for Explorations and Obligations."""

    def __init__(
        self,
        session: AsyncSession,
        generator: ObligationGenerator | None = None,
    ) -> None:
        self._session = session
        self._explorations = ExplorationRepository(session)
        self._obligations = ExplorationObligationRepository(session)
        self._runs = ExplorationRunRepository(session)
        self._run_companies = ExplorationCompanyRepository(session)
        self._research_runs = ResearchRunRepository(session)
        self._qualifications = ResearchCompanyQualificationRepository(session)
        self._generator = generator or create_configured_obligation_generator()

    async def create(
        self, business_context: str, max_obligations: int = 10
    ) -> Exploration:
        result = await self._generate(business_context, max_obligations)
        async with self._session.begin():
            exploration = await self._explorations.create(
                ExplorationCreate(
                    business_context=business_context,
                    max_obligations=max_obligations,
                    status="DRAFT",
                )
            )
            await self._obligations.create_many(
                exploration.id,
                [item.description for item in result.obligations],
            )
            return exploration

    async def get_by_id(self, exploration_id: UUID) -> Exploration | None:
        return await self._explorations.get_by_id(exploration_id)

    async def list(self) -> list[Exploration]:
        return await self._explorations.list()

    async def update(
        self, exploration_id: UUID, data: ExplorationUpdate
    ) -> Exploration | None:
        async with self._session.begin():
            current = await self._explorations.get_by_id_for_update(exploration_id)
            if current is None:
                return None

            business_context = (
                data.business_context
                if "business_context" in data.model_fields_set
                else current.business_context
            )
            max_obligations = (
                data.max_obligations
                if "max_obligations" in data.model_fields_set
                else current.max_obligations
            )
            inputs_changed = (
                business_context != current.business_context
                or max_obligations != current.max_obligations
            )

            if not inputs_changed:
                return await self._explorations.update(exploration_id, data)

            if await self._runs.exists_for_exploration(exploration_id):
                raise ExplorationLifecycleConflictError(
                    "Exploration business context and maximum obligations cannot "
                    "change after the Exploration has been run"
                )

            result = await self._generate(business_context, max_obligations)
            updated = await self._explorations.update(
                exploration_id,
                ExplorationUpdate(
                    business_context=business_context,
                    max_obligations=max_obligations,
                ),
            )
            await self._obligations.replace_for_exploration(
                exploration_id,
                [item.description for item in result.obligations],
            )
            return updated

    async def delete(self, exploration_id: UUID) -> bool:
        """Delete a pre-run Exploration and its generated obligations atomically."""
        async with self._session.begin():
            exploration = await self._explorations.get_by_id_for_update(exploration_id)
            if exploration is None:
                return False
            if await self._runs.exists_for_exploration(exploration_id):
                raise ExplorationLifecycleConflictError(
                    "This Exploration cannot be deleted because it has already been run."
                )
            await self._obligations.delete_for_exploration_id(exploration_id)
            await self._explorations.delete(exploration)
            return True

    async def start_run(
        self, exploration_id: UUID, research_run_id: UUID, company_ids: list[UUID]
    ) -> StartedExplorationRun | None:
        """Create a run and its selected-company snapshot under the parent lock."""
        unique_company_ids = list(dict.fromkeys(company_ids))
        async with self._session.begin():
            exploration = await self._explorations.get_by_id_for_update(exploration_id)
            if exploration is None:
                return None

            research_run = await self._research_runs.get_by_id(research_run_id)
            if research_run is None:
                raise ExplorationStartNotFoundError("Research run not found")
            if research_run.status != "COMPLETED":
                raise ExplorationStartConflictError(
                    "Only completed ResearchRuns can start an ExplorationRun"
                )

            eligible_ids = await self._qualifications.list_member_company_ids(
                research_run_id, unique_company_ids
            )
            if eligible_ids != set(unique_company_ids):
                raise ExplorationCompanySelectionError(
                    "One or more selected companies are not in this ResearchRun"
                )

            run = await self._runs.create(
                ExplorationRunCreate(
                    exploration_id=exploration_id,
                    research_run_id=research_run_id,
                    status="RUNNING",
                )
            )
            await self._run_companies.create_many(run.id, unique_company_ids)
            return StartedExplorationRun(run=run, company_ids=unique_company_ids)

    async def list_runs(
        self, exploration_id: UUID
    ) -> list[ExplorationRunSummary] | None:
        """List run summaries, returning None when the Exploration is missing."""
        if await self._explorations.get_by_id(exploration_id) is None:
            return None
        return [
            ExplorationRunSummary(
                id=run.id,
                research_run_id=run.research_run_id,
                status=run.status,
                started_at=run.started_at,
                completed_at=run.completed_at,
                campaign_name=campaign_name,
                selected_company_count=selected_company_count,
            )
            for run, campaign_name, selected_company_count in
            await self._runs.list_with_summary(exploration_id)
        ]

    async def list_obligations(
        self, exploration_id: UUID
    ) -> list[ExplorationObligation] | None:
        if await self._explorations.get_by_id(exploration_id) is None:
            return None
        return await self._obligations.list_by_exploration_id(exploration_id)

    async def _generate(
        self, business_context: str, max_obligations: int
    ) -> ObligationGenerationResult:
        try:
            return await self._generator.generate(business_context, max_obligations)
        except Exception as error:
            raise ExplorationObligationGenerationError(
                "Obligation generation failed"
            ) from error
