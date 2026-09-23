# Database Schema

## Entity

Represents a software entity discovered during analysis.

Table: campaign

| Column             | PostgreSQL type | Nullable | Description                             |
| ------------------ | --------------- | -------: | --------------------------------------- |
| `id`               | `UUID`          |       NO | unique ID campaign                      |
| `name`             | `VARCHAR(255)`  |       NO | name                                    |
| `description`      | `TEXT`          |      YES | detailed description                    |
| `target_market`    | `VARCHAR(255)`  |      YES | geographical market                     |
| `industry`         | `VARCHAR(255)`  |      YES | targeted industry                       |
| `technologies`     | `JSONB`         |      YES | technologies used                       |
| `company_size_min` | `INTEGER`       |      YES | minimum company size                    |
| `company_size_max` | `INTEGER`       |      YES | maximum company size                    |
| `target_count`     | `INTEGER`       |       NO | desired eventual qualified-target count |
| `status`           | `VARCHAR(30)`   |       NO | campaign status                         |
| `created_at`       | `TIMESTAMPTZ`   |       NO | created date                            |
| `updated_at`       | `TIMESTAMPTZ`   |       NO | last change date                        |

status:

- DRAFT
- RUNNING
- PAUSED
- COMPLETED
- FAILED

Indexes:

- PK(id)


Table: company

| Column            | PostgreSQL type | Nullable | Description          |
| ----------------- | --------------- | -------: | -------------------- |
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

- PK(id)


Table: campaign_targets

| Column        | Type        | Description                  |
| ------------- | ----------- | ---------------------------- |
| `campaign_id` | UUID        | campaign                     |
| `company_id`  | UUID        | company                      |
| `score`       | NUMERIC     | future qualification score   |
| `status`      | VARCHAR     | candidate/qualified/rejected |
| `created_at`  | TIMESTAMPTZ | created date                 |

Indexes:

- UNIQUE(campaign_id, company_id)
- FK(campaign_id) -> campaign(id) 
- FK(company_id) -> company(id) 


Table: evidence

| Column            | PostgreSQL type | Nullable | Description                                     |
| ----------------- | --------------- | -------: | ----------------------------------------------- |
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

- PK(id)
- FK(company_id) -> company(id) 
- FK(research_run_id) -> research_run(id)


Table: research_run

| Column            | PostgreSQL type | Nullable | Description              |
| ----------------- | --------------- | -------: | ------------------------ |
| `id`              | UUID            |       NO | ID execution             |
| `campaign_id`     | UUID            |       NO | campaign                 |
| `status`          | VARCHAR(30)     |       NO | RUNNING/COMPLETED/FAILED |
| `started_at`      | TIMESTAMPTZ     |       NO | started at               |
| `completed_at`    | TIMESTAMPTZ     |      YES | completed at             |
| `error`           | TEXT            |      YES | error text               |
| `companies_found` | INTEGER         |       NO | companies found          |
| `created_at`      | TIMESTAMPTZ     |       NO | record creation at       |

status:

- RUNNING
- COMPLETED
- FAILED

Indexes:

- PK(id)
- FK(company_id) -> company(id) 


## Final qualification snapshots

Table: `company_qualifications`

| Column             | PostgreSQL type | Nullable | Description                                     |
| ------------------ | --------------- | -------- | ----------------------------------------------- |
| `id`               | UUID            | NO       | Snapshot ID                                     |
| `research_run_id`  | UUID            | NO       | FK to research_run(id)                          |
| `campaign_id`      | UUID            | NO       | FK to campaign(id)                              |
| `company_id`       | UUID            | NO       | FK to company(id)                               |
| `status`           | VARCHAR(30)     | NO       | QUALIFIED, NOT_QUALIFIED, INSUFFICIENT_EVIDENCE |
| `criteria_results` | JSONB           | NO       | Object containing a criteria array              |
| `created_at`       | TIMESTAMPTZ     | NO       | Database timestamp, default now()               |

Unique constraint: `uq_company_qualifications_run_company` on
`(research_run_id, company_id)`, also supporting lookups by run.
Each criterion includes criterion, subject, status, evidence_ids (UUID strings),
and reason. No Evidence content is copied. Retries replace status and JSON while
preserving ID and created_at. Snapshots commit with research-run completion; no
intermediate rounds or legacy-run backfill are stored.
