"""Offline tests for PostgreSQL backup and restore orchestration."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

utility_path = Path(__file__).resolve().parents[2] / "scripts" / "virtual_company_backup.py"
spec = importlib.util.spec_from_file_location("virtual_company_backup", utility_path)
assert spec is not None and spec.loader is not None
backup = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = backup
spec.loader.exec_module(backup)


ARCHIVE_BYTES = b"synthetic PostgreSQL custom archive"
OLD_REVISION = "historical_revision"


class FakePostgres:
    """Small orchestration stub; these tests do not emulate PostgreSQL."""

    default_database = "virtual_company"

    def __init__(self) -> None:
        self.active_count = 0
        self.databases = {"virtual_company"}
        self.commands: list[str] = []
        self.restore_error: str | None = None
        self.metadata = {
            "database": "virtual_company",
            "postgresql_version": "16.4",
            "alembic_revision": "current_checkout_revision",
        }

    def query_json(self, database: str, sql: str) -> dict[str, object]:
        self.commands.append("metadata")
        return {**self.metadata, "database": database}

    def count(self, database: str, sql: str) -> int:
        self.commands.append("active_execution_count")
        return self.active_count

    def version(self, executable: str) -> str:
        self.commands.append(executable + "_version")
        return f"{executable} (PostgreSQL) 16.4"

    def dump(self, database: str, destination) -> None:
        self.commands.append("dump:" + database)
        destination.write(ARCHIVE_BYTES)

    def inspect_archive(self, archive) -> None:
        self.commands.append("inspect_archive")
        assert archive.read() == ARCHIVE_BYTES
        archive.seek(0)

    def database_exists(self, database: str) -> bool:
        self.commands.append("database_exists:" + database)
        return database in self.databases

    def create_database(self, database: str) -> None:
        self.commands.append("create_database:" + database)
        self.databases.add(database)

    def restore(self, database: str, archive) -> None:
        self.commands.append("restore:" + database)
        assert archive.read() == ARCHIVE_BYTES
        if self.restore_error:
            raise backup.BackupError(self.restore_error)


def _write_backup(
    directory: Path,
    *,
    old_fields: bool = True,
    source_database: str = "virtual_company",
) -> Path:
    directory.mkdir(parents=True)
    archive = directory / "database.dump"
    archive.write_bytes(ARCHIVE_BYTES)
    checksum = hashlib.sha256(ARCHIVE_BYTES).hexdigest()
    (directory / "database.dump.sha256").write_text(
        f"{checksum}  database.dump\n", encoding="ascii"
    )
    manifest: dict[str, object] = {
        "backup_timestamp": "2026-11-15T00:00:00+00:00",
        "postgresql_version": "16.2",
        "pg_dump_version": "pg_dump (PostgreSQL) 16.2",
        "database_identity": {
            "database": source_database,
            "compose_service": "postgres",
        },
        "backup_format": backup.BACKUP_FORMAT,
        "backup_format_version": backup.BACKUP_FORMAT_VERSION,
        "sha256": checksum,
    }
    if old_fields:
        manifest.update(
            application_git_commit="old-commit",
            alembic_revision=OLD_REVISION,
            counts={"campaign_count": 7},
            uuid_fingerprints={"campaign.id": "0" * 32},
        )
    (directory / "manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    return directory


def test_load_manifest_accepts_legacy_backup_with_removed_metadata(tmp_path: Path) -> None:
    directory = _write_backup(tmp_path / "legacy")

    _, archive, manifest = backup.load_manifest(directory)

    assert archive.read_bytes() == ARCHIVE_BYTES
    assert manifest["alembic_revision"] == OLD_REVISION
    assert manifest["counts"] == {"campaign_count": 7}


def test_checksum_mismatch_is_rejected(tmp_path: Path) -> None:
    directory = _write_backup(tmp_path / "backup")
    (directory / "database.dump").write_bytes(b"changed")

    with pytest.raises(backup.VerificationError, match="checksum mismatch"):
        backup.load_manifest(directory)


def test_missing_manifest_and_archive_are_rejected(tmp_path: Path) -> None:
    directory = tmp_path / "empty"
    directory.mkdir()
    (directory / "database.dump").write_bytes(ARCHIVE_BYTES)
    with pytest.raises(backup.VerificationError, match="manifest is missing"):
        backup.load_manifest(directory)

    directory = _write_backup(tmp_path / "missing-archive")
    (directory / "database.dump").unlink()
    with pytest.raises(backup.VerificationError, match="archive is missing or empty"):
        backup.load_manifest(directory)


def test_restore_target_name_policy_rejects_source_and_unapproved_names() -> None:
    for name in ("virtual_company", "production", "virtual_company_restore_"):
        with pytest.raises(backup.RestoreError, match="TARGET_DB must start"):
            backup._validate_database_name(name, restore_target=True)


def test_restore_refuses_existing_database_without_overwriting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    postgres = FakePostgres()
    postgres.databases.add("virtual_company_restore_taken")
    monkeypatch.setattr(backup.ComposePostgres, "connect", lambda: postgres)
    directory = _write_backup(tmp_path / "backup")

    with pytest.raises(backup.RestoreError, match="refusing to overwrite"):
        backup.restore_backup(
            backup=str(directory), target_database="virtual_company_restore_taken"
        )
    assert not any(command.startswith("restore:") for command in postgres.commands)


def test_restore_refuses_source_target_identity_before_database_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    postgres = FakePostgres()
    monkeypatch.setattr(backup.ComposePostgres, "connect", lambda: postgres)
    directory = _write_backup(
        tmp_path / "backup", source_database="virtual_company_restore_source"
    )

    with pytest.raises(backup.RestoreError, match="differ from the backup source"):
        backup.restore_backup(
            backup=str(directory), target_database="virtual_company_restore_source"
        )


def test_restore_accepts_legacy_revision_without_checkout_revision_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    postgres = FakePostgres()
    monkeypatch.setattr(backup.ComposePostgres, "connect", lambda: postgres)
    directory = _write_backup(tmp_path / "backup", old_fields=True)

    backup.restore_backup(
        backup=str(directory), target_database="virtual_company_restore_legacy"
    )

    assert "create_database:virtual_company_restore_legacy" in postgres.commands
    assert "restore:virtual_company_restore_legacy" in postgres.commands


def test_restore_failure_leaves_new_target_and_reports_transactional_behavior(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    postgres = FakePostgres()
    postgres.restore_error = "restore command failed"
    monkeypatch.setattr(backup.ComposePostgres, "connect", lambda: postgres)
    directory = _write_backup(tmp_path / "backup")

    with pytest.raises(backup.RestoreError, match="single-transaction"):
        backup.restore_backup(
            backup=str(directory), target_database="virtual_company_restore_failed"
        )
    assert "virtual_company_restore_failed" in postgres.databases


def test_verify_checks_archive_without_target_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    postgres = FakePostgres()
    monkeypatch.setattr(backup.ComposePostgres, "connect", lambda: postgres)
    directory = _write_backup(tmp_path / "backup")

    backup.verify_backup(backup=str(directory))

    assert postgres.commands == ["inspect_archive"]
    assert "does not verify a database restore" in capsys.readouterr().out


def test_backup_creates_native_archive_and_minimal_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    postgres = FakePostgres()
    monkeypatch.setattr(backup.ComposePostgres, "connect", lambda: postgres)
    monkeypatch.setattr(backup, "current_git_commit", lambda: "test-commit")

    output = backup.create_backup(
        source_database="virtual_company", backup_root=str(tmp_path / "host-backups")
    )

    assert (output / "database.dump").read_bytes() == ARCHIVE_BYTES
    manifest = backup.load_manifest(output)[2]
    assert manifest["alembic_revision"] == "current_checkout_revision"
    assert "counts" not in manifest
    assert "uuid_fingerprints" not in manifest
    assert "inspect_archive" in postgres.commands


def test_backup_refuses_active_workflow_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    postgres = FakePostgres()
    postgres.active_count = 1
    monkeypatch.setattr(backup.ComposePostgres, "connect", lambda: postgres)

    with pytest.raises(backup.BackupError, match="QUEUED or RUNNING"):
        backup.create_backup(
            source_database="virtual_company", backup_root=str(tmp_path / "backups")
        )
    assert not any(command.startswith("dump:") for command in postgres.commands)


def test_native_command_arguments_include_safe_transactional_restore_options(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    commands: list[tuple[list[str], dict[str, object]]] = []

    def run(command: list[str], **kwargs: object) -> SimpleNamespace:
        commands.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(backup, "_run", run)
    postgres = backup.ComposePostgres(["docker", "compose"], "virtual_company", "virtual_company")
    with (tmp_path / "dump").open("wb") as output:
        postgres.dump("virtual_company", output)
    with (tmp_path / "dump").open("rb") as archive:
        postgres.restore("virtual_company_restore_test", archive)

    dump_command, dump_kwargs = commands[0]
    restore_command, restore_kwargs = commands[1]
    assert dump_command == [
        "docker",
        "compose",
        "exec",
        "-T",
        "postgres",
        "pg_dump",
        "-U",
        "virtual_company",
        "-Fc",
        "-d",
        "virtual_company",
    ]
    assert dump_kwargs["stdout"] is not None
    assert "--exit-on-error" in restore_command
    assert "--single-transaction" in restore_command
    assert restore_command[-1] == "virtual_company_restore_test"
    assert restore_kwargs["stdin"] is not None


def test_successful_command_warnings_are_reported(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        backup.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout="ok", stderr="pg_dump: warning: sample"),
    )

    backup._run(["pg_dump"], capture_output=True, text=True)

    assert "pg_dump: warning: sample" in capsys.readouterr().err


def test_command_failure_includes_stderr_without_echoing_full_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(command, **kwargs):
        raise subprocess.CalledProcessError(2, command, stderr=b"database unavailable")

    monkeypatch.setattr(backup.subprocess, "run", fail)

    with pytest.raises(backup.BackupError, match="database unavailable") as error:
        backup._run(["docker", "compose", "private-option"], capture_output=True)
    assert "private-option" not in str(error.value)


def test_cli_verify_needs_only_backup(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    monkeypatch.setenv("BACKUP", "/tmp/backup")
    monkeypatch.delenv("TARGET_DB", raising=False)
    monkeypatch.setattr(backup, "verify_backup", lambda *, backup: seen.append(backup) or {})

    assert backup.main(["verify"]) == 0
    assert seen == ["/tmp/backup"]
