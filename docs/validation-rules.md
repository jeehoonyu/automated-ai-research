# Validation rules

Full validation verifies schemas, artifact/source hashes, source and chunk references, exact text spans,
page renders, visual boxes, claim-evidence links, review coverage, confidence factors, independence,
amendments, and lifecycle state.

Citation reviews contain typed per-claim decisions. `related_not_supporting`, `partially_supports`, and
`contradicts` cannot pass a material claim's citation gate. Contradiction reviews must attest that an
active search occurred. Low or unknown methodology and insufficient independence require human review.

`verified` is limited to directly checkable facts with passing citations and reviews, no material
contradiction, and no uncertain visual or OCR dependency. Broader claims can be at most
`strongly_supported`. Numeric aggregate confidence is intentionally absent.

The report command compares the current canonical artifact hashes with the last eligible validation.
Any later amendment or accepted artifact makes validation stale. `unable_to_determine` is a successful
research result when represented as an evidence-linked, reviewed claim.

