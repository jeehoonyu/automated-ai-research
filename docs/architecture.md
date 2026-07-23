# Architecture

## Authority

Original source bytes are authoritative evidence. SHA-256 establishes document identity. A specific
normalization toolchain and configuration produces an immutable document version. Versioned JSON is
canonical for chunks, evidence, claims, reviews, run state, amendments, validation, and reports.
Markdown reports and SQLite indexes are derived and rebuildable.

Artifacts use RFC 8785 canonical JSON for hashes, excluding the top-level `artifact_hash` field during
calculation. Accepted artifacts live at immutable, sharded paths. Full IDs and hashes remain in JSON;
short path shards only avoid platform path limits. Mutable `manifest.json`, `latest.md`, and index files
are projections whose history or inputs remain canonical.

## Components

- Workspace and security modules enforce discovery, path containment, size limits, and atomic writes.
- Ingestion preserves originals, extracts Markdown/PDF content, renders PDF pages, and creates chunks.
- Indexing rebuilds SQLite FTS5 from the latest validated document versions.
- Run management creates packets, promotes stage candidates, and appends lifecycle events.
- Validation checks deterministic structure and enforces typed semantic-review decisions.
- Reporting renders accepted claims verbatim without strengthening their classification.

## Determinism boundary

The CLI can verify bytes, hashes, schemas, ordering, references, text spans, image regions, state, and
review completeness. Host agents—not the CLI—judge whether a citation semantically supports a claim,
whether methodology is adequate, and whether contradictions matter. Those decisions are explicit,
typed, reviewable artifacts. Reproducibility means replayable inputs and decisions, not identical prose.

## Lifecycle

A run has an ordered `phase` and an orthogonal `disposition`. Review or validation can block a run
without erasing its completed phase. Every transition is append-only. Supplemental human reviews and
amendments invalidate report eligibility until full revalidation succeeds.

