"""PostgreSQL integration of the real Exploration graph and FastAPI API."""

from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateSchema, DropSchema

from virtual_company.api.dependencies import get_exploration_service
from virtual_company.db import Base
from virtual_company.db.models import (
    Campaign,
    ExplorationCompany,
    ExplorationEvidence,
    ExplorationFact,
    ExplorationHypothesis,
    ExplorationRun,
    ResearchCompany,
    ResearchCompanyQualification,
    ResearchRun,
)
from virtual_company.domain.exploration.run import ExplorationRunStatus
from virtual_company.main import app
from virtual_company.services.exploration import ExplorationService
from virtual_company.services.exploration_evidence_extractor import (
    ExplorationEvidenceExtractor,
)
from virtual_company.services.exploration_fact_extractor import (
    ExplorationFactExtractor,
)
from virtual_company.services.exploration_fetch import ExplorationFetchService
from virtual_company.services.exploration_hypothesis_generator import (
    ExplorationHypothesisGenerator,
)
from virtual_company.services.exploration_query_generator import (
    ExplorationQueryGenerator,
)
from virtual_company.services.exploration_search import ExplorationSearchService
from virtual_company.services.obligation_generator import (
    GeneratedObligation,
    ObligationGenerationResult,
)
from virtual_company.tools.web_fetch import WebPage
from virtual_company.tools.web_search import SearchResponse, SearchResult
from virtual_company.workflows.exploration.graph import ExplorationWorkflow

RUN_DB_TESTS = os.getenv("RUN_EXPLORATION_DB_TESTS") == "true"
EXCERPT = "The company provides payment services to regional businesses."


class StaticObligationGenerator:
    async def generate(self, business_context: str, max_obligations: int):
        del business_context, max_obligations
        return ObligationGenerationResult(
            obligations=[
                GeneratedObligation(description="Assess the product offering"),
                GeneratedObligation(description="Assess the target market"),
            ]
        )


class DeterministicLLMProvider:
    provider = "phase5-test"
    model = "deterministic"

    def __init__(self, sessions):
        self.sessions = sessions
        self.run_id: UUID | None = None
        self.response_counts: Counter[str] = Counter()
        self.query_inputs: list[tuple[str, str]] = []
        self.first_provider_status: str | None = None
        self.timeline: list[str] = []

    async def generate_structured(self, *, system_prompt, user_prompt, response_model):
        del system_prompt
        response_name = response_model.__name__
        self.response_counts[response_name] += 1
        if "provider_started" not in self.timeline:
            self.timeline.append("provider_started")
            assert self.run_id is not None
            async with self.sessions() as session:
                self.first_provider_status = await session.scalar(
                    select(ExplorationRun.status).where(
                        ExplorationRun.id == self.run_id
                    )
                )

        if response_name == "ExplorationQueryGenerationResult":
            payload = json.loads(user_prompt)
            self.query_inputs.append(
                (payload["company"]["name"], payload["obligation"]["description"])
            )
            return {
                "queries": [
                    {
                        "query": (
                            f"{payload['company']['name']} "
                            f"{payload['obligation']['description']}"
                        )
                    }
                ]
            }
        if response_name == "ExtractedExplorationEvidenceItems":
            return {
                "evidence": [
                    {
                        "claim": "Payment services are offered",
                        "evidence_text": EXCERPT,
                    }
                ]
            }
        if response_name == "ExtractedExplorationFacts":
            return {
                "facts": [
                    {
                        "statement": "The company provides payment services",
                        "evidence_refs": ["E1"],
                    },
                    {
                        "statement": "The company serves regional businesses",
                        "evidence_refs": ["E2"],
                    },
                ]
            }
        if response_name == "ExtractedExplorationHypotheses":
            return {
                "hypotheses": [
                    {
                        "statement": "The company may have regional growth potential",
                        "fact_refs": ["F1", "F2"],
                    }
                ]
            }
        raise AssertionError(f"Unexpected structured response model: {response_name}")


class DeterministicSearchTool:
    provider = "phase5-test"

    def __init__(self):
        self.calls = 0

    async def search(self, query: str, limit: int = 10) -> SearchResponse:
        assert limit > 0
        self.calls += 1
        return SearchResponse(
            results=[
                SearchResult(
                    title="Regional payment service information",
                    url=f"https://source-{self.calls}.example.test/page",
                    snippet=query,
                )
            ]
        )


class DeterministicFetchTool:
    provider = "phase5-test"

    def __init__(self):
        self.calls = 0

    async def fetch(self, url: str) -> WebPage:
        self.calls += 1
        return WebPage(
            url=url,
            title="Regional services",
            content=f"{EXCERPT} Reference {self.calls}.",
        )


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.skipif(not RUN_DB_TESTS, reason="Opt-in PostgreSQL Exploration E2E")
async def test_real_graph_and_fastapi_execute_multi_company_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = os.getenv("EXPLORATION_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip(
            "EXPLORATION_TEST_DATABASE_URL must target a dedicated test database"
        )

    schema = f"phase5_full_workflow_{uuid4().hex}"
    engine = create_async_engine(database_url)
    scoped_engine = engine.execution_options(schema_translate_map={None: schema})
    app.dependency_overrides.clear()
    try:
        async with engine.begin() as connection:
            await connection.execute(CreateSchema(schema))
        async with scoped_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(scoped_engine, expire_on_commit=False)

        async with sessions.begin() as session:
            campaign = Campaign(
                name="Phase 5 source campaign",
                keywords=[],
                target_count=2,
                max_companies_to_research=2,
                status="COMPLETED",
            )
            session.add(campaign)
            await session.flush()
            research_run = ResearchRun(
                campaign_id=campaign.id,
                status="COMPLETED",
                companies_found=2,
            )
            companies = [
                ResearchCompany(name="Phase Five Company Alpha", domain="alpha.test"),
                ResearchCompany(name="Phase Five Company Beta", domain="beta.test"),
            ]
            session.add_all([research_run, *companies])
            await session.flush()
            session.add_all(
                [
                    ResearchCompanyQualification(
                        research_run_id=research_run.id,
                        campaign_id=campaign.id,
                        company_id=company.id,
                        status="QUALIFIED",
                        criteria_results={},
                    )
                    for company in companies
                ]
            )
            research_run_id = research_run.id
            source_company_ids = [company.id for company in companies]

        async def exploration_service_override():
            async with sessions() as session:
                yield ExplorationService(session, StaticObligationGenerator())

        app.dependency_overrides[get_exploration_service] = exploration_service_override

        provider = DeterministicLLMProvider(sessions)
        search_tool = DeterministicSearchTool()
        fetch_tool = DeterministicFetchTool()
        workflow = ExplorationWorkflow(
            session_factory=sessions,
            query_generator=ExplorationQueryGenerator(provider),
            search_service=ExplorationSearchService(search_tool, max_results=1),
            fetch_service=ExplorationFetchService(fetch_tool, concurrency=1),
            evidence_extractor=ExplorationEvidenceExtractor(provider, concurrency=1),
            fact_extractor=ExplorationFactExtractor(provider, concurrency=1),
            hypothesis_generator=ExplorationHypothesisGenerator(provider),
        )

        from virtual_company.api import exploration_execution

        monkeypatch.setattr(
            exploration_execution,
            "create_configured_exploration_workflow",
            lambda: workflow,
        )

        async def tracked_app(scope, receive, send):
            async def tracked_send(message):
                if (
                    scope["type"] == "http"
                    and scope.get("path", "").endswith("/execute")
                    and message["type"] == "http.response.body"
                ):
                    provider.timeline.append("execute_response_body")
                await send(message)

            await app(scope, receive, tracked_send)

        transport = ASGITransport(app=tracked_app)
        async with AsyncClient(
            transport=transport, base_url="http://phase5.test"
        ) as client:
            created = await client.post(
                "/api/v1/explorations",
                json={
                    "business_context": "Evaluate regional payment platform fit",
                    "max_obligations": 2,
                },
            )
            assert created.status_code == 201
            exploration_id = created.json()["id"]

            obligation_response = await client.get(
                f"/api/v1/explorations/{exploration_id}/obligations"
            )
            assert obligation_response.status_code == 200
            obligations = obligation_response.json()
            assert {item["description"] for item in obligations} == {
                "Assess the product offering",
                "Assess the target market",
            }

            run_response = await client.post(
                f"/api/v1/explorations/{exploration_id}/runs",
                json={
                    "research_run_id": str(research_run_id),
                    "company_ids": [str(item) for item in source_company_ids],
                },
            )
            assert run_response.status_code == 201
            run_id = UUID(run_response.json()["id"])
            provider.run_id = run_id
            assert run_response.json()["status"] == "READY"

            queued = await client.post(
                f"/api/v1/explorations/{exploration_id}/runs/{run_id}/execute"
            )
            assert queued.status_code == 202
            assert queued.json() == {
                "exploration_run_id": str(run_id),
                "status": "QUEUED",
            }

            status_response = await client.get(
                f"/api/v1/explorations/{exploration_id}/runs/{run_id}"
            )
            assert status_response.status_code == 200
            run_status = status_response.json()
            assert run_status["status"] == "COMPLETED"
            assert run_status["started_at"] is not None
            assert run_status["completed_at"] is not None
            assert datetime.fromisoformat(
                run_status["started_at"]
            ) <= datetime.fromisoformat(run_status["completed_at"])

            companies_response = await client.get(
                f"/api/v1/explorations/{exploration_id}/runs/{run_id}/companies"
            )
            assert companies_response.status_code == 200
            selected_companies = companies_response.json()
            assert len(selected_companies) == 2
            assert all(
                company["id"] != company["company_id"]
                for company in selected_companies
            )

            expected_pairs = {
                (company["name"], obligation["description"])
                for company in selected_companies
                for obligation in obligations
            }
            assert len(provider.query_inputs) == 4
            assert set(provider.query_inputs) == expected_pairs
            assert search_tool.calls == 4
            assert fetch_tool.calls == 4
            assert provider.response_counts["ExplorationQueryGenerationResult"] == 4
            assert provider.response_counts["ExtractedExplorationEvidenceItems"] == 4
            assert provider.response_counts["ExtractedExplorationFacts"] == 2
            assert provider.response_counts["ExtractedExplorationHypotheses"] == 2
            assert provider.first_provider_status == ExplorationRunStatus.RUNNING.value
            assert provider.timeline.index(
                "execute_response_body"
            ) < provider.timeline.index("provider_started")

            statements: list[str] = []

            def collect_sql(_conn, _cursor, statement, _parameters, _context, _many):
                statements.append(statement.casefold())

            event.listen(engine.sync_engine, "before_cursor_execute", collect_sql)
            try:
                for company in selected_companies:
                    company_link_id = company["id"]
                    evidence_response = await client.get(
                        f"/api/v1/explorations/{exploration_id}/companies/{company_link_id}/evidence"
                    )
                    facts_response = await client.get(
                        f"/api/v1/explorations/{exploration_id}/companies/{company_link_id}/facts"
                    )
                    hypotheses_response = await client.get(
                        f"/api/v1/explorations/{exploration_id}/companies/{company_link_id}/hypotheses"
                    )
                    assert evidence_response.status_code == 200
                    assert facts_response.status_code == 200
                    assert hypotheses_response.status_code == 200

                    evidence = evidence_response.json()
                    facts = facts_response.json()
                    hypotheses = hypotheses_response.json()
                    assert len(evidence) == 2
                    assert len(facts) == 2
                    assert len(hypotheses) == 1
                    assert {item["exploration_obligation_id"] for item in evidence} == {
                        obligation["id"] for obligation in obligations
                    }
                    evidence_ids = {item["id"] for item in evidence}
                    fact_ids = {item["id"] for item in facts}
                    assert all(
                        item["exploration_company_id"] == company_link_id
                        for item in [*evidence, *facts, *hypotheses]
                    )
                    assert all(
                        set(item["evidence_ids"]) <= evidence_ids for item in facts
                    )
                    assert all(set(item["fact_ids"]) <= fact_ids for item in hypotheses)
                    assert {
                        identifier
                        for item in facts
                        for identifier in item["evidence_ids"]
                    } == evidence_ids
                    assert set(hypotheses[0]["fact_ids"]) == fact_ids

                    mismatch = await client.get(
                        f"/api/v1/explorations/{uuid4()}/companies/{company_link_id}/facts"
                    )
                    assert mismatch.status_code == 404
            finally:
                event.remove(engine.sync_engine, "before_cursor_execute", collect_sql)

            assert sum("exploration_fact_evidence" in sql for sql in statements) == 2
            assert sum("exploration_hypothesis_fact" in sql for sql in statements) == 2

        async with sessions() as session:
            persisted_status = await session.scalar(
                select(ExplorationRun.status).where(ExplorationRun.id == run_id)
            )
            assert persisted_status == ExplorationRunStatus.COMPLETED.value
            selected_company_ids = select(ExplorationCompany.id).where(
                ExplorationCompany.exploration_run_id == run_id
            )
            evidence_count = await session.scalar(
                select(func.count(ExplorationEvidence.id)).where(
                    ExplorationEvidence.exploration_company_id.in_(
                        selected_company_ids
                    )
                )
            )
            facts_count = await session.scalar(
                select(func.count(ExplorationFact.id)).where(
                    ExplorationFact.exploration_company_id.in_(selected_company_ids)
                )
            )
            hypotheses_count = await session.scalar(
                select(func.count(ExplorationHypothesis.id)).where(
                    ExplorationHypothesis.exploration_company_id.in_(
                        selected_company_ids
                    )
                )
            )
            assert (evidence_count, facts_count, hypotheses_count) == (4, 4, 2)
    finally:
        app.dependency_overrides.clear()
        async with engine.begin() as connection:
            await connection.execute(DropSchema(schema, cascade=True, if_exists=True))
        await engine.dispose()
