# Codex conformance artifacts

`workspace/` contains a real Codex CLI conformance run over the checked-in synthetic corpus.

- Run: `RUN-563cd90e-af4d-46fa-9302-f48c030cb398`
- Primary stages: Codex CLI with one or two bounded packets per fresh session
- Independent review: separate ephemeral Codex context, `confirmed_independent`
- Deterministic validation: zero blocking structural errors
- Expected disposition: `human_review_required`
- Expected human gates: explicit claim review, material unresolved contradiction, and the independent
  review's human-review decision
- Publication: correctly refused; an explicitly marked draft is retained for inspection

This is intentionally not represented as report-eligible. A real human must review the material
conflict before the final release gate can pass. `tests/benchmark/test_corpus.py` copies and validates
this workspace in CI without mutating the checked-in artifacts.
