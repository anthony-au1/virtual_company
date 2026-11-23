# AI and External Integrations

## LLM abstraction and configuration

Provider interfaces and implementations are under `src/virtual_company/llm/`.
The repository includes OpenAI and Anthropic providers, provider registry,
role configuration, prompt utilities, instrumentation, and usage accounting.
`src/virtual_company/config.py` defines configuration; model and role defaults
can vary by environment. Never copy `.env` contents or credentials into docs,
logs, examples, or generated reports.

Workflow prompt definitions are in `workflows/research/prompts.py` and
`workflows/exploration/prompts.py`; reusable/specialized prompts also live near
service functions. Structured output models constrain parsing/shape, but do not
guarantee factual correctness.

## Where model reasoning is used

- Research uses models for query/candidate/source interpretation and
  Evidence/qualification fact extraction. Final qualification status is
  calculated by deterministic application logic in
  `services/qualification.py`.
- Exploration uses models for obligation generation, query generation, Evidence
  extraction, Fact extraction, and Hypothesis generation. Graph routing,
  persistence, ownership validation, and lifecycle status are application
  logic.

The above is a high-level map; inspect each workflow graph and service before
changing call counts or semantics.

## Search and page retrieval

`src/virtual_company/tools/web_search.py` defines the search contract;
`exa_web_search.py` and `tavily_web_search.py` provide adapters, selected via
configuration/registry. Search results are candidate sources and do not by
themselves constitute persisted Evidence.

Fetching is defined by `tools/web_fetch.py` and implemented through
`httpx_web_fetch.py`; instrumentation wrappers record activity. Fetch limits
include timeout, response-byte/content-character bounds, and concurrency
settings. URL normalization is in `utils/url_normalization.py`. Inspect the
current implementation/tests for redirect, scheme, address/range, and response
handling before making security claims or changing fetch behavior.

`HttpxWebFetchTool` in `tools/httpx_web_fetch.py` accepts only absolute HTTP(S)
URLs without embedded credentials, resolves the host, rejects non-public/special
IP destinations, and connects to an already approved numeric address. Redirects
are not followed automatically: each hop is validated and limited to five
redirects. The client disables environment proxy trust, accepts HTML/plain text,
and bounds timeout, response bytes, and extracted text length. URL normalization
and telemetry sanitization are in `utils/url_normalization.py`. These are
concrete SSRF/resource controls, not a guarantee against every deployment-level
network policy issue. Test coverage is in `tests/tools/` and
`tests/services/test_exploration_fetch.py`; tests should use mocked providers
and local fixtures, not live company pages.

## Observability and usage

`src/virtual_company/observability/` provides structured logs and workflow/node,
HTTP, and LLM instrumentation. LLM usage accounting is under `llm/usage.py` and
instrumented provider modules. Web tools have instrumented search/fetch
wrappers. Optional OpenTelemetry and Langfuse behavior is configured in the
runtime/configuration. README states the current OpenTelemetry provider setup
does not include a configured span exporter or metric reader; therefore
`OTEL_ENABLED=true` alone does not export data. Langfuse is optional and
requires explicit configuration. Review current config and runtime before
relying on this operational limitation.

Research-oriented observability scripts/Make targets summarize retained logs;
they are not proof of provider billing. Token counts/costs may be unavailable
when providers do not report usage. See README “Observability.”

## Offline verification

Use unit tests with mocked provider clients, deterministic fixtures, and local
fetch fixtures. Examples include `tests/llm/`, `tests/tools/`,
`tests/services/test_exploration_search.py`, and
`tests/services/test_exploration_fetch.py`. Do not run provider-backed tests or
real web searches as a routine documentation or code check unless explicitly
requested and safely configured.
