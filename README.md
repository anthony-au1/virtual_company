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
`search_company_sources`. The latter should contain company-correlated provider searches
and candidate URLs only; it does not fetch pages or create Evidence records.
