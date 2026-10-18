# Database Schema

## Research entities

These tables persist entities owned by the Research workflow.
Research-scoped table names are created directly by the project's initial schema.

Table: campaign

| Column                      | PostgreSQL type | Nullable | Description                                        |
|-----------------------------|-----------------|---------:|----------------------------------------------------|
| `id`                        | `UUID`          |       NO | unique ID campaign                                 |
| `name`                      | `VARCHAR(255)`  |       NO | name                                               |
| `description`               | `TEXT`          |      YES | detailed description                               |
| `target_market`             | `VARCHAR(255)`  |      YES | geographical market                                |
| `industry`                  | `VARCHAR(255)`  |      YES | targeted industry                                  |
| `keywords`                  | `JSONB`         |       NO | company concepts/signals used as campaign criteria |
| `company_size`              | `JSONB`         |      YES | optional direct integer min/max employee bounds    |
| `max_companies_to_research` | `INTEGER`       |       NO | campaign research cap; at least `target_count`     |
| `target_count`              | `INTEGER`       |       NO | desired eventual qualified-target count            |
| `status`                    | `VARCHAR(30)`   |       NO | campaign status                                    |
| `created_at`                | `TIMESTAMPTZ`   |       NO | created date                                       |
| `updated_at`                | `TIMESTAMPTZ`   |       NO | last change date                                   |
| `sealed_at`                 | `TIMESTAMPTZ`   |      YES | first run start; campaign definition is sealed     |

status:

- DRAFT
- RUNNING
- PAUSED
- COMPLETED
- FAILED

Indexes:

- PK (id)

Table: research_company

| Column            | PostgreSQL type | Nullable | Description          |
|-------------------|-----------------|---------:|----------------------|
| `id`              | `UUID`          |       NO | Internal ID          |
| `name`            | `VARCHAR(500)`  |       NO | company name         |
| `website`         | `VARCHAR(1000)` |      YES | web site             |
| `domain`          | `VARCHAR(255)`  |      YES | web domain           |
| `industry`        | `VARCHAR(255)`  |      YES | targeted industry    |
| `country`         | `VARCHAR(100)`  |      YES | country              |
| `state`           | `VARCHAR(255)`  |      YES | state                |
| `city`            | `VARCHAR(255)`  |      YES | city                 |
| `employee_number` | `INTEGER`       |      YES | number of employees  |
| `created_at`      | `TIMESTAMPTZ`   |       NO | company created date |
| `updated_at`      | `TIMESTAMPTZ`   |       NO | company updated date |

Indexes:

- PK (id)

Table: `campaign_target`

| Column        | Type        | Description                  |
|---------------|-------------|------------------------------|
| `campaign_id` | UUID        | campaign                     |
| `company_id`  | UUID        | company                      |
| `score`       | NUMERIC     | future qualification score   |
| `status`      | VARCHAR     | candidate/qualified/rejected |
| `created_at`  | TIMESTAMPTZ | created date                 |

Constraints:

- PK `campaign_target_pkey` (`campaign_id`, `company_id`)
- FK `campaign_target_campaign_id_fkey` (`campaign_id`) -> campaign (`id`)
- FK `campaign_target_research_company_id_fkey` (`company_id`) -> research_company (`id`)

Table: research_evidence

| Column            | PostgreSQL type | Nullable | Description                                     |
|-------------------|-----------------|---------:|-------------------------------------------------|
| `id`              | UUID            |       NO | Internal ID                                     |
| `company_id`      | UUID            |       NO | company                                         |
| `research_run_id` | UUID            |      YES | research execution that extracted this evidence |
| `criterion`       | VARCHAR(50)     |      YES | campaign criterion supported                    |
| `subject`         | VARCHAR(500)    |      YES | criterion value or subject                      |
| `claim`           | TEXT            |       NO | claim                                           |
| `evidence_text`   | TEXT            |       NO | evidence confirmation                           |
| `source_url`      | TEXT            |       NO | information source                              |
| `source_title`    | VARCHAR(500)    |      YES | source title                                    |
| `source_type`     | VARCHAR(50)     |      YES | careers/blog/news/etc                           |
| `confidence`      | NUMERIC(4,3)    |      YES | agent confidence                                |
| `observed_at`     | TIMESTAMPTZ     |       NO | when information was found                      |
| `created_at`      | TIMESTAMPTZ     |       NO | when evidence was saved                         |

Indexes:

- PK (id)
- `ix_research_evidence_research_run_id` (research_run_id)
- FK (company_id) -> research_company (id)
- FK (research_run_id) -> research_run (id)

Table: research_run

| Column            | PostgreSQL type | Nullable | Description                                 |
|-------------------|-----------------|---------:|---------------------------------------------|
| `id`              | UUID            |       NO | ID execution                                |
| `campaign_id`     | UUID            |       NO | campaign                                    |
| `status`          | VARCHAR(30)     |       NO | RUNNING/COMPLETED/FAILED                    |
| `started_at`      | TIMESTAMPTZ     |       NO | execution start time                        |
| `completed_at`    | TIMESTAMPTZ     |      YES | terminal completion time, including failure |
| `error`           | TEXT            |      YES | error text                                  |
| `companies_found` | INTEGER         |       NO | companies found                             |
| `created_at`      | TIMESTAMPTZ     |       NO | Run record creation time                    |

status:

- RUNNING
- COMPLETED
- FAILED

Indexes:

- PK (id)
- FK (campaign_id) -> campaign (id)

## Final qualification snapshots

Table: `research_company_qualification`

| Column             | PostgreSQL type | Nullable | Description                                     |
|--------------------|-----------------|----------|-------------------------------------------------|
| `id`               | UUID            | NO       | Snapshot ID                                     |
| `research_run_id`  | UUID            | NO       | FK to research_run(id)                          |
| `campaign_id`      | UUID            | NO       | FK to campaign(id)                              |
| `company_id`       | UUID            | NO       | FK to research_company(id)                      |
| `status`           | VARCHAR(30)     | NO       | QUALIFIED, NOT_QUALIFIED, INSUFFICIENT_EVIDENCE |
| `criteria_results` | JSONB           | NO       | Object containing a criteria array              |
| `created_at`       | TIMESTAMPTZ     | NO       | Database timestamp, default now()               |

Constraints:

- PK `research_company_qualification_pkey` (`id`)
- FK `research_company_qualification_research_run_id_fkey` (`research_run_id`) -> research_run (`id`)
- FK `research_company_qualification_campaign_id_fkey` (`campaign_id`) -> campaign (`id`)
- FK `research_company_qualification_research_company_id_fkey` (`company_id`) -> research_company (`id`)
- Unique constraint `uq_research_company_qualification_run_company` on
  `(research_run_id, company_id)`, also supporting lookups by run.
  Each criterion includes criterion, subject, status, evidence_ids (UUID strings),
  and reason. No Evidence content is copied. Retries replace status and JSON while
  preserving ID and created_at. Snapshots commit with research-run completion; no
  intermediate rounds or legacy-run backfill are stored.

Qualification snapshots contain only the automatic qualification result and
criterion-level results for that run/company pair.

## Exploration entities

These tables describe the Exploration domain and its planned provenance model.
Currently implemented behavior includes Exploration CRUD, obligation generation
and regeneration, persistence entities/repositories, and lifecycle restrictions.
Company selection and Exploration Run start/execution are planned, followed by
Company × Obligation investigation, query generation, external search, Evidence
collection orchestration, Fact derivation, and Hypothesis derivation. These
execution steps are not currently orchestrated by the application.

```text
Business Context
      ↓
Obligation
      ↓
Evidence
      ↓
Fact
      ↓
Hypothesis
```

`business_context` is free text describing the user's business goal, decision,
problem, context, capabilities, and constraints for which investigating
companies selected from existing Research results may provide useful evidence.
It may directly concern those companies or describe a broader business question
that their investigation can help answer. Exploration remains company-focused:
it is not generic market, geographic, regulatory, labour-market, or technology
research. When the context cannot meaningfully support company-applicable
obligations, a valid empty obligation set may be generated.

An Exploration Obligation is a reusable question or condition to establish about
each selected company in order to address the Business Context. The obligation
set is shared across the selected company set and is generated without company
names. Obligations remain system-managed. In the planned execution workflow,
Evidence will support Facts, and Hypotheses will be derived from Facts.

Table: `exploration`

Represents an Exploration definition and its high-level business context.

| Column             | PostgreSQL type | Nullable | Description                                                 |
|--------------------|-----------------|---------:|-------------------------------------------------------------|
| `id`               | UUID            |       NO | Exploration ID                                              |
| `business_context` | TEXT            |       NO | Purpose/context guiding investigation of Research companies |
| `max_obligations`  | INTEGER         |       NO | Maximum system-derived obligation count; default `10`, 1–20 |
| `status`           | VARCHAR(30)     |       NO | Exploration status                                          |
| `created_at`       | TIMESTAMPTZ     |       NO | Creation time                                               |
| `updated_at`       | TIMESTAMPTZ     |       NO | Last update time                                            |

Constraints:

- PK (`id`)
- CHECK (`max_obligations` >= 1 AND `max_obligations` <= 20)

`max_obligations` is an upper bound, not an exact requested count. For example,
`10` means at most 10 obligations may be derived; the eventual count may be
anywhere from zero through 10, including zero when no meaningful
company-applicable obligations can be derived.

Currently, when an Exploration is created, the system generates its obligation
set from `business_context` and `max_obligations`. A successful empty result is valid
and creates no obligation rows. If generation fails, creation fails without
persisting an Exploration. Before the first Exploration run, changing either
generation input regenerates and replaces the complete obligation set in the
same transaction as the input update. A failed generation or persistence
operation leaves the previous inputs and obligations intact. Once any run
exists, `business_context` and `max_obligations` are immutable. Future run-start
behavior must establish this lifecycle boundary under the parent Exploration
row lock, shared with PATCH and DELETE, so start, input updates, and deletion
cannot race. PATCH requests that repeat the current values are no-ops and do not regenerate
obligations. The generated obligation order is not a guaranteed domain
property.

An Exploration may be permanently deleted before it has any ExplorationRun;
that deletion also removes its generated obligations. Once any ExplorationRun
exists, the Exploration is historical execution context and cannot be deleted.

Indexes:

- PK (`id`)

Table: `exploration_obligation`

Represents a reusable question or condition to establish about each selected
Research company to address the Exploration Business Context. Obligations are
system-managed and are not independently user-managed resources. Current
Exploration CRUD generates and persists them up to `max_obligations`; applying
them to companies and collecting Evidence are planned execution behavior.

| Column           | PostgreSQL type | Nullable | Description                                        |
|------------------|-----------------|---------:|----------------------------------------------------|
| `id`             | UUID            |       NO | Obligation ID                                      |
| `exploration_id` | UUID            |       NO | Owning Exploration                                 |
| `description`    | TEXT            |       NO | Shared company-investigation question or condition |
| `created_at`     | TIMESTAMPTZ     |       NO | Creation time                                      |

Constraints:

- PK (`id`)
- FK (`exploration_id`) -> `exploration` (`id`)

Indexes:

- PK (`id`)
- `ix_exploration_obligation_exploration_id` (`exploration_id`)

Relationship: `exploration` 1 -> N `exploration_obligation`.

Table: `exploration_run`

Represents one execution of an Exploration. The persistence entity exists;
starting and executing an Exploration Run is planned behavior.

| Column           | PostgreSQL type | Nullable | Description           |
|------------------|-----------------|---------:|-----------------------|
| `id`             | UUID            |       NO | Run ID                |
| `exploration_id` | UUID            |       NO | Exploration being run |
| `status`         | VARCHAR(30)     |       NO | Run status            |
| `started_at`     | TIMESTAMPTZ     |       NO | Execution start time  |
| `completed_at`   | TIMESTAMPTZ     |      YES | Completion time       |

Constraints:

- PK (`id`)
- FK (`exploration_id`) -> `exploration` (`id`)

Indexes:

- PK (`id`)
- `ix_exploration_run_exploration_id` (`exploration_id`)

Relationship: `exploration` 1 -> N `exploration_run`.

Table: `exploration_company`

Represents an existing `research_company` selected from Research results and
associated with one Exploration Run. It is not a company discovered by
Exploration. It carries no duplicate company identity or profile data.

| Column               | PostgreSQL type | Nullable | Description                |
|----------------------|-----------------|---------:|----------------------------|
| `id`                 | UUID            |       NO | Exploration-company ID     |
| `exploration_run_id` | UUID            |       NO | Exploration run            |
| `company_id`         | UUID            |       NO | Related `research_company` |

Constraints:

- PK (`id`)
- FK (`exploration_run_id`) -> `exploration_run` (`id`)
- FK (`company_id`) -> `research_company` (`id`)
- Unique (`exploration_run_id`, `company_id`)

Indexes:

- PK (`id`)
- Unique index on (`exploration_run_id`, `company_id`), supporting run-to-company
  lookup
- `ix_exploration_company_company_id` (`company_id`), supporting company-to-run
  lookup

Relationships:

- `exploration_run` 1 -> N `exploration_company`
- `research_company` 1 -> N `exploration_company`

Table: `exploration_evidence`

Represents the planned external supporting material for one
`ExplorationCompany × ExplorationObligation` investigation. Both associations
are required: `exploration_company_id` identifies which selected company the
evidence concerns, and `exploration_obligation_id` identifies the shared
question/condition it addresses. Future workflow logic must ensure both belong
to the same Exploration. Run ownership is derived through `exploration_company`
and does not need a duplicate `exploration_run_id`.

| Column                      | PostgreSQL type | Nullable | Description                       |
|-----------------------------|-----------------|---------:|-----------------------------------|
| `id`                        | UUID            |       NO | Evidence ID                       |
| `exploration_company_id`    | UUID            |       NO | Company context for this evidence |
| `exploration_obligation_id` | UUID            |       NO | Obligation motivating collection  |
| `source_url`                | TEXT            |      YES | Source URL                        |
| `source_type`               | VARCHAR(50)     |      YES | Source classification             |
| `content`                   | TEXT            |      YES | Captured content or excerpt       |
| `created_at`                | TIMESTAMPTZ     |       NO | When evidence was saved           |

Constraints:

- PK (`id`)
- FK (`exploration_company_id`) -> `exploration_company` (`id`)
- FK (`exploration_obligation_id`) -> `exploration_obligation` (`id`)

Indexes:

- PK (`id`)
- `ix_exploration_evidence_exploration_company_id` (`exploration_company_id`)
- `ix_exploration_evidence_exploration_obligation_id`
  (`exploration_obligation_id`)

Table: `exploration_fact`

Represents a factual statement derived from one or more Evidence records.
Company context is derived through its supporting Evidence rather than stored
on the Fact.

| Column       | PostgreSQL type | Nullable | Description       |
|--------------|-----------------|---------:|-------------------|
| `id`         | UUID            |       NO | Fact ID           |
| `statement`  | TEXT            |       NO | Factual statement |
| `created_at` | TIMESTAMPTZ     |       NO | Creation time     |

Constraints:

- PK (`id`)

Indexes:

- PK (`id`)

Table: `exploration_fact_evidence`

Associates Evidence and Facts in a many-to-many relationship. One Fact can be
supported by multiple Evidence records, and one Evidence record can support
multiple Facts.

| Column                    | PostgreSQL type | Nullable | Description         |
|---------------------------|-----------------|---------:|---------------------|
| `exploration_fact_id`     | UUID            |       NO | Related Fact        |
| `exploration_evidence_id` | UUID            |       NO | Supporting Evidence |

Constraints:

- PK (`exploration_fact_id`, `exploration_evidence_id`)
- FK (`exploration_fact_id`) -> `exploration_fact` (`id`)
- FK (`exploration_evidence_id`) -> `exploration_evidence` (`id`)

Indexes:

- PK (`exploration_fact_id`, `exploration_evidence_id`), supporting Fact-to-
  Evidence lookup
- `ix_exploration_fact_evidence_exploration_evidence_id`
  (`exploration_evidence_id`), supporting Evidence-to-Fact lookup

Table: `exploration_hypothesis`

Represents a higher-level inference derived from one or more Facts. Company
provenance is derived through its Facts and their supporting Evidence rather
than stored on the Hypothesis.

| Column       | PostgreSQL type | Nullable | Description        |
|--------------|-----------------|---------:|--------------------|
| `id`         | UUID            |       NO | Hypothesis ID      |
| `statement`  | TEXT            |       NO | Inferred statement |
| `created_at` | TIMESTAMPTZ     |       NO | Creation time      |

Constraints:

- PK (`id`)

Indexes:

- PK (`id`)

Table: `exploration_hypothesis_fact`

Associates Facts and Hypotheses in a many-to-many relationship. One Hypothesis
can be supported by multiple Facts, and one Fact can contribute to multiple
Hypotheses.

| Column                      | PostgreSQL type | Nullable | Description        |
|-----------------------------|-----------------|---------:|--------------------|
| `exploration_hypothesis_id` | UUID            |       NO | Related Hypothesis |
| `exploration_fact_id`       | UUID            |       NO | Supporting Fact    |

Constraints:

- PK (`exploration_hypothesis_id`, `exploration_fact_id`)
- FK (`exploration_hypothesis_id`) -> `exploration_hypothesis` (`id`)
- FK (`exploration_fact_id`) -> `exploration_fact` (`id`)

Indexes:

- PK (`exploration_hypothesis_id`, `exploration_fact_id`), supporting
  Hypothesis-to-Fact lookup
- `ix_exploration_hypothesis_fact_exploration_fact_id`
  (`exploration_fact_id`), supporting Fact-to-Hypothesis lookup

### Provenance and domain invariants

The intended provenance chain is:

```text
Exploration
│
├── ExplorationObligation
│
└── ExplorationRun
       │
       └── ExplorationCompany ─────→ ResearchCompany
              │
              └── ExplorationEvidence
                     │
                     │ M:N
                     ▼
              ExplorationFact
                     │
                     │ M:N
                     ▼
              ExplorationHypothesis
```

The planned reasoning flow is Business Context → Obligation → Evidence → Fact →
Hypothesis. In the planned execution workflow, a Hypothesis can be traced through
Facts and Evidence to its `research_company` and the Obligation that motivated
evidence collection.

Future execution logic must enforce these provenance invariants: the
`ExplorationCompany` and `ExplorationObligation` for Evidence must belong to the
same Exploration; all Evidence supporting one Fact must belong to the same
`ExplorationCompany`; and all Facts supporting one Hypothesis must ultimately
resolve through their Evidence to the same `ExplorationCompany`. These rules
are not currently enforced by an executing Exploration workflow. Company
ownership is not duplicated on Fact or Hypothesis.

Future run creation/start must acquire the same parent Exploration row lock used
by PATCH and DELETE before establishing the run lifecycle boundary. This is a
workflow requirement only; no run-start repository behavior is implemented.

```mermaid
erDiagram
    exploration ||--o{ exploration_obligation: defines
    exploration ||--o{ exploration_run: executes
    exploration_run ||--o{ exploration_company: associates_selected
    research_company ||--o{ exploration_company: identifies
    exploration_company ||--o{ exploration_evidence: concerns
    exploration_obligation ||--o{ exploration_evidence: motivates
    exploration_fact ||--o{ exploration_fact_evidence: supported_by
    exploration_evidence ||--o{ exploration_fact_evidence: supports
    exploration_hypothesis ||--o{ exploration_hypothesis_fact: supported_by
    exploration_fact ||--o{ exploration_hypothesis_fact: contributes_to
```
