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

**All ten phases of the MVP specification are implemented.** All nine public commands work.

| Command | State |
|---|---|
| `init` `import` `index` `search` `run` `status` `inspect` `validate` `report` | implemented |

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
- **Phase 4 (indexing and search)** — SQLite FTS5 built only from index-eligible chunks, a
  reproducible `index_hash` over the logical rows (with the SQLite file hash recorded separately),
  deterministic tie-breaking, literal-only query normalization, and search results carrying a
  locator that resolves to exact source text.

- **Phase 5 (run management)** — run manifests pinning the source collection, a two-field lifecycle
  (`phase` + `disposition`) with enforced one-step transitions, stage work packets carrying the
  independence exclusions, append-only lifecycle events, `research status`, and `research inspect`.

- **Phase 6 (research artifacts)** — 14 versioned JSON schemas covering every canonical artifact,
  a schema registry, and validation on **write** so an invalid artifact cannot reach disk. Spec rules
  are encoded as constraints, not prose: `verified` is refused for causal claims,
  `strongly_supported` requires two evidence records, numeric confidence scores are forbidden
  outright, OCR-dependent evidence must demand human review, and an independent review must declare
  its independence.

- **Phase 7 (validation and gating)** — 22 checks covering source hashes, locator resolution,
  claim-evidence links, review completeness, reviewer independence, OCR and visual certainty,
  contradiction disclosure, support classifications, and lifecycle replay. Each check reports
  `passed` / `failed` / `not_evaluated` / `not_applicable`, and **`not_evaluated` blocks publication
  exactly as `failed` does**.

- **Phase 8 (reporting)** — deterministic Markdown rendered from validated JSON with a citation
  index, provenance summary, and report manifest. Publication requires a passing validation result;
  `--draft` renders a visibly-marked draft that names what is blocking it. Claim wording is checked
  against its validated classification, and the renderer emits claim text **verbatim** plus a
  qualifier from a fixed table — so it has no vocabulary of its own for how well-supported something
  is.

- **Phase 9 (benchmark)** — a fully synthesized, redistributable corpus of nine documents whose
  *relationships* are the test: a byte-identical duplicate, a republication of the same study, an
  independent replication reporting the opposite direction, a topical survey that supports nothing,
  an image-only page, and a prompt-injection document. Ten cases each name the **specific** gate
  that must catch them.

- **Phase 10 (release)** — canonical workflow shipped into every generated workspace, research
  profiles, architecture / security-model / validation-rules documentation, `SECURITY.md`,
  `CONTRIBUTING.md`, a changelog, CI across Linux/macOS/Windows, and a release checklist that lists
  what is **not** met.

348 tests. A stage is complete only when its artifact exists **and** validates — never because a
file appeared, and never because an artifact says so about itself: every artifact validation loads
is checked against its own `artifact_hash`, and the derived bytes citations resolve against are
re-hashed too.

### What is not established

Spec §37 requires that Codex **and** Claude Code both complete the benchmark against the same
packets. **Claude Code has** — two real runs with artifacts committed under
[`benchmark/expected/claude-code/`](benchmark/expected/claude-code/), one correctly blocked on a
discovered contradiction and one published, with zero `not_evaluated` checks in either.
**Codex has not been run**, so the gate is half met; see
[`docs/release-checklist.md`](docs/release-checklist.md).

That run also exposed two defects worth knowing about: a validator bug that refused `verified` to
correctly-scoped single-source facts (fixed), and an independence violation by the primary agent —
the first review packet leaked the primary's own classification, which **nothing in the CLI could
have detected**.

The second one became the next goal, and is now partly closed: `confirmed_independent` requires a
`ReviewContext` artifact recording the text the host attests it gave the reviewer, which validation
scans for excluded material. See [`GOAL.md`](GOAL.md) and
[`docs/validation-rules.md`](docs/validation-rules.md). This catches an *accidental* leak and makes a
deliberate one require falsifying a hashed record — it does not make independence verifiable. A host
that sends a leaky context and attests a clean one still passes.

Applying that rule to our own evidence, **both committed conformance runs are downgraded**: they
declare `confirmed_independent`, attest no context, and would now be blocked rather than
grandfathered.

**CI has still never executed.** The first run on this repository was cancelled by GitHub before any
job started — private repositories bill Actions minutes, and the account's billing is blocked. That
is an account setting rather than a code defect, but "Verified on Linux and macOS" remains
unchecked either way.

**Until 2026-07-28 the built wheel did not work.** The canonical schemas lived beside the package
rather than inside it, so no wheel shipped them and an installed copy could run `--version` and
`init` and nothing else; the CI job meant to verify the install ran exactly those two commands.
Fixed, along with two more claims nothing backed — research profiles were never read by any code,
and exit code `6 HUMAN_REVIEW_REQUIRED` was unreachable. See [`GOAL.md`](GOAL.md).

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
- [`GOAL.md`](GOAL.md) — the current working goal against it, and what would count as meeting it
- `docs/lessons-carried-forward.md` — failures from a predecessor project and where each is now
  enforced. Worth reading before changing any gate.
- [`docs/architecture.md`](docs/architecture.md) — trust boundaries, authority model, determinism
- [`docs/security-model.md`](docs/security-model.md) — threat model, and what is *not* protected
- [`docs/validation-rules.md`](docs/validation-rules.md) — the 22 checks, the profile rules, and why `not_evaluated` blocks
- [`docs/release-checklist.md`](docs/release-checklist.md) — gate status, including the unmet one
- [`benchmark/README.md`](benchmark/README.md) — the corpus and the ten cases
- [`CONTRIBUTING.md`](CONTRIBUTING.md), [`SECURITY.md`](SECURITY.md), [`CHANGELOG.md`](CHANGELOG.md)

## Development

```bash
pip install -e ".[dev]"
pytest -q
```

Primary targets are Linux and macOS; Windows is supported where the PDF dependencies allow. Artifact
formats and CLI contracts are portable everywhere.

## License

Apache-2.0.
