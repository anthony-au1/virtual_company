# Exploration Workflow

## Purpose and definition

An Exploration investigates Research companies to address a business decision,
problem, goal, capabilities, or constraints expressed in its `business_context`.
Creating an Exploration generates shared, system-managed Research Obligations
from that context and `max_obligations`. An empty obligation set is allowed
when no meaningful company-applicable question can be generated. Name is
descriptive and does not drive obligation generation. Before a run exists,
context and obligation limit can be changed with regenerated obligations;
after a run exists, definition inputs are immutable. See
`services/obligation_generator.py` and `services/exploration.py`.

An obligation is a question/condition applied to each selected company, not a
company-specific generated question. Exploration remains company-focused.

## Research Run selection and company snapshot

Run creation selects exactly one completed ResearchRun and one or more
companies present in that run's qualification snapshot. The qualification
status does not gate selection. Service validation checks source-run completion
and membership. Run creation persists an `ExplorationRun` and
`ExplorationCompany` rows in one transaction; it saves a READY run and does not
start provider work.

In the UI, **Save for Later** leaves that run READY. **Save & Execute** saves
the selection, then calls the execution endpoint; execution is a separate
queued action. If the request response is ambiguous, the UI refreshes persisted
status instead of assuming execution did or did not start. Inspect
`frontend/src/features/exploration/components/new-exploration-run-page.tsx`
and `services/exploration.py` before changing this contract.

## Run lifecycle and graph

ExplorationRun statuses are `READY`, `QUEUED`, `RUNNING`, `COMPLETED`,
`PARTIAL`, `FAILED`, and `CANCELLED`. `READY` represents saved work awaiting
execution; TaskIQ lifecycle then owns queued/running execution. The graph in
`src/virtual_company/workflows/exploration/graph.py` uses conditional routes:

1. `load_context` validates run, source ResearchRun, selected company snapshot,
   obligations, and execution ownership.
2. `select_company` and `select_obligation` iterate selected companies and
   shared obligations.
3. For a company-obligation pair, `generate_queries` may skip if it yields no
   queries; otherwise `search` may skip when there are no successful results;
   `fetch` may skip when no page is available; `extract_evidence` may skip when
   there is no extracted Evidence. Successful results are persisted and the
   graph advances to the next obligation.
4. After obligations for a company, the graph loads Evidence, extracts Facts
   when possible, persists them, reloads company Facts, and generates/persists
   Hypotheses when appropriate.
5. It advances to the next company and finally `finalize_run`.

The explicit skip branches mean a company/obligation can produce no record at
one or more stages without immediately aborting the whole graph. Fatal errors,
ownership loss, persistence failures, and final status are handled by node and
workflow lifecycle logic. A `COMPLETED` run means the graph finalized without
an execution-level terminal failure; `PARTIAL` is selected when recoverable
processing failures occurred or the count of completed company-obligation pairs
is below the expected count. Fetch failures are counted separately and do not
by themselves force `PARTIAL` in `finalize_run`, so a completed run does **not**
mean every external fetch succeeded, every obligation has Evidence, or claims
were independently verified. Fatal execution errors result in failure through
the adapter. See `ExplorationNodes.finalize_run` and adapter terminal handling.

## Evidence, Facts, Hypotheses, and traceability

- `ExplorationEvidence` belongs to one selected company and one obligation and
  stores a claim, supporting excerpt, and final fetched source URL (plus
  optional requested URL/title).
- `ExplorationFact` is a normalized statement linked to one or more Evidence
  rows through `exploration_fact_evidence`.
- `ExplorationHypothesis` is an analytical interpretation linked to one or
  more Facts through `exploration_hypothesis_fact`.

Evidence extraction, fact extraction, and hypothesis generation use model
services; the graph and persistence layer decide whether outputs exist and
validate their relationships. Hypotheses remain hypotheses, not verified
business facts. Some ownership checks are application-level: evidence company
and obligation must belong to the same Exploration; supporting Evidence for a
Fact and supporting Facts for a Hypothesis must resolve to the same selected
company. They supplement database FKs and association tables.

## API and frontend results

The API is in `src/virtual_company/api/explorations.py` under
`/api/v1/explorations`. Important operations include `POST /{exploration_id}/runs`
to save a selection, `POST /{exploration_id}/runs/{run_id}/execute` to enqueue,
`GET /{exploration_id}/runs/{run_id}` for status,
`GET /{exploration_id}/runs/{run_id}/companies` for selected companies, and
company-link `evidence`, `facts`, and `hypotheses` endpoints. It also provides
definition, obligation, and run-history operations. The frontend provides Exploration listing, editing,
ResearchRun/company selection, history and result details. Run status is
polled; result tabs display nested supporting records and paginate top-level
collections client-side. See [Frontend](../frontend.md) for exact route paths
and pagination details.

## Quality and known limits

Search provider output and fetched page text can be unavailable, low relevance,
or incomplete. Model-extracted text and hypotheses can misinterpret source
context even when references are persisted. The schema does not persist search
queries/provider snippets or complete fetched page bodies for Exploration
Evidence. There is no independent truth-verification stage implied by
COMPLETED. Evaluate quality from source excerpts and provenance rather than
record counts alone.

## Source map and tests

- Graph: `src/virtual_company/workflows/exploration/graph.py`, `nodes.py`, `state.py`, `models.py`, and `prompts.py`.
- API: `src/virtual_company/api/explorations.py`.
- Services: `src/virtual_company/services/exploration.py`, `obligation_generator.py`, and the `exploration_*` modules
  named in the workflow stages above.
- Persistence:
  `src/virtual_company/repositories/{exploration,exploration_run,exploration_company,exploration_obligation,exploration_evidence,exploration_fact,exploration_hypothesis,workflow_execution}.py`.
- Frontend: `frontend/src/features/exploration/` and App Router paths listed in [Frontend](../frontend.md).
- Tests: `tests/workflows/`, `tests/services/`, `tests/api/`, `tests/repositories/`,
  `frontend/src/features/exploration/**/*.test.tsx`, and `frontend/tests/e2e/exploration-save-execute.spec.ts`.
