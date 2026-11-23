# Virtual Company Overview

## Purpose

Virtual Company is an AI-assisted application for discovering companies and
turning public-source research into evidence-backed qualification and
business-context-specific analysis. It combines a browser workflow with a
FastAPI backend, persisted research records, and background execution.

The implemented workflows address two related tasks: identify companies that
match a configured campaign, then investigate selected companies against
questions derived from a business context. The application does not establish
that public-source claims are complete or independently verified; see the
workflow guides for validation boundaries.

## Product language and core concepts

- **Campaign:** reusable Research configuration: company discovery criteria,
  target count, and research cap.
- **Research Run:** one execution of a Campaign, with discovered companies,
  source-backed Research Evidence, and qualification snapshots.
- **Research Company:** persisted company profile that can be selected by later
  Exploration runs.
- **Exploration:** named definition with Business Context and a generated set
  of Research Obligations.
- **Research Obligation:** a shared question/condition to investigate for each
  selected company in an Exploration Run.
- **Exploration Run:** one execution tied to one completed Research Run and a
  snapshot of selected companies.
- **Exploration Evidence:** source-backed claim associated with a selected
  company and obligation.
- **Fact:** normalized company statement linked to supporting Exploration
  Evidence.
- **Hypothesis:** analytical statement linked to supporting Facts; it is not a
  verified fact.

The product name used in current documentation is **Virtual Company**.

## Conceptual sequence and implementation status

```text
Research → Exploration → Engagement
```

| Workflow | Status | Implemented boundary |
|---|---|---|
| Research | Implemented | Campaign discovery and investigation, Evidence persistence, qualification evidence extraction, deterministic qualification, run results. |
| Exploration | Implemented | Business Context and obligation generation, selected-company runs, company-by-obligation research, Evidence, Facts, Hypotheses, and results. A terminal completed status does not certify that every external fetch succeeded or that every generated claim was independently verified. |
| Engagement | Not implemented | No Engagement workflow, API, persistence model, service, or frontend feature was found in the inspected repository. The term appears as a conceptual boundary in Exploration material only. No Engagement architecture or contract is established here. |

Research feeds Exploration through persisted ResearchRun and qualification
results. Exploration creates its own run-scoped company associations and
derived records; it does not revise Research output. The intended product
sequence beyond Exploration is conceptual only until an Engagement feature is
specified and implemented.

## Main user journeys

### Research

1. Create or edit a Campaign with company criteria and research limits.
2. Start a Research Run; it is queued for background work.
3. The workflow discovers and investigates companies, persists source-backed
   Evidence, and computes qualification snapshots.
4. View run status and result summaries, including each company's qualification
   and criterion-level reasoning/evidence references.

See [Research Workflow](workflows/research.md) and
[Frontend](frontend.md) for verified API and UI routes.

### Exploration

1. Create an Exploration with a name and Business Context; obligations are
   generated and saved with the definition.
2. Start a Run by selecting a completed Research Run and companies belonging
   to its persisted qualification snapshot.
3. Save the run in READY state, then either leave it for later or use Save &
   Execute to queue it.
4. The workflow investigates each selected company against each obligation and
   persists Evidence, Facts, and Hypotheses.
5. View run status and the per-company result tabs.

The actual distinction between saving and execution, eligible statuses, and
failure outcomes is described in [Exploration](workflows/exploration.md).

## Inputs and outputs at a glance

| Workflow | Principal input | Principal persisted output |
|---|---|---|
| Research | Campaign criteria and limits | ResearchRun, ResearchCompany, ResearchEvidence, and per-run/company qualification snapshots. |
| Exploration | Exploration Business Context/obligations plus selected companies from a completed ResearchRun | ExplorationRun and selected-company associations, Exploration Evidence, Facts, Hypotheses, and explicit supporting-record links. |

For schema details, see [Database schema](database-schema.md). For background
execution, see [Workflow execution](workflow-execution.md).
