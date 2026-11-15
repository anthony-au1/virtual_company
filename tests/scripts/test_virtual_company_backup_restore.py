"""Offline tests for Virtual Company database backup/restore safety."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

utility_path = Path(__file__).resolve().parents[2] / "scripts" / "virtual_company_backup.py"
spec = importlib.util.spec_from_file_location("virtual_company_backup", utility_path)
assert spec is not None and spec.loader is not None
backup = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = backup
spec.loader.exec_module(backup)


REVISION = "0001_initial_schema"
COUNTS = {key: 0 for key in backup.LEGACY_COUNT_KEYS}
COUNTS.update({f"table:{table}": 0 for table in backup.application_table_names()})
COUNTS.update(
    campaign_count=1,
    research_run_count=1,
    completed_research_run_count=1,
    research_company_count=1,
    campaign_target_count=1,
    research_evidence_count=1,
    research_qualification_count=1,
    workflow_execution_count=1,
)
RELATIONSHIPS = {key: 0 for key in backup.RESEARCH_ERROR_CHECK_KEYS}
RELATIONSHIPS.update(
    qualification_evidence_reference_count=1,
    completed_run_eligible_company_count=1,
)


class FakePostgres:
    """Small fake for orchestration tests, not PostgreSQL integration coverage."""

    pg_user = "test_user"
    default_database = "virtual_company"

    def __init__(self) -> None:
        self.databases = {"virtual_company": True}
        self.active_count = 0
        self.restore_calls: list[str] = []
        self.snapshot_counts = dict(COUNTS)
        self.relationships = dict(RELATIONSHIPS)
        self.revision = REVISION
        self.fail_archive_inspection = False
        self.unvalidated_foreign_keys = 0

    def query_json(self, database: str, sql: str) -> dict[str, object]:
        if "current_setting('server_version')" in sql and "alembic_version" not in sql:
            return {"postgresql_version": "16.2"}
        if "'database', current_database()" in sql:
            return {
                "database": database,
                "postgresql_version": "16.2",
                "alembic_revision": self.revision,
            }
        if "completed_run_eligible_company_count" in sql:
            return dict(self.relationships)
        return {
            key: self.snapshot_counts[key]
            for key in backup.LEGACY_COUNT_KEYS
        }

    def count(self, database: str, sql: str) -> int:
        if "workflow_execution" in sql and "QUEUED" in sql:
            return self.active_count
        if "pg_constraint" in sql:
            return self.unvalidated_foreign_keys
        if 'FROM "' in sql:
            table = sql.split('FROM "', 1)[1].split('"', 1)[0]
            return int(self.snapshot_counts.get(f"table:{table}", 0))
        return 0

    def query(self, database: str, sql: str) -> str:
        if "information_schema.columns" in sql:
            return "\n".join(
                f"{table}\tid" for table in backup.application_table_names()
            )
        if "md5(coalesce(string_agg" in sql:
            return hashlib.md5(sql.encode()).hexdigest()
        raise AssertionError(f"Unexpected SQL query: {sql}")

    def dump(self, database: str, destination) -> None:
        destination.write(b"synthetic postgres custom archive")

    def inspect_archive(self, archive) -> None:
        if self.fail_archive_inspection:
            raise backup.BackupError("invalid archive")
        assert archive.read()
        archive.seek(0)

    def version(self, executable: str) -> str:
        return "pg_dump (PostgreSQL) 16.2"

    def database_exists(self, database: str) -> bool:
        return self.databases.get(database, False)

    def create_database(self, database: str) -> None:
        self.databases[database] = True

    def restore(self, database: str, archive) -> None:
        archive.read()
        self.restore_calls.append(database)


def _manifest(
    directory: Path,
    *,
    revision: str = REVISION,
    uuid_fingerprints: dict[str, str] | None = None,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    archive = directory / "database.dump"
    archive.write_bytes(b"synthetic postgres custom archive")
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    (directory / "database.dump.sha256").write_text(
        f"{checksum}  database.dump\n", encoding="ascii"
    )
    document = {
        "backup_timestamp": "2026-11-15T00:00:00+00:00",
        "postgresql_version": "16.2",
        "pg_dump_version": "pg_dump (PostgreSQL) 16.2",
        "application_git_commit": "test-commit",
        "alembic_revision": revision,
        "database_identity": {"database": "source_test"},
        "counts": COUNTS,
        "backup_format": backup.BACKUP_FORMAT,
        "backup_format_version": backup.BACKUP_FORMAT_VERSION,
        "sha256": checksum,
    }
    if uuid_fingerprints is not None:
        document["uuid_fingerprints"] = uuid_fingerprints
    (directory / "manifest.json").write_text(json.dumps(document), encoding="utf-8")
    return directory


def test_backup_creates_manifest_checksum_and_archive(tmp_path, monkeypatch):
    postgres = FakePostgres()
    monkeypatch.setattr(backup.ComposePostgres, "connect", lambda: postgres)
    monkeypatch.setattr(backup, "current_alembic_head", lambda: REVISION)
    monkeypatch.setattr(backup, "current_git_commit", lambda: "test-commit")
    root = tmp_path / "host-backups"

    output = backup.create_backup(source_database="virtual_company", backup_root=str(root))

    assert (output / "database.dump").read_bytes()
    assert (output / "manifest.json").is_file()
    assert (output / "database.dump.sha256").is_file()
    assert output.name.startswith("virtual-company-")
    manifest = backup.load_manifest(output)[2]
    assert manifest["counts"] == COUNTS
    assert "campaign.id" in manifest["uuid_fingerprints"]


def test_backup_refuses_active_workflow_executions(tmp_path, monkeypatch):
    postgres = FakePostgres()
    postgres.active_count = 1
    monkeypatch.setattr(backup.ComposePostgres, "connect", lambda: postgres)

    with pytest.raises(backup.BackupError, match="QUEUED or RUNNING"):
        backup.create_backup(source_database="virtual_company", backup_root=str(tmp_path))


def test_missing_manifest_is_rejected(tmp_path):
    (tmp_path / "database.dump").write_bytes(b"archive")
    with pytest.raises(backup.VerificationError, match="manifest is missing"):
        backup.load_manifest(tmp_path)


def test_checksum_mismatch_is_rejected(tmp_path):
    directory = _manifest(tmp_path / "backup")
    (directory / "database.dump").write_bytes(b"tampered archive")
    with pytest.raises(backup.VerificationError, match="checksum mismatch"):
        backup.load_manifest(directory)


def test_empty_checksum_file_is_rejected(tmp_path):
    directory = _manifest(tmp_path / "backup")
    (directory / "database.dump.sha256").write_text("", encoding="ascii")
    with pytest.raises(backup.VerificationError, match="empty"):
        backup.load_manifest(directory)


@pytest.mark.parametrize("name", ["virtual_company", "production", "virtual_company_restore_"])
def test_restore_refuses_unapproved_target_names(name):
    with pytest.raises(backup.RestoreError, match="TARGET_DB must start"):
        backup._validate_database_name(name, restore_target=True)


def test_restore_refuses_existing_database(tmp_path, monkeypatch):
    postgres = FakePostgres()
    postgres.databases["virtual_company_restore_taken"] = True
    monkeypatch.setattr(backup.ComposePostgres, "connect", lambda: postgres)
    monkeypatch.setattr(backup, "current_alembic_head", lambda: REVISION)
    directory = _manifest(tmp_path / "backup")

    with pytest.raises(backup.RestoreError, match="refusing to overwrite"):
        backup.restore_backup(backup=str(directory), target_database="virtual_company_restore_taken")
    assert not postgres.restore_calls


def test_restore_checks_revision_before_creating_database(tmp_path, monkeypatch):
    postgres = FakePostgres()
    monkeypatch.setattr(backup.ComposePostgres, "connect", lambda: postgres)
    monkeypatch.setattr(backup, "current_alembic_head", lambda: "another_revision")
    directory = _manifest(tmp_path / "backup")

    with pytest.raises(backup.RestoreError, match="Schema revision mismatch"):
        backup.restore_backup(backup=str(directory), target_database="virtual_company_restore_new")
    assert "virtual_company_restore_new" not in postgres.databases


def test_restore_rejects_invalid_archive_before_database_creation(tmp_path, monkeypatch):
    postgres = FakePostgres()
    postgres.fail_archive_inspection = True
    monkeypatch.setattr(backup.ComposePostgres, "connect", lambda: postgres)
    monkeypatch.setattr(backup, "current_alembic_head", lambda: REVISION)
    directory = _manifest(tmp_path / "backup")

    with pytest.raises(backup.RestoreError, match="archive is invalid"):
        backup.restore_backup(backup=str(directory), target_database="virtual_company_restore_new")
    assert "virtual_company_restore_new" not in postgres.databases


def test_verify_fails_on_broken_research_relationships(tmp_path, monkeypatch):
    postgres = FakePostgres()
    postgres.relationships["qualification_parent_mismatch_count"] = 1
    monkeypatch.setattr(backup.ComposePostgres, "connect", lambda: postgres)
    directory = _manifest(tmp_path / "backup")

    with pytest.raises(backup.VerificationError, match="integrity checks failed"):
        backup.verify_backup(backup=str(directory), target_database="virtual_company_restore_test")


def test_verify_fails_on_broken_exploration_associations(tmp_path, monkeypatch):
    postgres = FakePostgres()
    postgres.relationships["exploration_fact_evidence_mismatch_count"] = 1
    monkeypatch.setattr(backup.ComposePostgres, "connect", lambda: postgres)
    directory = _manifest(tmp_path / "backup")

    with pytest.raises(backup.VerificationError, match="integrity checks failed"):
        backup.verify_backup(backup=str(directory), target_database="virtual_company_restore_test")


def test_verify_compares_exploration_table_counts(tmp_path, monkeypatch):
    postgres = FakePostgres()
    postgres.snapshot_counts["table:exploration_fact"] = 1
    monkeypatch.setattr(backup.ComposePostgres, "connect", lambda: postgres)
    directory = _manifest(tmp_path / "backup")

    with pytest.raises(backup.VerificationError, match="counts differ"):
        backup.verify_backup(backup=str(directory), target_database="virtual_company_restore_test")


def test_verify_rejects_unvalidated_foreign_keys(tmp_path, monkeypatch):
    postgres = FakePostgres()
    postgres.unvalidated_foreign_keys = 1
    monkeypatch.setattr(backup.ComposePostgres, "connect", lambda: postgres)
    directory = _manifest(tmp_path / "backup")

    with pytest.raises(backup.VerificationError, match="integrity checks failed"):
        backup.verify_backup(backup=str(directory), target_database="virtual_company_restore_test")


def test_verify_detects_uuid_value_changes(tmp_path, monkeypatch):
    postgres = FakePostgres()
    monkeypatch.setattr(backup.ComposePostgres, "connect", lambda: postgres)
    directory = _manifest(
        tmp_path / "backup",
        uuid_fingerprints={"campaign.id": "0" * 32},
    )

    with pytest.raises(backup.VerificationError, match="UUID values differ"):
        backup.verify_backup(backup=str(directory), target_database="virtual_company_restore_test")


def test_application_table_inventory_includes_exploration_associations():
    tables = backup.application_table_names()
    assert "exploration_fact_evidence" in tables
    assert "exploration_hypothesis_fact" in tables
    assert "workflow_execution" in tables


def test_verify_accepts_matching_restored_snapshot(tmp_path, monkeypatch):
    postgres = FakePostgres()
    monkeypatch.setattr(backup.ComposePostgres, "connect", lambda: postgres)
    directory = _manifest(tmp_path / "backup")

    result = backup.verify_backup(
        backup=str(directory), target_database="virtual_company_restore_test"
    )

    assert result["database"] == "virtual_company_restore_test"


def test_restore_and_repeat_restore_create_separate_fresh_targets(tmp_path, monkeypatch):
    postgres = FakePostgres()
    monkeypatch.setattr(backup.ComposePostgres, "connect", lambda: postgres)
    monkeypatch.setattr(backup, "current_alembic_head", lambda: REVISION)
    monkeypatch.setattr(backup, "current_git_commit", lambda: "test-commit")
    directory = _manifest(tmp_path / "backup")

    backup.restore_backup(
        backup=str(directory), target_database="virtual_company_restore_first"
    )
    backup.restore_backup(
        backup=str(directory), target_database="virtual_company_restore_second"
    )

    assert postgres.restore_calls == [
        "virtual_company_restore_first",
        "virtual_company_restore_second",
    ]


def test_database_connection_failure_is_reported(monkeypatch):
    def fail_connection():
        raise backup.BackupError("PostgreSQL connection refused")

    monkeypatch.setattr(backup.ComposePostgres, "connect", fail_connection)

    with pytest.raises(backup.BackupError, match="connection refused"):
        backup.create_backup(source_database="virtual_company")


def test_main_reports_missing_restore_arguments(capsys):
    assert backup.main(["restore"]) == 1
    assert "BACKUP is required" in capsys.readouterr().err

