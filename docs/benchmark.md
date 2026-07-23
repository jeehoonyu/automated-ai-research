# Benchmark and host conformance

The checked-in corpus is synthetic and Apache-2.0 licensed. Tests generate PDF fixtures locally for
text, multi-page, raster, vector, low-text, and malformed cases. Expected cases include exact citations,
a supporting result, a contradiction, source dependence, weak methodology, prompt injection, and an
insufficient-evidence outcome.

Deterministic acceptance requires stable document IDs, equivalent logical indexes, resolvable locators,
no unsupported high-confidence claims, surfaced seeded contradictions, correct OCR flags, and refusal
of ineligible reports.

Codex and Claude Code conformance runs use identical sources, profiles, packets, schemas, and gates.
Their prose may differ. Accepted conformance artifacts belong under `benchmark/expected/<host>/` and
must pass the normal CLI validator; host execution is intentionally not embedded in automated tests.

