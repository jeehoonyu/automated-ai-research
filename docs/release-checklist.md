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
| **38.7 Independent review** | met | packet excludes the prohibited context; status recorded; insufficient independence blocks; high-risk profiles require `confirmed_independent`, which now additionally requires an attested reviewer context that validation scans for leaks (`independence_context_attested`) |
| **38.8 Artifact validation** | met | all artifacts validate without manual repair; hashes verified on read — **true only since 2026-07-28**: validation loaded agent-written artifacts through a bare `json.load`, so a hand edit that stayed schema-valid was invisible and could flip a gate to passed; invalid lifecycle transitions rejected; unsupported schema versions fail clearly |
| **38.9 Report gating** | met | invalid citations and missing reviews block; disclosures emitted; report language checked against validated classification; **and since 2026-07-30 the verdict is bound to the artifacts it was computed over** — `report_eligible` was previously a boolean the renderer read before re-reading the run from disk, so a claim written after `validate` was published unvalidated |
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

**Both runs have since been downgraded.** `check_independence_attested` now requires a `ReviewContext`
artifact behind any `confirmed_independent` declaration. These runs declare it and attest nothing,
so under the current validator they are `not_evaluated` on that check — which blocks. They are kept
unmodified and marked down rather than exempted; `tests/unit/test_docs.py` pins the downgrade. Gate
38.6's discovery evidence and both runs' verdicts are unaffected.

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
- [x] Research profiles (`default`, `medicine`) — **this was previously ticked while no code read a
  profile file.** The whole feature was one hard-coded set, `{"medicine", "finance"}`, and
  `medicine.yaml`'s `prohibited_confidence`, methodology requirements and seven human-review
  triggers were inert. `risk`, `reviewer_independence`, `prohibited_confidence` and
  `human_review_triggers` are now loaded and applied; the four keys that still do nothing are
  declared unimplemented with reasons, and a key that is neither is a load error.
- [x] Every exit code in spec §34 is reachable — `6 HUMAN_REVIEW_REQUIRED` was not. It is only
  derived from `errors`, and `human_review_required` was only ever emitted as a warning, so an
  import reporting `failed 0` exited `4 SOURCE_PROCESSING_FAILURE`. Pinned by
  `tests/integration/test_exit_codes.py`, which enumerates `ExitCode` and produces each one.
- [x] Redistributable benchmark with no copyrighted material
- [x] Test suite green
- [x] `ruff check src tests` clean — **it had never been run.** Triggering CI for the first time on
  2026-07-28 exposed 102 findings, including three security lints (`S608` SQL construction, `S701`
  Jinja autoescape, `S110` swallowed exception) that were correct but undocumented, and one shared
  fixture imported across test modules. All fixed or annotated with the reason.
- [x] `mypy --strict src/research` clean — **also never run**; 17 errors. Two were worth having:
  `rel` was bound twice in `check_source_independence` (once as the relationship artifact, once as
  its type string), and `discover_sources` chose its destination list and its value in two separate
  ternaries. Both were runtime-correct and both were confusing.
- [~] Cross-host conformance runs — Claude Code done, Codex outstanding
- [x] CI configuration (`.github/workflows/ci.yml`) — Linux, macOS, Windows
- [ ] Verified on Linux and macOS — **still not met, and the reason has changed.** The workflow has
  now been triggered once (2026-07-28). Every job was cancelled by GitHub before starting:
  *"recent account payments have failed or your spending limit needs to be increased"*. Private
  repositories bill Actions minutes; this repository is private. Fixing it is an account setting —
  raise the Actions spending limit, or run CI from a public mirror. Until a run completes, the
  suite has only ever executed on Windows.
- [x] `pip install` from a built wheel verified in a clean environment (package data ships) —
  **this was ticked while it was false.** `SCHEMA_ROOT` pointed at the *repository* root, so no
  wheel ever contained a schema and an installed copy could run `--version` and `init` and nothing
  else. The CI job intended to verify it ran exactly `--version` and `init`: its coverage equalled
  the working subset, so it would have passed forever. Schemas and profiles now live under
  `src/research/`, the job drives import → index → search → run → validate, and
  `tests/unit/test_packaging.py` catches the class without needing CI at all.

## Known limitations to state in release notes

- No OCR engine. `ocr_required` content becomes usable only through a recorded human amendment.
- Table and figure detection reports `not_detected` — it is not implemented, and the full-page render
  is the fallback.
- PDF parsing is not sandboxed and runs in-process.
- Overstatement detection is lexical, not comprehension: it catches common absolutes and will miss a
  subtle one.
- Heuristic source-relationship detection is not implemented; relationships must be supplied by an
  agent or human, and unassessed independence blocks a `strongly_supported` claim.
