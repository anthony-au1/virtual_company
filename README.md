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
