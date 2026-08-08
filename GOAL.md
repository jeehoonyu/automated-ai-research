# Current goal

`PROJECT_GOAL.md` is the specification. **This file is the working goal against it** — what is being
built now and what would count as having built it. It changes; the specification does not.

---

## Goal 8 — the boundary, stated where a reader will hit it

Set 2026-08-07, out of a validation the owner asked for directly: *can this project really fulfil
automated AI researching — lab or industry level, for logic or experiments?*

The answer is **no, and the reason is structural, not a gap to close.** `Evidence` requires
`document_id` and `document_version_id`, and `locator` is a two-branch `oneOf` — a text span in
normalized text or a visual region on a rendered page. There is no third branch, and no profile can
add one: `registry.py` is a closed 15-name dict with no `Measurement`, `Dataset`, `Protocol` or
`Environment`. The importer accepts `{.pdf, .md, .markdown}` and nothing else.

So the platform can hold **a description of an experiment somebody published**. It cannot hold **an
experiment you ran.** The forced route is the wrong shape: write the result as prose, import the
prose, cite a span of your own sentence. Every gate passes, because every gate is verifying that you
quoted your own document accurately — which is true, and beside the point.

### Tier 0 — the four fixes the validation named — **done 2026-08-07**

Each reproduced before the fix and mutation-verified after (18 mutants, all caught, bytecode purged
between each). Details in `CHANGELOG.md`. Two were worse than the audit described:

1. **A refused promotion had already rewritten the canonical artifact.** The refusal printed, the
   exit was non-zero, the phase held, no event was logged — and `plan.json` was gone.
2. **A review bound to an id, not to bytes**, so edit-then-revalidate laundered a change past four
   reviewers and published.
3. **`confidence_factors` had no reader** — spec §23's "supported by explicit factor ratings" was
   satisfiable by writing nothing.
4. **Closing the schemas found six undeclared fields and one trap**: `Document.text_sha256` hashed
   the raw markdown while `normalized_text_sha256` beside it hashed the text locators resolve
   against.

And one the fixes found on their own: **`generate_schemas.py --check`, named in `AGENTS.md` as a
required verification step, did not exist** — it rewrote the schemas and exited 0. A verification
that repairs what it finds cannot report anything.

### Tier 1 — say the boundary where it will actually be read — **done 2026-08-07**

`PROJECT_GOAL.md` §1 is accurate ("across collections of locally stored documents"). `README.md` is
not wrong either. But nothing states the negative, and the negative is what a new user needs: this
holds documents, not measurements. Someone arriving at "automated AI research platform" reasonably
expects hypothesis → experiment → data → analysis, and will get four stages in before the schema
tells them.

Written as "What this holds, and what it does not", above the quickstart — before anyone installs
anything. It names the two locator kinds, the three importable extensions, and the artifact types
that do not exist, then says plainly that forcing a measurement in produces gates which verify you
quoted your own sentence accurately.

**A negative goes stale silently**, which is the part worth recording. Nobody deletes a scope
paragraph when they add an artifact type — they add the type, and the paragraph becomes a lie in the
one file every new user reads first. So `test_the_readme_scope_statement_still_describes_the_code`
asserts the three facts it rests on against the code, and adding `Measurement` or accepting `.csv`
now fails a test that names the README.

### Tier 1b — the two audit claims I had not acted on — **done 2026-08-07**

The capability validation made two further defect claims. Both probed before being believed, and my
first probe was wrong on both: it captured the event log before validation appended to it, and it
invoked the CLI by a path that does not exist. Corrected, both reproduced.

- **`lifecycle_transitions_valid` judged each event alone**, so a log missing its middle replayed
  "cleanly". The record that a stage was accepted could be deleted without trace.
- **`research inspect` crashed on evidence, claim and review ids** — three of the six kinds it
  returns, and the three a reviewer needs. Every test called the library function; none called the
  command.

The second is the more general lesson and is why it is recorded here rather than only in the
changelog. The precise shape of the gap, having gone and counted rather than assuming:

`tests/integration/test_exit_codes.py` does drive the CLI by subprocess — for `init`, `import`,
`index`, `run` and `validate`, always with `--json`, asserting only the process exit code. **Nine
commands were never invoked as commands at all** (`search`, `status`, `inspect`, `report`, `next`,
`amend`, `project init/new/list`, `doctor`), and **no test anywhere asserted a command's rendered
human output** — which is the code path `inspect` was broken in, and the one every user reads.

So the coverage was real but shaped like a keyhole: the library beneath and the exit code above,
with the formatting between them untested. A sweep of all seventeen commands — happy path, `--json`,
and ten cases that must refuse — found no other crash and no refusal that wrongly succeeded, so
`inspect` was isolated rather than systemic. That sweep is now
`tests/integration/test_cli_surface.py`.

### Tier 1c — nothing left the tool — **done 2026-08-07**

Goal 7 item 9 has said since it was written: *"A finished run produces Markdown. No BibTeX, no
CSL-JSON, no CSV of claims and their evidence. Research that cannot be cited elsewhere stays in the
tool."* `research export` closes it, in the shape the corpus actually supports:

- Three CSVs — claims, evidence, citations — through **the same gate as publication**, which meant
  first extracting that gate out of `render_report` into `reporting/gate.py`. Copying it would have
  created a second answer to one question, and a CSV circulates more easily than a report.
- `--draft` writes `report_eligible=false` into every **row**, not just the filename, because a
  filename is lost the moment someone opens the file in a spreadsheet.

**And no BibTeX or CSL, decided rather than deferred.** Probing first is what settled it: the
fixture PDFs carry `metadata={}`, and what a real one carries is `/Title`, `/Author` and
`/CreationDate` — attacker-controlled strings naming whoever made the *file*, and when the file was
made. Journal, volume and DOI are not extracted at all. A generated `.bib` would look like a
citation and be a guess, which is the one thing this package exists to refuse. `citations.csv`
carries what is known plus a `title_source` column naming its own provenance.

Mutation found two tests passing for the wrong reason: `complete_run` holds one claim and one
evidence record, so row ordering and the title-source branches were unobservable through it. Both
now have direct tests over several out-of-order items.

### Tier 2 — decided against, and why it is recorded rather than deferred

A `Measurement` artifact with its own locator kind would make this a different tool: it would need
non-document ingestion (colliding with `PROJECT_GOAL.md` §93), a notion of re-execution, and a way
to compare two runs of the same experiment. None of those are additive. Recorded here so that the
next person to notice the gap finds the decision instead of re-discovering the gap.

Also still true and still unowned: retrieval is FTS5/BM25 lexical only, so recall depends on the
agent guessing the right words — which caps this below systematic-review grade regardless of any
schema work.

---

## Goal 7 — the ways forward a blocked run is promised

Set 2026-07-31. Found by asking a question the test suite cannot: **when a gate blocks, can the user
actually do the thing the documentation says will unblock it?**

Every previous goal audited what the code *does*. This one audits what a person is left holding when
it says no. The platform's whole value is refusing to publish — which makes "and here is what to do
about it" load-bearing, not a nicety.

### Tier 0 — a documented route that did not exist — **done 2026-08-01**

All four were verified by running the code, fixed, and each fix confirmed by re-introducing the
defect and watching a named test go red. `research amend` exists; a schema-less stage refuses
artifacts instead of discarding them; source relationships are a declared route with a real id
factory; re-acceptance is reported rather than silent. Details in `CHANGELOG.md`.

The findings as they stood:

**1. Amendments are unreachable. This is the serious one.**
`docs/release-checklist.md` says *"`ocr_required` content becomes usable only through a recorded
human amendment."* There is no way to record one:

- no stage's packet declares `Amendment` in its `schema_versions`, so no stage will promote one;
- bundling an `Amendment` into a schema-less stage's file (`retrieval.json`) returns
  **`accepted: True` and promotes nothing** — the artifact is silently discarded;
- once a run advances past a stage, that stage cannot be re-promoted (the lifecycle refuses to move
  backwards), so there is no after-the-fact route either.

So a corpus containing one scanned page is a dead end: `ocr_evidence_human_verified` fails, and the
only sanctioned remedy cannot be performed. `visual_interpretation_certain` has the same shape. Both
gates additionally require `actor_type == "human"` — correctly — which rules out an agent doing it.

*Fix:* `research amend <run-id> --type <t> --target <artifact-id> --rationale "…"`, writing a
correctly-stamped Amendment against the *current* hash of its target, refusing when the target does
not exist or has since been re-stamped. It must record `actor_type: human`, and it must be the only
command in the CLI that says so — which means it should also say plainly that it is taking the
operator's word for it.

**2. A stage that declares no schemas silently discards artifacts.**
`_candidates` returns `declares_schemas=False` for `retrieval`, and `promote_stage` then accepts the
stage and promotes nothing. Anything in that file is dropped with only a `note` in the result. A
response file containing artifacts should be refused, not accepted-and-ignored: this is the exact
shape — reporting success about something it never did — that every other audit in this repository
has been hunting.

**3. Source relationships work only by an undocumented trick.**
`check_source_independence` blocks a `strongly_supported` claim until relationships are assessed, and
nothing in the workflow says how to record one. It turns out bundling a `SourceRelationship` into
`responses/claims.json` during `synthesis` **does** promote it — verified — but no packet, prompt or
document mentions this. Meanwhile `artifact_id` for that type has no pattern in the schema and no
factory in `identifiers.py`, so `REL-111111111111` validates fine. Either declare relationships
properly in the synthesis packet and give them an id factory, or add `research relate`.

**4. Re-promoting a completed stage silently succeeds.**
`transition` skips the state machine when `to_phase == from_phase`, so promoting a stage the run is
already at re-runs it and re-writes canonical artifacts. That may be the right behaviour — it is how
you fix a bad response — but nothing documents it, no test pins it, and it happens *after*
validation may have run. Decide it, then say so.

### Tier 1 — capabilities the model promises and no code provides

**5. Visual evidence could be produced — and nothing had ever done it. Corrected 2026-08-01.**

The plan claimed this path was broken. It is not: probing it end to end showed that
`make_visual_locator` produces a locator that resolves, validates, passes both visual gates, and
renders in the UI. What was true is narrower and different — **the whole path had never once been
exercised together**, and no document said how to use it. "A figure can be cited" was a claim resting
on unit-level parts that had never been assembled.

Now: five integration tests build real visual evidence and drive it through validation (including
that tampering with the page image breaks the citation, and that an uncertain reading is cleared by
`research amend --type human_visual_verification`), and `workflow/canonical-workflow.md` documents
the route. Automatic table and figure **detection** remains unimplemented, which the release
checklist has always said honestly.

Worth recording because the correction cuts the other way from usual: the code was better than the
plan assumed, and the gap was in coverage and documentation. Probing before building is what found
that — writing detection would have been solving a problem that did not exist.

**6. Overstatement detection is lexical.** Honestly documented, and the weakest gate in the system: a
regex of absolutes against a claim's classification. It will miss anything subtle. Worth stating what
it is *for* — flagging for disclosure — rather than improving until it looks like comprehension.

**7. Gate 38.10 and CI.** Withdrawn from scope by the owner, still unmet, still recorded as unmet.

### Tier 2 — the workflow is hard to actually drive

**8. Eight stages by hand is a lot.** `research status` says where you are; nothing says *what to do
next* in one step. A `research next <run-id>` that prints the current packet, the response path, and
the exact command that will judge it would remove most of the friction without adding any authority.

**9. Nothing leaves the tool.** A finished run produces Markdown. No BibTeX, no CSL-JSON, no CSV of
claims and their evidence. Research that cannot be cited elsewhere stays in the tool.

### Tier 3 — robustness, honestly ranked below the above

**10. PDF parsing is not sandboxed** and runs in-process, on attacker-controlled input.
**11. No corpus refresh path.** A run pins its sources; when a new paper arrives the answer is a new
run, and nothing helps you see what changed between the two.

### What this goal is not

Not a feature list. Items 1–4 are defects in the shape this project keeps finding — a route the
documentation asserts and the code does not have, and an operation that reports success without
doing anything. They come first for the same reason every previous goal ordered itself that way:
**restoring a guarantee the documentation already asserts outranks adding a capability.**

---

## Goal 6 — every vocabulary has one home, and an unlisted value never reads as fine

Set 2026-07-31, straight out of what Goal 5's audit found. Not a new capability: a guarantee the
codebase already implies and does not everywhere keep.

### The evidence this rests on

The UI's worst defect was not carelessness, it was **shape**. Two Jinja templates each restated the
Claim schema's `independent_review_status` enum from memory. Both blocked on `unknown` — a value the
schema does not contain — and both let `not_confirmed` and `not_yet_reviewed` fall through to the
green branch, so a claim that had never been independently reviewed rendered as fine.

The code beside it that was *correct* was correct for one reason: `status_class` asked
`CheckResult.blocks` instead of restating anything.

There are **53 enums across the 15 shipped schemas**, and Python all over this package restates
slices of them as sets, tuples, dict keys and inline membership tests. Each one is the same bet.

### The two properties to establish

Neither is about style. Both are about which way a gap falls.

**P1 — coverage.** Every Python vocabulary that mirrors a schema enum either names every member, or
omits members deliberately with the reason in a comment. A test derives the enum from the shipped
schema and fails when the schema gains a member the vocabulary has not been told about. Today a new
enum member lands silently in whichever branch the author did not think about.

**P2 — fail direction.** For a value a vocabulary does *not* list, the code must produce the strict
outcome: blocks, unknown, human review, or an exception. Never the reassuring one. This is the
property that decides whether a coverage gap is a latent bug or merely untidy — and the codebase is
already mostly right here, which is what makes the exceptions worth finding.

Two supporting questions the sweep also asks: is a vocabulary derived from one schema's enum being
applied to a value that comes from a **different** schema (`INDEPENDENCE_ORDER` carries the 4 values
of `review_independence.status`, while `independent_review_status` has 5), and is the same
vocabulary written out in more than one place, where the copies can drift.

### What would count as done

- `tests/unit/test_vocabularies.py` exists and checks **every** domain vocabulary in the package
  against the schema or `StrEnum` that defines it — one file, so there is a single place to look.
- Every gap it finds is either closed or recorded as deliberate with its reason, in code.
- Every P2 violation the sweep confirms is fixed, and each fix is mutation-tested: re-introduce the
  defect, watch a named test go red.
- The docs' own enumerations — check names, counts, exit codes, statuses — are pinned, because prose
  restating a vocabulary is a copy like any other.

### What this cannot claim

Coverage is not correctness. A vocabulary can name every enum member and put one in the wrong set,
and no test derived from the schema would notice — `not_confirmed` was in the *wrong* branch, not a
missing one, and only reading it against `check_support_classifications` caught that. P1 stops the
silent drift; only a human or a reviewer comparing intent against the validator catches a member
that is listed and misfiled.

### Where it stands — done, with nine defects found

The sweep ran five lenses over the codebase and one over the documentation, each finding handed to a
skeptic instructed to refute it. **Nine survived; one was refuted.** All nine are fixed, and each fix
was confirmed by re-introducing the defect and watching a named test go red. `schema_enum()` exists,
`tests/unit/test_vocabularies.py` exists, and 568 tests pass with ruff, `mypy --strict` and schema
regeneration clean.

Two of the nine were not merely untidy:

- **`check_ocr_evidence` asked about one extraction status out of seven**, so evidence declaring
  `ambiguous` or `human_review_required` — in the schema's own required boolean, which nothing in
  the package read — published. The asymmetry is the lesson: the flattering label was distrusted and
  cross-checked against the manifest; the honest ones were thrown away.
- **`research validate` raised `LifecycleError` on any run that had once been flagged**, after
  writing its verdict to disk, because the disposition was consulted by no check and `_record_verdict`
  then attempted a transition the state machine forbids. The ordinary "fix it and validate again"
  loop crashed.

### A note on the verification itself

One mutation reported MISSED that was actually caught. `elif lossy:` and `elif False:` are the same
eleven characters, and the restore landed in the same second, so Python's `(mtime, size)` cache
validation reused bytecode compiled from the mutated source. A mutation harness that edits files in
place must purge `__pycache__` on both sides of the run, or it will occasionally lie in **either**
direction. The earlier rounds are unaffected — every one of those mutations changed the file's length
— but the hazard was invisible until it fired.

---

## Goal 5 — a way to *look* at a run, that cannot lie about it

Requested 2026-07-31: "It will be nice to have a UI interface."

Everything the platform records is already reachable from the CLI. What was genuinely missing is
following a chain: a published claim rests on evidence, which rests on a locator, which resolves
into immutable source bytes, and checking that by hand is four `research inspect` calls and a lot of
copied identifiers. `research ui` makes it four clicks.

**The ordering rule still applies.** A UI is a capability, and this project ranks restoring a
guarantee above adding one — so the acceptance criteria are not "it looks good". They are that the
new component cannot become a way around anything:

| It must | How it is held to that |
|---|---|
| never write | No route mutates a workspace; every method but `GET`/`HEAD` is refused before a workspace is opened. A unit test greps the package for every write entry point; an integration test hashes every file in a workspace, browses every page, and re-hashes. `/search` deliberately records no retrieval log — `research search --run` does that on purpose, and a page load is not retrieval. |
| never round a gate up | Whether a check blocks is answered by `CheckResult.blocks` itself, not a table restated in the UI, so `not_evaluated` is painted exactly as `failed`. An unrecognised status — these come from JSON on disk — is treated as blocking. A run page re-derives the artifact roster and says loudly when the stored verdict no longer describes the files present. |
| never let document text become markup | Autoescaping unconditional, `Content-Security-Policy: default-src 'none'`, zero JavaScript. Verified in a real browser against a corpus document containing `<script>`, `<img onerror=…>` and an attribute break: present as text, `childElementCount: 0`, nothing executed. |
| add no dependency | `http.server` and the Jinja2 the report renderer already uses. |

Five deliberate mutations — autoescape off, `not_evaluated` painted neutral, the `Host` check
removed, the staleness comparison skipped, write methods answered instead of refused — were each
confirmed to turn a test red. A test that passes against the broken code too is not guarding
anything.

**It found one defect on its first day**, which is the argument for building it. `research status`
reported an unvalidated `final_validation` response for every run that had ever been validated —
including runs at `initialized` that had produced nothing — because that stage's declared output is
the validation result the CLI writes itself. The UI draws its stage list from that predicate, so a
run with zero artifacts showed work awaiting acceptance. Only `responses/` files count now.

### And then the audit found six in the UI itself

Five lenses over the new code, each finding handed to a skeptic told to refute it: nine confirmed
findings, deduplicating to six defects, one refuted. Full list in `CHANGELOG.md`. Two are worth
repeating here because of what they say about the acceptance criteria above.

**The worst one was the exact failure the table promised would not happen.** A claim that had never
been independently reviewed showed a *green* chip reading "not yet reviewed". Three lenses found it
separately. The cause was structural rather than careless: I had put the classification policy in
Jinja, and two templates each restated the Claim schema's enum from memory. Both blocked on a value
(`unknown`) that is not in the schema at all and let `not_confirmed` and `not_yet_reviewed` fall
through to the reassuring branch — so *recording* that independence was unestablished rendered
calmer than recording nothing.

**The lesson generalises past this component.** `status_class` was correct throughout, because it
asked `CheckResult.blocks` instead of restating anything. Every place I let a vocabulary be typed
out a second time is where the defect was. Policy now lives in `views.py`, is derived from the
shipped schema, and a test asserts no template inspects those fields at all.

**Second: the "Report eligible" banner never checked the checks printed underneath it.** Flipping
the stored boolean and re-stamping produced a green "every gate cleared" above ten blocking rows —
and neither guard I was proud of catches that, because a re-stamped result is internally consistent
and a validation result is not part of its own artifact roster. Two independent integrity mechanisms,
both blind to the same edit, and only comparing the verdict against its own evidence closes it.

That is the argument for auditing a component whose entire claim is that it does not lie: the claim
is not evidence. Writing the acceptance criteria down did not make them true — it made it possible
to check, and checking found six places where they weren't.

**What the UI cannot do, stated so nobody expects it to:** it cannot judge whether a claim is true,
whether a figure was read correctly, or whether a reviewer was genuinely independent. It shows what
was recorded and what the validator made of it. Making a record easier to read does not make the
record more true.

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

- **Codex cross-host conformance (§38.10)** and **one green CI run** — both **withdrawn from scope
  on 2026-07-31 by the repository owner**, who decided they are not worth pursuing. That is a
  decision about effort, not a change in status: gate 38.10 remains **half met** and "Verified on
  Linux and macOS" remains **unchecked**. Nothing was rounded up. See `docs/release-checklist.md`,
  which still records both as unmet and still carries the procedure for closing them if anyone
  wants to.

### The deferred items, now decided

All four were closed on 2026-07-31 rather than left standing.

- **Phase progression is required.** `check_run_progressed` blocks a run that has not reached
  `independently_reviewed`. This exposed something worse than the deferral: `Phase.REPORT_ELIGIBLE`
  and `Phase.PUBLISHED` were referenced in exactly one comparison and **nothing ever set them**,
  `Phase.VALIDATION_PASSED` was referenced nowhere, and `Disposition.VALIDATION_FAILED` was never
  assigned — so `research status` answered `report_eligible: False` for every run that ever
  existed, including runs `research validate` had just called eligible and `research report` went
  on to publish. Two commands disagreeing about the central question. `validate` now records its
  verdict in the lifecycle and `report` records publication.
- **Visual evidence must declare its certainty.** An absent `interpretation_status` was
  indistinguishable from `clear`, so the gate never fired for evidence that simply did not answer.
  The CLI still cannot judge whether a figure was read correctly — it can insist the agent say how
  sure it was.
- **A human verification must come from a human.** `actor_type == "human"` is required for
  `human_ocr_verification` and `human_visual_verification`. An agent recording one about its own
  evidence is the self-attestation those gates exist to refuse.
- **`methodology_review.require_*` is honoured.** Not by judging study design — that remains the
  agent's job — but by checking the review RECORDED an assessment for each required item. "Was this
  considered?" is answerable deterministically; "was it considered well?" is not.

Closing the first one forced the suite's own fixture to stop writing canonical artifacts directly
and start walking the workflow through `research validate --stage`. It had never exercised the loop
the documentation describes.

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

### The caveat that threatened this plan, and how it was settled

Across two rounds, **20 of 20 findings survived refutation** — and a verifier that never disagrees is
indistinguishable from one that is not looking.

So the refuter was calibrated on 2026-07-31: six claims about stable parts of the codebase, **three
of them deliberately false**, each given to a skeptic told nothing about which was which.

| Planted claim | Verdict |
|---|---|
| `document_id` includes the filename | **refuted** |
| `safe_join` follows symlinks out of the workspace | **refuted** |
| `normalize_query` passes FTS operators through | **refuted** |
| UUIDv7 has an intra-millisecond counter | upheld |
| `artifact_hash` omits itself from the digest | upheld |
| `not_evaluated` blocks exactly as `failed` | upheld |

**3/3 falsehoods caught, 3/3 true claims upheld.** The refutation step works; the 20/20 survival rate
was because those claims were true — each had already survived a ranking pass and cited a specific
file and line.

Two refuters also went further than asked, which is the behaviour you want: the `safe_join` one
refuted the claim *and* noted a genuine TOCTOU gap (the returned path is unresolved, so a symlink
planted between check and write would be followed — bounded by `atomic_write_bytes` re-checking with
`assert_within`). The UUIDv7 one confirmed the counter and then established by experiment that it
saturates at ~3,840 ids inside a single millisecond and is not thread-safe, verifying that nothing
under `src/` is threaded.

Calibration should be repeated whenever the refuting prompt changes.

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

- **Codex conformance (gate 38.10)** — was blocked on account usage limits; **withdrawn from scope
  on 2026-07-31**. The gate stays half met and the directory stays empty. Never simulated: a Claude
  subagent role-playing as Codex would be a fabricated conformance record, which is the precise
  failure this platform exists to refuse.
- **CI execution** — GitHub cancels every job before it starts (*"recent account payments have
  failed or your spending limit needs to be increased"*; private repositories bill Actions minutes).
  **Withdrawn from scope on 2026-07-31.** Every step the pipeline runs has been executed by hand
  against a real install instead, but no CI run has proved it, and the checklist says so.

## What no fix in this file can claim

**An artifact hash is an integrity check, not a signature.** It detects an edit made outside the
process. It cannot detect a host that writes a false artifact and stamps it correctly, because the
host holds no key and nothing here does. Every tamper-detection statement in this repository means
the first thing.
