"""Real PostgreSQL/Redis failure-path checks with isolated Taskiq workers."""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from redis.asyncio import BlockingConnectionPool, Redis
from sqlalchemy import event, func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateSchema, DropSchema

from virtual_company.api.dependencies import get_exploration_service
from virtual_company.config import Settings
from virtual_company.db import Base
from virtual_company.db.models import (
    Campaign,
    ExplorationCompany,
    ExplorationEvidence,
    ExplorationFact,
    ExplorationHypothesis,
    ExplorationObligation,
    ExplorationRun,
    ResearchCompany,
    ResearchCompanyQualification,
    ResearchRun,
    WorkflowExecution,
)
from virtual_company.domain.exploration.evidence import (
    ExplorationEvidence as DomainEvidence,
)
from virtual_company.domain.exploration.facts import ExplorationFact as DomainFact
from virtual_company.domain.exploration.hypotheses import (
    ExplorationHypothesis as DomainHypothesis,
)
from virtual_company.main import app
from virtual_company.repositories.workflow_execution import (
    ExecutionOwnershipLostError,
    WorkflowExecutionRepository,
)
from virtual_company.services.exploration import ExplorationService
from virtual_company.services.exploration_evidence_extractor import (
    ExplorationEvidenceExtractionBatchResult,
    ExplorationEvidenceExtractionOutcome,
    ExplorationEvidencePageResult,
)
from virtual_company.services.exploration_evidence_persistence import (
    ExplorationEvidencePersistenceService,
)
from virtual_company.services.exploration_hypothesis_generator import (
    ExplorationHypothesisGenerationOutcome,
    ExplorationHypothesisGenerationResult,
)
from virtual_company.services.obligation_generator import (
    GeneratedObligation,
    ObligationGenerationResult,
)
from virtual_company.task_queue.broker import broker
from virtual_company.task_queue.lifecycle import (
    claim_workflow_run,
    transition_workflow_run,
)
from virtual_company.task_queue.reconciliation import reconcile_taskiq_runs_once
from virtual_company.task_queue.workflow_types import WorkflowType
from virtual_company.workflows.exploration.models import (
    ExplorationFactExtractionBatchResult,
)
from virtual_company.workflows.exploration.nodes import ExplorationNodes

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.getenv("RUN_TASKIQ_FAILURE_PATH_TESTS") != "true",
        reason="Requires isolated PostgreSQL, Redis, and Taskiq worker subprocesses",
    ),
]


class _ObligationGenerator:
    async def generate(self, business_context: str, max_obligations: int):
        del business_context, max_obligations
        return ObligationGenerationResult(
            obligations=[
                GeneratedObligation(description="Assess product offering"),
                GeneratedObligation(description="Assess target market"),
            ]
        )


class _WorkerHarness:
    def __init__(self, process: subprocess.Popen[bytes], log_file) -> None:
        self.process = process
        self.log_file = log_file

    def logs(self) -> str:
        self.log_file.flush()
        return Path(self.log_file.name).read_text(encoding="utf-8", errors="replace")

    def kill_group(self, signum: int = signal.SIGTERM) -> None:
        if self.process.poll() is None:
            with suppress(ProcessLookupError):
                os.killpg(self.process.pid, signum)
            try:
                self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                with suppress(ProcessLookupError):
                    os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait(timeout=8)
        self.log_file.close()


@asynccontextmanager
async def _isolated_runtime(tmp_path: Path) -> AsyncIterator[dict[str, object]]:
    database_url = os.getenv("TASKIQ_TEST_DATABASE_URL") or os.getenv(
        "EXPLORATION_TEST_DATABASE_URL"
    )
    redis_url = os.getenv("TASKIQ_TEST_REDIS_URL")
    if not database_url or not redis_url:
        pytest.skip(
            "Dedicated TASKIQ_TEST_DATABASE_URL and TASKIQ_TEST_REDIS_URL are required"
        )
    if "test" not in database_url.rsplit("/", 1)[-1].lower():
        pytest.fail("Refusing to use a PostgreSQL database without 'test' in its name")

    schema = f"phase3_failure_{uuid4().hex}"
    engine = create_async_engine(database_url)
    scoped_engine = engine.execution_options(schema_translate_map={None: schema})
    pool_before = broker.connection_pool
    queue_before = broker.queue_name
    group_before = broker.consumer_group_name
    original_overrides = dict(app.dependency_overrides)
    workers: list[_WorkerHarness] = []
    await broker.shutdown()
    broker.connection_pool = BlockingConnectionPool.from_url(redis_url)
    broker.queue_name = f"phase3-failure-{uuid4().hex}"
    broker.consumer_group_name = f"phase3-failure-workers-{uuid4().hex}"

    async def service_override():
        async with runtime["sessions"]() as session:
            yield ExplorationService(session, _ObligationGenerator())

    runtime: dict[str, object] = {}
    try:
        async with engine.begin() as connection:
            await connection.execute(CreateSchema(schema))
        async with scoped_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(scoped_engine, expire_on_commit=False)
        runtime.update(
            {
                "schema": schema,
                "engine": engine,
                "sessions": sessions,
                "database_url": database_url,
                "redis_url": redis_url,
                "markers": tmp_path / "provider-markers",
                "release": tmp_path / "provider.release",
                "workers": workers,
            }
        )
        app.dependency_overrides.clear()
        app.dependency_overrides[get_exploration_service] = service_override
        await broker.startup()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://phase3-failure.test"
        ) as client:
            runtime["client"] = client
            yield runtime
    finally:
        runtime["client"] = None
        for worker in workers:
            worker.kill_group()
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)
        await broker.shutdown()
        await broker.connection_pool.disconnect()
        broker.connection_pool = pool_before
        broker.queue_name = queue_before
        broker.consumer_group_name = group_before
        async with engine.begin() as connection:
            await connection.execute(DropSchema(schema, cascade=True, if_exists=True))
        await engine.dispose()


async def _create_run(
    runtime: dict[str, object], *, company_count: int = 2
) -> tuple[UUID, UUID, list[UUID]]:
    sessions = runtime["sessions"]
    async with sessions.begin() as session:
        campaign = Campaign(
            name="Failure path campaign",
            keywords=[],
            target_count=company_count,
            max_companies_to_research=company_count,
            status="COMPLETED",
        )
        session.add(campaign)
        await session.flush()
        research_run = ResearchRun(
            campaign_id=campaign.id, status="COMPLETED", companies_found=company_count
        )
        companies = [
            ResearchCompany(
                name=f"Failure Company {index}", domain=f"fail-{index}.test"
            )
            for index in range(company_count)
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
        company_ids = [company.id for company in companies]

    client = runtime["client"]
    created = await client.post(
        "/api/v1/explorations",
        json={"business_context": "Assess payment services", "max_obligations": 2},
    )
    assert created.status_code == 201
    exploration_id = UUID(created.json()["id"])
    started = await client.post(
        f"/api/v1/explorations/{exploration_id}/runs",
        json={
            "research_run_id": str(research_run_id),
            "company_ids": [str(i) for i in company_ids],
        },
    )
    assert started.status_code == 201
    return exploration_id, UUID(started.json()["id"]), company_ids


def _start_worker(
    runtime: dict[str, object],
    tmp_path: Path,
    *,
    worker_id: str,
    block_company: str | None = None,
    fail_company: str | None = None,
    block_query_call: int | None = None,
    empty: bool = False,
) -> _WorkerHarness:
    marker_dir = runtime["markers"]
    marker_dir.mkdir(parents=True, exist_ok=True)
    log_path = tmp_path / f"{worker_id}.log"
    log_file = log_path.open("wb")
    environment = os.environ.copy()
    environment.update(
        {
            "DATABASE_URL": runtime["database_url"],
            "TASKIQ_REDIS_URL": runtime["redis_url"],
            "TASKIQ_STREAM_NAME": broker.queue_name,
            "TASKIQ_CONSUMER_GROUP": broker.consumer_group_name,
            "TASKIQ_HEARTBEAT_INTERVAL_SECONDS": "1",
            "TASKIQ_RUNNING_STALE_AFTER_SECONDS": "5",
            "TASKIQ_RECONCILIATION_INTERVAL_SECONDS": "1",
            "TASKIQ_QUEUED_STALE_AFTER_SECONDS": "30",
            "PHASE3_WORKER_SCHEMA": runtime["schema"],
            "PHASE3_WORKER_MARKER_DIR": str(marker_dir),
            "PHASE3_WORKER_RELEASE_FILE": str(runtime["release"]),
        }
    )
    if block_company:
        environment["PHASE3_WORKER_BLOCK_COMPANY"] = block_company
    if fail_company:
        environment["PHASE3_WORKER_FAIL_COMPANY"] = fail_company
    if block_query_call:
        environment["PHASE3_WORKER_BLOCK_QUERY_CALL"] = str(block_query_call)
    if empty:
        environment["PHASE3_WORKER_EMPTY"] = "true"
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "taskiq",
            "worker",
            "virtual_company.task_queue.broker:broker",
            "virtual_company.task_queue.tasks",
            "tests.integration.taskiq_worker_bootstrap",
            "--workers",
            "1",
            "--max-async-tasks",
            "1",
            "--max-prefetch",
            "0",
            "--ack-type",
            "when_executed",
            "--shutdown-timeout",
            "10",
            "--wait-tasks-timeout",
            "10",
            "--no-configure-logging",
        ],
        cwd=Path(__file__).resolve().parents[2],
        env=environment,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    worker = _WorkerHarness(process, log_file)
    runtime["workers"].append(worker)
    return worker


async def _eventually(check, *, timeout: float = 20, interval: float = 0.05):
    deadline = asyncio.get_running_loop().time() + timeout
    last = None
    while asyncio.get_running_loop().time() < deadline:
        last = await check()
        if last:
            return last
        await asyncio.sleep(interval)
    raise AssertionError(f"condition not met within {timeout}s; last={last!r}")


async def _wait_worker_ready(worker: _WorkerHarness) -> None:
    async def ready() -> bool:
        if worker.process.poll() is not None:
            raise AssertionError(f"worker exited early: {worker.logs()}")
        return "Listening started." in worker.logs()

    await _eventually(ready)


async def _wait_marker(path: Path) -> None:
    await _eventually(lambda: asyncio.sleep(0, result=path.exists()))


async def _statuses(sessions, run_id: UUID):
    async with sessions() as session:
        run = await session.scalar(
            select(ExplorationRun).where(ExplorationRun.id == run_id)
        )
        execution = await session.scalar(
            select(WorkflowExecution).where(
                WorkflowExecution.workflow_type == "exploration",
                WorkflowExecution.run_id == run_id,
            )
        )
        return (
            run.status if run else None,
            execution.status if execution else None,
            execution.heartbeat_at if execution else None,
            execution.id if execution else None,
        )


async def _execute_api(runtime: dict[str, object], exploration_id: UUID, run_id: UUID):
    response = await runtime["client"].post(
        f"/api/v1/explorations/{exploration_id}/runs/{run_id}/execute"
    )
    assert response.status_code == 202
    return response


async def _result_counts(sessions, run_id: UUID) -> tuple[int, int, int]:
    async with sessions() as session:
        company_ids = select(ExplorationCompany.id).where(
            ExplorationCompany.exploration_run_id == run_id
        )
        counts = []
        for model in (ExplorationEvidence, ExplorationFact, ExplorationHypothesis):
            counts.append(
                await session.scalar(
                    select(func.count(model.id)).where(
                        model.exploration_company_id.in_(company_ids)
                    )
                )
            )
        return tuple(counts)


async def _wait_terminal(sessions, run_id: UUID, expected: str) -> None:
    async def done() -> bool:
        run_status, execution_status, *_ = await _statuses(sessions, run_id)
        return run_status == expected and execution_status == expected

    await _eventually(done)


async def _terminal_settings() -> Settings:
    return Settings(
        taskiq_heartbeat_interval_seconds=1,
        taskiq_running_stale_after_seconds=5,
        taskiq_queued_stale_after_seconds=30,
        taskiq_reconciliation_interval_seconds=1,
    )


async def _claim_running(runtime, exploration_id: UUID, run_id: UUID) -> UUID:
    sessions = runtime["sessions"]
    async with sessions() as session:
        queued = await ExplorationService(
            session, _ObligationGenerator()
        ).claim_run_for_execution(exploration_id, run_id)
    assert queued is not None and queued.outcome.value == "CLAIMED"
    return await _claim_execution(runtime, run_id)


async def _claim_execution(runtime, run_id: UUID) -> UUID:
    claim = await claim_workflow_run(
        runtime["sessions"], WorkflowType.EXPLORATION, run_id
    )
    assert claim.execution_id is not None
    return claim.execution_id


async def _persistence_nodes(runtime):
    return ExplorationNodes(
        runtime["sessions"],
        query_generator=None,
        search_service=None,
        fetch_service=None,
        evidence_extractor=None,
        fact_extractor=None,
        hypothesis_generator=None,
    )


async def _persistence_state(runtime, run_id: UUID, execution_id: UUID):
    async with runtime["sessions"]() as session:
        link = await session.scalar(
            select(ExplorationCompany).where(
                ExplorationCompany.exploration_run_id == run_id
            )
        )
        run = await session.get(ExplorationRun, run_id)
        assert link is not None and run is not None
        obligation = await session.scalar(
            select(ExplorationObligation).where(
                ExplorationObligation.exploration_id == run.exploration_id
            )
        )
        assert obligation is not None
    evidence = DomainEvidence(
        exploration_run_id=run_id,
        exploration_company_id=link.id,
        company_id=link.company_id,
        exploration_obligation_id=obligation.id,
        claim="A test claim",
        supporting_excerpt="A supported test excerpt",
        query="test query",
        search_result_url="https://source.example.test/page",
        search_result_title="Test source",
        source_url="https://source.example.test/page",
    )
    evidence_batch = ExplorationEvidenceExtractionBatchResult(
        provider="deterministic",
        model="test",
        results=[
            ExplorationEvidencePageResult(
                query="test query",
                search_result_url="https://source.example.test/page",
                search_result_title="Test source",
                source_url="https://source.example.test/page",
                outcome=ExplorationEvidenceExtractionOutcome.SUCCEEDED,
                evidence=[evidence],
            )
        ],
    )
    fact = DomainFact(
        exploration_company_id=link.id,
        statement="A test company fact",
        evidence_ids=(uuid4(),),
    )
    fact_batch = ExplorationFactExtractionBatchResult(
        exploration_company_id=link.id,
        provider="deterministic",
        model="test",
        outcomes=[],
        facts=[fact],
    )
    hypothesis = DomainHypothesis(
        exploration_company_id=link.id,
        statement="A test hypothesis",
        fact_ids=(uuid4(),),
    )
    hypothesis_result = ExplorationHypothesisGenerationResult(
        outcome=ExplorationHypothesisGenerationOutcome.SUCCEEDED,
        hypotheses=(hypothesis,),
    )
    return {
        "exploration_run_id": run_id,
        "workflow_execution_id": execution_id,
        "evidence_result": evidence_batch,
        "fact_result": fact_batch,
        "hypothesis_result": hypothesis_result,
        "evidence_persisted_count": 0,
        "facts_persisted_count": 0,
        "hypotheses_persisted_count": 0,
    }


async def _wait_for_postgres_lock(runtime, *, statement_fragment: str) -> None:
    async def locked():
        async with runtime["sessions"]() as session:
            count = await session.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() AND wait_event_type = 'Lock' "
                    "AND query ILIKE :pattern"
                ),
                {"pattern": f"%{statement_fragment}%"},
            )
            return count > 0

    await _eventually(locked, timeout=10)


async def test_separate_worker_sigkill_reconciles_and_rejects_redelivery(tmp_path):
    async with _isolated_runtime(tmp_path) as runtime:
        exploration_id, run_id, _company_ids = await _create_run(runtime)
        worker = _start_worker(
            runtime, tmp_path, worker_id="crash-worker", block_query_call=3
        )
        await _wait_worker_ready(worker)
        await _execute_api(runtime, exploration_id, run_id)
        await _wait_marker(runtime["markers"] / "provider-blocked.txt")

        run_status, execution_status, first_heartbeat, execution_id = await _statuses(
            runtime["sessions"], run_id
        )
        assert (run_status, execution_status) == ("RUNNING", "RUNNING")
        assert execution_id is not None and first_heartbeat is not None
        assert await _result_counts(runtime["sessions"], run_id) != (0, 0, 0)

        async def heartbeat_advanced():
            *_, current, _execution_id = await _statuses(runtime["sessions"], run_id)
            return current is not None and current > first_heartbeat

        await _eventually(heartbeat_advanced)
        graph_worker_pid = int(
            (runtime["markers"] / "graph-started.txt")
            .read_text(encoding="utf-8")
            .splitlines()[0]
        )
        assert os.getpgid(graph_worker_pid) == worker.process.pid
        os.kill(graph_worker_pid, signal.SIGKILL)
        os.killpg(worker.process.pid, signal.SIGKILL)
        worker.process.wait(timeout=8)
        worker.log_file.close()

        await asyncio.sleep(1.2)
        stopped_heartbeat = (await _statuses(runtime["sessions"], run_id))[2]
        await asyncio.sleep(1.2)
        assert (await _statuses(runtime["sessions"], run_id))[2] == stopped_heartbeat
        reconciled = await reconcile_taskiq_runs_once(
            runtime["sessions"],
            await _terminal_settings(),
            now=datetime.now(UTC) + timedelta(seconds=10),
        )
        assert reconciled.running_failed == 1
        assert (await _statuses(runtime["sessions"], run_id))[:2] == (
            "FAILED",
            "FAILED",
        )
        before = await _result_counts(runtime["sessions"], run_id)
        assert before != (0, 0, 0)

        restarted = _start_worker(runtime, tmp_path, worker_id="restart-worker")
        await _wait_worker_ready(restarted)
        from virtual_company.task_queue.tasks import execute_workflow

        await execute_workflow.kiq("exploration", str(run_id))
        await asyncio.sleep(0.5)
        assert restarted.process.poll() is None
        assert (
            len((runtime["markers"] / "graph-started.txt").read_text().splitlines())
            == 1
        )
        assert await _result_counts(runtime["sessions"], run_id) == before
        assert (await _statuses(runtime["sessions"], run_id))[:2] == (
            "FAILED",
            "FAILED",
        )


async def test_heartbeat_advances_during_provider_wait_and_reconciliation(tmp_path):
    async with _isolated_runtime(tmp_path) as runtime:
        exploration_id, run_id, _company_ids = await _create_run(
            runtime, company_count=1
        )
        worker = _start_worker(
            runtime,
            tmp_path,
            worker_id="heartbeat-worker",
            block_company="Failure Company 0",
        )
        await _wait_worker_ready(worker)
        await _execute_api(runtime, exploration_id, run_id)
        await _wait_marker(runtime["markers"] / "provider-blocked.txt")

        _, _, initial, _ = await _statuses(runtime["sessions"], run_id)
        assert initial is not None
        advanced: set[datetime] = set()

        async def collect_updates():
            _, _, current, _ = await _statuses(runtime["sessions"], run_id)
            if current and current > initial:
                advanced.add(current)
            return len(advanced) >= 2

        await _eventually(collect_updates, timeout=12)
        result = await reconcile_taskiq_runs_once(
            runtime["sessions"], await _terminal_settings(), now=datetime.now(UTC)
        )
        assert result.running_failed == 0
        assert (await _statuses(runtime["sessions"], run_id))[:2] == (
            "RUNNING",
            "RUNNING",
        )
        runtime["release"].touch()
        await _wait_terminal(runtime["sessions"], run_id, "COMPLETED")


async def test_concurrent_duplicate_messages_start_one_graph(tmp_path):
    async with _isolated_runtime(tmp_path) as runtime:
        exploration_id, run_id, _company_ids = await _create_run(
            runtime, company_count=1
        )
        workers = [
            _start_worker(
                runtime,
                tmp_path,
                worker_id=f"duplicate-worker-{index}",
                block_company="Failure Company 0",
            )
            for index in range(2)
        ]
        for worker in workers:
            await _wait_worker_ready(worker)
        await _execute_api(runtime, exploration_id, run_id)
        await _wait_marker(runtime["markers"] / "provider-blocked.txt")

        from virtual_company.task_queue.tasks import execute_workflow

        await execute_workflow.kiq("exploration", str(run_id))
        client = Redis.from_url(runtime["redis_url"])
        try:

            async def duplicate_acknowledged():
                pending = await client.xpending(
                    broker.queue_name, broker.consumer_group_name
                )
                return pending["pending"] == 1

            await _eventually(duplicate_acknowledged)
        finally:
            await client.aclose()
        assert (
            len((runtime["markers"] / "graph-started.txt").read_text().splitlines())
            == 1
        )
        runtime["release"].touch()
        await _wait_terminal(runtime["sessions"], run_id, "COMPLETED")
        assert await _result_counts(runtime["sessions"], run_id) == (2, 1, 1)
        assert all(worker.process.poll() is None for worker in workers)


async def test_real_partial_outcome_preserves_successful_company_results(tmp_path):
    async with _isolated_runtime(tmp_path) as runtime:
        exploration_id, run_id, _company_ids = await _create_run(runtime)
        worker = _start_worker(
            runtime,
            tmp_path,
            worker_id="partial-worker",
            fail_company="Failure Company 1",
        )
        await _wait_worker_ready(worker)
        await _execute_api(runtime, exploration_id, run_id)
        await _wait_terminal(runtime["sessions"], run_id, "PARTIAL")
        assert await _result_counts(runtime["sessions"], run_id) == (2, 1, 1)
        companies = (
            await runtime["client"].get(
                f"/api/v1/explorations/{exploration_id}/runs/{run_id}/companies"
            )
        ).json()
        alpha = next(item for item in companies if item["name"] == "Failure Company 0")
        beta = next(item for item in companies if item["name"] == "Failure Company 1")
        alpha_results = await runtime["client"].get(
            f"/api/v1/explorations/{exploration_id}/companies/{alpha['id']}/evidence"
        )
        beta_results = await runtime["client"].get(
            f"/api/v1/explorations/{exploration_id}/companies/{beta['id']}/evidence"
        )
        assert alpha_results.status_code == beta_results.status_code == 200
        evidence = alpha_results.json()
        assert len(evidence) == 2
        assert beta_results.json() == []
        facts = (
            await runtime["client"].get(
                f"/api/v1/explorations/{exploration_id}/companies/{alpha['id']}/facts"
            )
        ).json()
        hypotheses = (
            await runtime["client"].get(
                f"/api/v1/explorations/{exploration_id}/companies/{alpha['id']}/hypotheses"
            )
        ).json()
        assert len(facts) == len(hypotheses) == 1
        evidence_ids = {item["id"] for item in evidence}
        assert set(facts[0]["evidence_ids"]) <= evidence_ids
        assert facts[0]["evidence_ids"]
        assert set(hypotheses[0]["fact_ids"]) == {facts[0]["id"]}


async def test_real_valid_empty_result_completes_with_empty_result_apis(tmp_path):
    async with _isolated_runtime(tmp_path) as runtime:
        exploration_id, run_id, _company_ids = await _create_run(
            runtime, company_count=1
        )
        worker = _start_worker(runtime, tmp_path, worker_id="empty-worker", empty=True)
        await _wait_worker_ready(worker)
        await _execute_api(runtime, exploration_id, run_id)
        await _wait_terminal(runtime["sessions"], run_id, "COMPLETED")
        assert await _result_counts(runtime["sessions"], run_id) == (0, 0, 0)
        companies = (
            await runtime["client"].get(
                f"/api/v1/explorations/{exploration_id}/runs/{run_id}/companies"
            )
        ).json()
        company_id = companies[0]["id"]
        for result_type in ("evidence", "facts", "hypotheses"):
            response = await runtime["client"].get(
                f"/api/v1/explorations/{exploration_id}/companies/{company_id}/{result_type}"
            )
            assert response.status_code == 200
            assert response.json() == []


async def test_graph_persistence_stages_reject_lost_execution_ownership(tmp_path):
    async with _isolated_runtime(tmp_path) as runtime:
        exploration_id, run_id, _company_ids = await _create_run(
            runtime, company_count=1
        )
        execution_id = await _claim_running(runtime, exploration_id, run_id)
        nodes = await _persistence_nodes(runtime)
        state = await _persistence_state(runtime, run_id, execution_id)

        await nodes.persist_evidence(state)
        async with runtime["sessions"]() as session:
            evidence_id = await session.scalar(
                select(ExplorationEvidence.id)
                .join(
                    ExplorationCompany,
                    ExplorationEvidence.exploration_company_id == ExplorationCompany.id,
                )
                .where(ExplorationCompany.exploration_run_id == run_id)
            )
        assert evidence_id is not None
        state["fact_result"].facts[0] = DomainFact(
            exploration_company_id=state["fact_result"].exploration_company_id,
            statement="A test company fact",
            evidence_ids=(evidence_id,),
        )
        await nodes.persist_facts(state)
        async with runtime["sessions"]() as session:
            fact_id = await session.scalar(
                select(ExplorationFact.id)
                .join(
                    ExplorationCompany,
                    ExplorationFact.exploration_company_id == ExplorationCompany.id,
                )
                .where(ExplorationCompany.exploration_run_id == run_id)
            )
        assert fact_id is not None
        state["hypothesis_result"] = ExplorationHypothesisGenerationResult(
            outcome=ExplorationHypothesisGenerationOutcome.SUCCEEDED,
            hypotheses=(
                DomainHypothesis(
                    exploration_company_id=state["fact_result"].exploration_company_id,
                    statement="A test hypothesis",
                    fact_ids=(fact_id,),
                ),
            ),
        )
        await nodes.persist_hypotheses(state)
        committed_counts = await _result_counts(runtime["sessions"], run_id)
        assert committed_counts == (1, 1, 1)

        await reconcile_taskiq_runs_once(
            runtime["sessions"],
            await _terminal_settings(),
            now=datetime.now(UTC) + timedelta(seconds=10),
        )
        assert (await _statuses(runtime["sessions"], run_id))[:2] == (
            "FAILED",
            "FAILED",
        )

        for persist in (
            nodes.persist_evidence,
            nodes.persist_facts,
            nodes.persist_hypotheses,
        ):
            with pytest.raises(ExecutionOwnershipLostError):
                await persist(state)
        assert await _result_counts(runtime["sessions"], run_id) == committed_counts


async def test_postgres_persistence_and_reconciliation_lock_orderings(
    tmp_path, monkeypatch
):
    async with _isolated_runtime(tmp_path) as runtime:
        settings = await _terminal_settings()
        nodes = await _persistence_nodes(runtime)

        # Persistence locks ownership first; reconciliation waits until the write commits.
        exploration_id, run_id, _ = await _create_run(runtime, company_count=1)
        execution_id = await _claim_running(runtime, exploration_id, run_id)
        state = await _persistence_state(runtime, run_id, execution_id)
        ownership_locked = asyncio.Event()
        release_persistence = asyncio.Event()
        original_persist = ExplorationEvidencePersistenceService.persist

        async def held_persist(service, batch):
            ownership_locked.set()
            await release_persistence.wait()
            return await original_persist(service, batch)

        monkeypatch.setattr(
            ExplorationEvidencePersistenceService, "persist", held_persist
        )
        persistence_task = asyncio.create_task(nodes.persist_evidence(state))
        await asyncio.wait_for(ownership_locked.wait(), timeout=10)
        reconciliation_task = asyncio.create_task(
            reconcile_taskiq_runs_once(
                runtime["sessions"],
                settings,
                now=datetime.now(UTC) + timedelta(seconds=10),
            )
        )
        await _wait_for_postgres_lock(runtime, statement_fragment="workflow_execution")
        release_persistence.set()
        await asyncio.wait_for(persistence_task, timeout=10)
        reconciled = await asyncio.wait_for(reconciliation_task, timeout=10)
        assert reconciled.running_failed == 1
        assert (await _statuses(runtime["sessions"], run_id))[:2] == (
            "FAILED",
            "FAILED",
        )
        assert await _result_counts(runtime["sessions"], run_id) == (1, 0, 0)

        # Reconciliation owns the row first; a later graph-node persistence is rejected.
        monkeypatch.setattr(
            ExplorationEvidencePersistenceService, "persist", original_persist
        )
        exploration_id, run_id, _ = await _create_run(runtime, company_count=1)
        execution_id = await _claim_running(runtime, exploration_id, run_id)
        state = await _persistence_state(runtime, run_id, execution_id)
        stale_updated = asyncio.Event()
        release_reconciliation = asyncio.Event()
        original_fail_stale = WorkflowExecutionRepository.fail_stale

        async def held_fail_stale(repository, **kwargs):
            result = await original_fail_stale(repository, **kwargs)
            stale_updated.set()
            await release_reconciliation.wait()
            return result

        monkeypatch.setattr(WorkflowExecutionRepository, "fail_stale", held_fail_stale)
        reconciliation_task = asyncio.create_task(
            reconcile_taskiq_runs_once(
                runtime["sessions"],
                settings,
                now=datetime.now(UTC) + timedelta(seconds=10),
            )
        )
        await asyncio.wait_for(stale_updated.wait(), timeout=10)
        persistence_task = asyncio.create_task(nodes.persist_evidence(state))
        await _wait_for_postgres_lock(runtime, statement_fragment="workflow_execution")
        release_reconciliation.set()
        result = await asyncio.wait_for(reconciliation_task, timeout=10)
        assert result.running_failed == 1
        with pytest.raises(ExecutionOwnershipLostError):
            await asyncio.wait_for(persistence_task, timeout=10)
        assert (await _statuses(runtime["sessions"], run_id))[:2] == (
            "FAILED",
            "FAILED",
        )
        assert await _result_counts(runtime["sessions"], run_id) == (0, 0, 0)


async def test_postgres_lifecycle_failure_boundaries_roll_back_both_rows(tmp_path):
    async with _isolated_runtime(tmp_path) as runtime:
        sync_engine = runtime["sessions"].kw["bind"].sync_engine

        def inject_failure(fragment: str):
            def fail(_connection, _cursor, statement, _parameters, _context, _many):
                normalized = statement.casefold()
                is_insert_failure = fragment == "insert workflow_execution" and (
                    normalized.lstrip().startswith("insert")
                    and "workflow_execution" in normalized
                )
                is_run_update_failure = fragment == "update exploration_run" and (
                    normalized.lstrip().startswith("update")
                    and "exploration_run" in normalized
                )
                if is_insert_failure or is_run_update_failure:
                    raise RuntimeError(f"injected database failure at {fragment}")

            event.listen(sync_engine, "before_cursor_execute", fail)

            return fail

        def remove_failure(callback):
            event.remove(sync_engine, "before_cursor_execute", callback)

        exploration_id, run_id, _ = await _create_run(runtime, company_count=1)
        failed_insert = inject_failure("insert workflow_execution")
        with pytest.raises(RuntimeError, match="injected database failure"):
            async with runtime["sessions"]() as session:
                await ExplorationService(
                    session, _ObligationGenerator()
                ).claim_run_for_execution(exploration_id, run_id)
        remove_failure(failed_insert)
        assert (await _statuses(runtime["sessions"], run_id))[:2] == ("READY", None)

        async with runtime["sessions"]() as session:
            prepared = await ExplorationService(
                session, _ObligationGenerator()
            ).claim_run_for_execution(exploration_id, run_id)
        assert prepared is not None and prepared.outcome.value == "CLAIMED"
        assert (await _statuses(runtime["sessions"], run_id))[:2] == (
            "QUEUED",
            "QUEUED",
        )

        failed_claim = inject_failure("update exploration_run")
        with pytest.raises(RuntimeError, match="injected database failure"):
            await claim_workflow_run(
                runtime["sessions"], WorkflowType.EXPLORATION, run_id
            )
        remove_failure(failed_claim)
        assert (await _statuses(runtime["sessions"], run_id))[:2] == (
            "QUEUED",
            "QUEUED",
        )

        claim = await claim_workflow_run(
            runtime["sessions"], WorkflowType.EXPLORATION, run_id
        )
        assert claim.execution_id is not None
        execution_id = claim.execution_id
        failed_terminal = inject_failure("update exploration_run")
        with pytest.raises(RuntimeError, match="injected database failure"):
            await transition_workflow_run(
                runtime["sessions"],
                WorkflowType.EXPLORATION,
                run_id,
                execution_id,
                "PARTIAL",
            )
        remove_failure(failed_terminal)
        assert (await _statuses(runtime["sessions"], run_id))[:2] == (
            "RUNNING",
            "RUNNING",
        )
        assert await transition_workflow_run(
            runtime["sessions"],
            WorkflowType.EXPLORATION,
            run_id,
            execution_id,
            "PARTIAL",
        )
        assert (await _statuses(runtime["sessions"], run_id))[:2] == (
            "PARTIAL",
            "PARTIAL",
        )

        for terminal in ("CANCELLED", "FAILED"):
            exploration_id, run_id, _ = await _create_run(runtime, company_count=1)
            async with runtime["sessions"]() as session:
                await ExplorationService(
                    session, _ObligationGenerator()
                ).claim_run_for_execution(exploration_id, run_id)
            execution_id = await _claim_execution(runtime, run_id)
            assert await transition_workflow_run(
                runtime["sessions"],
                WorkflowType.EXPLORATION,
                run_id,
                execution_id,
                terminal,
            )
            assert (await _statuses(runtime["sessions"], run_id))[:2] == (
                terminal,
                terminal,
            )

        # A database failure after execution staleness is written rolls both updates back.
        exploration_id, run_id, _ = await _create_run(runtime, company_count=1)
        async with runtime["sessions"]() as session:
            await ExplorationService(
                session, _ObligationGenerator()
            ).claim_run_for_execution(exploration_id, run_id)
        await _claim_execution(runtime, run_id)
        failed_stale = inject_failure("update exploration_run")
        with pytest.raises(RuntimeError, match="injected database failure"):
            await reconcile_taskiq_runs_once(
                runtime["sessions"],
                await _terminal_settings(),
                now=datetime.now(UTC) + timedelta(seconds=10),
            )
        remove_failure(failed_stale)
        assert (await _statuses(runtime["sessions"], run_id))[:2] == (
            "RUNNING",
            "RUNNING",
        )
        result = await reconcile_taskiq_runs_once(
            runtime["sessions"],
            await _terminal_settings(),
            now=datetime.now(UTC) + timedelta(seconds=10),
        )
        assert result.running_failed == 1
        assert (await _statuses(runtime["sessions"], run_id))[:2] == (
            "FAILED",
            "FAILED",
        )

        # Definitive queued failure compensation is atomic as well.
        exploration_id, run_id, _ = await _create_run(runtime, company_count=1)
        async with runtime["sessions"]() as session:
            await ExplorationService(
                session, _ObligationGenerator()
            ).claim_run_for_execution(exploration_id, run_id)
        failed_compensation = inject_failure("update exploration_run")
        with pytest.raises(RuntimeError, match="injected database failure"):
            async with runtime["sessions"]() as session:
                await ExplorationService(
                    session, _ObligationGenerator()
                ).fail_queued_execution(run_id)
        remove_failure(failed_compensation)
        assert (await _statuses(runtime["sessions"], run_id))[:2] == (
            "QUEUED",
            "QUEUED",
        )
        async with runtime["sessions"]() as session:
            assert await ExplorationService(
                session, _ObligationGenerator()
            ).fail_queued_execution(run_id)
        assert (await _statuses(runtime["sessions"], run_id))[:2] == (
            "FAILED",
            "FAILED",
        )
