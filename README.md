# Virtual Company

Virtual Company combines a FastAPI research backend with a Next.js frontend for
company discovery, evidence-backed qualification, and business-context-driven
company exploration. The canonical agent-oriented architecture and workflow
documentation is indexed in [docs/README.md](docs/README.md).

## Prerequisites

- Docker with Docker Compose for the complete local stack
- Python 3.12 and `uv` for native backend development
- Node.js 20.9 or newer, Corepack, and the pnpm version pinned in
  `frontend/package.json` for native frontend development

## Run the application

Copy the backend environment example and provide any provider credentials needed by
the workflows:

```bash
cp .env.example .env
make start
```

OpenAI calls use `OPENAI_CONNECT_TIMEOUT_SECONDS` (default `5`),
`OPENAI_READ_TIMEOUT_SECONDS` (default `120`), and `OPENAI_MAX_RETRIES` (default
`1`). One retry permits up to two attempts for an individual SDK request. The HTTPX
read timeout limits inactivity while reading from the socket; it is not a guaranteed
end-to-end deadline, and retries, backoff, connection/write timeouts, and streaming
can affect total duration.

OpenAI structured responses have a provider-wide output limit of
`OPENAI_MAX_OUTPUT_TOKENS` (default `32768`); Research uses
`OPENAI_RESEARCH_MAX_OUTPUT_TOKENS` (default `4096`) unless that role override is
unset or blank, in which case it inherits the global limit. These are configurable
request limits, not verified capacity guarantees for every configured model;
responses marked incomplete fail safely. Empty/unset
`OPENAI_REASONING_EFFORT` and `OPENAI_RESEARCH_REASONING_EFFORT` omit the optional
Responses API reasoning parameter. Explicit reasoning values must be supported by
the selected model. Output limits include any reasoning tokens counted by the API.

Research uses `OPENAI_RESEARCH_MODEL` for query generation and
`OPENAI_EXTRACTION_MODEL` for candidate extraction, page attribution, and page
Evidence extraction. `OPENAI_QUALIFICATION_FACT_EXTRACTION_MODEL` independently
selects the model for Research Qualification Fact Extraction; when unset or empty,
it falls back to `OPENAI_EXTRACTION_MODEL`. Exploration Evidence and Fact extraction
use their separate `OPENAI_EXPLORATION_*_EXTRACTION_MODEL` settings.

The frontend is available at `http://localhost:3000`, and the FastAPI service remains
available directly at `http://localhost:8000`. `make start` migrates the database and
builds and starts the complete Compose stack, including the Taskiq worker and Redis.
Use `make backend-up` for the backend services, `make logs` to follow the app and
frontend, and `make down` to stop the stack. `make down` preserves PostgreSQL and Redis
volumes; `make down-reset` removes both local data volumes and should only be used
when intentionally resetting development data.

## Taskiq infrastructure probe

Redis Streams is available internally as `redis:6379`; Redis is not published on a
host port. The dedicated worker starts with one process and one concurrent task by
default. Change `TASKIQ_WORKER_CONCURRENCY` in `.env` to adjust async task concurrency.
The worker uses `TASKIQ_IDLE_TIMEOUT_MS` for pending-message reclaim (default 24 hours)
and `TASKIQ_RECLAIM_LOCK_TIMEOUT_SECONDS` for the reclaim lock. Keep the idle timeout
above expected task duration to avoid routine redelivery of a still-running task.
In the pinned Taskiq Redis broker, pending-message reclaim is checked after a stream
read returns messages. A restarted worker may therefore leave an old pending entry
untouched until another message arrives.

Start the backend and worker with `make backend-up`, then enqueue a harmless probe:

```bash
make taskiq-probe
```

For a bounded long-running probe, run:

```bash
docker compose exec worker uv run --no-dev python -m virtual_company.task_queue.enqueue_probe --sleep-seconds 20
```

The command prints the probe and Taskiq task IDs. Follow execution logs with
`docker compose logs -f worker`; verify broker readiness with
`docker compose exec redis redis-cli ping`. If the worker cannot connect, check
`docker compose ps`, `docker compose logs redis worker`, and confirm that the worker
uses `TASKIQ_REDIS_URL=redis://redis:6379/0`. The probe only emits safe lifecycle
events and does not access PostgreSQL or external providers.

To stop and restart only the worker without removing data:

```bash
docker compose stop worker
docker compose start worker
```

`docker compose stop worker` allows the configured graceful wait (default one hour).
Redis Streams may reclaim pending messages after the idle timeout, so delivery is not
exactly once. Duplicate Taskiq messages are guarded by the shared PostgreSQL execution
claim, so an already-claimed or terminal Research or Exploration run is not executed a
second time. A pending message may remain idle until new stream traffic causes the
broker to check for reclaim; reconciliation marks abandoned executions failed but does
not resume their graphs or automatically republish them. The automated suite does not
currently exercise this recovery behavior against live PostgreSQL and Redis.

## Frontend development

The frontend uses Next.js App Router, React 19, strict TypeScript, Tailwind CSS 4,
shadcn/ui backed by Base UI, and Lucide icons. The recommended native workflow keeps
Next.js hot reload outside Docker:

```bash
cp frontend/.env.example frontend/.env.local
make backend-up
make frontend-install
make frontend-dev
```

Corepack reads the pinned pnpm version automatically. Equivalent raw commands can be
run from `frontend/`, for example `corepack pnpm dev` or `corepack pnpm build`.

`BACKEND_API_URL` is server-only. Native development points it at the backend's host
address, while Compose uses the internal `http://app:8000` service address. Browser
requests use the same-origin `/api/backend` proxy, so Docker hostnames and secrets are
never exposed through `NEXT_PUBLIC_*`, and backend CORS is not required.

Research and Exploration have feature-owned API clients and use TanStack Query for
status polling, caching, and mutation invalidation. The same-origin proxy and
`apiFetch<T>` provide shared transport. The intended contract workflow is:

```text
Pydantic backend DTOs -> OpenAPI -> generated TypeScript types/client -> frontend
```

Large backend DTOs should not be duplicated manually. The frontend uses feature-based
Research/Campaign and Exploration modules, with thin App Router route files and shared
UI primitives. Local component state remains appropriate for transient form state.
React Hook Form with Zod can be considered when form complexity warrants it; Zod is
already available for schema and configuration validation.

## Checks and builds

Repository-level commands run the relevant backend and frontend checks:

```bash
make test
make lint
make check
make build
```

Targeted frontend commands are also available:

```bash
make frontend-test
make frontend-lint
make frontend-format
make frontend-format-check
make frontend-build
make frontend-e2e-install
make frontend-e2e
```

`frontend-e2e-install` installs the Playwright Chromium binary once. The production
frontend image uses Next.js standalone output and runs the built Node server rather
than the development server.

## Observability

Application events use structured logs with UTC timestamps and campaign/run
correlation fields. Select `LOG_FORMAT=json` for JSON output; console output includes
available structured context in a readable form. OpenTelemetry instrumentation
creates workflow, node, HTTP, and LLM spans and records lightweight metrics, but the
current providers have no configured span exporter or metric reader. Setting
`OTEL_ENABLED=true` alone therefore does not make traces or metrics available to an
external collector. Langfuse is optional and disabled by default; it can export
observations when explicitly configured.

The Research Workflow reports read the app container's retained Docker logs and
select the latest completed run by default:

```bash
make research-observability
make research-cost
make research-log
```

Select a particular execution with `make research-observability RUN_ID=<uuid>` or
filter for the latest completed run of a campaign with
`make research-cost CAMPAIGN_ID=<uuid>`. Tavily credits are displayed only when
the provider reports actual usage; unavailable credits and LLM token counts are
shown as `N/A`.

Set `LOG_FORMAT=json` in `.env` when machine-readable logs are useful, then restart
the app container before collecting new runs.

To enable Langfuse locally, set `LANGFUSE_ENABLED=true` plus its public/secret keys
and base URL in `.env`, then restart the app. Prompts and structured outputs are not
captured by default; normal logs never include them or credentials.

## Web search

Research uses one configured provider at a time. Tavily is the default:

```dotenv
WEB_SEARCH_PROVIDER=tavily
TAVILY_API_KEY=...
```

To compare the same campaign with Exa, change only the provider and key, then run a
new research request:

```dotenv
WEB_SEARCH_PROVIDER=exa
EXA_API_KEY=...
```

For a manual comparison, use equivalent campaigns such as Australian fintech companies (Java, Spring, Spring Boot;
100–5000 employees; target 10), then inspect search result
quality, discovered companies, workflow latency, and provider spans in tracing.

Company-specific source discovery runs after initial companies are persisted. For a manual
end-to-end check, create a small campaign targeting 2–3 Australian fintech companies with
Java and Spring criteria, then inspect the traces for `generate_company_queries` and
`search_company_sources`, `select_company_sources`, and `fetch_company_sources`. The latter
fetches a bounded set of company-correlated candidate URLs into readable transient page text;
it does not create Evidence records. Fetches are limited by `WEB_FETCH_TIMEOUT_SECONDS`,
`WEB_FETCH_MAX_RESPONSE_BYTES`, `WEB_FETCH_MAX_CONTENT_CHARS`,
`WEB_FETCH_CONCURRENCY`, `COMPANY_RESEARCH_SUCCESSFUL_FETCH_TARGET_PER_COMPANY`, and
`COMPANY_RESEARCH_FOLLOWUP_SUCCESSFUL_FETCH_TARGET_PER_COMPANY`.

## Qualification

Research qualification has four stages:

1. **Evidence collection:** the workflow searches for company sources, fetches selected
   pages, and validates evidence and company attribution.
2. **Fact extraction:** an LLM extracts evidence-grounded facts relevant to the configured
   criteria. It does not choose the final qualification status.
3. **Criterion evaluation:** application code deterministically evaluates the validated facts
   against each criterion. Company-size bounds are compared against validated employee-count
   facts; categorical facts are checked against their configured subject.
4. **Status aggregation:** application code calculates the overall qualification
   status from the individual criterion results after company investigations finish.

Configured campaign fields produce independent qualification criteria:

- Target market produces one criterion when configured.
- Industry produces one criterion when configured.
- Every keyword produces its own criterion.
- Configured minimum and maximum employee counts produce separate criteria.

Every generated criterion is required for a company to be `QUALIFIED`; there are no
required/preferred settings, scores, or qualification thresholds. Each criterion is `MATCH`
when evidence supports it, `MISMATCH` when evidence establishes a contradiction, or `UNKNOWN`
when available evidence is insufficient to establish either outcome. `UNKNOWN` is not the same
as `MISMATCH`.

| Criterion results                         | Overall status          |
|-------------------------------------------|-------------------------|
| Every criterion is `MATCH`                | `QUALIFIED`             |
| At least one criterion is `MISMATCH`      | `NOT_QUALIFIED`         |
| No `MISMATCH`, but at least one `UNKNOWN` | `INSUFFICIENT_EVIDENCE` |

For example, a company with eight matches, no mismatches, and two unknowns is
`INSUFFICIENT_EVIDENCE`: the unknown criteria prevent qualification, but do not establish a
contradiction.

Industry describes a company's business category, market segment, or principal business
activities. Evidence of actual products, services, and activities can establish industry
membership without an exact phrase match. Compound industry descriptions are interpreted
using campaign context; separators such as `/` do not automatically mean AND or OR, and
material qualifiers must still be supported. The campaign description helps clarify industry
intent; it is not evidence about a company. Unsupported or materially ambiguous industry
evidence remains `UNKNOWN`.

Keywords are not merely discovery hints: every keyword is an independent qualification
criterion. Evidence must support the specific requested concept and the company's own activity.
A related concept or topical mention alone is insufficient. For example, Spring Boot does not
imply Spring, and Apache Kafka does not imply Kafka. Missing evidence remains `UNKNOWN`, not a
`MISMATCH`.

Coverage remains a separate presence check, and both coverage and qualification use
conservative spelling/formatting normalization. Size qualification uses deterministic
comparisons over normalized employee-count facts and conservative bounds.

Results and supporting evidence IDs remain in LangGraph's
`research_company_qualifications` state and are persisted once all investigations terminate.
The `research_company_qualification` table stores one final snapshot per run/company; retries
replace its status and criterion results without changing its ID or creation time.
Snapshots commit with run completion. They do not change campaign-target records
or the public research response. Company qualification spans contain status and criterion
counts, never source documents. Discovery sources pass through the normal attribution
and Evidence validation gates before company-specific searches. Evidence collection follows
the configured search limits and unresolved criteria before final qualification; qualification
does not use required/preferred criteria or stop searches based on a criterion priority.

Inspect a completed run using the Research-scoped tables:

```sql
SELECT c.name, q.status, q.criteria_results
FROM research_company_qualification q
JOIN research_company c ON c.id = q.company_id
WHERE q.research_run_id = :research_run_id
ORDER BY c.name;
```

Apply the initial schema with `uv run alembic upgrade head` against an empty database.
Criterion JSON contains requirement levels and Evidence IDs, not source content.

## Virtual Company Database Backup & Restore

These utilities back up and restore one complete PostgreSQL application database
using PostgreSQL's native `pg_dump` and `pg_restore` tools. A custom-format dump
includes the selected database's schema and data, indexes, constraints, foreign
keys, triggers, sequences and their values, large objects, and Alembic version
table. PostgreSQL provides the complete object list; the script does not maintain a
table allowlist. Backups do not include other databases, cluster roles/tablespaces,
Redis queue state, or a full PostgreSQL cluster. The commands do not run application
workflows or call external providers.

### Prerequisites and backup location

- Docker Compose must already be running and the `postgres` service must be healthy.
- The scripts use PostgreSQL client tools inside that already-running container;
  backup, disposable restore, and verification do not start or restart services.
- Backups are written on the host to `$HOME/virtual-company-backups` by default,
  outside the repository and Docker-managed volumes. They survive
  `docker compose down -v`. Override with `BACKUP_DIR`.
- A backup directory contains `database.dump` (PostgreSQL custom format),
  `database.dump.sha256`, and `manifest.json`. The manifest records source identity
  without credentials, PostgreSQL/tool versions, Alembic revision, Git commit, and
  checksum. Backup files are private to the current host user.

### Create and identify a backup

The backup script refuses to start when it finds a queued or running workflow
execution. PostgreSQL `pg_dump` takes a transaction-consistent snapshot, so ordinary
concurrent database writes do not require application tables to be copied manually.

```bash
make virtual-company-backup
```

The command prints the timestamped backup directory. To choose another host path:

```bash
make virtual-company-backup BACKUP_DIR="$HOME/Backups/Virtual Company"
```

To back up a different database in the same Compose PostgreSQL server:

```bash
make virtual-company-backup SOURCE_DB=virtual_company
```

List and inspect backups without exposing credentials:

```bash
find "$HOME/virtual-company-backups" -mindepth 2 -maxdepth 2 \
  -name manifest.json -print
cat "$HOME/virtual-company-backups/<backup-directory>/manifest.json"
```

Do not commit backups to Git. They contain company data and source excerpts. Keep
them on a protected host or external storage location. Deleting Compose containers
and volumes, including with `docker compose down -v`, does not delete files in this
host directory.

### Restore into a new disposable database

Restore always creates a new database whose name starts with
`virtual_company_restore_`. It refuses all existing database names, so it cannot
replace the normal `virtual_company` database or any existing Exploration data.
There is no overwrite mode.

```bash
make virtual-company-restore \
  BACKUP="$HOME/virtual-company-backups/<backup-directory>" \
  TARGET_DB=virtual_company_restore_01
```

You may pass either the backup directory or its `database.dump` file. The manifest,
checksum, custom archive, and PostgreSQL major version are checked before creating
the target. Alembic revision and Git commit are informational; an older valid backup
is not rejected merely because this checkout has advanced. Restore does not run
migrations. The restore runs in one PostgreSQL transaction and stops on the first
error. If it fails, schema/data changes roll back and the newly created empty target
database remains for inspection; choose a different fresh target for the next
attempt. The source and any existing database are never dropped, replaced, or
cleaned.

### Verify the restored data

```bash
make virtual-company-verify \
  BACKUP="$HOME/virtual-company-backups/<backup-directory>"
```

Verification checks that the backup files and manifest exist, the archive is
nonempty, the SHA-256 checksum matches, and PostgreSQL can read the archive listing.
It does not restore the archive or prove that a full restore will succeed. Perform
an occasional restore into a new disposable database to validate recovery end to
end. `verify` does not require `TARGET_DB`.

### Recover a lost primary database

`virtual-company-recover` is for disaster recovery after losing the PostgreSQL data
volume. It restores a backup of the primary `virtual_company` database into the
fresh, uninitialized `virtual_company` database created by the local Compose
PostgreSQL initialization. It is separate from disposable restore: recovery never
accepts a restore target name and never replaces an existing database.

```bash
make virtual-company-recover \
  BACKUP="$HOME/virtual-company-backups/<backup-directory>"

make up
```

Recovery verifies the backup manifest/checksum and archive, checks that the resolved
Compose configuration is this repository's PostgreSQL 16 setup with its persistent
`postgres_data` volume, and refuses to continue while `app` or `worker` is running.
It starts only `postgres` if needed, waits for readiness, and refuses if the primary
database contains any user-created objects or Alembic state. An initialized schema is
refused even when its tables contain no application rows. The restore uses one
transaction and performs schema/catalog checks afterward without running migrations.
If recovery started PostgreSQL, it stops only that service afterward; the PostgreSQL
data volume is retained. If PostgreSQL was already running, its state is preserved.
The command never starts the application or worker and never removes volumes. A
successful recovery is then used by the normal `make up` flow without changing
`DATABASE_URL`; `make up` applies the repository's regular migrations before starting
the application stack.

Use the commands for these distinct purposes:

- `virtual-company-backup` creates a host-side database archive.
- `virtual-company-verify` checks archive files, checksum, and archive readability.
- `virtual-company-restore` restores to a new `virtual_company_restore_*` database for
  inspection and never touches the primary database.
- `virtual-company-recover` restores to the primary database only when it is
  demonstrably fresh and uninitialized.

If the Compose identity or database state is ambiguous, recovery fails closed. It is
not a replacement for keeping backups outside the Docker volume, and it does not
recover Redis queue state or cluster-global PostgreSQL roles/tablespaces.

The command-line entry points are `scripts/virtual_company_backup.py`,
`scripts/backup-virtual-company.sh`, `scripts/restore-virtual-company.sh`,
`scripts/verify-virtual-company.sh`, and `scripts/recover-virtual-company.sh`.

### Connect the application to a restored database

Restoring a database does **not** switch the running API or worker. The current
Compose file sets `DATABASE_URL` directly for both services, so changing `.env`
alone does not switch them. When you intentionally want to run the app against a
restored target, use a temporary Compose override and recreate only `app` and
`worker`:

```bash
TARGET_DB=virtual_company_restore_01
current_url="$(docker compose config --format json | python3 -c \
  'import json,sys; print(json.load(sys.stdin)["services"]["app"]["environment"]["DATABASE_URL"])')"
export RESTORE_DATABASE_URL="${current_url%/*}/$TARGET_DB"
override_file="$(mktemp)"
chmod 600 "$override_file"
cat >"$override_file" <<'YAML'
services:
  app:
    environment:
      DATABASE_URL: ${RESTORE_DATABASE_URL}
  worker:
    environment:
      DATABASE_URL: ${RESTORE_DATABASE_URL}
YAML
docker compose -f docker-compose.yml -f "$override_file" up -d app worker
rm -f "$override_file"
unset RESTORE_DATABASE_URL
```

This derives the existing local database URL from rendered Compose configuration,
changes only its database name, and keeps credentials out of the repository and
command output. The override is temporary; it does not change `docker-compose.yml`.
To return the API and worker to the normal development database, run:

```bash
docker compose up -d app worker
```

Compose may recreate the API and worker when switching either direction. Do not
point workers at a restored database while it contains unintended queued jobs. The
backup preflight checks for queued/running workflow rows; archive verification only
checks files and archive readability. Exploration execution itself can use external
providers and incur costs; backup, restore, and verification are provider-free.

### What happens to later Exploration results

A full database restore reproduces the database as it existed when the backup was
made. Exploration results created after that snapshot are not included in the
restored copy. Restoring to the separate `virtual_company_restore_*` database
leaves the original database and its later Exploration results intact. This tool
does not merge Research rows into an existing database.

### Troubleshooting

- **PostgreSQL service is unavailable:** start/repair it separately, then retry;
  backup and restore scripts intentionally do not start Compose services.
- **Active execution refusal:** wait for all Research and Exploration work to reach
  a terminal state, then run backup again.
- **Existing target refusal:** choose a different `virtual_company_restore_*` name.
  Existing databases are never dropped or cleaned automatically.
- **Checksum/archive failure:** retain the source backup, check the copied files,
  and do not attempt to use a partial backup.
- **PostgreSQL major version mismatch:** restore with a compatible PostgreSQL
  version. The script does not migrate the database or rewrite the archive.
