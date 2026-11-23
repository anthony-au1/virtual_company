# Development and Operations

This guide maps safe development and operations. The root `README.md` remains
the command-level quickstart and full backup/restore runbook; link there rather
than keeping two competing copies of long command sequences.

## Prerequisites and local startup

The repository targets Python 3.12 with `uv`, Node.js 20.9 or newer with
Corepack/pnpm, and Docker Compose for the complete stack. Use root README for
environment setup and startup commands. Native frontend development can use
the Docker backend while Next runs locally; `BACKEND_API_URL` is server-only.
Do not print or commit backend `.env` or local frontend environment-file values.

## Compose services and persistence

`docker-compose.yml` defines frontend, FastAPI app, worker, Redis, and
PostgreSQL services. PostgreSQL uses a Compose volume; Redis carries worker
messages. A database restore does not restore Redis pending messages. Inspect
the resolved local Compose config and environment examples before operational
changes; this guide does not authorize modifying a running environment.

## Configuration and migrations

- Backend settings: `src/virtual_company/config.py`, `.env.example`.
- Frontend environment validation: `frontend/src/lib/schemas/environment.ts`,
  `frontend/.env.example`.
- Compose: `docker-compose.yml`.
- Schema source: `src/virtual_company/db/models.py` and `alembic/versions/`.
- Alembic setup: `alembic.ini`, `alembic/env.py`.

Important backend environment-variable families (names only; defaults and
constraints are defined in `config.py` and `.env.example`):

- Database and queue: `DATABASE_URL`, `TASKIQ_REDIS_URL`, `TASKIQ_STREAM_NAME`,
  `TASKIQ_CONSUMER_GROUP`, `TASKIQ_WORKER_CONCURRENCY`,
  `TASKIQ_HEARTBEAT_INTERVAL_SECONDS`, `TASKIQ_RUNNING_STALE_AFTER_SECONDS`,
  `TASKIQ_QUEUED_STALE_AFTER_SECONDS`, `TASKIQ_RECONCILIATION_ENABLED`.
- Provider selection and credentials: `LLM_PROVIDER`, role-specific
  `LLM_*_PROVIDER`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `WEB_SEARCH_PROVIDER`,
  `TAVILY_API_KEY`, `EXA_API_KEY`.
- Models and call limits: `OPENAI_*_MODEL`, `ANTHROPIC_*_MODEL`, token/retry
  settings, `WEB_SEARCH_*`, `WEB_FETCH_*`, and Exploration extraction limits.
- Observability: `LOG_LEVEL`, `LOG_FORMAT`, `OTEL_ENABLED`, `OTEL_SERVICE_NAME`,
  and `LANGFUSE_*`.
- Frontend backend origin: `BACKEND_API_URL` (server-side only).

Do not copy values from environment files into docs. The frontend package name
still contains the historical `virtual-consultancy-frontend` identifier; the
canonical product-facing name is Virtual Company.

Use the Makefile migration target or the root instructions. For schema changes,
the repository convention requires an Alembic migration; do not treat editing
models alone as a complete schema change. The database guide describes source
schema and does not certify a deployed database's revision.

## Tests, lint, and builds

Root Makefile commands include `make test`, `make lint`, `make check`, and
`make build`; frontend targets include `make frontend-test`,
`make frontend-lint`, `make frontend-build`, and Playwright E2E targets. The
direct backend test command in root `AGENTS.md` is `uv run pytest`. Inspect
`Makefile`, `pyproject.toml`, `frontend/package.json`, and fixtures to determine
what a target invokes and whether it needs services. Test trees are `tests/`
and `frontend/src/**/*.test.*`; E2E tests are in `frontend/tests/e2e/`.

Do not run suites that can mutate a developer/production database or invoke
live providers without inspecting fixtures/environment and obtaining the
necessary explicit authorization. Documentation-only work normally needs link
and reference checks, not application tests.

## Workers and diagnostics

The app lifespan and worker are separate processes. README documents
`make taskiq-probe` and worker lifecycle operations. The probe checks queue
infrastructure without invoking Research/Exploration provider workflows.
Research log/telemetry/cost commands parse local retained application logs;
provider cost is unavailable if usage data was not recorded. See
[Workflow execution](workflow-execution.md) for stale-run semantics.

## Backup, restore, and recovery

Root README contains the authoritative backup, disposable restore, verification,
and disaster-recovery procedures, including their fail-closed safety behavior
and data limitations. The scripts are in `scripts/`. These operations may
create databases or alter local services; do not execute them during routine
documentation validation. Backups contain application data and should not be
committed.

