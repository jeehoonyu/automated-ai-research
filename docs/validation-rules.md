# Validation rules

Full validation verifies every canonical JSON file, artifact/source hashes, the frozen configuration
and index manifests, append-only lifecycle continuity, work-packet isolation, retrieval references,
source and chunk references, exact text spans, page renders, visual boxes, claim-evidence links, review
coverage, confidence factors, source relationships, independence, amendments, and lifecycle state.

Citation reviews contain typed per-claim decisions. `related_not_supporting`, `partially_supports`, and
`contradicts` cannot pass a material claim's citation gate. Contradiction reviews must attest that an
active search occurred. New-run citation reviews must also cover every evidence ID with a context
preservation decision. Low or unknown methodology and insufficient independence require human review.

`verified` is limited to directly checkable facts with passing citations and reviews, no material
contradiction, and no uncertain visual or OCR dependency. Broader claims can be at most
`strongly_supported`. Numeric aggregate confidence is intentionally absent.

The report command compares the current frozen source and run artifact hashes with the last eligible
validation and immediately rechecks original bytes, renders, locators, packets, and lifecycle state.
Any later amendment, accepted artifact, or byte-level tampering makes validation stale.
`unable_to_determine` is a successful research result when represented as an evidence-linked, reviewed
claim.
