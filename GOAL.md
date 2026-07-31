# Current goal

`PROJECT_GOAL.md` is the specification. **This file is the working goal against it** — what is being
built now and what would count as having built it. It changes; the specification does not.

---

## Goal 4 — make every shipped guarantee true, in the order they depend on each other

Six themes. Every item below was found by auditing this repository, not by reading the spec and
imagining what might be missing. Each names the guarantee it restores and what would prove it done.

The ordering rule is the project's own: **restoring a guarantee the documentation already asserts
outranks adding a capability, and making an existing gate true outranks adding a gate.**

### 1. Bind the publication verdict to the artifacts it was computed over — **done**

*Restores: `report_eligible: true` refers to the artifacts actually published.*

`validate_run` writes a `ValidationResult` that names **no artifact ids and no hashes**, and
`render_report` gates on its stored `report_eligible` while re-reading `claims/` and `evidence/`
fresh from disk. A claim written after `validate` is published having never been validated. A
subagent's probe demonstrated this end to end before I deleted it.

In the same last mile, `check_citation_support` folds every citation review's per-claim verdicts
into one dict, last-write-wins in filename order — so a second review saying `passed` **erases** an
earlier `related_not_supporting`. And `if entry.get("citation_support")` treats the string
`not_checked` as truthy, so an unjudged claim counts as judged.

**Done.** `ValidationResult.validated_inputs` is required and carries the sorted roster, the
load-error count and a digest. `render_report` rebuilds it and refuses, naming what changed.
Verdicts are collected per claim; disagreement is `not_evaluated`; `not_checked` counts as unjudged.
Re-validating restores publication and `--draft` is exempt, both pinned. The conflict test is
parametrised over **both** filename orders, because order-dependence was the bug.

### 2. Make the human-verification gate read the record instead of the label — **done**

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

**Done.** The page comes from the manifest (`page_map` for text, render digest for visual), never
from `locator["page"]`. Amendments are filtered by `schema_name` and schema-validated, and must name
the version of the evidence they checked. A two-key stub, a self-labelled `extracted`, and a
stale-hash verification each leave the gate `failed`; a markdown-only run still validates. The
`actor_type == "human"` question is called out in `docs/validation-rules.md` as deliberately
undecided rather than silently skipped.

Fixing it exposed a latent bug in the suite's own fixture: the amendment in
`test_a_recorded_human_verification_amendment_clears_the_ocr_gate` named the *pre-edit* hash,
because `stamp_artifact_hash` returns a copy. It passed only because nothing checked.

### 3. Make stage acceptance exist — **done**

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

**Done.** `src/research/runs/promotion.py` reads the `responses/` paths a stage's packet names,
validates each artifact, stamps the hash it validated, writes the valid ones into `evidence/`,
`claims/`, `reviews/` or `plan.json`, and advances exactly one phase. All or nothing: one invalid
artifact promotes none and the phase stays. A supplied-but-wrong hash is refused rather than quietly
re-stamped. `--stage` refuses an unknown name and refuses the two CLI-performed stages by name.
`transition()` now has a caller, so `is_valid_transition` decides for the first time — skipping
`retrieval` and `evidence_extraction` is refused, naming both.

The reason to implement rather than retract: the spec never required `responses/`, so deleting the
claim was an option. But since validation began verifying hashes, an agent writing straight into a
canonical directory must produce an RFC 8785 digest by hand or have its work rejected as tampering.
Promotion is what makes plain JSON usable.

`check_lifecycle` also cross-checks the manifest against the log — `phase` is a field, and a
manifest claiming `published` above a one-line log used to pass.

**Not done, and deliberately so:** validation still does not *require* a run to have progressed
through the phases before publishing. Writing canonical artifacts directly and validating remains
supported. Requiring progression is a policy change, not a bug fix, so it is named here rather than
slipped in.

### 4. Make the read surface answer from the artifacts — **done**

*Restores: what spec §8.6 and §8.7 promise a host agent reading a run.*

`research status` hardcodes `unresolved_contradictions: []` and `superseded_artifacts: []` with the
comments *"populated by validation in Phase 7"* and *"populated by amendments in Phase 6"*. Both
phases shipped. `research inspect` refuses evidence, claim and review ids — the three classes §8.7
most requires.

Also here: the TRUSTED / UNTRUSTED separation the security model relies on is three constant strings
in `packets.py` that never wrap any document content, so nothing is structurally delimited where
document bytes leave the CLI.

**Done.** `status` computes `unresolved_contradictions`, `unchecked_contradictions` (a separate
answer, because "nobody looked" is not "none found") and `superseded_artifacts` from the run's own
claims and amendments. `inspect` handles `EVD-`, `CLM-` and `REV-`: evidence re-slices the stored
text and reports a divergence from `exact_text` rather than reprinting it, names the claims and
reviews that reference it, and carries surrounding context; a claim shows its evidence resolved and
every review verdict on it. Payloads carrying imported bytes carry an explicit untrusted-content
note.

Adding the computation exposed that **nothing exercised `status` at all** — a missing `import json`
sat there through a full green run.

### 5. Persist the retrieval record — **done**

*Restores: the missing half of spec §29.*

`research search` already computes the full retrieval record and a stable `retrieval_log_hash`, and
then **discards it**. Nothing on disk records which queries produced the evidence a run rests on,
while reports assert the search was reproducible.

**Done.** New `RetrievalLog` artifact (15 schemas) with a content-derived `RTL-sha256-` id that
includes the `index_hash`, because the same words over a different corpus are a different retrieval.
`research search --run <run-id>` records it; `check_retrieval_provenance` (23 checks) blocks when a
run has evidence and no record, and **fails** when a recorded search ran against an index the run
did not pin. The report manifest names the retrieval log hashes.

An absent record is `not_evaluated`, not `failed`: evidence can legitimately arrive through
`research inspect`, so the honest verdict is "how this was found is unknown" — which blocks without
calling it wrong.

The suite's own fixture and the benchmark harness both had to start recording their searches, which
is the point: they were not exercising the pipeline they claimed to.

### 6. Make the assertions that guard all of the above capable of failing — **done**

*Restores: the benchmark's and the suite's ability to notice a regression.*

`compare_hosts.py` — the harness that decides gate 38.10 — has a weakness in its difference
detection. A schema test asserts a loaded schema is a dict; a page-disclosure test asserts only that
a list is a list.

**Done.** `compare_hosts.py` reduced each host's claims to three *independently sorted* lists, which
threw away which value belonged to which claim — and `claim_types` was collected and never compared
at all. Verdicts are now compared per claim, **anchored to the content-derived evidence ids** the
claim rests on. That anchor is the only thing available: claim ids are UUIDs and spec §37 permits
the prose to differ, so neither can key the comparison; evidence ids are the same across hosts that
cite the same passage.

Six mutation tests, including a control that identical copies agree — without it, a harness that
always disagreed would pass everything else.

The schema test asserted `is_valid(...) in (True, False)`, which is true of every boolean ever
returned; it would have passed for a schema accepting anything, rejecting everything, or containing
no constraints. It now checks each schema against the Draft 2020-12 meta-schema and that it names
itself and constrains something.

The OCR disclosure is asserted present in a report with an unreadable page and **absent** in one
without — a disclosure that is always present discloses nothing.

Also: `benchmark/` and `tools/` ship and were never linted. CI lints them now.

---

## Where Goal 4 stands

All six themes are done. `pytest`, `ruff check src tests benchmark tools`, `mypy --strict
src/research` and schema regeneration are clean, and the CI wheel job drives a real pipeline against
a real install.

What that does **not** mean is that the program logic is flawless — see the plan below, which says
so at more length. It means the defects found by two audits are closed and pinned, and the
invariants I1–I6 hold.

Still open, and not closeable by iterating:

- **Codex cross-host conformance (§38.10)** — account usage limits until 2026-08-01.
- **One green CI run** — GitHub cancels every job before it starts; private repositories bill
  Actions minutes and the account's billing is blocked.

Named, deliberately deferred, and recorded rather than slipped in:

- Validation does not *require* phase progression before publishing; direct writes to canonical
  directories remain supported (Theme 3).
- `interpretation_status` on visual evidence is still self-reported, and whether
  `actor_type == "human"` should be required for `human_*` amendments is undecided (Theme 2).
- `methodology_review.require_*` profile keys are declared unimplemented with their reason.

---

## The iteration plan — how this converges, and what it can never prove

**"Flawless" is not a state this process can certify, and saying otherwise would be the exact
failure the platform exists to refuse.** No amount of auditing shows the absence of defects. What
the loop below *can* establish is narrower and worth stating precisely:

> every defect found so far is closed and pinned by a test that fails without the fix, and repeated
> independent adversarial sweeps find nothing new.

That is a claim about the *search*, not about the code. Treat it as `strongly_supported`, never
`verified` — the platform's own vocabulary applies to the platform.

### The loop

One round, repeated until the exit condition below:

1. **Sweep.** Multi-lens audit of the whole repository — spec conformance, fail-open hunting,
   doc-vs-code, threat model, test quality. Lenses run blind to each other; overlap is signal.
2. **Refute.** Every finding goes to a skeptic instructed to refute by default and to narrow rather
   than inflate what survives.
3. **Spot-check by execution.** Pick at least three survivors and confirm them by *running* the
   code, not reading it. This exists because the refutation step has so far refuted nothing —
   see the caveat below.
4. **Fix in dependency order.** Restoring a guarantee the docs already assert outranks adding a
   capability; making an existing gate true outranks adding a gate.
5. **Pin.** Every fix gets a test that fails without it. Where a limitation remains, pin the
   limitation too, so it stays honest instead of becoming a surprise.
6. **Record, including the cost.** Update `CHANGELOG.md`, `docs/`, and this file — *including when
   the fix invalidates something already shipped.* Four claims have been retracted this way so far.

### The invariants each round must leave true

Cheap to re-check, and each one is a class of defect already found here:

| | Invariant |
|---|---|
| I1 | Every artifact validation loads is hash-verified; a mismatch blocks |
| I2 | Every gate distinguishes *"looked and found nothing"* from *"never looked"* |
| I3 | Every published verdict names the artifacts it was computed over |
| I4 | Every documented capability is reachable from an installed wheel, not just a source checkout |
| I5 | Every claim in `README.md` / `docs/` traces to executing code, or says it does not |
| I6 | `pytest`, `ruff check src tests`, `mypy --strict src/research`, schema regeneration — all clean |

### Exit condition

Stop iterating when **all** of these hold:

- the six themes above are done, each with its `done_when` met;
- two consecutive full sweeps, run independently, produce **zero** new confirmed findings;
- I1–I6 hold, checked mechanically;
- the release checklist has no gate marked met without evidence a reader can follow;
- the two external blockers are closed: Codex cross-host conformance (§38.10) and one green CI run
  on Linux and macOS.

The last two are not code problems and cannot be closed by iterating.

### What would falsify the exit condition

Worth writing down before it is reached, so it cannot be quietly redefined: a *new* defect found
after two clean sweeps means the sweeps were not independent enough or the lenses were too narrow.
The response is to add a lens, not to lower the bar.

### The caveat that most threatens this plan

**Across two rounds, 20 of 20 findings survived refutation.** A verifier that never disagrees is
indistinguishable from one that is not looking. Until a sweep produces a genuine refutation, step 3
is doing the real work and steps 2 is unproven. Next round should deliberately seed one false claim
into the refutation batch and check that it comes back refuted.

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
