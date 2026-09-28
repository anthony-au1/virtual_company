# Campaign criteria

`target_market` and `industry` are required criteria whenever configured. The
`technologies` object has independent `required` and `preferred` lists. The optional
`company_size` object has independent `min` and `max` bounds, each carrying a
nonnegative employee count and a `required` or `preferred` requirement.

Each configured criterion produces `MATCH`, `MISMATCH`, or `UNKNOWN` from validated
Evidence. For target market, industry, and technology, normalized Evidence existence
produces `MATCH` and absence produces `UNKNOWN`; qualification does not reinterpret
the evidence text. Employee-count Evidence is normalized into structured facts before
deterministic bound evaluation. Coverage only indicates whether relevant Evidence
exists; company-size coverage does not itself assert a match.

Any required mismatch makes a company `NOT_QUALIFIED`. Otherwise, any required
unknown yields `INSUFFICIENT_EVIDENCE`. A company is `QUALIFIED` when every required
criterion matches. Preferred results remain in the qualification snapshot but never
change eligibility.
