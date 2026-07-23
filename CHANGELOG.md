# Changelog

## Unreleased

- Verify all canonical JSON, work packets, lifecycle chains, frozen configuration/index snapshots, and
  retrieval references during full validation.
- Recheck source, render, locator, lifecycle, and packet integrity immediately before publication.
- Select extraction versions by active configuration, bind logical index identity to input artifact
  hashes, and reject modified SQLite bytes during search.
- Enforce typed stage outputs, non-advancing blocked stages, and explicit human actor attestations.
- Redact secret-shaped search text while hash-binding exact queries, validate configuration before
  processing, and reject unrecorded canonical artifacts or dependent strong-support sources.
- Expand integration coverage for Markdown/PDF tables, multi-column pages, visual captions,
  post-validation provenance tampering, and successful insufficient-evidence findings.
- Add isolated wheel-install smoke testing to the cross-platform CI matrix.

## 0.1.0

- Initial local-first MVP implementation.
- Content-addressed PDF and Markdown ingestion with page rendering and OCR-required detection.
- Deterministic SQLite FTS5 retrieval.
- Canonical schemas, work packets, lifecycle management, validation, amendments, and report gating.
- Shared Codex and Claude Code workflow plus a redistributable benchmark.
