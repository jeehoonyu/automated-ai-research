# Automated AI Research Platform

Local-first, evidence-first research over your own document collections.

You point it at PDFs and Markdown files. It preserves the originals, extracts and indexes them, and
then hands your coding agent — Codex, Claude Code, or another — structured **work packets**. The
agent does the reasoning. This package does the parts that must be deterministic: hashing, extraction,
indexing, search, state, validation, citation resolution, gating, and report rendering.

**The point is not to produce a report. It is to refuse to produce one that isn't supported.**

## Quickstart

```bash
git clone https://github.com/jeehoonyu/automated-ai-research
cd automated-ai-research
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
```

### One folder, many topics

Most people research more than one thing. A **project** is a folder of independent **studies**, each
with its own field, corpus, runs and rules:

```bash
research project init ~/ai-research --name "My research"
research project new "Statins and cardiac outcomes" --field medicine --profile medicine
research project new "PIM architecture" --field computer-architecture
research project list
```

```
project My research
  2 study(ies) across 2 field(s): computer-architecture, medicine

  PIM architecture  [computer-architecture]  profile=default
    8 document(s), indexed, 2 run(s) — 2 blocked

  Statins and cardiac outcomes  [medicine]  profile=medicine
    0 document(s), NOT INDEXED, 0 run(s)

  totals: 2 run(s); 0 awaiting a human, 2 blocked, 0 published
```

`research ui --project ~/ai-research` shows the same thing in a browser, ordered so that studies
needing attention come first. Click a study and it opens in place at `/studies/<name>/` — its runs,
claims, evidence, documents, search and page renders, with a link back out. Drop a profile into
`~/ai-research/profiles/` and every study can use it; a study can override it with a stricter one of
the same name, never a looser one.

**Studies do not share a corpus, on purpose.** A run pins its sources when it is created, and that
pinning is what makes it answerable months later. Sharing one document store would let an import in
one topic move ground under another topic's citations. Import the same PDF into two studies and
content-addressing gives it the same identity in both — you pay disk, not agreement.

A study is just a workspace. Move its directory out of the project and it still works.

### A single study on its own

Skip projects entirely if you only have one topic:

```bash
research init ~/my-research
research import ~/papers/*.pdf --workspace ~/my-research
research index                 --workspace ~/my-research
research run --question "Does X reduce Y?" --workspace ~/my-research
```

`research run` does no reasoning. It records the question, pins the corpus as it stands, writes ten
work packets, and stops. Your agent does the thinking; the packets tell it what each stage owes and
what it may not look at. Then:

```bash
research validate <run-id> --workspace ~/my-research
research report   <run-id> --workspace ~/my-research
research ui       --workspace ~/my-research --open
```

`research report` exits 5 and refuses if any gate blocks. **That refusal is the product working.**

Want to see it work before pointing it at your own sources? The benchmark corpus is synthetic and
ships with the repo:

```bash
python benchmark/build_corpus.py /tmp/corpus
research init /tmp/demo && research import /tmp/corpus --workspace /tmp/demo
research index --workspace /tmp/demo
```

## Drive it with an AI agent

The platform is deliberately not an agent. It expects one, and ships the prompts:

| File | For |
|---|---|
| [`AGENTS.md`](AGENTS.md) | orienting any AI tool in this repository — folder map, the workflow, the invariants that must not break, how to verify a change |
| [`prompts/run-research.md`](prompts/run-research.md) | taking a run from empty workspace to report |
| [`prompts/independent-review.md`](prompts/independent-review.md) | the independent review — **paste into a fresh session**, never the one that did the synthesis |
| [`prompts/audit-this-repo.md`](prompts/audit-this-repo.md) | auditing a change you made to the tool. This prompt found most of the defects in `CHANGELOG.md` |
| [`prompts/extend-a-gate.md`](prompts/extend-a-gate.md) | adding a validation check for your own field |

`AGENTS.md` is read by Codex, Cursor and others directly; [`CLAUDE.md`](CLAUDE.md) points Claude Code
at the same file. There is deliberately no host-specific guidance, for the same reason the research
workflow has none: two tools with two sets of rules quietly become two standards of evidence.

## What it does not do

Deliberately, and not as a temporary gap:

- No embedded model APIs, no local model server, no Ollama, no bundled agent framework
- No web browsing, no web search, no automatic downloading of URLs found in documents
- No vector database, no embeddings, no knowledge graph
- **No network access in core processing at all**

Your host environment supplies the intelligence. This repository supplies the parts that make its
output checkable.

## How a run works

Ten stages. Eight are your agent's; two are the CLI's.

```
planning → retrieval → evidence_extraction → synthesis → contradiction_review
   → citation_review → methodology_review → independent_review → final_validation → report
```

Each stage has a **work packet** in `runs/<run-id>/packets/` naming its allowed inputs, its forbidden
inputs, what it must produce, and the command that will judge it. The agent writes plain JSON to
`responses/`; `research validate <run-id> --stage <stage>` validates it, promotes it into the
canonical directories, and advances the run by exactly one phase.

**A stage is complete when its artifact validates — never because a file appeared.** Promotion is
all-or-nothing, stages cannot be skipped, and the CLI stamps `artifact_hash` so the agent never has
to.

The full version, including what each stage owes and the independence rules, is
[`workflow/canonical-workflow.md`](workflow/canonical-workflow.md) — which is also copied into every
workspace `research init` creates, so an agent working in a workspace has it to hand.

## Looking at a workspace

```bash
research ui --workspace example-workspace --open
```

Serves a read-only view on `http://127.0.0.1:8787/`. Everything it shows is already available from
the CLI; what a browser adds is following a chain — a claim, the evidence under it, the locator, and
the source text that locator resolves to — without copying identifiers between commands.

Three properties are enforced rather than intended, and each has a test that fails when it is broken:

- **It never writes.** No route mutates a workspace, every method except `GET` and `HEAD` is refused,
  and an integration test hashes every file in a workspace, browses every page, and re-hashes.
  Notably `/search` does *not* record a retrieval log — `research search --run` does that on purpose,
  and a page load is not retrieval.
- **It cannot make a gate look better than it is.** Whether a check blocks is answered by
  `CheckResult.blocks` itself, not by a table restated in the UI, so `not_evaluated` is painted
  exactly as `failed` and labelled *"nobody looked — blocks publication exactly as a failure does"*.
  A run page also re-derives the artifact roster and says so loudly when the stored verdict no longer
  describes the files on disk.
- **Document text stays data.** Autoescaping is unconditional, every response carries
  `default-src 'none'`, and the interface ships no JavaScript at all.

It binds to loopback and refuses anything else without `--allow-remote`, because it exposes every
document and artifact in the workspace and has no authentication. See
[`docs/security-model.md`](docs/security-model.md).

**Page renders are shown.** A quote cannot settle a figure or a table — someone has to look — so a
document's pages are displayed as the CLI rendered them, and visual evidence shows the page it cites.
Each image is re-hashed against the digest the manifest recorded before it is served; a render whose
bytes changed under an existing citation is refused with an explanation rather than displayed.

### Running it on your own machine

The UI opens an existing workspace and never creates one. A workspace is any directory containing
`research.yaml`; pass `--workspace`, or run from inside one and it walks up to find it.

Paths are not a special case. Verified on Windows against directories with spaces, non-ASCII names
(`한글 폴더`, `café — ünïcode`), dots in directory names, and twelve levels of nesting — every page
serves, and `--workspace` accepts the path with backslashes, forward slashes, a trailing separator,
or relative. Files stored under OneDrive work too, including cloud-only placeholders: they are not
symlinks, so import accepts them, though reading one triggers a download and needs the network.

The document page lists the **absolute** location of the original bytes, the normalized text and the
chunk set, so you can open them yourself — the artifacts record workspace-relative paths, which are
right for a workspace that gets moved and useless for finding a file.

## Forking it for your own research

The tool is domain-agnostic. Your field goes in the **rules**, not the code.

**Start with a profile.** `src/research/profiles/medicine.yaml` is the worked example — higher risk
tier, `confirmed_independent` required rather than merely requested, `verified` forbidden outright,
and six human-review triggers. Copy it and change what your field demands.

A profile may only name triggers the validator can actually fire, and may only require methodology
items a review can record. A key that nothing reads is **rejected at load time** rather than silently
ignored — a rule nothing enforces is a promise, not a rule, and this is the one place where that
distinction is cheap to enforce.

**Then, if you need a gate that does not exist**, [`prompts/extend-a-gate.md`](prompts/extend-a-gate.md)
walks an agent through adding one correctly: what it must answer when its input is absent (
`not_evaluated`, which blocks), why it may check that something was *recorded* but not whether it was
any good, and how to prove the check can actually fail.

Three housekeeping notes for a fork:

- **Replace [`GOAL.md`](GOAL.md), or delete it.** It is the original build's working log — what was
  found, what was fixed, and what remains unmet. It is not about your fork.
- **Keep [`docs/release-checklist.md`](docs/release-checklist.md) honest.** Restate it for your build,
  including what you have not done. A checklist that only records successes is a marketing document.
- **The benchmark corpus is synthetic and redistributable.** Nothing in it is copyrighted. Add cases
  for gates you add — `benchmark/expected/cases.json` names the specific check each case must trip,
  because asserting only "publication was blocked" passes when the wrong gate fires.

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

## Status

**All ten phases of the MVP specification are implemented.** All nine public commands work.

| Command | State |
|---|---|
| `init` `import` `index` `search` `run` `status` `inspect` `validate` `report` | implemented |
| `ui` | implemented — a read-only local web view, **not** part of the specification |

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

- **Phase 5 (run management)** — run manifests pinning the source collection, stage acceptance
  (`research validate --stage` validates a stage's responses, promotes them, and advances one
  phase), a two-field lifecycle
  (`phase` + `disposition`) with enforced one-step transitions, stage work packets carrying the
  independence exclusions, append-only lifecycle events, `research status`, and `research inspect`.

- **Phase 6 (research artifacts)** — 15 versioned JSON schemas covering every canonical artifact,
  a schema registry, and validation on **write** so an invalid artifact cannot reach disk. Spec rules
  are encoded as constraints, not prose: `verified` is refused for causal claims,
  `strongly_supported` requires two evidence records, numeric confidence scores are forbidden
  outright, OCR-dependent evidence must demand human review, and an independent review must declare
  its independence.

- **Phase 7 (validation and gating)** — 25 checks covering source hashes, locator resolution,
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

609 tests (606 passing, 3 skipped). A stage is complete only when its artifact exists **and**
validates — never because a
file appeared, and never because an artifact says so about itself: every artifact validation loads
is checked against its own `artifact_hash`, and the derived bytes citations resolve against are
re-hashed too.

### What is not established

**This repository contains two independent implementations of `PROJECT_GOAL.md`.** The one at the tip
was built by Claude Code. The one Codex built is preserved in this history at the tag
`codex-implementation` (`git checkout codex-implementation`), and it carries a real Codex benchmark
run that this build does not have. They were developed separately, on purpose — a conformance gate
that compares two hosts proves nothing if both run the same code — and merged into one repository on
2026-07-31 without discarding either.

That preserved run **does not** close the cross-host gate, and is not counted as if it did; see
[`docs/release-checklist.md`](docs/release-checklist.md) for why (different artifact layouts, so
there is nothing to compare).

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

## Documentation

- [`AGENTS.md`](AGENTS.md) — **start here if you are an AI tool.** Folder map, the workflow, the
  invariants, how to verify a change. [`CLAUDE.md`](CLAUDE.md) points Claude Code at the same file.
- [`prompts/`](prompts/) — copy-paste prompts for running research, independent review, auditing a
  change, and adding a gate
- `PROJECT_GOAL.md` — the full specification (authoritative, and does not change)
- [`GOAL.md`](GOAL.md) — the **original build's** working log: what was found, what was fixed, what
  remains unmet. Replace or delete it in a fork; it is not about yours.
- `docs/lessons-carried-forward.md` — failures from a predecessor project and where each is now
  enforced. Worth reading before changing any gate.
- [`docs/architecture.md`](docs/architecture.md) — trust boundaries, authority model, determinism
- [`docs/security-model.md`](docs/security-model.md) — threat model, and what is *not* protected
- [`docs/validation-rules.md`](docs/validation-rules.md) — the 25 checks, the profile rules, and why `not_evaluated` blocks
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
