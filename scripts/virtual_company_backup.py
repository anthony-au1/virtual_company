"""Create, restore, and verify PostgreSQL custom-format database archives."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BACKUP_DIR = Path.home() / "virtual-company-backups"
BACKUP_FORMAT = "postgresql_custom"
BACKUP_FORMAT_VERSION = 1
DATABASE_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
RESTORE_TARGET_PATTERN = re.compile(r"^virtual_company_restore_[A-Za-z0-9_]{1,36}$")
CHECKSUM_PATTERN = re.compile(r"^[0-9a-f]{64}$")

METADATA_SQL = """
SELECT json_build_object(
  'database', current_database(),
  'postgresql_version', current_setting('server_version'),
  'alembic_revision', (SELECT version_num FROM alembic_version LIMIT 1)
)::text;
"""
ACTIVE_EXECUTIONS_SQL = """
SELECT count(*)
FROM workflow_execution
WHERE status IN ('QUEUED', 'RUNNING');
"""


class BackupError(RuntimeError):
    """Raised when a backup operation cannot safely complete."""


class RestoreError(RuntimeError):
    """Raised when a restore operation is invalid or incomplete."""


class VerificationError(RuntimeError):
    """Raised when a backup archive or its metadata is invalid."""


def _compose_command() -> list[str]:
    command = shlex.split(os.environ.get("COMPOSE", "docker compose"))
    if not command:
        raise BackupError("COMPOSE command is empty")
    return command


def _stderr_text(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        value = value.decode(errors="replace")
    return (value or "").strip()


def _run(command: Sequence[str], **kwargs) -> subprocess.CompletedProcess:
    """Run a tool, preserving successful warnings and useful failure details."""
    capture_output = kwargs.pop("capture_output", False)
    if capture_output:
        if kwargs.get("stdout") is None and kwargs.get("stderr") is None:
            kwargs["capture_output"] = True
        elif kwargs.get("stderr") is None:
            kwargs["stderr"] = subprocess.PIPE
    try:
        result = subprocess.run(command, check=True, **kwargs)
    except FileNotFoundError as error:
        raise BackupError(f"Required command is unavailable: {command[0]}") from error
    except subprocess.CalledProcessError as error:
        detail = _stderr_text(error.stderr)
        message = f"Command failed (exit {error.returncode}): {command[0]}"
        if detail:
            message += f"\n{detail}"
        raise BackupError(message) from error

    warning = _stderr_text(result.stderr)
    if warning:
        print(warning, file=sys.stderr)
    return result


class ComposePostgres:
    """Invoke PostgreSQL client tools in the already-running Compose service."""

    def __init__(self, compose: list[str], user: str, default_database: str) -> None:
        self.compose = compose
        self.user = user
        self.default_database = default_database

    @classmethod
    def connect(cls) -> ComposePostgres:
        compose = _compose_command()
        result = _run(
            [*compose, "ps", "--status", "running", "-q", "postgres"],
            capture_output=True,
            text=True,
        )
        if not result.stdout.strip():
            raise BackupError(
                "The Compose PostgreSQL service is not already running. "
                "Start it separately; this utility never starts services."
            )

        def container_env(name: str) -> str:
            result = _run(
                [*compose, "exec", "-T", "postgres", "printenv", name],
                capture_output=True,
                text=True,
            )
            return result.stdout.strip()

        user = container_env("POSTGRES_USER")
        default_database = container_env("POSTGRES_DB")
        if not DATABASE_NAME_PATTERN.fullmatch(user):
            raise BackupError("PostgreSQL container returned an invalid user name")
        if not DATABASE_NAME_PATTERN.fullmatch(default_database):
            raise BackupError("PostgreSQL container returned an invalid database name")
        return cls(compose, user, default_database)

    def _client(self, executable: str, *arguments: str) -> list[str]:
        return [
            *self.compose,
            "exec",
            "-T",
            "postgres",
            executable,
            "-U",
            self.user,
            *arguments,
        ]

    def query(self, database: str, sql: str) -> str:
        _validate_database_name(database)
        result = _run(
            self._client(
                "psql",
                "-X",
                "-A",
                "-t",
                "-v",
                "ON_ERROR_STOP=1",
                "-d",
                database,
            ),
            input=sql,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    def query_json(self, database: str, sql: str) -> dict[str, object]:
        try:
            value = json.loads(self.query(database, sql))
        except json.JSONDecodeError as error:
            raise BackupError("PostgreSQL returned invalid metadata") from error
        if not isinstance(value, dict):
            raise BackupError("PostgreSQL metadata must be a JSON object")
        return value

    def count(self, database: str, sql: str) -> int:
        try:
            return int(self.query(database, sql))
        except ValueError as error:
            raise BackupError("PostgreSQL returned an invalid count") from error

    def version(self, executable: str) -> str:
        result = _run(
            [*self.compose, "exec", "-T", "postgres", executable, "--version"],
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    def database_exists(self, database: str) -> bool:
        _validate_database_name(database)
        result = self.query(
            self.default_database,
            f"SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname = '{database}');",
        )
        return result.lower() == "t"

    def create_database(self, database: str) -> None:
        _validate_database_name(database, restore_target=True)
        _run(
            self._client("createdb", "-T", "template0", database),
            capture_output=True,
            text=True,
        )

    def dump(self, database: str, destination: BinaryIO) -> None:
        _validate_database_name(database)
        _run(
            self._client("pg_dump", "-Fc", "-d", database),
            stdout=destination,
            capture_output=True,
        )

    def restore(self, database: str, archive: BinaryIO) -> None:
        _validate_database_name(database, restore_target=True)
        _run(
            self._client(
                "pg_restore",
                "--exit-on-error",
                "--single-transaction",
                "-d",
                database,
            ),
            stdin=archive,
            capture_output=True,
        )

    def inspect_archive(self, archive: BinaryIO) -> None:
        _run(
            self._client("pg_restore", "--list"),
            stdin=archive,
            stdout=subprocess.DEVNULL,
            capture_output=True,
        )


def _validate_database_name(name: str, *, restore_target: bool = False) -> None:
    pattern = RESTORE_TARGET_PATTERN if restore_target else DATABASE_NAME_PATTERN
    if not pattern.fullmatch(name):
        if restore_target:
            raise RestoreError(
                "TARGET_DB must start with 'virtual_company_restore_' and "
                "contain only letters, digits, and underscores"
            )
        raise BackupError("Database name contains unsupported characters")


def current_git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(REPOSITORY_ROOT), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip()


def _backup_reference(value: str | Path) -> tuple[Path, Path, Path]:
    path = Path(value).expanduser().resolve()
    if path.is_dir():
        directory = path
        archive = directory / "database.dump"
    elif path.is_file():
        archive = path
        directory = path.parent
    else:
        raise VerificationError(f"Backup does not exist: {path}")
    if archive.name != "database.dump":
        raise VerificationError("Archive must be named database.dump")
    return directory, archive, directory / "manifest.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_manifest(manifest: object) -> dict[str, object]:
    if not isinstance(manifest, dict):
        raise VerificationError("Backup manifest must contain a JSON object")
    required = {
        "backup_timestamp",
        "postgresql_version",
        "pg_dump_version",
        "database_identity",
        "backup_format",
        "backup_format_version",
        "sha256",
    }
    missing = sorted(required - manifest.keys())
    if missing:
        raise VerificationError(f"Backup manifest is missing fields: {', '.join(missing)}")
    if manifest["backup_format"] != BACKUP_FORMAT:
        raise VerificationError("Unsupported backup format")
    version = manifest["backup_format_version"]
    if not isinstance(version, int) or isinstance(version, bool):
        raise VerificationError("Backup format version is invalid")
    if version != BACKUP_FORMAT_VERSION:
        raise VerificationError("Unsupported backup format version")
    identity = manifest["database_identity"]
    if not isinstance(identity, dict) or not isinstance(identity.get("database"), str):
        raise VerificationError("Manifest database_identity is invalid")
    try:
        _validate_database_name(identity["database"])
    except BackupError as error:
        raise VerificationError("Manifest source database name is invalid") from error
    for field in ("backup_timestamp", "postgresql_version", "pg_dump_version"):
        if not isinstance(manifest[field], str) or not manifest[field]:
            raise VerificationError(f"Manifest field '{field}' is invalid")
    checksum = manifest["sha256"]
    if not isinstance(checksum, str) or not CHECKSUM_PATTERN.fullmatch(checksum):
        raise VerificationError("Manifest SHA-256 is invalid")
    return manifest


def load_manifest(value: str | Path) -> tuple[Path, Path, dict[str, object]]:
    directory, archive, manifest_path = _backup_reference(value)
    if not manifest_path.is_file():
        raise VerificationError(f"Backup manifest is missing: {manifest_path}")
    if not archive.is_file() or archive.stat().st_size == 0:
        raise VerificationError(f"Backup archive is missing or empty: {archive}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as error:
        raise VerificationError(f"Backup manifest is invalid: {manifest_path}") from error
    manifest = validate_manifest(manifest)

    checksum_path = directory / "database.dump.sha256"
    if not checksum_path.is_file():
        raise VerificationError("Backup SHA-256 file is missing")
    try:
        parts = checksum_path.read_text(encoding="ascii").strip().split()
    except (OSError, UnicodeError) as error:
        raise VerificationError("Backup SHA-256 file is invalid") from error
    if not parts:
        raise VerificationError("Backup SHA-256 file is empty")
    expected = parts[0]
    if not CHECKSUM_PATTERN.fullmatch(expected):
        raise VerificationError("Backup SHA-256 file has invalid contents")
    actual = sha256_file(archive)
    if actual != expected:
        raise VerificationError("Backup checksum mismatch")
    if manifest["sha256"] != expected:
        raise VerificationError("Manifest SHA-256 does not match the checksum file")
    return directory, archive, manifest


def _safe_backup_root(value: str | None) -> Path:
    root = Path(value).expanduser() if value else DEFAULT_BACKUP_DIR
    root = root.resolve()
    try:
        root.relative_to(REPOSITORY_ROOT)
    except ValueError:
        return root
    raise BackupError("Backup directory must be outside the repository")


def _database_metadata(postgres: ComposePostgres, database: str) -> dict[str, object]:
    metadata = postgres.query_json(database, METADATA_SQL)
    if metadata.get("database") != database:
        raise BackupError("Connected to an unexpected source database")
    if not isinstance(metadata.get("postgresql_version"), str):
        raise BackupError("PostgreSQL returned an invalid server version")
    revision = metadata.get("alembic_revision")
    if revision is not None and not isinstance(revision, str):
        raise BackupError("PostgreSQL returned an invalid Alembic revision")
    return metadata


def create_backup(*, source_database: str, backup_root: str | None = None) -> Path:
    _validate_database_name(source_database)
    postgres = ComposePostgres.connect()
    metadata = _database_metadata(postgres, source_database)
    active_count = postgres.count(source_database, ACTIVE_EXECUTIONS_SQL)
    if active_count:
        raise BackupError(
            f"Refusing backup: {active_count} workflow execution(s) are QUEUED or RUNNING"
        )

    root = _safe_backup_root(backup_root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    timestamp = datetime.now(UTC)
    backup_name = f"virtual-company-{timestamp.strftime('%Y%m%dT%H%M%S%fZ')}"
    final_directory = root / backup_name
    if final_directory.exists():
        raise BackupError(f"Refusing to overwrite existing backup: {final_directory}")
    staging = Path(tempfile.mkdtemp(prefix=".virtual-company-backup-", dir=root))
    os.chmod(staging, 0o700)
    archive = staging / "database.dump"
    try:
        with archive.open("wb") as output:
            postgres.dump(source_database, output)
        os.chmod(archive, 0o600)
        if archive.stat().st_size == 0:
            raise BackupError("pg_dump produced an empty archive")
        with archive.open("rb") as input_stream:
            postgres.inspect_archive(input_stream)

        checksum = sha256_file(archive)
        manifest: dict[str, object] = {
            "backup_timestamp": timestamp.isoformat(),
            "postgresql_version": metadata["postgresql_version"],
            "pg_dump_version": postgres.version("pg_dump"),
            "application_git_commit": current_git_commit(),
            "alembic_revision": metadata.get("alembic_revision"),
            "database_identity": {
                "database": source_database,
                "compose_service": "postgres",
            },
            "backup_format": BACKUP_FORMAT,
            "backup_format_version": BACKUP_FORMAT_VERSION,
            "sha256": checksum,
        }
        (staging / "database.dump.sha256").write_text(
            f"{checksum}  database.dump\n", encoding="ascii"
        )
        (staging / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.chmod(staging / "database.dump.sha256", 0o600)
        os.chmod(staging / "manifest.json", 0o600)
        staging.rename(final_directory)
    except Exception:
        if staging.exists():
            for child in staging.iterdir():
                child.unlink()
            staging.rmdir()
        raise

    print(f"Backup created: {final_directory}")
    print(f"SHA-256: {checksum}")
    return final_directory


def _postgres_major(version: str) -> int:
    match = re.match(r"\s*(\d+)", version)
    if not match:
        raise RestoreError(f"Could not parse PostgreSQL version: {version}")
    return int(match.group(1))


def restore_backup(*, backup: str, target_database: str) -> None:
    _validate_database_name(target_database, restore_target=True)
    _, archive, manifest = load_manifest(backup)
    source_database = str(manifest["database_identity"]["database"])
    if target_database == source_database:
        raise RestoreError("Target database must differ from the backup source database")

    postgres = ComposePostgres.connect()
    target_metadata = _database_metadata(postgres, postgres.default_database)
    if _postgres_major(str(manifest["postgresql_version"])) != _postgres_major(
        str(target_metadata["postgresql_version"])
    ):
        raise RestoreError("Backup and target PostgreSQL major versions differ")
    try:
        with archive.open("rb") as input_stream:
            postgres.inspect_archive(input_stream)
    except BackupError as error:
        raise RestoreError(f"Backup archive is invalid: {error}") from error
    if postgres.database_exists(target_database):
        raise RestoreError(
            f"Target database already exists; refusing to overwrite it: {target_database}"
        )

    print(f"Creating new disposable target database: {target_database}")
    try:
        postgres.create_database(target_database)
    except BackupError as error:
        raise RestoreError(f"Could not create target database: {error}") from error
    try:
        with archive.open("rb") as input_stream:
            postgres.restore(target_database, input_stream)
    except BackupError as error:
        raise RestoreError(
            f"Restore failed; target database {target_database} was left in place. "
            f"--single-transaction prevents partial schema/data changes. Details: {error}"
        ) from error
    print(f"Database restored: {target_database}")


def verify_backup(*, backup: str) -> dict[str, object]:
    """Verify archive files, checksum, and native archive readability only."""
    directory, archive, manifest = load_manifest(backup)
    postgres = ComposePostgres.connect()
    try:
        with archive.open("rb") as input_stream:
            postgres.inspect_archive(input_stream)
    except BackupError as error:
        raise VerificationError(f"PostgreSQL could not read the backup archive: {error}") from error
    print(f"Backup verification passed: {directory}")
    print("Manifest and SHA-256 checksum are valid; PostgreSQL can list the archive.")
    print("This does not verify a database restore.")
    return manifest


def _environment_value(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in {None, ""} else default


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1 or args[0] not in {"backup", "restore", "verify"}:
        print("Usage: virtual_company_backup.py {backup|restore|verify}", file=sys.stderr)
        return 2
    command = args[0]
    try:
        if command == "backup":
            output = create_backup(
                source_database=_environment_value("SOURCE_DB", "virtual_company") or "virtual_company",
                backup_root=_environment_value("BACKUP_DIR"),
            )
            print(f"Manifest: {output / 'manifest.json'}")
        elif command == "restore":
            backup = _environment_value("BACKUP")
            target = _environment_value("TARGET_DB")
            if not backup:
                raise RestoreError("BACKUP is required (a backup directory or database.dump path)")
            if not target:
                raise RestoreError("TARGET_DB is required")
            restore_backup(backup=backup, target_database=target)
        else:
            backup = _environment_value("BACKUP")
            if not backup:
                raise VerificationError("BACKUP is required")
            verify_backup(backup=backup)
        return 0
    except (BackupError, RestoreError, VerificationError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
