# Virtual Consultancy

Virtual Consultancy combines a FastAPI research backend with a Next.js frontend
foundation for campaign, evidence, and lead workflows.

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
exactly once. The shortened-timeout/redelivery scenarios are for isolated
infrastructure verification only; business workflow duplicate protection is a later
phase.

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

The proxy and `apiFetch<T>` are transport foundations only; product-specific clients
will be added with their screens. The intended contract workflow is:

```text
Pydantic backend DTOs -> OpenAPI -> generated TypeScript types/client -> frontend
```

Large backend DTOs should not be duplicated manually. Local component state is the
current UI-state strategy. Add TanStack Query when polling, caching, refetching, and
mutation invalidation become concrete requirements. Add React Hook Form with Zod when
the first real product form is implemented; Zod is already available for schema and
configuration validation.

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

Application events use structured JSON logs by default, with UTC timestamps and
campaign/run correlation fields. OpenTelemetry records workflow, node, HTTP, and LLM
spans plus lightweight metrics. Langfuse is optional and disabled by default.

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

If you already have a `.env` file created before JSON became the default, set
`LOG_FORMAT=json` there and restart the app container before collecting new runs.

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

For a manual comparison, use equivalent campaigns such as Australian fintech companies
(Java, Spring, Spring Boot; 100–5000 employees; target 10), then inspect search result
quality, discovered companies, workflow latency, and provider spans in tracing.

Live provider smoke tests are opt-in and never run under the normal suite:

```bash
RUN_WEB_SEARCH_INTEGRATION_TESTS=true TAVILY_API_KEY=... uv run pytest tests/integration/test_web_search_live.py
```

Replace the provider/key prefix with `WEB_SEARCH_PROVIDER=exa EXA_API_KEY=...` to smoke-test Exa.

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

After every company investigation is terminal, `qualify_companies` evaluates validated
Evidence from the current research run for each company. Coverage remains a separate
presence check. Both stages share
conservative spelling/formatting normalization. Keyword criteria are independent:
Spring Boot does not imply Spring, and Apache Kafka does not imply Kafka.

Qualification uses no LLM, search, or page fetch. Criteria are MATCH, MISMATCH, or
UNKNOWN; missing evidence never means mismatch. Only required criteria determine
eligibility: any required mismatch produces NOT_QUALIFIED, otherwise a required
unknown produces INSUFFICIENT_EVIDENCE, otherwise the company is QUALIFIED. Preferred
results remain in the snapshot without changing status. Validated target-market,
industry, and keyword Evidence satisfies its normalized criterion/subject without
reinterpreting claim or excerpt wording. Size qualification remains a deterministic
comparison over normalized employee-count facts and conservative bounds.

Results and supporting evidence IDs remain in LangGraph's
`research_company_qualifications` state and are persisted once all investigations terminate.
The `research_company_qualification` table stores one final snapshot per run/company; retries
replace its status and criterion results without changing its ID or creation time.
Snapshots commit with run completion. They do not change campaign-target records
or the public research response. Company qualification spans contain status and criterion
counts, never source documents. Discovery sources pass through the normal attribution
and Evidence validation gates before company-specific searches. A required mismatch
stops that company's search; unknown required criteria receive priority, followed by
preferred enrichment within the configured investigation rounds. Evidence extraction
continues to request positive facts and qualification remains deterministic.

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

Run the opt-in PostgreSQL snapshot test with
`RUN_QUALIFICATION_DB_TESTS=true uv run pytest tests/integration/test_qualification_postgres.py`.
It uses an isolated temporary schema and removes it after the test. Set
`QUALIFICATION_TEST_DATABASE_URL` to override the default local PostgreSQL URL.
Run the isolated initial-migration check with
`RUN_MIGRATION_DB_TESTS=true uv run pytest tests/integration/test_initial_migration_postgres.py`.
