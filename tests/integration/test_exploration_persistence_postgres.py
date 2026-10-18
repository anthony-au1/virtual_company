"""Opt-in PostgreSQL verification for Exploration persistence."""

import os
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateSchema, DropSchema

from virtual_company.config import DEFAULT_DATABASE_URL
from virtual_company.db import Base
from virtual_company.db.models import ResearchCompany
from virtual_company.repositories.dtos import (
    ExplorationCompanyCreate,
    ExplorationCreate,
    ExplorationEvidenceCreate,
    ExplorationFactCreate,
    ExplorationHypothesisCreate,
    ExplorationObligationCreate,
    ExplorationObligationUpdate,
    ExplorationRunCreate,
    ExplorationUpdate,
)
from virtual_company.repositories.exploration import ExplorationRepository
from virtual_company.repositories.exploration_company import (
    ExplorationCompanyRepository,
)
from virtual_company.repositories.exploration_evidence import (
    ExplorationEvidenceRepository,
)
from virtual_company.repositories.exploration_fact import ExplorationFactRepository
from virtual_company.repositories.exploration_hypothesis import (
    ExplorationHypothesisRepository,
)
from virtual_company.repositories.exploration_obligation import (
    ExplorationObligationRepository,
)
from virtual_company.repositories.exploration_run import ExplorationRunRepository
from virtual_company.services.exploration import (
    ExplorationGenerationConflictError,
    ExplorationService,
)
from virtual_company.services.obligation_generator import (
    GeneratedObligation,
    ObligationGenerationResult,
)


class StaticObligationGenerator:
    async def generate(self, business_context: str, max_obligations: int):
        return ObligationGenerationResult(
            obligations=[
                GeneratedObligation(description="Generated for " + business_context)
            ]
        )


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("RUN_EXPLORATION_DB_TESTS") != "true",
    reason="Opt-in local PostgreSQL Exploration persistence test",
)
async def test_exploration_entities_and_provenance_relationships() -> None:
    schema = f"test_exploration_{uuid4().hex}"
    engine = create_async_engine(
        os.getenv("EXPLORATION_TEST_DATABASE_URL", DEFAULT_DATABASE_URL)
    )
    scoped = engine.execution_options(schema_translate_map={None: schema})
    try:
        async with engine.begin() as connection:
            await connection.execute(CreateSchema(schema))
        async with scoped.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        sessions = async_sessionmaker(scoped, expire_on_commit=False)
        async with sessions() as session:
            exploration_repo = ExplorationRepository(session)
            obligation_repo = ExplorationObligationRepository(session)
            run_repo = ExplorationRunRepository(session)
            company_repo = ExplorationCompanyRepository(session)
            evidence_repo = ExplorationEvidenceRepository(session)
            fact_repo = ExplorationFactRepository(session)
            hypothesis_repo = ExplorationHypothesisRepository(session)

            exploration = await exploration_repo.create(
                ExplorationCreate(
                    business_context="Assess payment-provider fit",
                    max_obligations=20,
                    status="DRAFT",
                )
            )
            assert exploration.max_obligations == 20
            assert (
                await exploration_repo.get_by_id(exploration.id)
            ).max_obligations == 20
            assert any(
                item.id == exploration.id and item.max_obligations == 20
                for item in await exploration_repo.list()
            )
            obligation_one = await obligation_repo.create(
                ExplorationObligationCreate(
                    exploration_id=exploration.id,
                    description="Identify target market",
                )
            )
            obligation_two = await obligation_repo.create(
                ExplorationObligationCreate(
                    exploration_id=exploration.id,
                    description="Assess product capabilities",
                )
            )
            run = await run_repo.create(
                ExplorationRunCreate(
                    exploration_id=exploration.id,
                    status="RUNNING",
                )
            )
            company = ResearchCompany(name="Tyro Payments")
            session.add(company)
            await session.flush()
            link = await company_repo.create(
                ExplorationCompanyCreate(
                    exploration_run_id=run.id,
                    company_id=company.id,
                )
            )
            assert link.company_id == company.id
            assert (
                await company_repo.get_by_run_and_company(run.id, company.id)
            ).company.name == "Tyro Payments"

            evidence_one = await evidence_repo.create(
                ExplorationEvidenceCreate(
                    exploration_company_id=link.id,
                    exploration_obligation_id=obligation_one.id,
                    source_url="https://example.com/market",
                    source_type="company-site",
                    content="Serves Australian businesses.",
                )
            )
            evidence_two = await evidence_repo.create(
                ExplorationEvidenceCreate(
                    exploration_company_id=link.id,
                    exploration_obligation_id=obligation_two.id,
                    source_url="https://example.com/product",
                    source_type="product-page",
                    content="Offers payment processing.",
                )
            )
            fact_one = await fact_repo.create(
                ExplorationFactCreate(
                    statement="The company serves Australian businesses.",
                    evidence_ids=[evidence_one.id, evidence_two.id],
                )
            )
            fact_two = await fact_repo.create(
                ExplorationFactCreate(
                    statement="The company offers payment processing.",
                    evidence_ids=[evidence_two.id],
                )
            )
            hypothesis = await hypothesis_repo.create(
                ExplorationHypothesisCreate(
                    statement="The company may fit the Exploration target.",
                    fact_ids=[fact_one.id, fact_two.id],
                )
            )
            await session.commit()

            loaded_fact = await fact_repo.get_by_id_with_evidence(fact_one.id)
            loaded_hypothesis = await hypothesis_repo.get_by_id_with_facts(
                hypothesis.id
            )
            assert loaded_fact is not None
            assert {item.id for item in loaded_fact.evidence} == {
                evidence_one.id,
                evidence_two.id,
            }
            assert loaded_hypothesis is not None
            assert {item.id for item in loaded_hypothesis.facts} == {
                fact_one.id,
                fact_two.id,
            }
            assert len(await exploration_repo.list_obligations(exploration.id)) == 2
            assert len(await exploration_repo.list_runs(exploration.id)) == 1

            # Exercise Exploration CRUD/read access and internal obligation
            # persistence independently of the public API.
            service = ExplorationService(session, StaticObligationGenerator())
            app_exploration = await service.create("Application service context", 4)
            assert app_exploration.status == "DRAFT"
            assert (await service.get_by_id(app_exploration.id)).business_context == (
                "Application service context"
            )
            assert app_exploration.max_obligations == 4
            assert [item.id for item in await service.list()]  # persisted list result
            assert [
                item.description
                for item in await service.list_obligations(app_exploration.id)
            ] == ["Generated for Application service context"]
            changed = await service.update(
                app_exploration.id,
                ExplorationUpdate(
                    business_context="Updated application context",
                    max_obligations=8,
                ),
            )
            assert changed.business_context == "Updated application context"
            assert changed.max_obligations == 8
            app_obligation = (await service.list_obligations(app_exploration.id))[0]
            changed_obligation = await obligation_repo.update(
                app_obligation.id,
                ExplorationObligationUpdate(description="Updated requirement"),
            )
            assert changed_obligation.description == "Updated requirement"
            await obligation_repo.delete(changed_obligation)
            assert await service.list_obligations(app_exploration.id) == []
            assert len(await run_repo.list_companies(run.id)) == 1
            assert len(await evidence_repo.list_by_exploration_company_id(link.id)) == 2
            assert (
                len(await evidence_repo.list_by_obligation_id(obligation_one.id)) == 1
            )

            with pytest.raises(ExplorationGenerationConflictError):
                await service.delete(exploration.id)
            assert await exploration_repo.get_by_id(exploration.id) is not None
            assert len(await service.list_obligations(exploration.id)) == 2

            assert await service.delete(app_exploration.id) is True
            assert await exploration_repo.get_by_id(app_exploration.id) is None
            assert await service.list_obligations(app_exploration.id) is None

            with pytest.raises(IntegrityError):
                await company_repo.create(
                    ExplorationCompanyCreate(
                        exploration_run_id=run.id,
                        company_id=company.id,
                    )
                )
            await session.rollback()
    finally:
        async with engine.begin() as connection:
            await connection.execute(DropSchema(schema, cascade=True, if_exists=True))
        await engine.dispose()
