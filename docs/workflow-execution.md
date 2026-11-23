# Shared Workflow Execution

## Components and dispatch

Research and Exploration are the registered workflow types
(`src/virtual_company/task_queue/workflow_types.py`). API/service code prepares
the business run and a shared `workflow_execution` record, then
`task_queue/dispatcher.py` publishes a TaskIQ task. `task_queue/broker.py`
configures the Redis Streams-backed broker; `tasks.py` receives the task and
dispatches through the workflow-type adapter in `task_queue/adapters/`. Each
adapter builds/invokes its configured LangGraph workflow.

The business run stores feature-specific status, timestamps, and outputs. The
shared `workflow_execution` stores queue/worker lifecycle and ownership. Its
`(workflow_type, run_id)` is unique; `run_id` is polymorphic and has no ordinary
FK. See [Database schema](database-schema.md).

## Claim, ownership, and duplicate delivery

Worker `claim_workflow_run` calls `WorkflowExecutionRepository.claim` in a
transaction. A queued execution changes atomically to RUNNING and returns its
execution UUID as an ownership token. A second delivery that finds no
claimable QUEUED execution is skipped. Heartbeats and terminal transitions are
fenced by that execution UUID. This prevents duplicate TaskIQ delivery from
executing a business run twice under normal claim semantics and prevents an
old worker from finalizing after ownership changes.

`ExecutionHeartbeat` writes liveness independently of graph progress. Repeated
heartbeat persistence failures or ownership loss raise lifecycle errors and
supervise/cancel the graph operation. Exploration persistence also checks live
execution ownership around result writes; inspect repository/service
transaction code for the exact guarded operations.

## Statuses and failure handling

`WorkflowExecution` uses `QUEUED`, `RUNNING`, `COMPLETED`, `PARTIAL`, `FAILED`,
and `CANCELLED`. Business ResearchRun and ExplorationRun statuses are separate
vocabularies. Workflow status transition and matching business-run terminal
status are coordinated through the repository/service paths. Errors are
persisted with the terminal execution where available; safe lifecycle events
are emitted through observability.

Cancellation is handled by asyncio/task cancellation paths where received.
Exploration adapter cancellation transitions its business run to `CANCELLED`;
Research adapter cancellation currently transitions its business run to
`FAILED`. No user-facing cancellation endpoint was identified in the task API.
Exploration emits `PARTIAL` for recoverable processing failures or incomplete
company-obligation processing; Research's adapter records successful graph
completion as `COMPLETED` and exceptions/cancellation as `FAILED`.

## Retry, redelivery, and stale work

Redis Streams may redeliver pending messages after idle time. **Message
redelivery is not workflow resumption:** no durable LangGraph checkpoint or
graph-state restore is configured in the inspected code. A delivery can claim
only a QUEUED execution; a prior RUNNING or terminal record is not restarted by
the duplicate message.

`task_queue/reconciliation.py` periodically fails stale queued/running
executions based on configured age thresholds. The repository updates the
corresponding business run only if it is still nonterminal. Reconciliation
does not resume the graph or automatically republish the task. A queued record
without a delivered/claimable message can therefore become a terminal failure
after the configured stale interval. Exact intervals come from
`src/virtual_company/config.py`, not constants in this guide.

There is no general automatic retry/attempt history or durable graph resume in
the shared persistence model. Provider SDK retry behavior is distinct from
workflow retry; see [AI and integrations](ai-and-integrations.md).

## Operational diagnostics and tests

Use structured application/worker logs and `workflow_execution` plus business
run status for local diagnostics. README documents `make taskiq-probe` and
Research observability/cost/log commands; the probe does not exercise real
workflow providers. Do not run a probe or query production from documentation
work.

Implementation: `src/virtual_company/task_queue/{broker,dispatcher,tasks,lifecycle,reconciliation,workflow_types}.py`,
`task_queue/adapters/`, `repositories/workflow_execution.py`, and app lifespan
in `main.py`. Tests are in `tests/task_queue/`, `tests/repositories/`,
`tests/api/` (execution routes/background), and `tests/workflows/`. Tests that
require Redis/PostgreSQL have environment requirements; inspect fixtures before
running them.
