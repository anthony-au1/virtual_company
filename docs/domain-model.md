# Campaign criteria

`target_market` and `industry` are required criteria whenever configured. The
`technologies` object has independent `required` and `preferred` lists. The optional
`company_size` object has independent `min` and `max` bounds, each carrying a
nonnegative employee count and a `required` or `preferred` requirement.

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

Any required mismatch makes a company `NOT_QUALIFIED`. Otherwise, any required
unknown yields `INSUFFICIENT_EVIDENCE`. A company is `QUALIFIED` when every required
criterion matches. Preferred results remain in the qualification snapshot but never
change eligibility.
