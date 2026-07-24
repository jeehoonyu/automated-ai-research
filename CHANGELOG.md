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
- Add checked-in deterministic visual/table benchmark PDFs, same-ID human visual-verification
  amendments, strict RFC3339/actor metadata, supplemental-stage blocking, explicit report uncertainty
  factors and contradictory excerpts, atomic-failure recovery, and HTML-escaping coverage.
- Add a hashed two-question cross-host conformance preparer that clones one canonical source/index
  base and verifies normalized Codex/Claude packet parity, plus shorter sharded run-manifest history
  paths for Windows compatibility.
- Add a hashed cross-host conformance checker that applies the normal validation and publication gates
  to both benchmark cases and rejects incomplete or outcome-incompatible host runs.
- Add isolated wheel-install smoke testing to the cross-platform CI matrix.
- Publish the public repository, verify the full three-platform CI matrix, and make canonical report
  paths portable across operating systems.

## 0.1.0

- Initial local-first MVP implementation.
- Content-addressed PDF and Markdown ingestion with page rendering and OCR-required detection.
- Deterministic SQLite FTS5 retrieval.
- Canonical schemas, work packets, lifecycle management, validation, amendments, and report gating.
- Shared Codex and Claude Code workflow plus a redistributable benchmark.
