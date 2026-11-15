"""Safe Virtual Company PostgreSQL snapshot, restore, and integrity checks."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BACKUP_DIR = Path.home() / "virtual-company-backups"
BACKUP_FORMAT = "postgresql_custom"
BACKUP_FORMAT_VERSION = 1
RESTORE_DATABASE_PREFIX = "virtual_company_restore_"
DATABASE_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
RESTORE_TARGET_PATTERN = re.compile(r"^virtual_company_restore_[A-Za-z0-9_]{1,36}$")
UUID_PATTERN = (
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
LEGACY_COUNT_KEYS = (
    "campaign_count",
    "research_run_count",
    "completed_research_run_count",
    "research_company_count",
    "campaign_target_count",
    "research_evidence_count",
    "research_qualification_count",
    "exploration_run_count",
    "workflow_execution_count",
)
RESEARCH_ERROR_CHECK_KEYS = (
    "research_run_missing_campaign_count",
    "campaign_target_missing_parent_count",
    "research_evidence_missing_parent_count",
    "research_evidence_wrong_campaign_company_count",
    "qualification_parent_mismatch_count",
    "invalid_qualification_evidence_reference_count",
    "nonterminal_workflow_execution_count",
    "research_execution_status_mismatch_count",
    "exploration_run_missing_parent_count",
    "exploration_company_missing_parent_count",
    "exploration_evidence_relationship_mismatch_count",
    "exploration_fact_evidence_mismatch_count",
    "exploration_hypothesis_fact_mismatch_count",
    "exploration_execution_run_mismatch_count",
)

LEGACY_COUNTS_SQL = """
SELECT json_build_object(
  'campaign_count', (SELECT count(*) FROM campaign),
  'research_run_count', (SELECT count(*) FROM research_run),
  'completed_research_run_count',
      (SELECT count(*) FROM research_run WHERE status = 'COMPLETED'),
  'research_company_count', (SELECT count(*) FROM research_company),
  'campaign_target_count', (SELECT count(*) FROM campaign_target),
  'research_evidence_count', (SELECT count(*) FROM research_evidence),
  'research_qualification_count',
      (SELECT count(*) FROM research_company_qualification),
  'exploration_run_count', (SELECT count(*) FROM exploration_run),
  'workflow_execution_count', (SELECT count(*) FROM workflow_execution)
)::text;
"""

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

TABLE_COUNTS_SQL = 'SELECT count(*) FROM "{table}";'
FOREIGN_KEY_SQL = """
SELECT count(*) FROM pg_constraint
WHERE contype = 'f' AND connamespace = 'public'::regnamespace AND NOT convalidated;
"""
UUID_COLUMNS_SQL = """
SELECT table_name || E'\\t' || column_name
FROM information_schema.columns
WHERE table_schema = 'public' AND udt_name = 'uuid'
ORDER BY table_name, column_name;
"""

INTEGRITY_SQL = f"""
WITH criteria AS (
  SELECT q.id AS qualification_id,
         q.research_run_id,
         q.company_id,
         CASE
           WHEN jsonb_typeof(q.criteria_results->'criteria') = 'array'
             THEN q.criteria_results->'criteria'
           ELSE '[]'::jsonb
         END AS criteria_json
  FROM research_company_qualification q
), evidence_refs AS (
  SELECT c.qualification_id, c.research_run_id, c.company_id,
         jsonb_array_elements_text(
           CASE
             WHEN jsonb_typeof(item->'evidence_ids') = 'array'
               THEN item->'evidence_ids'
             ELSE '[]'::jsonb
           END
         ) AS evidence_id
  FROM criteria c
  CROSS JOIN LATERAL jsonb_array_elements(c.criteria_json) AS item
), checked_refs AS (
  SELECT r.qualification_id,
         CASE WHEN r.evidence_id ~ '{UUID_PATTERN}'
              THEN r.evidence_id::uuid ELSE NULL END AS evidence_uuid,
         r.research_run_id,
         r.company_id
  FROM evidence_refs r
), ref_results AS (
  SELECT count(*) AS reference_count,
         count(*) FILTER (
           WHERE c.evidence_uuid IS NULL OR e.id IS NULL
         ) AS invalid_evidence_reference_count
  FROM checked_refs c
  LEFT JOIN research_evidence e
    ON e.id = c.evidence_uuid
   AND e.research_run_id = c.research_run_id
   AND e.company_id = c.company_id
)
SELECT json_build_object(
  'research_run_missing_campaign_count', (
    SELECT count(*) FROM research_run r
    LEFT JOIN campaign c ON c.id = r.campaign_id WHERE c.id IS NULL
  ),
  'campaign_target_missing_parent_count', (
    SELECT count(*) FROM campaign_target t
    LEFT JOIN campaign c ON c.id = t.campaign_id
    LEFT JOIN research_company co ON co.id = t.company_id
    WHERE c.id IS NULL OR co.id IS NULL
  ),
  'research_evidence_missing_parent_count', (
    SELECT count(*) FROM research_evidence e
    LEFT JOIN research_company co ON co.id = e.company_id
    LEFT JOIN research_run r ON r.id = e.research_run_id
    WHERE co.id IS NULL OR (e.research_run_id IS NOT NULL AND r.id IS NULL)
  ),
  'research_evidence_wrong_campaign_company_count', (
    SELECT count(*) FROM research_evidence e
    JOIN research_run r ON r.id = e.research_run_id
    WHERE NOT EXISTS (
      SELECT 1 FROM campaign_target t
      WHERE t.campaign_id = r.campaign_id AND t.company_id = e.company_id
    )
  ),
  'qualification_parent_mismatch_count', (
    SELECT count(*) FROM research_company_qualification q
    LEFT JOIN research_run r ON r.id = q.research_run_id
    LEFT JOIN campaign c ON c.id = q.campaign_id
    LEFT JOIN research_company co ON co.id = q.company_id
    WHERE r.id IS NULL OR c.id IS NULL OR co.id IS NULL
       OR r.campaign_id <> q.campaign_id
       OR NOT EXISTS (
         SELECT 1 FROM campaign_target t
         WHERE t.campaign_id = q.campaign_id AND t.company_id = q.company_id
       )
  ),
  'qualification_evidence_reference_count', (SELECT reference_count FROM ref_results),
  'invalid_qualification_evidence_reference_count',
       (SELECT invalid_evidence_reference_count FROM ref_results),
  'nonterminal_workflow_execution_count', (
    SELECT count(*) FROM workflow_execution
    WHERE status IN ('QUEUED', 'RUNNING')
  ),
  'research_execution_status_mismatch_count', (
    SELECT count(*) FROM workflow_execution e
    LEFT JOIN research_run r ON r.id = e.run_id
    WHERE e.workflow_type = 'research'
      AND (r.id IS NULL OR e.status <> r.status)
  ),
  'exploration_run_missing_parent_count', (
    SELECT count(*) FROM exploration_run x
    LEFT JOIN exploration e ON e.id = x.exploration_id
    LEFT JOIN research_run r ON r.id = x.research_run_id
    WHERE e.id IS NULL OR r.id IS NULL
  ),
  'exploration_company_missing_parent_count', (
    SELECT count(*) FROM exploration_company ec
    LEFT JOIN exploration_run xr ON xr.id = ec.exploration_run_id
    LEFT JOIN research_company c ON c.id = ec.company_id
    WHERE xr.id IS NULL OR c.id IS NULL
  ),
  'exploration_evidence_relationship_mismatch_count', (
    SELECT count(*) FROM exploration_evidence ee
    JOIN exploration_company ec ON ec.id = ee.exploration_company_id
    JOIN exploration_run xr ON xr.id = ec.exploration_run_id
    JOIN exploration_obligation eo ON eo.id = ee.exploration_obligation_id
    JOIN exploration x ON x.id = xr.exploration_id
    WHERE eo.exploration_id <> x.id
  ),
  'exploration_fact_evidence_mismatch_count', (
    SELECT count(*) FROM exploration_fact_evidence fe
    JOIN exploration_fact f ON f.id = fe.exploration_fact_id
    JOIN exploration_evidence e ON e.id = fe.exploration_evidence_id
    WHERE f.exploration_company_id <> e.exploration_company_id
  ),
  'exploration_hypothesis_fact_mismatch_count', (
    SELECT count(*) FROM exploration_hypothesis_fact hf
    JOIN exploration_hypothesis h ON h.id = hf.exploration_hypothesis_id
    JOIN exploration_fact f ON f.id = hf.exploration_fact_id
    WHERE h.exploration_company_id <> f.exploration_company_id
  ),
  'exploration_execution_run_mismatch_count', (
    SELECT count(*) FROM workflow_execution e
    LEFT JOIN exploration_run r ON e.workflow_type = 'exploration' AND r.id = e.run_id
    WHERE e.workflow_type = 'exploration'
      AND (r.id IS NULL OR e.status <> r.status)
  ),
  'completed_run_eligible_company_count', (
    SELECT count(*) FROM research_company_qualification q
    JOIN research_run r ON r.id = q.research_run_id
    JOIN research_company c ON c.id = q.company_id
    WHERE r.status = 'COMPLETED' AND q.status = 'QUALIFIED'
  )
)::text;
"""


class BackupError(RuntimeError):
    """Raised when a backup operation cannot safely complete."""


class RestoreError(RuntimeError):
    """Raised when a restore operation is invalid or incomplete."""


class VerificationError(RuntimeError):
    """Raised when a backup or restored database fails verification."""


def _compose_command() -> list[str]:
    command = shlex.split(os.environ.get("COMPOSE", "docker compose"))
    if not command:
        raise BackupError("COMPOSE command is empty")
    return command


def _run(command: Sequence[str], **kwargs) -> subprocess.CompletedProcess:
    try:
        if kwargs.get("stdout") is not None and kwargs.get("capture_output"):
            # `pg_dump` streams its archive to the requested file while stderr
            # remains captured for a useful, credential-safe diagnostic.
            kwargs.pop("capture_output")
            kwargs.setdefault("stderr", subprocess.PIPE)
        return subprocess.run(command, check=True, **kwargs)
    except FileNotFoundError as error:
        raise BackupError(f"Required command is unavailable: {command[0]}") from error
    except subprocess.CalledProcessError as error:
        detail = error.stderr
        if isinstance(detail, bytes):
            detail = detail.decode(errors="replace")
        detail = (detail or "").strip()
        message = f"Command failed (exit {error.returncode}): {command[0]}"
        if detail:
            message += f"\n{detail}"
        raise BackupError(message) from error


@dataclass
class ComposePostgres:
    """Run PostgreSQL client utilities in the already-running Compose service."""

    compose: list[str]
    pg_user: str = ""
    default_database: str = ""

    @classmethod
    def connect(cls) -> ComposePostgres:
        instance = cls(_compose_command())
        result = _run(
            [*instance.compose, "ps", "--status", "running", "-q", "postgres"],
            capture_output=True,
            text=True,
        )
        if not result.stdout.strip():
            raise BackupError(
                "The Compose PostgreSQL service is not already running; "
                "start it separately and retry. This utility never starts services."
            )
        instance.pg_user = instance.container_env("POSTGRES_USER")
        instance.default_database = instance.container_env("POSTGRES_DB")
        if not DATABASE_NAME_PATTERN.fullmatch(instance.pg_user):
            raise BackupError("PostgreSQL container returned an invalid user name")
        if not DATABASE_NAME_PATTERN.fullmatch(instance.default_database):
            raise BackupError("PostgreSQL container returned an invalid database name")
        return instance

    def container_env(self, name: str) -> str:
        result = _run(
            [*self.compose, "exec", "-T", "postgres", "printenv", name],
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    def _client(self, executable: str, *arguments: str) -> list[str]:
        return [
            *self.compose,
            "exec",
            "-T",
            "postgres",
            executable,
            "-U",
            self.pg_user,
            *arguments,
        ]

    def query(self, database: str, sql: str) -> str:
        if not DATABASE_NAME_PATTERN.fullmatch(database):
            raise BackupError("Invalid database name")
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
        output = self.query(database, sql)
        try:
            value = json.loads(output)
        except json.JSONDecodeError as error:
            raise BackupError("PostgreSQL returned invalid JSON metadata") from error
        if not isinstance(value, dict):
            raise BackupError("PostgreSQL metadata must be a JSON object")
        return value

    def count(self, database: str, sql: str) -> int:
        value = self.query(database, sql)
        try:
            return int(value)
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
        literal = database.replace("'", "''")
        result = self.query(
            self.default_database,
            f"SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname = '{literal}');",
        )
        return result.lower() == "t"

    def create_database(self, database: str) -> None:
        if not DATABASE_NAME_PATTERN.fullmatch(database):
            raise RestoreError("Invalid target database name")
        _run(self._client("createdb", "-T", "template0", database), capture_output=True)

    def dump(self, database: str, destination: BinaryIO) -> None:
        if not DATABASE_NAME_PATTERN.fullmatch(database):
            raise BackupError("Invalid source database name")
        _run(
            self._client("pg_dump", "-Fc", "-d", database),
            stdout=destination,
            capture_output=True,
        )

    def restore(self, database: str, archive: BinaryIO) -> None:
        if not DATABASE_NAME_PATTERN.fullmatch(database):
            raise RestoreError("Invalid target database name")
        _run(
            self._client("pg_restore", "--exit-on-error", "-d", database),
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


def current_alembic_head() -> str:
    revisions: dict[str, str | None] = {}
    versions_dir = REPOSITORY_ROOT / "alembic" / "versions"
    for migration in versions_dir.glob("*.py"):
        tree = ast.parse(migration.read_text(encoding="utf-8"))
        values: dict[str, object] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if node.target.id in {"revision", "down_revision"}:
                    values[node.target.id] = ast.literal_eval(node.value)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in {
                        "revision",
                        "down_revision",
                    }:
                        values[target.id] = ast.literal_eval(node.value)
        revision = values.get("revision")
        down_revision = values.get("down_revision")
        if isinstance(revision, str):
            if isinstance(down_revision, tuple):
                raise BackupError("Multiple migration branches are not supported")
            revisions[revision] = down_revision if isinstance(down_revision, str) else None
    if not revisions:
        raise BackupError("No Alembic revisions were found")
    referenced = {value for value in revisions.values() if value is not None}
    heads = set(revisions) - referenced
    if len(heads) != 1:
        raise BackupError("Expected exactly one Alembic head")
    return next(iter(heads))


def application_table_names() -> tuple[str, ...]:
    """Read mapped and association table names from SQLAlchemy model source."""
    model_path = REPOSITORY_ROOT / "src" / "virtual_company" / "db" / "models.py"
    tree = ast.parse(model_path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if (
            any(
                isinstance(target, ast.Name) and target.id == "__tablename__"
                for target in node.targets
            )
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            names.add(node.value.value)
        if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id == "Table" and node.value.args:
            first = node.value.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                names.add(first.value)
    if not names:
        raise BackupError("No SQLAlchemy application tables were found")
    return tuple(sorted(names))


def _validate_database_name(name: str, *, restore_target: bool = False) -> None:
    pattern = RESTORE_TARGET_PATTERN if restore_target else DATABASE_NAME_PATTERN
    if not pattern.fullmatch(name):
        if restore_target:
            raise RestoreError(
                "TARGET_DB must start with 'virtual_company_restore_' and "
                "contain only letters, digits, and underscores"
            )
        raise BackupError("Database name contains unsupported characters")


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
    manifest_path = directory / "manifest.json"
    if archive.name != "database.dump":
        raise VerificationError("Archive must be named database.dump")
    return directory, archive, manifest_path


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
    validate_manifest(manifest)
    checksum_file = directory / "database.dump.sha256"
    if not checksum_file.is_file():
        raise VerificationError("Backup SHA-256 file is missing")
    checksum_parts = checksum_file.read_text(encoding="ascii").strip().split()
    if not checksum_parts:
        raise VerificationError("Backup SHA-256 file is empty")
    expected_checksum = checksum_parts[0]
    actual_checksum = sha256_file(archive)
    if not re.fullmatch(r"[0-9a-f]{64}", expected_checksum):
        raise VerificationError("Backup SHA-256 file has invalid contents")
    if actual_checksum != expected_checksum:
        raise VerificationError("Backup checksum mismatch")
    if manifest.get("sha256") != expected_checksum:
        raise VerificationError("Manifest SHA-256 does not match the checksum file")
    return directory, archive, manifest


def validate_manifest(manifest: object) -> None:
    if not isinstance(manifest, dict):
        raise VerificationError("Backup manifest must contain a JSON object")
    required = {
        "backup_timestamp",
        "postgresql_version",
        "pg_dump_version",
        "application_git_commit",
        "alembic_revision",
        "database_identity",
        "counts",
        "backup_format",
        "backup_format_version",
        "sha256",
    }
    missing = sorted(required - manifest.keys())
    if missing:
        raise VerificationError(f"Backup manifest is missing fields: {', '.join(missing)}")
    if manifest["backup_format"] != BACKUP_FORMAT:
        raise VerificationError("Unsupported backup format")
    if manifest["backup_format_version"] != BACKUP_FORMAT_VERSION:
        raise VerificationError("Unsupported backup format version")
    if not isinstance(manifest["database_identity"], dict):
        raise VerificationError("Manifest database_identity must be an object")
    if not isinstance(manifest["counts"], dict):
        raise VerificationError("Manifest counts must be an object")
    fingerprints = manifest.get("uuid_fingerprints")
    if fingerprints is not None and not isinstance(fingerprints, dict):
        raise VerificationError("Manifest uuid_fingerprints must be an object")
    if fingerprints is not None and any(
        not isinstance(key, str)
        or not isinstance(value, str)
        or not re.fullmatch(r"[0-9a-f]{32}", value)
        for key, value in fingerprints.items()
    ):
        raise VerificationError("Manifest contains an invalid UUID fingerprint")
    counts = manifest["counts"]
    for key, value in counts.items():
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise VerificationError(f"Manifest count '{key}' is invalid")
    missing_counts = set(LEGACY_COUNT_KEYS) - counts.keys()
    if missing_counts:
        raise VerificationError(f"Manifest is missing counts: {', '.join(sorted(missing_counts))}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _database_snapshot(postgres: ComposePostgres, database: str) -> tuple[dict, dict]:
    metadata = postgres.query_json(database, METADATA_SQL)
    counts = postgres.query_json(database, LEGACY_COUNTS_SQL)
    if set(counts) != set(LEGACY_COUNT_KEYS):
        raise BackupError("PostgreSQL returned an unexpected count set")
    for table in application_table_names():
        counts[f"table:{table}"] = postgres.count(
            database, TABLE_COUNTS_SQL.format(table=table)
        )
    return metadata, counts


def _uuid_fingerprints(postgres: ComposePostgres, database: str) -> dict[str, str]:
    """Hash ordered UUID values for every UUID column in application tables."""
    tables = set(application_table_names())
    fingerprints: dict[str, str] = {}
    for line in postgres.query(database, UUID_COLUMNS_SQL).splitlines():
        table, separator, column = line.partition("\t")
        if not separator or table not in tables:
            continue
        if not re.fullmatch(r"[a-z_][a-z0-9_]*", table) or not re.fullmatch(
            r"[a-z_][a-z0-9_]*", column
        ):
            raise BackupError("PostgreSQL returned an invalid UUID column name")
        quoted_table = f'"{table}"'
        quoted_column = f'"{column}"'
        sql = (
            f"SELECT md5(coalesce(string_agg({quoted_column}::text, ',' "
            f"ORDER BY {quoted_column}::text), '')) FROM {quoted_table};"
        )
        fingerprint = postgres.query(database, sql)
        if not re.fullmatch(r"[0-9a-f]{32}", fingerprint):
            raise BackupError("PostgreSQL returned an invalid UUID fingerprint")
        fingerprints[f"{table}.{column}"] = fingerprint
    return fingerprints


def _safe_backup_root(value: str | None) -> Path:
    root = Path(value).expanduser() if value else DEFAULT_BACKUP_DIR
    root = root.resolve()
    try:
        root.relative_to(REPOSITORY_ROOT)
    except ValueError:
        pass
    else:
        raise BackupError("Backup directory must be outside the repository")
    return root


def create_backup(*, source_database: str, backup_root: str | None = None) -> Path:
    _validate_database_name(source_database)
    postgres = ComposePostgres.connect()
    before_metadata, before_counts = _database_snapshot(postgres, source_database)
    before_uuid_fingerprints = _uuid_fingerprints(postgres, source_database)
    print(f"Source database: {before_metadata['database']}")
    active_count = postgres.count(source_database, ACTIVE_EXECUTIONS_SQL)
    if active_count:
        raise BackupError(
            f"Refusing Virtual Company database backup: {active_count} workflow execution(s) "
            "are QUEUED or RUNNING"
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

        after_metadata, after_counts = _database_snapshot(postgres, source_database)
        after_active_count = postgres.count(source_database, ACTIVE_EXECUTIONS_SQL)
        after_uuid_fingerprints = _uuid_fingerprints(postgres, source_database)
        if (
            after_active_count
            or before_metadata != after_metadata
            or before_counts != after_counts
            or before_uuid_fingerprints != after_uuid_fingerprints
        ):
            raise BackupError(
                "Source database changed during backup; retry while workflows and "
                "database writes are quiescent"
            )
        if before_metadata["alembic_revision"] != current_alembic_head():
            raise BackupError(
                "Source Alembic revision does not match this checkout; refusing backup"
            )

        checksum = sha256_file(archive)
        manifest = {
            "backup_timestamp": timestamp.isoformat(),
            "postgresql_version": before_metadata["postgresql_version"],
            "pg_dump_version": postgres.version("pg_dump"),
            "application_git_commit": current_git_commit(),
            "alembic_revision": before_metadata["alembic_revision"],
            "database_identity": {
                "database": before_metadata["database"],
                "compose_service": "postgres",
            },
            "counts": before_counts,
            "uuid_fingerprints": before_uuid_fingerprints,
            "description": "Complete Virtual Company application database snapshot",
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
    expected_head = current_alembic_head()
    if manifest["alembic_revision"] != expected_head:
        raise RestoreError(
            "Schema revision mismatch: backup has "
            f"{manifest['alembic_revision']}, this checkout expects {expected_head}. "
            "No migrations were run."
        )
    current_commit = current_git_commit()
    if current_commit != "unknown" and manifest["application_git_commit"] != current_commit:
        print(
            "Warning: backup application commit differs from this checkout "
            f"({manifest['application_git_commit']} vs {current_commit}); "
            "the Alembic schema revision matches.",
            file=sys.stderr,
        )

    postgres = ComposePostgres.connect()
    target_meta = postgres.query_json(postgres.default_database, "SELECT json_build_object('postgresql_version', current_setting('server_version'))::text;")
    if _postgres_major(str(manifest["postgresql_version"])) != _postgres_major(
        str(target_meta["postgresql_version"])
    ):
        raise RestoreError(
            "PostgreSQL major version mismatch: backup uses "
            f"{manifest['postgresql_version']}, target server uses "
            f"{target_meta['postgresql_version']}"
        )
    source_database = str(manifest["database_identity"].get("database", ""))
    if target_database == source_database:
        raise RestoreError("Target database must differ from the backup source database")
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
            f"Restore failed. The isolated target database was left in place for "
            f"inspection: {target_database}. Details: {error}"
        ) from error

    print(f"Database restored: {target_database}")
    print("Running read-only post-restore verification...")
    try:
        verify_backup(backup=backup, target_database=target_database)
    except (BackupError, VerificationError) as error:
        raise RestoreError(
            f"Restore completed but verification failed. Target database remains "
            f"isolated for inspection: {target_database}. Details: {error}"
        ) from error


def _relationship_results(postgres: ComposePostgres, database: str) -> dict[str, int]:
    results = postgres.query_json(database, INTEGRITY_SQL)
    converted: dict[str, int] = {}
    for key, value in results.items():
        if not isinstance(value, int):
            raise VerificationError(f"Integrity check returned invalid value for {key}")
        converted[key] = value
    return converted


def verify_backup(*, backup: str, target_database: str) -> dict[str, object]:
    _validate_database_name(target_database)
    _, archive, manifest = load_manifest(backup)
    postgres = ComposePostgres.connect()
    with archive.open("rb") as input_stream:
        postgres.inspect_archive(input_stream)
    metadata, counts = _database_snapshot(postgres, target_database)
    if metadata["alembic_revision"] != manifest["alembic_revision"]:
        raise VerificationError(
            "Alembic revision mismatch: expected "
            f"{manifest['alembic_revision']}, found {metadata['alembic_revision']}"
        )
    mismatched_counts = {
        key: {"expected": expected, "actual": counts.get(key)}
        for key, expected in manifest["counts"].items()
        if counts.get(key) != expected
    }
    if mismatched_counts:
        raise VerificationError(f"Database counts differ from manifest: {mismatched_counts}")
    expected_uuid_fingerprints = manifest.get("uuid_fingerprints")
    if expected_uuid_fingerprints is not None:
        actual_uuid_fingerprints = _uuid_fingerprints(postgres, target_database)
        if actual_uuid_fingerprints != expected_uuid_fingerprints:
            raise VerificationError("UUID values differ from the backup manifest")

    relationships = _relationship_results(postgres, target_database)
    invalid_relations = {
        key: relationships[key]
        for key in RESEARCH_ERROR_CHECK_KEYS
        if relationships[key] != 0
    }
    unvalidated_foreign_keys = postgres.count(target_database, FOREIGN_KEY_SQL)
    if unvalidated_foreign_keys:
        invalid_relations["unvalidated_foreign_key_count"] = unvalidated_foreign_keys
    if invalid_relations:
        raise VerificationError(f"Virtual Company database integrity checks failed: {invalid_relations}")
    if counts["completed_research_run_count"] < 1:
        raise VerificationError("Database contains no completed Research runs")
    if relationships["completed_run_eligible_company_count"] < 1:
        raise VerificationError(
            "No company from a completed Research run is available to Exploration"
        )

    summary = {
        "database": metadata["database"],
        "alembic_revision": metadata["alembic_revision"],
        "counts": counts,
        "relationships": relationships,
    }
    print(f"Verification passed for database: {metadata['database']}")
    print(f"Alembic revision: {metadata['alembic_revision']}")
    for key, value in counts.items():
        print(f"{key}: {value}")
    print(
        "Exploration-eligible company selections in completed Research runs: "
        f"{relationships['completed_run_eligible_company_count']}"
    )
    print(
        "Qualification evidence references checked: "
        f"{relationships['qualification_evidence_reference_count']}"
    )
    return summary


def _environment_value(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in {None, ""} else default


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] not in {"backup", "restore", "verify"}:
        print("Usage: virtual_company_backup.py {backup|restore|verify}", file=sys.stderr)
        return 2
    command = args[0]
    try:
        if command == "backup":
            source = _environment_value("SOURCE_DB", "virtual_company")
            output = create_backup(
                source_database=str(source),
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
            target = _environment_value("TARGET_DB")
            if not backup:
                raise VerificationError("BACKUP is required")
            if not target:
                raise VerificationError("TARGET_DB is required")
            verify_backup(backup=backup, target_database=target)
        return 0
    except (BackupError, RestoreError, VerificationError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
