# Artifact contracts

Schemas under `schemas/v1/` are authoritative. Every canonical artifact declares its schema name,
semantic version, unique artifact ID, RFC 8785 content hash, UTC creation time, and actor metadata.

Source documents use `DOC-sha256-<full hash>`. Document versions, chunks, and evidence use deterministic
SHA-256-derived identifiers. Runs use UUIDv4. Claims, reviews, and amendments use UUIDv7; immutable
claim-version artifact IDs append `-vN`.

PDF pages and Markdown source lines are 1-based. Chunk start/end values are Unicode code-point offsets
into normalized document text. Evidence text-span offsets are relative to the chunk's exact text and
include a UTF-8 SHA-256 span hash. Visual boxes use normalized top-left coordinates in `[0,1]` and bind
to a complete page-render hash.

Agent responses are staging data, not canonical artifacts. Promotion validates and stores new versions.
Amendments bind exact target and replacement hashes, and published content must be revalidated.

Run manifests freeze the full effective configuration alongside its RFC 8785 hash and bind the logical
index manifest used at initialization. Index logical identity includes sorted canonical input artifact
hashes; the SQLite byte hash is recorded separately and checked before every search.
Run-scoped searches append hashed events containing normalized queries, filters, index identity, and
ordered result IDs; retrieval artifacts bind those event IDs and hashes. Secret-shaped query text is
redacted in the log while SHA-256 fields bind the exact query, normalized query, and FTS expression.
