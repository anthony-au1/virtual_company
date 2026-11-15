"""Opt-in PostgreSQL end-to-end test using disposable Compose databases."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[2]
UTILITY = ROOT / "scripts" / "virtual_company_backup.py"
RUN_TESTS = os.getenv("RUN_VIRTUAL_COMPANY_BACKUP_RESTORE_POSTGRES_TESTS") == "true"
COMPOSE = os.getenv("COMPOSE", "docker compose").split()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not RUN_TESTS,
        reason="Opt-in disposable PostgreSQL backup/restore test",
    ),
]


def _run(command: list[str], *, input_text: str | None = None) -> str:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        input=input_text,
        text=True,
        capture_output=True,
        check=True,
        timeout=90,
    )
    return completed.stdout.strip()


def _compose(*args: str, input_text: str | None = None) -> str:
    return _run([*COMPOSE, *args], input_text=input_text)


def _migrate(database: str) -> None:
    _compose(
        "run",
        "--rm",
        "--no-deps",
        "-T",
        "app",
        "sh",
        "-lc",
        f'DATABASE_URL="${{DATABASE_URL%/*}}/{database}" uv run --no-dev alembic upgrade head',
    )


def _database_exists(database: str) -> bool:
    value = _compose(
        "exec",
        "-T",
        "postgres",
        "sh",
        "-lc",
        'psql -X -A -t -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c '
        '"SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname = \'$1\');"',
        "check-disposable-db",
        database,
    )
    return value == "t"


def _identity(database: str) -> dict[str, object]:
    sql = (
        "SELECT json_build_object('database', current_database(), "
        "'campaigns', (SELECT count(*) FROM campaign), "
        "'companies', (SELECT count(*) FROM research_company), "
        "'explorations', (SELECT count(*) FROM exploration), "
        "'exploration_facts', (SELECT count(*) FROM exploration_fact), "
        "'exploration_hypotheses', (SELECT count(*) FROM exploration_hypothesis), "
        "'workflow_executions', (SELECT count(*) FROM workflow_execution))::text;"
    )
    value = _compose(
        "exec",
        "-T",
        "postgres",
        "sh",
        "-lc",
        'psql -X -A -t -U "$POSTGRES_USER" -d "$1" -c "$2"',
        "read-disposable-db-identity",
        database,
        sql,
    )
    return json.loads(value)


def _synthetic_ids(database: str) -> dict[str, str]:
    sql = """
    SELECT json_build_object(
      'campaign', (SELECT id::text FROM campaign WHERE name = 'Synthetic backup test'),
      'research_run', (SELECT id::text FROM research_run WHERE companies_found = 1),
      'company', (SELECT id::text FROM research_company WHERE domain = 'backup-test.invalid'),
      'evidence', (SELECT id::text FROM research_evidence WHERE claim = 'Synthetic claim'),
      'qualification', (SELECT id::text FROM research_company_qualification
                        WHERE status = 'QUALIFIED'),
      'execution', (SELECT id::text FROM workflow_execution WHERE workflow_type = 'research')
      , 'exploration', (SELECT id::text FROM exploration WHERE business_context = 'Synthetic backup test')
      , 'exploration_run', (SELECT id::text FROM exploration_run)
      , 'exploration_company', (SELECT id::text FROM exploration_company)
      , 'exploration_evidence', (SELECT id::text FROM exploration_evidence)
      , 'exploration_fact', (SELECT id::text FROM exploration_fact)
      , 'exploration_hypothesis', (SELECT id::text FROM exploration_hypothesis)
    )::text;
    """
    value = _compose(
        "exec",
        "-T",
        "postgres",
        "sh",
        "-lc",
        'psql -X -A -t -U "$POSTGRES_USER" -d "$1" -c "$2"',
        "read-synthetic-record-ids",
        database,
        sql,
    )
    result = json.loads(value)
    assert all(result.values())
    return result


def _seed(database: str) -> None:
    campaign_id = "11111111-1111-4111-8111-111111111111"
    run_id = "22222222-2222-4222-8222-222222222222"
    company_id = "33333333-3333-4333-8333-333333333333"
    evidence_id = "44444444-4444-4444-8444-444444444444"
    qualification_id = "55555555-5555-4555-8555-555555555555"
    execution_id = "66666666-6666-4666-8666-666666666666"
    exploration_id = "77777777-7777-4777-8777-777777777777"
    obligation_id = "88888888-8888-4888-8888-888888888888"
    exploration_run_id = "99999999-9999-4999-8999-999999999999"
    exploration_company_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    exploration_evidence_id = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    exploration_fact_id = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
    exploration_hypothesis_id = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
    exploration_execution_id = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
    sql = f"""
    INSERT INTO campaign
      (id, name, keywords, target_count, max_companies_to_research, status)
    VALUES ('{campaign_id}', 'Synthetic backup test', '[]'::jsonb, 1, 1, 'COMPLETED');
    INSERT INTO research_run
      (id, campaign_id, status, completed_at, companies_found)
    VALUES ('{run_id}', '{campaign_id}', 'COMPLETED', now(), 1);
    INSERT INTO research_company (id, name, domain)
    VALUES ('{company_id}', 'Synthetic Test Company', 'backup-test.invalid');
    INSERT INTO campaign_target (campaign_id, company_id, status)
    VALUES ('{campaign_id}', '{company_id}', 'QUALIFIED');
    INSERT INTO research_evidence
      (id, company_id, research_run_id, criterion, claim, evidence_text,
       source_url, source_title, source_type)
    VALUES ('{evidence_id}', '{company_id}', '{run_id}', 'test',
       'Synthetic claim', 'Synthetic evidence', 'https://example.invalid/source',
       'Synthetic source', 'web');
    INSERT INTO research_company_qualification
      (id, research_run_id, campaign_id, company_id, status, criteria_results)
    VALUES ('{qualification_id}', '{run_id}', '{campaign_id}', '{company_id}',
       'QUALIFIED', jsonb_build_object('criteria', jsonb_build_array(
          jsonb_build_object('evidence_ids', jsonb_build_array('{evidence_id}'))
       )));
    INSERT INTO workflow_execution
      (id, workflow_type, run_id, status, completed_at)
    VALUES ('{execution_id}', 'research', '{run_id}', 'COMPLETED', now());
    INSERT INTO exploration (id, business_context, status)
    VALUES ('{exploration_id}', 'Synthetic backup test', 'DRAFT');
    INSERT INTO exploration_obligation (id, exploration_id, description)
    VALUES ('{obligation_id}', '{exploration_id}', 'Verify backup preservation');
    INSERT INTO exploration_run (id, exploration_id, research_run_id, status, completed_at)
    VALUES ('{exploration_run_id}', '{exploration_id}', '{run_id}', 'COMPLETED', now());
    INSERT INTO exploration_company (id, exploration_run_id, company_id)
    VALUES ('{exploration_company_id}', '{exploration_run_id}', '{company_id}');
    INSERT INTO exploration_evidence
      (id, exploration_company_id, exploration_obligation_id, claim, supporting_excerpt, source_url)
    VALUES ('{exploration_evidence_id}', '{exploration_company_id}', '{obligation_id}',
      'Synthetic exploration claim', 'Synthetic exploration evidence', 'https://example.invalid/exploration');
    INSERT INTO exploration_fact (id, exploration_company_id, statement)
    VALUES ('{exploration_fact_id}', '{exploration_company_id}', 'Synthetic fact');
    INSERT INTO exploration_fact_evidence (exploration_fact_id, exploration_evidence_id)
    VALUES ('{exploration_fact_id}', '{exploration_evidence_id}');
    INSERT INTO exploration_hypothesis (id, exploration_company_id, statement)
    VALUES ('{exploration_hypothesis_id}', '{exploration_company_id}', 'Synthetic hypothesis');
    INSERT INTO exploration_hypothesis_fact (exploration_hypothesis_id, exploration_fact_id)
    VALUES ('{exploration_hypothesis_id}', '{exploration_fact_id}');
    INSERT INTO workflow_execution (id, workflow_type, run_id, status, completed_at)
    VALUES ('{exploration_execution_id}', 'exploration', '{exploration_run_id}', 'COMPLETED', now());
    """
    _compose(
        "exec",
        "-T",
        "postgres",
        "sh",
        "-lc",
        'psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$1"',
        "seed-synthetic-test-data",
        database,
        input_text=sql,
    )


def _drop_owned_database(database: str) -> None:
    if not database.startswith("virtual_company_restore_test_"):
        raise AssertionError("Refusing cleanup outside this test's unique database prefix")
    _compose(
        "exec",
        "-T",
        "postgres",
        "sh",
        "-lc",
        'dropdb --if-exists -U "$POSTGRES_USER" "$1"',
        "drop-owned-test-database",
        database,
    )


def test_backup_restore_and_verify_reproducibly(tmp_path: Path) -> None:
    suffix = uuid4().hex[:12]
    source = f"virtual_company_restore_test_src_{suffix}"
    targets = [
        f"virtual_company_restore_test_a_{suffix}",
        f"virtual_company_restore_test_b_{suffix}",
    ]
    candidates = [source, *targets]
    assert all(name.startswith("virtual_company_restore_test_") for name in candidates)
    assert "virtual_company" not in candidates
    owned: list[str] = []

    backup_root = tmp_path / "host-backups"
    normal_database_before = _identity("virtual_company")
    print(f"Disposable source database: {source}")
    print(f"Disposable restore targets: {', '.join(targets)}")
    env = {
        **os.environ,
        "COMPOSE": " ".join(COMPOSE),
        "SOURCE_DB": source,
        "BACKUP_DIR": str(backup_root),
    }
    try:
        assert not any(_database_exists(database) for database in owned)
        user = _compose("exec", "-T", "postgres", "printenv", "POSTGRES_USER")
        _compose("exec", "-T", "postgres", "createdb", "-U", user, source)
        owned.append(source)
        _migrate(source)
        _seed(source)
        source_identity = _identity(source)
        source_ids = _synthetic_ids(source)
        subprocess.run(
            [sys.executable, str(UTILITY), "backup"],
            cwd=ROOT,
            env=env,
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        backup_dirs = list(backup_root.glob("virtual-company-*"))
        assert len(backup_dirs) == 1
        backup_dir = backup_dirs[0]

        for target in targets:
            assert not _database_exists(target)
            # It was absent immediately before this test's restore attempt.
            owned.append(target)
            restore_env = {
                **os.environ,
                "COMPOSE": " ".join(COMPOSE),
                "BACKUP": str(backup_dir),
                "TARGET_DB": target,
            }
            subprocess.run(
                [sys.executable, str(UTILITY), "restore"],
                cwd=ROOT,
                env=restore_env,
                check=True,
                capture_output=True,
                text=True,
                timeout=180,
            )
            verified = subprocess.run(
                [sys.executable, str(UTILITY), "verify"],
                cwd=ROOT,
                env=restore_env,
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            assert f"Verification passed for database: {target}" in verified.stdout
            restored_identity = _identity(target)
            assert restored_identity["database"] == target
            assert restored_identity["campaigns"] == source_identity["campaigns"] == 1
            assert restored_identity["companies"] == source_identity["companies"] == 1
            assert restored_identity["explorations"] == source_identity["explorations"] == 1
            assert restored_identity["exploration_facts"] == source_identity["exploration_facts"] == 1
            assert restored_identity["exploration_hypotheses"] == source_identity["exploration_hypotheses"] == 1
            assert _synthetic_ids(target) == source_ids
        assert _identity("virtual_company") == normal_database_before
    finally:
        for database in set(owned):
            if _database_exists(database):
                _drop_owned_database(database)
