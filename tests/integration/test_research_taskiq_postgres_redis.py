"""Real API-to-Redis receiver integration for the Research workflow."""

from __future__ import annotations

import asyncio
import os
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from redis.asyncio import BlockingConnectionPool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateSchema, DropSchema
from taskiq.receiver.receiver import Receiver

from virtual_company.api.dependencies import (
    get_research_results_service,
    get_research_service,
)
from virtual_company.config import Settings
from virtual_company.db import Base
from virtual_company.db.models import Campaign, ResearchRun, WorkflowExecution
from virtual_company.main import app
from virtual_company.services.research import ResearchService
from virtual_company.services.research_results import ResearchResultsService
from virtual_company.task_queue import tasks
from virtual_company.task_queue.adapters import research as research_adapter
from virtual_company.task_queue.broker import broker
from virtual_company.task_queue.reconciliation import reconcile_taskiq_runs_once
from virtual_company.task_queue.tasks import execute_workflow
from virtual_company.tools.web_search import SearchResponse
from virtual_company.workflows.research import graph as research_graph
from virtual_company.workflows.research.graph import ResearchWorkflow

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.getenv("RUN_RESEARCH_TASKIQ_TESTS") != "true",
        reason="Requires isolated PostgreSQL and Redis Taskiq services",
    ),
]


class _EmptyLLM:
    provider = "phase4-test"
    model = "empty-result"

    def __init__(self) -> None:
        self.calls = 0
        self.fail_next = False
        self.provider_started: asyncio.Event | None = None
        self.release_provider: asyncio.Event | None = None

    async def generate_structured(self, *, system_prompt, user_prompt, response_model):
        del system_prompt, user_prompt
        self.calls += 1
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("deterministic provider failure")
        if self.calls == 1 and self.provider_started is not None:
            self.provider_started.set()
            assert self.release_provider is not None
            await self.release_provider.wait()
        if response_model.__name__ == "GeneratedSearchQueries":
            return response_model(queries=["deterministic empty research query"])
        if response_model.__name__ == "DiscoveredCompanies":
            return response_model(companies=[])
        raise AssertionError(f"Unexpected Research provider operation: {response_model.__name__}")


class _EmptySearch:
    provider = "phase4-test"

    async def search(self, _query: str, limit: int = 10) -> SearchResponse:
        assert limit > 0
        return SearchResponse(results=[])


class _UnusedFetch:
    async def fetch(self, _url: str):
        raise AssertionError("Empty result workflow must not fetch company pages")


async def test_research_api_redis_receiver_graph_and_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = os.getenv("TASKIQ_TEST_DATABASE_URL")
    redis_url = os.getenv("TASKIQ_TEST_REDIS_URL")
    if not database_url or not redis_url:
        pytest.skip("TASKIQ_TEST_DATABASE_URL and TASKIQ_TEST_REDIS_URL are required")
    if "test" not in database_url.rsplit("/", 1)[-1].lower():
        pytest.fail("Refusing to use a PostgreSQL database without 'test' in its name")

    schema = f"research_taskiq_e2e_{uuid4().hex}"
    engine = create_async_engine(database_url)
    scoped_engine = engine.execution_options(schema_translate_map={None: schema})
    sessions = async_sessionmaker(scoped_engine, expire_on_commit=False)
    original_overrides = dict(app.dependency_overrides)
    previous_pool = broker.connection_pool
    previous_queue = broker.queue_name
    previous_group = broker.consumer_group_name
    previous_create_engine = tasks.create_async_engine
    previous_sessionmaker = tasks.async_sessionmaker
    previous_worker_process = broker.is_worker_process
    await broker.shutdown()
    broker.connection_pool = BlockingConnectionPool.from_url(redis_url)
    broker.queue_name = f"phase4-research-{uuid4().hex}"
    broker.consumer_group_name = f"phase4-research-workers-{uuid4().hex}"
    await broker.startup()
    try:
        async with engine.begin() as connection:
            await connection.execute(CreateSchema(schema))
        async with scoped_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with sessions.begin() as session:
            campaign = Campaign(
                name="Taskiq Research E2E",
                keywords=["empty"],
                target_count=1,
                max_companies_to_research=1,
                status="DRAFT",
            )
            session.add(campaign)
            await session.flush()
            campaign_id = campaign.id

        llm = _EmptyLLM()
        provider_started = asyncio.Event()
        release_provider = asyncio.Event()
        llm.provider_started = provider_started
        llm.release_provider = release_provider

        def configured(*, campaigns, research):
            return ResearchWorkflow(
                campaigns=campaigns,
                research=research,
                research_llm=llm,
                extraction_llm=llm,
                web_search=_EmptySearch(),
                web_fetch=_UnusedFetch(),
            )

        monkeypatch.setattr(
            research_graph, "create_configured_research_workflow", configured
        )
        lifecycle_settings = Settings(
            taskiq_heartbeat_interval_seconds=1,
            taskiq_running_stale_after_seconds=4,
            taskiq_queued_stale_after_seconds=30,
            taskiq_reconciliation_interval_seconds=1,
        )
        monkeypatch.setattr(research_adapter, "get_settings", lambda: lifecycle_settings)
        monkeypatch.setattr(tasks, "create_async_engine", lambda *_a, **_k: scoped_engine)
        monkeypatch.setattr(tasks, "async_sessionmaker", lambda *_a, **_k: sessions)

        async def research_service_override():
            async with sessions() as session:
                yield ResearchService(session)

        async def results_service_override():
            async with sessions() as session:
                yield ResearchResultsService(session)

        app.dependency_overrides.clear()
        app.dependency_overrides[get_research_service] = research_service_override
        app.dependency_overrides[get_research_results_service] = results_service_override

        finish = asyncio.Event()
        broker.is_worker_process = True
        receiver = Receiver(broker, run_startup=True, propagate_exceptions=True)
        receiver_task = asyncio.create_task(receiver.listen(finish))
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://phase4-research.test"
            ) as client:
                queued = await client.post(f"/api/v1/campaigns/{campaign_id}/research")
                assert queued.status_code == 202
                assert queued.json()["status"] == "QUEUED"
                run_id = UUID(queued.json()["research_run_id"])

                await asyncio.wait_for(provider_started.wait(), timeout=10)
                heartbeat_values = []
                for _ in range(12):
                    async with sessions() as session:
                        heartbeat_values.append(
                            await session.scalar(
                                select(WorkflowExecution.heartbeat_at).where(
                                    WorkflowExecution.workflow_type == "research",
                                    WorkflowExecution.run_id == run_id,
                                )
                            )
                        )
                    await asyncio.sleep(0.2)
                distinct_heartbeats = set(heartbeat_values)
                assert len(distinct_heartbeats) >= 2
                reconciliation = await reconcile_taskiq_runs_once(
                    sessions, lifecycle_settings
                )
                assert reconciliation.running_failed == 0
                await execute_workflow.kiq("research", str(run_id))
                await execute_workflow.kiq("research", str(run_id))
                await asyncio.sleep(0.3)
                assert llm.calls == 1
                release_provider.set()

                deadline = asyncio.get_running_loop().time() + 30
                status_value = "QUEUED"
                while asyncio.get_running_loop().time() < deadline:
                    async with sessions() as session:
                        status_value = await session.scalar(
                            select(ResearchRun.status).where(ResearchRun.id == run_id)
                        )
                    if status_value in {"COMPLETED", "FAILED"}:
                        break
                    await asyncio.sleep(0.05)
                assert status_value == "COMPLETED"
                assert llm.calls == 2

                await execute_workflow.kiq("research", str(run_id))
                await execute_workflow.kiq("research", str(run_id))
                await asyncio.sleep(0.3)
                assert llm.calls == 2

                results = await client.get(f"/api/v1/research-runs/{run_id}/results")
                assert results.status_code == 200
                assert results.json()["research_run"]["status"] == "COMPLETED"
                assert results.json()["companies"] == []
                async with sessions() as session:
                    execution = await session.scalar(
                        select(WorkflowExecution).where(
                            WorkflowExecution.workflow_type == "research",
                            WorkflowExecution.run_id == run_id,
                        )
                    )
                    assert execution is not None
                    assert execution.status == "COMPLETED"

                async with sessions.begin() as session:
                    failed_campaign = Campaign(
                        name="Taskiq Research failure test",
                        keywords=[],
                        target_count=1,
                        max_companies_to_research=1,
                        status="DRAFT",
                    )
                    session.add(failed_campaign)
                    await session.flush()
                    failed_campaign_id = failed_campaign.id
                llm.fail_next = True
                failed_response = await client.post(
                    f"/api/v1/campaigns/{failed_campaign_id}/research"
                )
                assert failed_response.status_code == 202
                failed_run_id = UUID(failed_response.json()["research_run_id"])
                deadline = asyncio.get_running_loop().time() + 15
                failed_status = "QUEUED"
                while asyncio.get_running_loop().time() < deadline:
                    async with sessions() as session:
                        failed_status = await session.scalar(
                            select(ResearchRun.status).where(
                                ResearchRun.id == failed_run_id
                            )
                        )
                    if failed_status in {"COMPLETED", "FAILED"}:
                        break
                    await asyncio.sleep(0.05)
                assert failed_status == "FAILED"
                async with sessions() as session:
                    failed_run = await session.get(ResearchRun, failed_run_id)
                    failed_execution = await session.scalar(
                        select(WorkflowExecution).where(
                            WorkflowExecution.workflow_type == "research",
                            WorkflowExecution.run_id == failed_run_id,
                        )
                    )
                    assert failed_run.error == "Research workflow failed: RuntimeError"
                    assert failed_execution.status == "FAILED"
        finally:
            release_provider.set()
            finish.set()
            await asyncio.wait_for(receiver_task, timeout=10)
            broker.is_worker_process = False
    finally:
        await broker.shutdown()
        await broker.connection_pool.disconnect()
        broker.connection_pool = previous_pool
        broker.queue_name = previous_queue
        broker.consumer_group_name = previous_group
        broker.is_worker_process = previous_worker_process
        tasks.create_async_engine = previous_create_engine
        tasks.async_sessionmaker = previous_sessionmaker
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)
        async with engine.begin() as connection:
            await connection.execute(DropSchema(schema, cascade=True))
        await engine.dispose()
