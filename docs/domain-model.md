# Campaign criteria

Campaign criteria are all evaluated equally. `target_market`, `industry`, and
`keywords` are optional criteria. They may describe technologies, platforms,
capabilities, business practices, transformation initiatives, or other
company-specific signals. The optional `company_size` object has
independent optional integer `min` and `max` bounds, each a nonnegative employee
count, for example `{"min": 500, "max": 5000}`.
`target_count` is the desired number of fully matching companies, and
`max_companies_to_research` caps the companies investigated for one campaign.

Each configured criterion produces `MATCH`, `MISMATCH`, or `UNKNOWN` from validated
Evidence. A structured-output extraction model first converts the persisted Evidence
into evidence-ID-backed semantic facts. It may recognize equivalent wording, but it
must use only the supplied Evidence and must preserve missing, vague, approximate, or
conflicting information as unknown. The model never returns a qualification decision.

Application code deterministically maps supported target-market, industry, and
keyword facts to `MATCH`; missing or conflicting support produces `UNKNOWN`.
Employee-count facts retain their relation, optional year, and scope before deterministic
bound evaluation. Coverage only indicates whether relevant Evidence exists and remains
separate from semantic fact extraction and qualification.

Any criterion mismatch makes a company `NOT_QUALIFIED`. With no mismatch, any unknown
yields `INSUFFICIENT_EVIDENCE`. A company is `QUALIFIED` when every configured
criterion matches.

Once a Campaign's first Research Run starts, its definition and qualification
criteria are sealed permanently. Run deletion does not remove the seal.

A Campaign may be hard-deleted before it has any Research Run. Once any
Research Run exists, the Campaign is part of Research execution history and
cannot be deleted. Deleting a pre-run Campaign removes its campaign-specific
target associations; shared ResearchCompany records are retained.

## Exploration

Research discovers and qualifies companies. An Exploration describes why and
what the user wants to learn about companies they will select from existing
Research results. Its obligations are shared, reusable questions or conditions
to establish about each selected company; they do not discover or shortlist
companies.

Exploration CRUD and obligation generation/regeneration are implemented. Company
selection, run start/execution, Company × Obligation investigation, query
generation, external search, Evidence orchestration, Fact derivation, and
Hypothesis derivation are future workflow work. Future execution must lock the
parent Exploration row at run start against PATCH/DELETE and enforce same-
Exploration Evidence associations plus same-company Evidence→Fact and
Fact→Hypothesis provenance. Those execution invariants are not currently
enforced by an Exploration workflow.
