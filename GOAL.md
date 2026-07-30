# Current goal

`PROJECT_GOAL.md` is the specification. **This file is the working goal against it** — what is being
built now and what would count as having built it. It changes; the specification does not.

---

## Goal 4 — make every shipped guarantee true, in the order they depend on each other

Six themes. Every item below was found by auditing this repository, not by reading the spec and
imagining what might be missing. Each names the guarantee it restores and what would prove it done.

The ordering rule is the project's own: **restoring a guarantee the documentation already asserts
outranks adding a capability, and making an existing gate true outranks adding a gate.**

### 1. Bind the publication verdict to the artifacts it was computed over — `blocks-a-release`

*Restores: `report_eligible: true` refers to the artifacts actually published.*

`validate_run` writes a `ValidationResult` that names **no artifact ids and no hashes**, and
`render_report` gates on its stored `report_eligible` while re-reading `claims/` and `evidence/`
fresh from disk. A claim written after `validate` is published having never been validated. A
subagent's probe demonstrated this end to end before I deleted it.

In the same last mile, `check_citation_support` folds every citation review's per-claim verdicts
into one dict, last-write-wins in filename order — so a second review saying `passed` **erases** an
earlier `related_not_supporting`. And `if entry.get("citation_support")` treats the string
`not_checked` as truthy, so an unjudged claim counts as judged.

**Done when** a `ValidationResult` carries a sorted roster of every artifact `build_context` loaded
plus the load-error count; `research report` without `--draft` exits 5 naming the added, removed or
re-stamped artifacts when the roster differs; two citation reviews disagreeing about one claim yield
`not_evaluated` in **both** filename orders; `not_checked` counts as unjudged; the happy path still
publishes.

### 2. Make the human-verification gate read the record instead of the label — `weakens-a-guarantee`

*Restores: OCR-dependent and uncertain-visual material reaches a claim only through a verification
the platform actually checked.*

`check_ocr_evidence` selects OCR-dependent evidence purely by `extraction_status` on the
**agent-authored** Evidence artifact, never reading the CLI-produced Document manifest's
`ocr_required_pages` or `pages[].extraction_status`. An agent clears the gate by labelling its own
evidence `extracted`. `check_visual_certainty`'s `interpretation_status` is self-reported in exactly
the same shape.

When the gate does fire, a minimal JSON blob in `amendments/` clears it: `_amendments` does not
filter on `schema_name == "Amendment"` (unlike `_relationships`), amendments are absent from
`check_artifacts_conform`, and the loader's error list is discarded.

**Done when** a three-key amendment stub leaves both gates `failed`; evidence whose locator lands on
a page the manifest flags `ocr_required` blocks even when the Evidence declares `extracted`; a
malformed or hash-mismatched amendment is a blocking load error; a markdown-only run (no pages at
all) still validates; and whether `actor_type == "human"` is required for `human_*` amendments is
answered either way in the docs.

### 3. Make stage acceptance exist — `weakens-a-guarantee`, large

*Restores: the host loop that `docs/architecture.md`, `workflow/canonical-workflow.md` and
`validator.py`'s own docstring all describe.*

Three shipped documents state that validation promotes `responses/` into canonical artifacts and
that a stage completes when it validates. **Nothing ever reads `runs/<id>/responses/`**, though
eight of ten packets name `responses/*.json` as their required output. A host following the shipped
workflow literally produces artifacts validation never sees. `tests/unit/test_docs.py` explicitly
skips `responses/` in its path check, so the doc tests cannot catch it.

`research validate --stage` is declared and never read — `--stage bogus_nonsense` produces
byte-identical output to no flag at all (22 checks either way, verified), while `cli.py` prints
`research validate <run> --stage planning` as the next step a host should run.

`runs.manager.transition()` has **no caller in `src/`**, so `events.jsonl` holds only the creation
event, which `check_lifecycle` skips — `is_valid_transition` has been called zero times in
production and the check reports "event log replays cleanly".

The planning packet asks for `responses/plan.json` while `build_context` reads `runs/<id>/plan.json`,
so a compliant host's plan — and its `high_risk` flag — is never read.

**Done when** a host following `canonical-workflow.md` literally can reach `report_eligible`;
`--stage` either advances the phase or refuses an unknown name; and `check_lifecycle` replays a real
multi-transition log, including a rejected skip.

### 4. Make the read surface answer from the artifacts — `weakens-a-guarantee`

*Restores: what spec §8.6 and §8.7 promise a host agent reading a run.*

`research status` hardcodes `unresolved_contradictions: []` and `superseded_artifacts: []` with the
comments *"populated by validation in Phase 7"* and *"populated by amendments in Phase 6"*. Both
phases shipped. `research inspect` refuses evidence, claim and review ids — the three classes §8.7
most requires.

Also here: the TRUSTED / UNTRUSTED separation the security model relies on is three constant strings
in `packets.py` that never wrap any document content, so nothing is structurally delimited where
document bytes leave the CLI.

**Done when** `status --json` reports real contradictions and superseded artifacts; `inspect EVD-…`
re-resolves the locator, names the claims and reviews referencing it, and reports divergence from
`exact_text` rather than hiding it; search and inspect output visibly delimits document-derived
text; and `security-model.md` no longer describes a split the packet does not carry.

### 5. Persist the retrieval record — `weakens-a-guarantee`

*Restores: the missing half of spec §29.*

`research search` already computes the full retrieval record and a stable `retrieval_log_hash`, and
then **discards it**. Nothing on disk records which queries produced the evidence a run rests on,
while reports assert the search was reproducible.

**Done when** a run cannot validate with no retrieval record on disk; a search executed against a
different corpus than the run pins fails; the report's Provenance section names the retrieval log
hashes; and a run whose evidence came from `inspect` rather than `search` still passes.

### 6. Make the assertions that guard all of the above capable of failing — `weakens-a-guarantee`

*Restores: the benchmark's and the suite's ability to notice a regression.*

`compare_hosts.py` — the harness that decides gate 38.10 — has a weakness in its difference
detection. A schema test asserts a loaded schema is a dict; a page-disclosure test asserts only that
a list is a list.

**Done when** a mutated copy of `benchmark/expected/claude-code` (a changed `claim_type`, or two
claims with swapped verdicts) produces a non-empty diff and a non-zero exit, pinned by a test; the
OCR disclosure is asserted present in one report and absent in another; and the schema test checks
meta-schema well-formedness rather than a tautology.

---

## How this list was produced, and what is weak about it

A twelve-agent audit across five lenses (spec conformance, fail-open hunting, doc-vs-code,
threat model, test quality) produced **37 raw findings**. Ten were fixed in Goals 2 and 3. The
remainder were deduplicated into 14 falsifiable claims and given to one skeptic each, instructed to
refute by default.

**All 14 survived. So did all six in the first audit. A zero percent refutation rate across two
rounds is not a strength — it is a reason to distrust the refutation step.** The likely explanation
is benign (the claims had already survived one ranking pass, and each cites a specific file and
line), but a verifier that never disagrees is indistinguishable from one that is not looking.

So three were spot-checked independently, by execution rather than reading:

- `--stage bogus_nonsense` → 22 checks; no flag → 22 checks. Byte-identical.
- `check_citation_support` assigns `judged[claim_id] = verdict` in a loop over all reviews — last
  write wins.
- `manager.py` still contains both hardcoded empty lists and their "populated by Phase 6/7" comments.

Treat the rest as *verified once and cited precisely*, not as proven.

---

## Completed

### Goal 3 — close the gates that report "no problems" for what they never inspected

Four fixed: artifacts are hash-verified where validation actually loads them;
`contradiction_status: not_checked` blocks; `unknown` no longer clears the source-independence gate
that recording nothing blocks (and `independent` now exists to clear it honestly); and the derived
bytes citations resolve against — normalized text and page renders — are re-hashed.

The last is the one `span_sha256` could not cover, because the span hash lives in the locator the
agent writes: an agent could rewrite the normalized text and mint evidence agreeing with it. A test
pins that `text_locators_resolve` passes on the fabrication while `derived_text_hashes_match` fails.

The remaining two items of Goal 3 are now Themes 1 and 2 above.

### Goal 2 — make the shipped thing be the thing the docs describe

The wheel shipped no schemas, so an installed copy could run `--version` and `init` and nothing
else — and the CI job meant to verify it ran exactly those two commands. Research profiles were read
by no code at all. Exit code 6 was unreachable. All three fixed, with a load-time rule that a
profile key must be honoured or declared unimplemented with its reason.

### Goal 1 — attested reviewer independence

`confirmed_independent` requires a `ReviewContext` recording the verbatim text the host attests it
gave the reviewer, scanned for excluded material. Both committed conformance runs were **downgraded
rather than grandfathered**.

---

## Not in scope

- **Codex conformance (gate 38.10)** — blocked on account usage limits until 2026-08-01. Procedure
  is in `docs/release-checklist.md`. Not simulated.
- **CI execution** — GitHub cancels every job before it starts: *"recent account payments have
  failed or your spending limit needs to be increased"*. Private repositories bill Actions minutes.
  An account setting, not a code defect.

## What no fix in this file can claim

**An artifact hash is an integrity check, not a signature.** It detects an edit made outside the
process. It cannot detect a host that writes a false artifact and stamps it correctly, because the
host holds no key and nothing here does. Every tamper-detection statement in this repository means
the first thing.
