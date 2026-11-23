# Project Status

**Last verified:** 2026-11-23 (repository inspection; no live deployment or
production database was queried). **MVP phase:** Core Research and Exploration workflows are implemented in the
repository. The next workflow, Engagement, is not implemented. This is a code
status statement, not evidence of customer adoption, product-market validation,
or commercial readiness.

## Verified implementation facts

- FastAPI backend, SQLAlchemy/PostgreSQL persistence, Alembic schema, Next.js
  frontend, Redis Streams/TaskIQ workers, and LangGraph workflow graphs exist.
- Research supports Campaign-based discovery, investigation, Evidence, and
  deterministic qualification snapshots.
- Exploration supports definitions and generated obligations, completed
  ResearchRun selection, queued company-by-obligation research, Evidence, Facts,
  Hypotheses, and result presentation.
- Engagement has no workflow/API/model/service/repository/frontend feature in
  the inspected source tree.
- Source migration inventory contains `alembic/versions/0001_initial_schema.py`.
  This does not establish the revision installed in any deployment.

## Functional status and limitations

“Implemented” means a code path and associated tests exist, not that every
provider interaction succeeds or every generated claim is correct. Research
may complete with incomplete evidence; Exploration can finalize as `PARTIAL`
when its processing-failure/pair-completion rules require it. Both depend on
external search, fetch, and model results. Exploration `COMPLETED`
does not mean every fetch produced evidence or every business claim received
independent verification. Background recovery fails stale work; it does not
resume a persisted LangGraph checkpoint or automatically republish abandoned
work. OpenTelemetry instrumentation exists but README documents that there is
no configured span exporter or metric reader in the current setup; Langfuse is
optional.

No confirmed runtime P0/P1 defect was established by this documentation audit.
The stale Exploration descriptions and status inaccuracies in the previous
schema guide were documentation defects; they are corrected in this knowledge
base. No live production service, deployed database, or provider billing was
examined.

## Historical reports, decisions, and plans

- The repository's prior `VIRTUAL-COMPANY-AGENT-DOCUMENTATION-AUDIT.md` was a
  proposal and audit input. It is not a higher authority than current code.
- Root-level Exploration implementation/audit reports remain historical
  artifacts. They are not canonical current specifications.
- The task framing identifies Engagement as the next workflow focus. That
  priority is a supplied development direction; no Engagement requirements or
  architecture are recorded as approved in source by this document.
- Improvements such as durable workflow resume, richer OpenTelemetry export,
  and Engagement are not recorded as approved or scheduled features here.

## Immediate priorities

1. Maintain the canonical documentation when Research, Exploration, shared
   execution, or data contracts change.
2. Before Engagement implementation, establish its business requirements and
   acceptance criteria; do not derive them from Exploration's conceptual
   boundary text.
3. For operational/reliability work, decide explicitly whether stale runs
   should remain terminal failures or gain a separately designed recovery
   mechanism. Current implementation does not resume graphs.

These are maintenance and planning recommendations, not completed work or
approved product decisions. See [Architecture decisions](architecture-decisions.md)
for rationale confidence and [Development and operations](development-and-operations.md)
for safe validation.
