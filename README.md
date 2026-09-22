## Run

docker compose up --build uv run alembic upgrade head

uv run uvicorn virtual_company.main:app --reload

## Observability

Application events use standard logging (`LOG_FORMAT=console` locally or `json` for
machine-readable output). OpenTelemetry records workflow, node, HTTP, and LLM spans
plus lightweight metrics. Langfuse is optional and disabled by default.

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
`WEB_FETCH_CONCURRENCY`, and `COMPANY_RESEARCH_MAX_FETCHES_PER_COMPANY`.

## Qualification

After every company investigation is terminal, `qualify_companies` evaluates all
persisted Evidence for each researched company, including evidence from earlier
runs. Coverage remains a separate current-run presence check. Both stages share
conservative subject normalization and the one-way Spring Boot → Spring implication.

Qualification uses no LLM, search, or page fetch. Criteria are MATCH, MISMATCH, or
UNKNOWN; missing evidence never means mismatch. Any explicit mismatch produces
NOT_QUALIFIED, otherwise unknown criteria produce INSUFFICIENT_EVIDENCE, otherwise
QUALIFIED (including a campaign with no configured criteria). Narrow subject-bound
negative claims are supported; ambiguous wording and contradictory evidence remain
UNKNOWN. Size qualification accepts exact employee counts and inclusive, optionally
one-sided bounds; approximate counts and ranges are not interpreted.

Results and supporting evidence IDs are transient in LangGraph's
`company_qualifications` state. They do not change campaign-target records or the
public research response. Company qualification spans contain status and criterion
counts, never source documents. Evidence extraction continues to request positive
facts; qualification does not add further research or change extraction semantics.
