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
builds and starts the complete Compose stack. Use `make backend-up` when only FastAPI
and PostgreSQL are needed, `make logs` to follow both application services, and
`make down` to stop the stack and remove its local database volume.

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
conservative subject normalization and the one-way Spring Boot → Spring implication.

Qualification uses no LLM, search, or page fetch. Criteria are MATCH, MISMATCH, or
UNKNOWN; missing evidence never means mismatch. Only required criteria determine
eligibility: any required mismatch produces NOT_QUALIFIED, otherwise a required
unknown produces INSUFFICIENT_EVIDENCE, otherwise the company is QUALIFIED. Preferred
results remain in the snapshot without changing status. Validated target-market,
industry, and technology Evidence satisfies its normalized criterion/subject without
reinterpreting claim or excerpt wording. Size qualification remains a deterministic
comparison over normalized employee-count facts and conservative bounds.

Results and supporting evidence IDs remain in LangGraph's
`company_qualifications` state and are persisted once all investigations terminate.
The `company_qualifications` table stores one final snapshot per run/company; retries
replace its status and criterion results without changing its ID or creation time.
Snapshots commit with run completion. They do not change campaign-target records
or the public research response. Company qualification spans contain status and criterion
counts, never source documents. Discovery sources pass through the normal attribution
and Evidence validation gates before company-specific searches. A required mismatch
stops that company's search; unknown required criteria receive priority, followed by
preferred enrichment within the configured investigation rounds. Evidence extraction
continues to request positive facts and qualification remains deterministic.

Inspect a completed run using the existing singular company table:

```sql
SELECT c.name, q.status, q.criteria_results
FROM company_qualifications q
JOIN company c ON c.id = q.company_id
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
