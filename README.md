# Automated AI Research Platform

Local-first, evidence-first research over your own document collections.

You point it at PDFs and Markdown files. It preserves the originals, extracts and indexes them, and
then hands your coding agent — Codex, Claude Code, or another — structured **work packets**. The
agent does the reasoning. This package does the parts that must be deterministic: hashing, extraction,
indexing, search, state, validation, citation resolution, gating, and report rendering.

**The point is not to produce a report. It is to refuse to produce one that isn't supported.**

## What it does not do

Deliberately, and not as a temporary gap:

- No embedded model APIs, no local model server, no Ollama, no bundled agent framework
- No web browsing, no web search, no automatic downloading of URLs found in documents
- No vector database, no embeddings, no knowledge graph
- **No network access in core processing at all**

Your host environment supplies the intelligence. This repository supplies the parts that make its
output checkable.

## Status

**Phases 1–3 of 10 are implemented.** Everything else is scaffolded and honest about it: commands
for unimplemented phases exit non-zero and name the phase. They do not pretend to succeed.

| Command | State |
|---|---|
| `research init`, `research import` | implemented |
| `index` `search` `run` `status` `inspect` `validate` `report` | routable; exit 1 with `not_implemented` |

- **Phase 1 (foundation)** — RFC 8785 canonical JSON, SHA-256 content addressing, the
  `artifact_hash` self-reference rule, content-derived identifiers, UUIDv7 with intra-millisecond
  monotonicity, path containment and filename sanitization, atomic writes, workspace discovery, the
  versioned result envelope, stable exit codes.
- **Phase 2 (import)** — content-addressed originals, PDF and Markdown importers, deduplication by
  content with import aliases, seven explicit extraction statuses, page rendering with per-render
  hashes, OCR-required detection, append-only import events.
- **Phase 3 (normalization and chunking)** — one canonical normalized text per document version,
  page maps, section extraction, chunk generation that never straddles a page boundary, text
  locators with span hashes, and the visual-region model.

93 tests. `research import` produces everything the index will later consume.

## Install

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e .
research --help
```

```bash
research init example-workspace
```

## Why it is built this way

**Originals are authoritative.** Imported bytes are never modified. A document's identity is
`SHA-256` of those bytes — not its filename, path, import time, or who imported it. Re-importing the
same file anywhere produces the same identity, which is what makes deduplication and the audit trail
work.

**JSON is canonical; Markdown is a view.** Reports are rendered *from* validated JSON artifacts.
A Markdown file never becomes more authoritative than the artifacts beneath it, and the report
generator may not strengthen a claim's language beyond its validated classification.

**Extraction is versioned.** `document_version_id` derives from the document hash *plus* the
extraction toolchain and configuration. Upgrading the PDF parser produces a new version rather than
silently moving the text under someone's existing citation.

**Evidence before synthesis.** A claim cannot appear in a publishable report unless it references
evidence that resolves to immutable source bytes at an exact locator, the citation genuinely supports
it, contradictions were sought, and the required reviews passed.

**Insufficient evidence is a result.** `unable_to_determine` is a successful research outcome, not a
failure. The platform prefers refusing publication over publishing an unsupported conclusion.

**Imported content is untrusted.** Documents may carry prompt injection, scripts, hostile filenames,
or traversal paths. Document text is data, never instructions. Work packets separate trusted workflow
instructions from untrusted document content explicitly.

## Documentation

- `PROJECT_GOAL.md` — the full specification (authoritative)
- `docs/lessons-carried-forward.md` — failures from a predecessor project and where each is now
  enforced. Worth reading before changing any gate.
- `docs/architecture.md`, `docs/security-model.md`, `docs/validation-rules.md` — Phase 10

## Development

```bash
pip install -e ".[dev]"
pytest -q
```

Primary targets are Linux and macOS; Windows is supported where the PDF dependencies allow. Artifact
formats and CLI contracts are portable everywhere.

## License

Apache-2.0.
