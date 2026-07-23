# MVP release checklist

## Deterministic package gates

- [ ] Python 3.12 CI passes on Linux, macOS, and supported Windows runners.
- [ ] Ruff, formatting, mypy, unit, integration, benchmark, and wheel-install smoke tests pass.
- [ ] Identical bytes deduplicate to one document identity with traceable aliases.
- [ ] Every PDF page renders; low-text/image-only pages are marked `ocr_required`.
- [ ] Rebuilt logical FTS contents and tie-breaking are equivalent.
- [ ] Every citation resolves to immutable source bytes and exact text or visual locators.
- [ ] No unsupported claim is `verified` or `strongly_supported`.
- [ ] Invalid citations, missing reviews, unresolved human gates, and stale amendments block publication.

## Host conformance gates

- [ ] Codex completes identical packets and produces schema-valid artifacts.
- [ ] Claude Code completes identical packets and produces schema-valid artifacts.
- [ ] Independent reviewers use fresh/excluded context and record the truthful independence status.
- [ ] Seeded contradiction and related-but-non-supporting source are surfaced by both hosts.
- [ ] A real human resolves any mandatory human-review gate before a validated report is published.
- [ ] Canonical conformance artifacts are checked in; deterministic CI validates their expected outcome.

The release is not complete while any item remains unchecked. A structurally valid run that is blocked
for human review is a successful safety outcome, but it is not a report-eligible cross-host release run.
