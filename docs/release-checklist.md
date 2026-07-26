# Release checklist

Status as of the current tree. A gate that is not met is listed as **not met**, with what remains —
a checklist that only records successes is a marketing document.

## MVP release gates (spec §38)

| Gate | Status | Evidence |
|---|---|---|
| **38.1 Import determinism** | met | same bytes → same `document_id` across independent workspaces; renaming does not change identity; re-import is a duplicate with the alias retained |
| **38.2 Extraction integrity** | met | every PDF page rendered with a stable hash; low-text pages flagged `ocr_required`; `OCR_REQUIRED.is_usable_as_evidence` is `False` |
| **38.3 Index determinism** | met | rebuild reproduces `index_hash`; matches across workspaces built a second apart; tokenizer, ranking, SQLite version and input hashes recorded |
| **38.4 Citation resolution** | met | every emitted citation resolves; `span_mismatch` distinguishes a moved quote from a missing one; dangling references block |
| **38.5 Claim support** | met | claims without evidence rejected; related-but-non-supporting citations rejected (benchmark B3); `verified` refused for causal claims at the schema layer |
| **38.6 Contradiction detection** | **partly met** | a seeded contradiction attached to a claim is surfaced and blocks (B4). **Not met:** the platform does not *discover* contradictions itself — that is the contradiction-review agent's job, and no test proves an agent does it |
| **38.7 Independent review** | met | packet excludes the prohibited context; status recorded; insufficient independence blocks; high-risk profiles require `confirmed_independent` |
| **38.8 Artifact validation** | met | all artifacts validate without manual repair; hashes verified on read; invalid lifecycle transitions rejected; unsupported schema versions fail clearly |
| **38.9 Report gating** | met | invalid citations and missing reviews block; disclosures emitted; report language checked against validated classification |
| **38.10 Cross-host benchmark** | **NOT MET** | the benchmark simulates agent stages with pre-authored artifacts. Neither Codex nor Claude Code has been run against these packets. See below. |

## The outstanding gate

**Spec §37 / §38.10 requires that Codex and Claude Code each complete the benchmark** using the same
repository, workflow, schemas, packets, CLI and report gates, producing schema-valid and
report-eligible outputs, with their canonical artifacts committed and validated in CI.

What exists: the contracts a host must satisfy, and a benchmark proving those contracts are enforced.

What does not exist: evidence that either host satisfies them.

To close it:

1. `research init`, `research import benchmark/sources`, `research index`, `research run`.
2. Give each stage packet to Codex; commit the resulting artifacts under
   `benchmark/expected/codex/`.
3. Repeat with Claude Code under `benchmark/expected/claude-code/`.
4. Assert both reach the same **outcomes** — prose may differ; schemas, references, gate results and
   benchmark verdicts must agree.
5. Wire that comparison into CI.

## Pre-release tasks

- [x] Apache-2.0 licence
- [x] `SECURITY.md`, `CONTRIBUTING.md`, `CHANGELOG.md`
- [x] Architecture, security-model, validation-rules documentation
- [x] Canonical workflow shipped into generated workspaces
- [x] Research profiles (`default`, `medicine`)
- [x] Redistributable benchmark with no copyrighted material
- [x] Test suite green
- [ ] Cross-host conformance runs (above)
- [x] CI configuration (`.github/workflows/ci.yml`) — Linux, macOS, Windows
- [ ] Verified on Linux and macOS — CI covers all three, but no run has executed yet
- [x] `pip install` from a built wheel verified in a clean environment (package data ships)

## Known limitations to state in release notes

- No OCR engine. `ocr_required` content becomes usable only through a recorded human amendment.
- Table and figure detection reports `not_detected` — it is not implemented, and the full-page render
  is the fallback.
- PDF parsing is not sandboxed and runs in-process.
- Overstatement detection is lexical, not comprehension: it catches common absolutes and will miss a
  subtle one.
- Heuristic source-relationship detection is not implemented; relationships must be supplied by an
  agent or human, and unassessed independence blocks a `strongly_supported` claim.
