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
| **38.6 Contradiction detection** | met | a seeded contradiction attached to a claim is surfaced and blocks (B4), **and** the Claude Code conformance run *discovered* the contradiction by searching for disagreement rather than being handed it — see `benchmark/expected/claude-code/` |
| **38.7 Independent review** | met | packet excludes the prohibited context; status recorded; insufficient independence blocks; high-risk profiles require `confirmed_independent` |
| **38.8 Artifact validation** | met | all artifacts validate without manual repair; hashes verified on read; invalid lifecycle transitions rejected; unsupported schema versions fail clearly |
| **38.9 Report gating** | met | invalid citations and missing reviews block; disclosures emitted; report language checked against validated classification |
| **38.10 Cross-host benchmark** | **half met** | **Claude Code has completed the benchmark** — two runs, artifacts committed under `benchmark/expected/claude-code/`, one correctly blocked and one published, zero `not_evaluated` in either. **Codex has not been run.** The gate requires both. |

## The outstanding gate

**Spec §37 / §38.10 requires that Codex *and* Claude Code each complete the benchmark.** Claude Code
has; Codex has not.

### Done — Claude Code

Two runs against the generated corpus, artifacts committed under
`benchmark/expected/claude-code/`:

- **run-a** asked the corpus's central question, discovered the seeded contradiction by searching for
  disagreement, classified the claim `conflicting_evidence`, and was **correctly blocked** on
  `contradictions_disclosed` (14 passed, 1 failed, 0 not_evaluated). `research report` refused with
  exit 5.
- **run-b** asked a directly checkable question and **published** (15 passed, 0 failed, 0
  not_evaluated).

Both used a genuinely fresh subagent context for the independent review. The reviewer reached the
same classification as the primary agent in both runs without being shown it, and independently
deduplicated the primary study against its copy and republication.

The run exposed two defects, both recorded in that directory's README: a validator bug that refused
`verified` to correctly-scoped single-source facts (now fixed, with regression tests), and an
independence violation by the primary agent — the first review packet leaked the primary's
classification, which nothing in the CLI could have detected.

### Remaining — Codex

**Attempted 2026-07-26 and blocked.** Codex is installed (`@openai/codex@0.133.0`) and
authenticated on this machine, but two things stopped the run:

1. The configured model (`gpt-5.6-sol`) requires a newer CLI than 0.133.0 — recoverable by
   `-c model=gpt-5.5` or upgrading the CLI.
2. With a supported model, the account returned
   *"You've hit your usage limit… try again at Aug 1st, 2026"*. No `OPENAI_API_KEY` is configured
   as an alternative path.

The run was **not simulated**. A Claude subagent role-playing as Codex, with its output committed
under `benchmark/expected/codex/`, would be a fabricated conformance record — the precise failure
this platform exists to refuse. The directory stays empty until Codex actually runs.

When credits reset:

```bash
python benchmark/build_corpus.py /tmp/corpus
research init /tmp/ws-codex && research import /tmp/corpus --workspace /tmp/ws-codex
research index --workspace /tmp/ws-codex
research run --question "Does process-in-memory reduce off-chip data movement?" --workspace /tmp/ws-codex
research run --question "What evaluation scope did the primary process-in-memory study use?" --workspace /tmp/ws-codex

# Give Codex each stage packet in turn. Use a SEPARATE `codex exec` invocation for the
# independent-review stage — a new exec session is a genuinely fresh context, which is what
# `confirmed_independent` requires.
codex exec -c model=gpt-5.5 "$(cat /tmp/ws-codex/runs/<run-id>/packets/00-planning.json)"

research validate <run-id> --workspace /tmp/ws-codex
research report   <run-id> --workspace /tmp/ws-codex
```

Then copy the canonical artifacts to `benchmark/expected/codex/` mirroring the Claude Code layout,
and run the comparison:

```bash
python benchmark/compare_hosts.py benchmark/expected/claude-code benchmark/expected/codex
```

Exit 0 = hosts agree on every outcome and the gate is closed. Exit 1 = they disagree, with the
differing fields listed. Exit 3 = a host is missing, so nothing was compared — the harness reports
"cannot compare" rather than "agree", because an empty comparison passing silently is exactly the
fail-open pattern this project keeps finding in itself.

Finally, wire that command into CI.

## Pre-release tasks

- [x] Apache-2.0 licence
- [x] `SECURITY.md`, `CONTRIBUTING.md`, `CHANGELOG.md`
- [x] Architecture, security-model, validation-rules documentation
- [x] Canonical workflow shipped into generated workspaces
- [x] Research profiles (`default`, `medicine`)
- [x] Redistributable benchmark with no copyrighted material
- [x] Test suite green
- [~] Cross-host conformance runs — Claude Code done, Codex outstanding
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
