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

Research discovers and qualifies companies. An Exploration Business Context is
a free-text description of the user's business goal, decision, problem, context,
capabilities, and constraints for which investigating companies selected from
existing Research results may provide useful evidence. It may directly concern
those companies or describe a broader business question their investigation can
help answer. Exploration remains company-focused rather than becoming generic
market, geographic, regulatory, labour-market, or technology research. When
company investigation cannot meaningfully address the context, zero obligations
is valid.

Obligations remain shared, reusable questions or conditions to establish about
each selected company. They do not discover or shortlist companies.

Each ExplorationRun references exactly one ResearchRun, which identifies the
Research result set used to select that run's companies. Campaign is obtained
through ResearchRun and is not duplicated on ExplorationRun. Each
ExplorationCompany continues to reference a ResearchCompany. Runs under one
Exploration may use different ResearchRuns. A referenced ResearchRun cannot be
deleted, preserving the provenance link.

To start an ExplorationRun, the user chooses one ResearchRun and one or more
companies from that run's persisted qualification results, then calls the
Exploration run-start endpoint. Each selected company must have a
`ResearchCompanyQualification` snapshot for that ResearchRun. Qualification
status does not gate selection: `QUALIFIED`, `NOT_QUALIFIED`, and
`INSUFFICIENT_EVIDENCE` companies are all eligible. One Exploration may have
multiple ExplorationRuns; those runs may reference different ResearchRuns, and
the same ResearchRun may be reused. Starting a run creates only the
ExplorationRun and its ExplorationCompany references. It does not execute
Exploration research. The parent Exploration is locked at start using the same
row lock as PATCH and DELETE, establishing the existing immutability boundary.

Company × Obligation investigation, query generation, external search,
Evidence orchestration, Fact derivation, and Hypothesis derivation remain
future workflow work. Future execution must enforce same-Exploration Evidence
associations plus same-company Evidence→Fact and Fact→Hypothesis provenance.
Those execution invariants are not currently enforced by an Exploration
workflow.
