# Virtual Company Documentation

This documentation is an agent-oriented map of the current application. It
explains business purpose, implementation status, architecture, workflows,
data, decisions, and safe development paths without copying the source code.
Repository code and migrations are authoritative when documentation and
implementation disagree.

## Canonical document index

- [Overview](overview.md) — product, business concepts, user journeys, and
  implemented versus unimplemented functionality.
- [Project status](project-status.md) — concise current MVP state, known
  limitations, and next priorities.
- [Architecture](architecture.md) — runtime components, boundaries, and data
  flow diagrams.
- [Architecture decisions](architecture-decisions.md) — evidence-backed
  decisions and explicitly labeled rationale inferences.
- [Database schema](database-schema.md) — persisted entities, constraints,
  relationships, and application-level invariants.
- [Workflow execution](workflow-execution.md) — TaskIQ delivery, execution
  ownership, worker lifecycle, and recovery semantics.
- [Research Workflow](workflows/research.md) — campaign discovery,
  investigation, evidence, and qualification.
- [Exploration Workflow](workflows/exploration.md) — business context,
  obligations, company investigation, Evidence, Facts, and Hypotheses.
- [Frontend](frontend.md) — routes, feature modules, API transport, user
  journeys, and presentation behavior.
- [AI and integrations](ai-and-integrations.md) — LLM providers, web search,
  fetching, security boundaries, and telemetry.
- [Development and operations](development-and-operations.md) — local setup,
  configuration, verification, migrations, and operational tooling.

## Recommended reading order

### Full Context Recovery

For a new agent or conversation with no prior project context:

1. Read root [`AGENTS.md`](../AGENTS.md).
2. Read this index in full.
3. Read every canonical document in the index, in the order listed above,
   including both nested workflow guides.
4. Read [`frontend/AGENTS.md`](../frontend/AGENTS.md) for frontend-specific
   conventions. `frontend/CLAUDE.md` aliases that file.
5. Use each document's source map to verify uncertain or implementation-level
   details. The goal is to reconstruct status, architecture, workflows, data
   relationships, integrations, and decisions well enough to continue work
   without asking the user to restate project context.

If a detail is not established by code, tests, configuration, or a documented
decision, label it unknown or unverified. Do not infer a product contract from
a prompt, a historical task report, or a proposed feature.

### Task-Specific Context

For a normal coding task, read root `AGENTS.md`, this index, [Overview](overview.md),
and [Architecture](architecture.md), then load the following relevant documents:

| Task | Additional reading |
|---|---|
| Research workflow | [Research](workflows/research.md), [Workflow execution](workflow-execution.md), [Database schema](database-schema.md); add [AI and integrations](ai-and-integrations.md) for prompts/providers/search/fetch. |
| Exploration workflow | [Exploration](workflows/exploration.md), [Workflow execution](workflow-execution.md), [Database schema](database-schema.md); add [AI and integrations](ai-and-integrations.md) and [Frontend](frontend.md) as relevant. |
| Shared execution/worker | [Workflow execution](workflow-execution.md), [Database schema](database-schema.md), and the affected workflow guide. |
| Database/persistence | [Database schema](database-schema.md), relevant workflow guide, and [Development and operations](development-and-operations.md) for migration verification. |
| Frontend | [Frontend](frontend.md), [`frontend/AGENTS.md`](../frontend/AGENTS.md), and the matching workflow guide/API implementation. |
| LLM, search, or web fetching | [AI and integrations](ai-and-integrations.md) and the workflow guide using that integration. |
| Infrastructure/configuration/operations | [Development and operations](development-and-operations.md), then the relevant README and configuration files. |

Inspect referenced source and tests before implementation. When a task changes
contracts or behavior, update the affected canonical documentation alongside
the implementation.

## Canonical docs and historical reports

The files listed above are the canonical maintained project documentation.
Root-level task/audit reports are historical artifacts and may describe a
point-in-time change; they do not override current source or canonical docs.
Do not use them as a specification without checking their claims against the
current implementation. No historical reports are required for Full Context
Recovery.

## Source-of-truth hierarchy

1. Current application code and configuration establish runtime behavior.
2. SQLAlchemy models plus the active Alembic revision chain establish source
   schema intent; a live database can differ and must be checked separately.
3. Tests establish covered examples and expected contracts, but do not prove
   untested behavior.
4. Canonical docs explain navigation, business meaning, and verified design
   context; update them when code changes.
5. Historical reports and prior conversations are context only.

## Maintenance expectations

Keep documents concise, linked to repository-relative source paths, and
explicit about implemented, incomplete, planned, or unimplemented behavior.
Separate database constraints from service/workflow checks. Do not include
credentials or environment-specific secrets. Verify links and code references
when moving files, and update the relevant guide when behavior, persistence,
API contracts, or operational semantics change.
