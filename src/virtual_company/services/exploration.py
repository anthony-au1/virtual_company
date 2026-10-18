"""Application service for Exploration definitions and their Obligations."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from virtual_company.db.models import Exploration, ExplorationObligation
from virtual_company.repositories.dtos import (
    ExplorationCreate,
    ExplorationUpdate,
)
from virtual_company.repositories.exploration import ExplorationRepository
from virtual_company.repositories.exploration_obligation import (
    ExplorationObligationRepository,
)
from virtual_company.repositories.exploration_run import ExplorationRunRepository
from virtual_company.services.obligation_generator import (
    ObligationGenerationResult,
    ObligationGenerator,
    create_configured_obligation_generator,
)


class ExplorationGenerationConflictError(ValueError):
    """Raised when generation inputs are changed after an Exploration run."""


class ExplorationObligationGenerationError(RuntimeError):
    """Raised when obligation generation fails for technical reasons."""


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
                raise ExplorationGenerationConflictError(
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
