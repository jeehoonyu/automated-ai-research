# Citation review

Resolve every locator against the source, compare paraphrases with exact text, and classify support as
`supports`, `partially_supports`, `related_not_supporting`, or `contradicts`. Only `supports` passes a
material claim's citation gate. Emit a superseding claim version.
For new runs, include one `evidence_assessments` entry per supporting and contradicting evidence ID and
record whether surrounding context was preserved. Aggregate claim-level support cannot substitute for
complete evidence-level citation review.
