# Benchmark and host conformance

The checked-in corpus is synthetic and Apache-2.0 licensed. Deterministically generated benchmark PDF
fixtures cover tables, multi-page rendering, vector regions, captions, raster content, and an
image-only OCR-required page; tests generate additional malformed and encrypted cases locally.
Expected cases include exact citations, a supporting result, a contradiction, source dependence, weak
methodology, prompt injection, and an insufficient-evidence outcome.

Deterministic acceptance requires stable document IDs, equivalent logical indexes, resolvable locators,
no unsupported high-confidence claims, surfaced seeded contradictions, correct OCR flags, and refusal
of ineligible reports.

Codex and Claude Code conformance runs use identical sources, profiles, packets, schemas, and gates.
Their prose may differ. Accepted conformance artifacts belong under `benchmark/expected/<host>/` and
must pass the normal CLI validator; host execution is intentionally not embedded in automated tests.
`python benchmark/prepare_conformance.py <output>` constructs both workspaces from one copied canonical
source/index base and verifies a normalized packet-contract hash before any host reasoning begins.
After host and human stages finish, `python benchmark/check_conformance.py <output>` runs the ordinary
validator and report gate for all four runs, checks the seeded contradiction and insufficient-evidence
outcomes, writes a hashed check manifest, and exits nonzero unless the entire pair passes.
