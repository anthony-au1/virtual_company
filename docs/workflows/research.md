# Research Workflow

## Purpose and contract

Research turns a Campaign into a persisted set of discovered companies,
source-backed company Evidence, and qualification snapshots. A ResearchRun is
the business record for one execution. Exploration consumes a completed run's
company/qualification results but does not mutate them.

## Campaign configuration and lifecycle

Campaign fields and validation are defined by API schemas/services and
`src/virtual_company/db/models.py`. The campaign includes criteria such as
target market, industry, keywords and employee bounds, plus target count and a
maximum number of companies to investigate. `CampaignService` seals criteria
when research starts; inspect `services/campaign.py` and
`services/research.py` for mutability and run-start rules. The DB check
`max_companies_to_research >= target_count` is not a replacement for API-level
validation.

Users create/update campaigns through `POST`, `GET`, and `PATCH
/api/v1/campaigns`. `POST /api/v1/campaigns/{campaign_id}/research` queues a
Research Run and returns HTTP 202. Run history and results are
`GET /api/v1/research-runs` and `GET /api/v1/research-runs/{run_id}/results`;
company profile/Evidence routes are under `/api/v1/companies`. See
`api/campaigns.py`, `api/research_runs.py`, `api/research_companies.py`, and
[Frontend](../frontend.md) for the UI journey.

## Graph execution

`src/virtual_company/workflows/research/graph.py` compiles a fixed graph with
conditional iteration rather than one simple linear pass:

1. `load_campaign` and `create_research_run` establish context and run state.
2. `generate_search_queries` → `search_web` → `extract_company_candidates` →
   `aggregate_company_candidates` → `rank_company_candidates` →
   `persist_companies` create a ranked candidate supply.
3. `reuse_discovery_sources` prepares initial candidate sources. The
   investigation loop runs `generate_company_queries` (or
   `generate_followup_queries`) → `search_company_sources` →
   `select_company_sources` → `fetch_company_sources` →
   `validate_company_page_attribution` → `extract_company_evidence` →
   `persist_evidence` → `check_evidence_coverage`.
4. Coverage routing either launches follow-up research, advances to
   qualification when no company remains active, or continues initial company
   investigation. Qualification extracts criterion-relevant semantic facts,
   evaluates them deterministically, and persists run/company snapshots.
5. Candidate-pool routing refills from the remaining ranked candidates until
   target count, research cap, or candidate supply ends; then the graph
   completes the ResearchRun.

Consult graph edges and `route_investigation`, `route_candidate_pool`, and
`_research_run_stop_reason` for exact conditions. Node-level failures are
wrapped by `_with_failure_handling`; they are not equivalent to every company
having produced complete Evidence.

## Search, sources, and qualification

Discovery results are not automatically accepted as company evidence.
Company-specific page attribution is validated before extracted Evidence is
persisted. Coverage/follow-up logic is distinct from qualification: coverage
checks required evidence presence, while qualification maps validated facts to
criterion outcomes. Criterion outcomes include `MATCH`, `MISMATCH`, and
`UNKNOWN`; overall outcomes are `QUALIFIED`, `NOT_QUALIFIED`, and
`INSUFFICIENT_EVIDENCE`. `UNKNOWN` means evidence is insufficient, not a
contradiction. See README's Qualification section and
`services/qualification.py`.

Persisted Research outputs include `research_company`, `research_evidence`,
`research_run`, and `research_company_qualification`. Qualification snapshots
contain criterion results and evidence UUID strings in JSON; they do not
duplicate Evidence content. Exact column relationships are in
[Database schema](../database-schema.md).

## Research-to-Exploration handoff

Exploration requires a completed ResearchRun and selects companies represented
in its persisted qualification snapshot. Application validation checks run
membership; qualification status does not gate eligibility. Selected
`research_company` rows are associated to an `exploration_run` through
`exploration_company`. This is a reference/snapshot of selected companies, not
a copy of their profiles. See
[Exploration Workflow](exploration.md#research-run-selection-and-company-snapshot).

## Failures and status

ResearchRun business statuses include `QUEUED`, `RUNNING`, `COMPLETED`, and
`FAILED` in current code paths; the status column is a string, not a DB enum or
status check. Shared `workflow_execution` statuses have their own constraint.
Worker failures are recorded through the shared execution lifecycle and
business service. Stale execution reconciliation marks eligible stale records
failed; it does not resume a graph. See [Workflow execution](../workflow-execution.md).

## Source map and tests

- Graph and state: `src/virtual_company/workflows/research/graph.py`, `nodes.py`, `state.py`, `models.py`, and
  `prompts.py`.
- API: `src/virtual_company/api/campaigns.py`, `research_runs.py`, and `research_companies.py`.
- Services: `src/virtual_company/services/campaign.py`, `research.py`, `research_results.py`, `qualification.py`,
  `qualification_evidence_extractor.py`, and `coverage.py`.
- Persistence: `src/virtual_company/repositories/` (campaign, company, evidence, run, qualification, workflow
  execution).
- Tests: `tests/workflows/`, `tests/services/`, `tests/api/`, `tests/repositories/`, `tests/llm/`, and `tests/tools/`;
  exact cases are discoverable by filename and test names.

