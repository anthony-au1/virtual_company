# Campaign criteria

Campaign criteria are all evaluated equally. `target_market`, `industry`, and
`technologies` are optional criteria. The optional `company_size` object has
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
technology facts to `MATCH`; missing or conflicting support produces `UNKNOWN`.
Employee-count facts retain their relation, optional year, and scope before deterministic
bound evaluation. Coverage only indicates whether relevant Evidence exists and remains
separate from semantic fact extraction and qualification.

Any criterion mismatch makes a company `NOT_QUALIFIED`. With no mismatch, any unknown
yields `INSUFFICIENT_EVIDENCE`. A company is `QUALIFIED` when every configured
criterion matches.

# Human lead review

Each final company qualification snapshot has an independent human review status:
`UNREVIEWED`, `ACCEPTED`, or `REJECTED`. It belongs to one company within one
research run, may move freely between all three values, and never changes automated
qualification, criterion results, or evidence.
