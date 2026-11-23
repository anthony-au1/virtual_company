# Architecture Decisions and Evidence

This document records implementation choices and only asserts historical
rationale where repository evidence supports it. **Inference** means the code
shows a design choice but not why it was originally made. No prior discussion
or decision log was found to substantiate unrecorded history.

## Separate Research and Exploration workflows

- **Decision:** Research discovers/investigates companies and qualifies them;
  Exploration investigates selected Research companies against a separate
  Business Context and obligations.
- **Context/problem:** Campaign qualification and contextual follow-on analysis
  have different inputs, outputs, and run lifecycles.
- **Rationale:** **Inference:** separate graphs, API modules, persistence
  entities, and run records isolate their responsibilities and allow an
  Exploration to reference a Research result set.
- **Consequences/trade-offs:** A handoff and eligibility validation are needed;
  data is not one continuous mutable workflow record.
- **Status:** Implemented.
- **Evidence:** `workflows/research/`, `workflows/exploration/`,
  `api/campaigns.py`, `api/explorations.py`, `services/exploration.py`,
  `ExplorationRun.research_run_id` in `db/models.py`.

## Shared TaskIQ and LangGraph execution

- **Decision:** Both workflow types dispatch through shared TaskIQ execution
  infrastructure and invoke workflow-specific LangGraph adapters/graphs.
- **Context/problem:** Long-running provider-backed work should run outside the
  request/response path.
- **Rationale:** **Inference:** a common worker lifecycle reduces duplicated
  queue/ownership handling while adapters keep graph invocation workflow-aware.
- **Consequences/trade-offs:** Redis message delivery and PostgreSQL execution
  state must be coordinated; queue redelivery is not graph resume.
- **Status:** Implemented for Research and Exploration.
- **Evidence:** `task_queue/{broker,dispatcher,tasks,lifecycle,reconciliation}.py`,
  `task_queue/adapters/`, `repositories/workflow_execution.py`.

## Business Run separated from WorkflowExecution

- **Decision:** `research_run`/`exploration_run` store business-facing run data;
  `workflow_execution` stores common worker execution ownership and status.
- **Context/problem:** Workflow execution is shared across two run models, but
  business fields and output relationships differ.
- **Rationale:** **Inference:** separating these records allows shared execution
  mechanics without merging domain-specific schemas.
- **Consequences/trade-offs:** `workflow_execution.run_id` is polymorphic and
  lacks a conventional FK; `(workflow_type, run_id)` uniqueness and repository
  validation maintain the association.
- **Status:** Implemented.
- **Evidence:** `db/models.py`, migration `0001_initial_schema.py`,
  `repositories/workflow_execution.py`.

## LLM provider abstraction and role configuration

- **Decision:** LLM implementations are registered behind provider interfaces
  and selected/configured through roles/settings.
- **Context/problem:** Workflow services require model calls but should not
  hard-code provider clients at each call site.
- **Rationale:** **Inference:** a registry/role boundary permits configuration
  and instrumentation to be shared across features.
- **Consequences/trade-offs:** Provider-specific capabilities and failure
  behavior still need correct adapter handling; configuration must be kept in
  environment, not documentation.
- **Status:** Implemented; exact model/role defaults are configuration-sensitive.
- **Evidence:** `llm/base.py`, `llm/registry.py`, `llm/roles.py`,
  `llm/providers/`, `config.py`, `tests/llm/`.

## Deterministic qualification after semantic extraction

- **Decision:** LLM-assisted extraction produces candidate semantic facts;
  application logic evaluates criteria and aggregates qualification status.
- **Context/problem:** Final qualification needs criterion-level reproducible
  outcomes and must distinguish unsupported evidence from contradiction.
- **Rationale:** **Verified in implementation behavior, historical intent
  unverified:** qualification is calculated deterministically by
  `services/qualification.py`; README describes this separation. No ADR states
  the original decision history.
- **Consequences/trade-offs:** Deterministic rules are inspectable, while source
  interpretation and extraction can still be wrong or incomplete.
- **Status:** Implemented.
- **Evidence:** `services/qualification.py`,
  `services/qualification_evidence_extractor.py`, README “Qualification”,
  qualification tests.

## Evidence → Facts → Hypotheses in Exploration

- **Decision:** Exploration persists source-backed Evidence, normalized Facts
  supported by Evidence, and analytical Hypotheses supported by Facts.
- **Context/problem:** Preserve provenance from source excerpts through
  normalized statements to analysis.
- **Rationale:** **Inference:** separate records and association tables provide
  traceability and keep interpretation layers distinct. Original rationale is
  not explicitly recorded.
- **Consequences/trade-offs:** More relationships must be validated and returned
  by APIs; traceability does not guarantee that a source or inference is true.
- **Status:** Implemented.
- **Evidence:** `db/models.py`, `exploration_fact_evidence`,
  `exploration_hypothesis_fact`, `services/exploration_fact_*`,
  `services/exploration_hypothesis_*`, corresponding repositories.

## Provenance and ownership validation

- **Decision:** Persisted outputs refer to selected company/obligation context;
  Facts and Hypotheses use explicit supporting-record associations.
- **Context/problem:** Prevent cross-company or cross-Exploration contamination.
- **Rationale:** **Verified behavior; historical motivation unverified.** Service
  and repository validation checks ownership not fully encoded by ordinary
  single-column foreign keys.
- **Consequences/trade-offs:** Correctness depends on application checks as well
  as FK integrity; the schema guide must distinguish these layers.
- **Status:** Implemented in persistence paths.
- **Evidence:** `services/exploration_evidence_persistence.py`,
  `services/exploration_fact_persistence.py`,
  `services/exploration_hypothesis_persistence.py`, repositories and
  `tests/api/test_exploration_result_provenance.py`.

## Company selection and qualification semantics

- **Decision:** Exploration Run company selections must come from the chosen
  completed ResearchRun's persisted qualification snapshot; qualification
  status itself does not gate eligibility.
- **Context/problem:** Tie selected companies to a reproducible Research result
  set without silently restricting selection to only QUALIFIED companies.
- **Rationale:** **Verified contract in code/docs; why this eligibility rule was
  chosen historically is unverified.**
- **Consequences/trade-offs:** An `INSUFFICIENT_EVIDENCE` or
  `NOT_QUALIFIED` company can still be selected if present in the snapshot.
- **Status:** Implemented.
- **Evidence:** `services/exploration.py` (`start_run`),
  `repositories/research_company_qualification.py`, Exploration run-start tests.

## Frontend result pagination

- **Decision:** Exploration result tabs fetch a company's top-level result
  collections and paginate client-side at 50 top-level items per page; evidence,
  facts, and hypotheses have independent page state. Supporting records remain
  nested under their parent result.
- **Context/problem:** Present potentially large persisted collections without
  splitting their supporting provenance across independent API pages.
- **Rationale:** **Inference:** current client structure retains nested support
  records while paging top-level arrays; no recorded ADR establishes why this
  strategy was selected.
- **Consequences/trade-offs:** Full result arrays are retrieved before local
  paging, which can increase response/memory size for large runs.
- **Status:** Implemented in current Exploration result component; recheck when
  changing response shape.
- **Evidence:** `frontend/src/features/exploration/components/exploration-run-details-page.tsx`,
  `frontend/src/features/exploration/api/explorations.ts`, component tests.
- **Implementation note:** the pagination strategy is a verified fact; the
  explanation of its original motivation above is an inference, not a recorded
  historical decision.

## Failure isolation and completion semantics

- **Decision:** Workflow records and business run records transition together
  under execution ownership; stale work is marked failed by reconciliation.
- **Context/problem:** Guard duplicate delivery and prevent a worker that lost
  ownership from finalizing a run.
- **Rationale:** **Inference from implementation:** ownership-fenced updates and
  heartbeat supervision are visible; original design history is not.
- **Consequences/trade-offs:** Stale work becomes terminal failure; no durable
  graph resume or automatic republish is implemented. Exploration completion
  does not assert success for every individual search/fetch.
- **Status:** Implemented as described; recovery behavior is a known limitation.
- **Evidence:** `task_queue/lifecycle.py`, `reconciliation.py`,
  `repositories/workflow_execution.py`, README worker notes, Exploration graph
  branch/finalization logic.

## Deferred work and unverified rationale

- Engagement has no implemented workflow. Its requirements and architecture
  are not established; no permanent design constraint is inferred from
  Exploration prompt boundary text.
- Durable graph checkpoint/resume, automatic stale-task requeue, and external
  OTel export are not present in the inspected runtime. They are limitations,
  not approved roadmap commitments.
- The repository has no verified historical decision record explaining every
  design choice above. Inferred rationale is labeled as such rather than
  presented as prior agreement.
