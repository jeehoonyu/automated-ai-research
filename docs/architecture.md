# Architecture

## The split

```
        YOUR HOST AGENT                    THIS PACKAGE
   ┌───────────────────────┐        ┌──────────────────────────┐
   │ reads sources         │        │ hashing, extraction      │
   │ judges support        │◄──────►│ indexing, search         │
   │ finds contradictions  │ packets│ state, validation        │
   │ assesses methodology  │  and   │ locator resolution       │
   │ writes claim text     │artifacts│ gating, report rendering │
   └───────────────────────┘        └──────────────────────────┘
     semantic judgement                deterministic mechanism
```

The dividing line: **the CLI verifies structure, hashes, references, locators, lifecycle and gates.
Agents assess meaning. The CLI enforces the agents' decisions but never claims to have understood a
source itself.**

That boundary is why there is no model provider in the dependency set. It is not an omission to be
filled in later.

## Authority

When two things disagree, this order decides:

1. **Original source bytes** — the ultimate evidence
2. **Content hashes** — establish which bytes those are
3. **Versioned JSON artifacts** — canonical representation of processing, claims, evidence, reviews
4. **Locators** — connect an artifact back to the bytes
5. **Validation results** — decide whether the artifacts are consistent and publishable
6. **Markdown reports** — a *view*, never authoritative
7. **Amendments** — how a human corrects anything above
8. **Agent prose** — authoritative for nothing merely because it was generated confidently

## Data flow

```
sources ──import──► originals/sha256/…        (bytes, never modified)
                    documents/manifests/      Document artifact
                    documents/normalized/     ONE canonical text per version
                    documents/renders/        one PNG per PDF page
                    documents/chunks/         ChunkSet
                            │
                        index (FTS5, index-eligible chunks only)
                            │
                        search ──► candidates with resolvable locators
                            │
run ──► packets/ ──► [ HOST AGENT ] ──► responses/ ──validate──► evidence/ claims/ reviews/
                            │
                        validation/validation-result.json
                            │
                        report/report.md + report-manifest.json
```

Nothing in `responses/` is canonical. Validation promotes.

## Determinism boundaries

**Deterministic** — same inputs, same bytes out: identifiers, hashes, normalization, chunking, index
contents (`index_hash`), search result ordering, report rendering.

**Not deterministic, and not claimed to be** — agent prose. Two runs of the same question produce
different wording. What must be reproducible is the *inputs, configurations, queries and validated
artifacts*, not the sentences.

Two subtleties worth knowing:

- `index_hash` covers the logical rows and content-derived identity **only**. It deliberately
  excludes `artifact_hash` values, which cover `created_at` — including them made the hash differ
  between two workspaces built from identical bytes at different moments.
- `sqlite_file_hash` is recorded separately and is *not* the reproducibility claim. Database bytes
  legitimately differ across SQLite builds.

## Versioning

`document_version_id` derives from the document hash **plus** the extraction toolchain and
configuration. Upgrading the PDF parser therefore produces a *new version* rather than silently
moving text under an existing citation. Old evidence keeps pointing at the extraction it was actually
read from.

Schema versions are declared per artifact. An unsupported major version fails clearly rather than
being coerced. Migrations create new artifacts and record what they supersede; historical artifacts
are never rewritten.

## Run lifecycle

Two fields, not one:

```
phase        how far the run got   — ordered, advances exactly one step
disposition  whether it may advance — active / blocked / review_pending /
                                       human_review_required / validation_failed /
                                       superseded / cancelled
```

A blocked run is `phase=synthesized, disposition=human_review_required`. Collapsing these into one
field would overwrite the progress, and nothing would know where to resume.

`human_review_required` is the only non-active disposition with a way forward: a recorded human
amendment.

## Stage isolation

Work packets declare `allowed_inputs` and `excluded_inputs`. The independent-review packet excludes
the primary agent's rationale, confidence, and prior review conclusions, and requests a fresh context.

The resulting independence status is *recorded, not assumed*: `confirmed_independent` requires the
host to confirm; `procedurally_isolated` means the packet excluded the right things but nothing
technically guarantees it. The default profile accepts the latter **and discloses it in the report**.
High-risk profiles do not accept it.

## Source independence

Multiple documents are not multiple independent sources. A preprint and its published version, a
study and a brief summarising it, or three papers reusing one dataset are **one** source.

Relationships are tracked (`duplicate`, `republication`, `revision_of`, `shares_primary_dataset`, …).
Hash identity and explicit metadata identifiers are definitive; heuristics are not, and are capped at
medium confidence with human review required. **Unknown independence is never promoted to
independent** — a claim whose sources were never assessed returns `not_evaluated`, which blocks.

## Citation resolution

A text locator is a pair of Python code-point offsets into the stored normalized text, plus a hash of
the span it names. Resolving is a *slice and compare*, giving three distinguishable outcomes:

| | Meaning |
|---|---|
| `resolved` | the span exists and hashes to what was recorded |
| `span_mismatch` | the offsets exist but the text there changed — **the quote moved** |
| `out_of_range` | the offsets do not exist in this version |

Without the span hash, offset drift would silently return *different words at the same coordinates*
and the citation would appear to resolve. That middle outcome is the entire reason the hash is there.

Visual locators name a page-render hash plus a normalized bounding box, so a re-render at a different
DPI cannot quietly change what a figure citation points at.

## Module map

| Module | Responsibility |
|---|---|
| `hashing` | RFC 8785 canonicalization, SHA-256, `artifact_hash` |
| `identifiers` | content-derived and time-ordered ids |
| `security/paths` | containment, sanitization, atomic writes |
| `config`, `workspace` | discovery, configuration, `init` |
| `extraction/` | PDF, Markdown, normalization, chunking, statuses |
| `artifacts/` | envelope IO, schema registry, locators |
| `indexing/`, `search/` | FTS5 build and query |
| `runs/` | lifecycle, packets, manager, inspector |
| `validation/` | the checks and the gate |
| `reporting/` | renderer, language rule, template |
