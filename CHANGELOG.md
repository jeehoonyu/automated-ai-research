# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[semantic versioning](https://semver.org/).

## [Unreleased]

### Added
- Canonical workflow document, now copied into every generated workspace so `AGENTS.md` and
  `CLAUDE.md` do not point at a file the workspace lacks.
- Research profiles (`default`, `medicine`) — profiles customise validation rules, never the
  artifact model or stage order.
- Architecture, security-model, and validation-rules documentation.
- `SECURITY.md`, `CONTRIBUTING.md`, this changelog, and a release checklist.

## [0.1.0] — unreleased

First implementation of the MVP specification in `PROJECT_GOAL.md`.

### Added
- **Foundation** — RFC 8785 canonical JSON, SHA-256 content addressing, `artifact_hash` computed
  with the hash field omitted, content-derived identifiers, UUIDv7 with an intra-millisecond
  counter, path containment, atomic writes, versioned result envelope, stable exit codes 0-8.
- **Import** — content-addressed originals, PDF and Markdown importers, deduplication by content
  with filename aliases, seven extraction statuses, page rendering with per-render hashes,
  OCR-required detection, append-only import events.
- **Normalization and chunking** — one canonical normalized text per document version, page maps,
  section extraction, chunks that never straddle a page boundary, text locators carrying a span
  hash, normalized-bounding-box visual locators.
- **Indexing and search** — SQLite FTS5 over index-eligible chunks only, reproducible
  `index_hash` over logical rows, deterministic tie-breaking, literal-only query normalization,
  results carrying resolvable locators and no evidence-quality field.
- **Run management** — run manifests pinning the source collection, two-field lifecycle
  (`phase` + `disposition`), enforced one-step transitions, work packets, append-only lifecycle
  events, `status` and `inspect`.
- **Artifacts** — 13 versioned JSON schemas, registry, validation on write.
- **Validation** — 18 checks with four statuses, where `not_evaluated` blocks exactly as `failed`
  does.
- **Reporting** — deterministic Markdown from validated JSON, citation index, report manifest and
  hash, `--draft` mode, claim-wording checked against validated classification.
- **Benchmark** — synthesized nine-document corpus and ten cases, each naming the specific gate
  that must catch it.

### Known limitations
- Cross-host conformance (spec 37) is **not** demonstrated: the benchmark simulates agent stages.
- Table and figure detection reports `not_detected`; it is not implemented.
- No OCR engine. `ocr_required` content becomes usable only through a human amendment.
- PDF parsing is not sandboxed.
