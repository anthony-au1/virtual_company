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
import time
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
PRIMARY_DATABASE = "virtual_company"
POSTGRES_SERVICE = "postgres"
RECOVERY_WAIT_SECONDS = 30

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
RECOVERY_DATABASE_STATE_SQL = """
SELECT json_build_object(
  'database', current_database(),
  'user', current_user,
  'database_owner', pg_get_userbyid((
    SELECT datdba FROM pg_database WHERE datname = current_database()
  )),
  'extra_schemas', (
    SELECT count(*) FROM pg_namespace
    WHERE nspname NOT IN ('pg_catalog', 'information_schema', 'public', 'pg_toast')
      AND nspname NOT LIKE 'pg_temp_%'
      AND nspname NOT LIKE 'pg_toast_temp_%'
  ),
  'user_objects', (
    (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
      WHERE n.nspname = 'public') +
    (SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
      WHERE n.nspname = 'public') +
    (SELECT count(*) FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
      WHERE n.nspname = 'public') +
    (SELECT count(*) FROM pg_operator o JOIN pg_namespace n ON n.oid = o.oprnamespace
      WHERE n.nspname = 'public') +
    (SELECT count(*) FROM pg_collation c JOIN pg_namespace n ON n.oid = c.collnamespace
      WHERE n.nspname = 'public') +
    (SELECT count(*) FROM pg_conversion c JOIN pg_namespace n ON n.oid = c.connamespace
      WHERE n.nspname = 'public') +
    (SELECT count(*) FROM pg_opclass c JOIN pg_namespace n ON n.oid = c.opcnamespace
      WHERE n.nspname = 'public') +
    (SELECT count(*) FROM pg_opfamily f JOIN pg_namespace n ON n.oid = f.opfnamespace
      WHERE n.nspname = 'public') +
    (SELECT count(*) FROM pg_ts_config c JOIN pg_namespace n ON n.oid = c.cfgnamespace
      WHERE n.nspname = 'public') +
    (SELECT count(*) FROM pg_ts_dict d JOIN pg_namespace n ON n.oid = d.dictnamespace
      WHERE n.nspname = 'public') +
    (SELECT count(*) FROM pg_ts_parser p JOIN pg_namespace n ON n.oid = p.prsnamespace
      WHERE n.nspname = 'public') +
    (SELECT count(*) FROM pg_ts_template t JOIN pg_namespace n ON n.oid = t.tmplnamespace
      WHERE n.nspname = 'public') +
    (SELECT count(*) FROM pg_statistic_ext s JOIN pg_namespace n ON n.oid = s.stxnamespace
      WHERE n.nspname = 'public') +
    (SELECT count(*) FROM pg_extension WHERE extname <> 'plpgsql') +
    (SELECT count(*) FROM pg_largeobject_metadata) +
    (SELECT count(*) FROM pg_publication) +
    (SELECT count(*) FROM pg_subscription) +
    (SELECT count(*) FROM pg_event_trigger WHERE NOT evtenabled = 'D')
  ),
  'alembic_table', to_regclass('public.alembic_version') IS NOT NULL,
  'application_tables', (
    SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
      AND c.relname <> 'alembic_version'
  ),
  'foreign_keys', (
    SELECT count(*) FROM pg_constraint WHERE contype = 'f'
  ),
  'indexes', (
    SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND c.relkind = 'i'
  )
)::text;
"""


class BackupError(RuntimeError):
    """Raised when a backup operation cannot safely complete."""


class RestoreError(RuntimeError):
    """Raised when a restore operation is invalid or incomplete."""


class RecoveryError(RestoreError):
    """Raised when primary-database recovery cannot safely complete."""


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

    def __init__(
        self, compose: list[str], user: str, default_database: str, *, cwd: Path | None = None
    ) -> None:
        self.compose = compose
        self.user = user
        self.default_database = default_database
        self.cwd = cwd

    @classmethod
    def connect(cls, *, cwd: Path | None = None) -> ComposePostgres:
        compose = _compose_command()
        result = _run(
            [*compose, "ps", "--status", "running", "-q", "postgres"],
            capture_output=True,
            text=True,
            cwd=cwd,
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
                cwd=cwd,
            )
            return result.stdout.strip()

        user = container_env("POSTGRES_USER")
        default_database = container_env("POSTGRES_DB")
        if not DATABASE_NAME_PATTERN.fullmatch(user):
            raise BackupError("PostgreSQL container returned an invalid user name")
        if not DATABASE_NAME_PATTERN.fullmatch(default_database):
            raise BackupError("PostgreSQL container returned an invalid database name")
        return cls(compose, user, default_database, cwd=cwd)

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
            cwd=self.cwd,
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
            cwd=self.cwd,
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
            cwd=self.cwd,
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
            cwd=self.cwd,
        )

    def restore_primary(self, archive: BinaryIO) -> None:
        if self.default_database != PRIMARY_DATABASE:
            raise RestoreError("Compose PostgreSQL default database is not the primary database")
        _run(
            [
                *self.compose,
                "exec",
                "-T",
                POSTGRES_SERVICE,
                "pg_restore",
                "--exit-on-error",
                "--single-transaction",
                "-U",
                self.user,
                "-d",
                PRIMARY_DATABASE,
            ],
            stdin=archive,
            capture_output=True,
            cwd=self.cwd,
        )

    def inspect_archive(self, archive: BinaryIO) -> None:
        _run(
            self._client("pg_restore", "--list"),
            stdin=archive,
            stdout=subprocess.DEVNULL,
            capture_output=True,
            cwd=self.cwd,
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


def _validate_recovery_compose(compose: list[str]) -> None:
    if len(compose) < 2 or Path(compose[0]).name != "docker" or compose[1] != "compose":
        raise RecoveryError("Recovery is supported only with Docker Compose")
    context = _run(
        [compose[0], "context", "show"],
        capture_output=True,
        text=True,
        cwd=REPOSITORY_ROOT,
    ).stdout.strip()
    if not context:
        raise RecoveryError("Could not identify the Docker context for recovery")
    context_result = _run(
        [compose[0], "context", "inspect", context],
        capture_output=True,
        text=True,
        cwd=REPOSITORY_ROOT,
    )
    try:
        context_data = json.loads(context_result.stdout)
        endpoint = context_data[0]["Endpoints"]["docker"]["Host"]
    except (json.JSONDecodeError, IndexError, KeyError, TypeError) as error:
        raise RecoveryError("Could not verify that Docker is using a local context") from error
    if not isinstance(endpoint, str) or not endpoint.startswith(("unix://", "npipe://")):
        raise RecoveryError("Recovery is restricted to a local Docker context")
    result = _run(
        [*compose, "config", "--format", "json"],
        capture_output=True,
        text=True,
        cwd=REPOSITORY_ROOT,
    )
    try:
        config = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RecoveryError("Could not identify the local Docker Compose configuration") from error
    services = config.get("services") if isinstance(config, dict) else None
    service = services.get(POSTGRES_SERVICE) if isinstance(services, dict) else None
    environment = service.get("environment") if isinstance(service, dict) else None
    volumes = service.get("volumes") if isinstance(service, dict) else None
    project_volumes = config.get("volumes") if isinstance(config, dict) else None
    if (
        not isinstance(config, dict)
        or config.get("name") != "virtual_company"
        or not isinstance(services, dict)
        or not {"app", "worker", POSTGRES_SERVICE}.issubset(services)
        or not isinstance(service, dict)
        or service.get("image") != "postgres:16"
        or not isinstance(environment, dict)
        or environment.get("POSTGRES_DB") != PRIMARY_DATABASE
        or environment.get("POSTGRES_USER") != "virtual_company"
        or not isinstance(volumes, list)
        or not isinstance(project_volumes, dict)
    ):
        raise RecoveryError(
            "Recovery is restricted to this repository's virtual_company Compose setup "
            "with its PostgreSQL 16 service and primary database"
        )
    database_volume = next(
        (
            volume
            for volume in volumes
            if isinstance(volume, dict)
            and volume.get("type") == "volume"
            and volume.get("source") == "postgres_data"
            and volume.get("target") == "/var/lib/postgresql/data"
        ),
        None,
    )
    if database_volume is None or "postgres_data" not in project_volumes:
        raise RecoveryError(
            "Recovery requires the configured persistent postgres_data Compose volume"
        )


def _running_services(compose: list[str], *services: str) -> bool:
    result = _run(
        [*compose, "ps", "--status", "running", "-q", *services],
        capture_output=True,
        text=True,
        cwd=REPOSITORY_ROOT,
    )
    return bool(result.stdout.strip())


def _wait_for_primary(compose: list[str]) -> None:
    command = [
        *compose,
        "exec",
        "-T",
        POSTGRES_SERVICE,
        "pg_isready",
        "-U",
        "virtual_company",
        "-d",
        PRIMARY_DATABASE,
    ]
    for attempt in range(RECOVERY_WAIT_SECONDS):
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            cwd=REPOSITORY_ROOT,
        )
        if result.returncode == 0:
            return
        if attempt + 1 < RECOVERY_WAIT_SECONDS:
            time.sleep(1)
    raise RecoveryError(
        f"PostgreSQL did not become ready after {RECOVERY_WAIT_SECONDS} seconds"
    )


def _validate_recovery_database(
    postgres: ComposePostgres, *, restored: bool
) -> dict[str, object]:
    state = postgres.query_json(PRIMARY_DATABASE, RECOVERY_DATABASE_STATE_SQL)
    if (
        state.get("database") != PRIMARY_DATABASE
        or state.get("user") != "virtual_company"
        or state.get("database_owner") != "virtual_company"
    ):
        raise RecoveryError("Connected to an unexpected primary database or owner")
    if not restored:
        if (
            state.get("extra_schemas") != 0
            or state.get("user_objects") != 0
            or state.get("alembic_table") is not False
        ):
            raise RecoveryError(
                "Primary database is initialized or contains user-created objects; "
                "recovery refuses to overwrite it"
            )
        return state
    if (
        state.get("alembic_table") is not True
        or not isinstance(state.get("application_tables"), int)
        or state["application_tables"] < 1
        or not isinstance(state.get("foreign_keys"), int)
        or state["foreign_keys"] < 1
        or not isinstance(state.get("indexes"), int)
        or state["indexes"] < 1
    ):
        raise RecoveryError("Restored primary database failed schema verification")
    try:
        revision_rows = postgres.count(
            PRIMARY_DATABASE, "SELECT count(*) FROM public.alembic_version;"
        )
    except BackupError as error:
        raise RecoveryError("Restored Alembic version table could not be read") from error
    if revision_rows < 1:
        raise RecoveryError("Restored Alembic version table is empty")
    return state


def recover_primary_database(*, backup: str) -> None:
    """Restore a valid primary-database backup only into a fresh Compose database."""
    _, archive, manifest = load_manifest(backup)
    identity = manifest["database_identity"]
    if (
        not isinstance(identity, dict)
        or identity.get("database") != PRIMARY_DATABASE
        or identity.get("compose_service") != POSTGRES_SERVICE
    ):
        raise RecoveryError(
            "Recovery backup must identify the virtual_company database from the postgres service"
        )

    compose = _compose_command()
    _validate_recovery_compose(compose)
    if _running_services(compose, "app", "worker"):
        raise RecoveryError("Refusing recovery while the app or worker service is running")

    postgres_was_running = _running_services(compose, POSTGRES_SERVICE)
    started_by_recovery = not postgres_was_running
    operation_error: Exception | None = None
    try:
        if started_by_recovery:
            print("Starting only the PostgreSQL Compose service for recovery")
            _run(
                [*compose, "up", "-d", "--no-deps", POSTGRES_SERVICE],
                capture_output=True,
                text=True,
                cwd=REPOSITORY_ROOT,
            )
            _wait_for_primary(compose)

        postgres = ComposePostgres.connect(cwd=REPOSITORY_ROOT)
        if postgres.default_database != PRIMARY_DATABASE or postgres.user != "virtual_company":
            raise RecoveryError("Compose PostgreSQL environment is not the primary application DB")
        if not postgres.database_exists(PRIMARY_DATABASE):
            raise RecoveryError("The primary database was not created by PostgreSQL initialization")
        _validate_recovery_database(postgres, restored=False)
        target_version = postgres.query(
            PRIMARY_DATABASE, "SELECT current_setting('server_version');"
        )
        if _postgres_major(str(manifest["postgresql_version"])) != _postgres_major(target_version):
            raise RecoveryError("Backup and target PostgreSQL major versions differ")
        with archive.open("rb") as archive_stream:
            postgres.inspect_archive(archive_stream)
        print("Restoring backup into the verified-empty primary database")
        with archive.open("rb") as archive_stream:
            postgres.restore_primary(archive_stream)
        restored_state = _validate_recovery_database(postgres, restored=True)
        print(
            "Primary database recovery verified: "
            f"{restored_state['application_tables']} application tables, "
            f"{restored_state['foreign_keys']} foreign keys, "
            f"{restored_state['indexes']} indexes"
        )
    except Exception as error:  # noqa: BLE001 - preserve cleanup for any operation failure
        operation_error = error
    finally:
        if started_by_recovery:
            try:
                _run(
                    [*compose, "stop", POSTGRES_SERVICE],
                    capture_output=True,
                    text=True,
                    cwd=REPOSITORY_ROOT,
                )
            except Exception as stop_error:  # noqa: BLE001 - report lifecycle cleanup failure
                if operation_error is None:
                    operation_error = RecoveryError(
                        "Recovery finished, but PostgreSQL could not be stopped; "
                        "the persistent volume was left intact"
                    )
                else:
                    operation_error = RecoveryError(
                        f"{operation_error}; PostgreSQL also could not be stopped: {stop_error}"
                    )
    if operation_error is not None:
        if isinstance(operation_error, RecoveryError):
            raise operation_error
        raise RecoveryError(f"Recovery failed: {operation_error}") from operation_error
    if started_by_recovery:
        print("Stopped PostgreSQL; recovered data remains in its Compose volume")


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
    if len(args) != 1 or args[0] not in {"backup", "restore", "verify", "recover"}:
        print("Usage: virtual_company_backup.py {backup|restore|verify|recover}", file=sys.stderr)
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
        elif command == "verify":
            backup = _environment_value("BACKUP")
            if not backup:
                raise VerificationError("BACKUP is required")
            verify_backup(backup=backup)
        else:
            backup = _environment_value("BACKUP")
            if not backup:
                raise RecoveryError("BACKUP is required")
            recover_primary_database(backup=backup)
        return 0
    except (BackupError, RestoreError, VerificationError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
