# Validation rules

`research validate <run-id>` decides whether a run may be published. It decides by **checking**,
never by trusting what an artifact says about itself.

## Four statuses, and why the third one matters

| Status | Meaning | Blocks publication |
|---|---|---|
| `passed` | the check ran and the property holds | no |
| `failed` | the check ran and the property does not hold | **yes** |
| `not_evaluated` | the check **could not run** — inputs missing, artifact unreadable | **yes** |
| `not_applicable` | the check does not apply to this run | no |

`not_evaluated` blocking is the single most important rule here. An empty finding list is
indistinguishable from a clean bill of health, so a validator that silently skips what it cannot
inspect reports "no problems found" about a run it never looked at.

The distinction against `not_applicable` is equally load-bearing in the other direction: a run
that correctly concludes `unable_to_determine` has no evidence records, and that is *nothing to
check*, not *could not check*. Treating them the same made the specification's sanctioned
successful outcome unpublishable — a real bug, caught by benchmark case B9.

## Report eligibility

```
report_eligible = (no check failed)
              AND (no check was not_evaluated)
              AND (no outstanding human review)
```

The `ValidationResult` schema refuses the contradiction outright: `report_eligible: true`
alongside blocking errors is not a representable artifact.

## What must block publication (spec 8.8)

- a claim lacking evidence
- an evidence locator that cannot be resolved
- a source hash that no longer matches
- a required review missing
- insufficient reviewer independence
- OCR-required material used as evidence without human review
- an uncertain visual interpretation
- a citation that is related but does not support its claim
- an undisclosed required contradiction
- an artifact that does not conform to its schema
- an invalid lifecycle transition

**6 of these eleven have a benchmark case naming the specific check that must catch them** — see
`benchmark/expected/cases.json`. Asserting only "publication was blocked" would pass when the wrong
gate fired, so the cases that exist name their mechanism.

**This paragraph used to say "each".** It did not; the sentence was written when the list was
shorter and never revisited. Measured rather than asserted: of the 27 checks, the benchmark pins
`claims_reference_evidence`, `citations_support_their_claims`, `contradictions_disclosed`,
`source_independence_established`, `ocr_evidence_human_verified` and `text_locators_resolve`.
Deleting any of the other 19 from `CHECKS` leaves the benchmark fully green. Not covered by a
mechanism-naming case: a source hash that no longer matches, a required review missing, insufficient
**reviewer** independence (B5/B6 pin *source* independence, `check_source_independence` — a
different gate), an uncertain visual interpretation, and an invalid lifecycle transition. Each of
those has unit or integration coverage; none has a benchmark case.

`B10` declares `artifacts_conform_to_schema / failed` and never evaluates it — its test asserts that
`validate_artifact` raises and never calls `validate_run`, so the declared pair is dead metadata.
`tests/unit/test_vocabularies.py` pins the six, so this paragraph now fails a test when it drifts.

## The checks

| Check | What it establishes |
|---|---|
| `profile_rules_loaded` | the profile the manifest names loaded, so the rules applied are the rules stated |
| `artifacts_conform_to_schema` | every run artifact validates **and its `artifact_hash` matches its content**; an unreadable or edited one is `not_evaluated`, not skipped |
| `profile_confidence_permitted` | no claim carries a classification the profile forbids outright |
| `source_hashes_match` | stored originals still hash to their recorded value |
| `derived_text_hashes_match` | the **normalized text citations actually resolve against** still hashes to what extraction recorded |
| `evidence_references_resolve` | evidence points at a document version this workspace holds |
| `text_locators_resolve` | offsets re-slice to the recorded span, and `exact_text` matches it |
| `visual_locators_resolve` | the named page render exists **and its bytes still hash to the cited digest** |
| `claims_reference_evidence` | no claim without evidence; no dangling evidence id |
| `citations_support_their_claims` | citation review judged every claim, reviews do not disagree, and none rests on a related-but-non-supporting source |
| `contradiction_review_complete` | the review exists and did not fail |
| `citation_review_complete` | as above |
| `methodology_review_complete` | as above |
| `independent_review_complete` | as above |
| `reviewer_independence_sufficient` | independence declared and meeting the profile's bar |
| `independence_context_attested` | `confirmed_independent` is backed by an attested reviewer context containing no excluded material |
| `reviews_bind_to_reviewed_bytes` | every review records the `artifact_hash` it read, and that hash is still what is on disk — an approval does not transfer to a rewritten artifact |
| `run_reached_a_publishable_phase` | the run walked the stages, so when each was accepted is on the record |
| `methodology_items_assessed` | the methodology review recorded an assessment for each item the profile requires |
| `retrieval_provenance_recorded` | the searches that produced this evidence are on disk and ran against the run's pinned index |
| `ocr_evidence_human_verified` | evidence on a page **the Document manifest flags** `ocr_required` has a valid human-verification amendment naming that version of it |
| `visual_interpretation_certain` | uncertain visual readings were human-verified |
| `contradictions_disclosed` | every claim was actually checked, and none carries an unresolved contradiction |
| `confidence_factors_recorded` | a claim asserting support rated its confidence factors (spec §23), and no factor is rated `not_applicable` where the run's own artifacts show it applies |
| `support_classifications_earned` | `verified` has a passed independent review; `strongly_supported` has multiple evidence records |
| `source_independence_established` | strongly-supported claims rest on sources positively recorded as `independent`; absent, `unknown` and `cites` all block |
| `lifecycle_transitions_valid` | the event log replays as a legal sequence |

## Four gates that used to fail open

Found by a multi-lens audit of this repository on 2026-07-28, each confirmed by executing the check
rather than by reading it:

- **Artifacts were never hash-verified where it counted.** Validation loaded evidence, claims,
  reviews, relationships and amendments through a bare `json.load`. `read_artifact` verifies; this
  loader did not, and this loader is the one validation uses. A hand edit that stayed schema-valid
  was invisible, and one word in a citation review flipped the run to publishable. Note how many
  tests in `tests/integration/test_validation.py` now re-stamp their seeded defects — every one of
  them was relying on the absence of this check.
- **`contradiction_status: not_checked` returned `passed`.** The check asked only whether any claim
  was `unresolved`, so a run where nobody had looked reported "none unresolved". `not_checked` is in
  the schema enum and is a claim's initial state.
- **Recording `unknown` cleared the independence gate that recording nothing blocked.** The same
  statement — "we did not assess this" — passed or blocked depending on whether it was written down.
  There was no enum value meaning `independent` at all, so the passing verdict was unearnable
  honestly. `independent` now exists and is the only thing that clears the gate.

- **The bytes citations actually resolve against were never re-hashed.** `source_hashes_match`
  re-hashes `originals/` and its docstring says "evidence rests on those bytes" — it does not. A
  text locator is an offset pair into `normalized_text_path`, a derived, mutable file; page renders
  were trusted by path, and `resolve_visual_locator`'s docstring claimed a re-hash it never
  performed. `span_sha256` does not close this, because the span hash lives in the locator the
  agent writes: an agent with workspace write access could rewrite the normalized text and mint
  evidence agreeing with it, and every locator check passed. A test pins exactly that —
  `text_locators_resolve` returns `passed` on the fabrication while `derived_text_hashes_match`
  fails.

The third is the sharpest: the check's own docstring said "`unknown` independence is never promoted
to independent … returns `not_evaluated`, which blocks, rather than passing by default", directly
above code that did the opposite. The fourth is the most consequential, because
`src/research/reporting/renderer.py` deliberately quotes *through the locator* rather than from
`evidence["exact_text"]`, on the reasoning that validation would have caught any divergence — so the
one defence-in-depth measure was the path that carried altered text into `report.md`.

## Human verification reads the record, not the label

`ocr_evidence_human_verified` selected its candidates purely by `extraction_status` on the
**agent-authored** Evidence artifact. Writing `extracted` on evidence taken from a scanned page
cleared the gate, while the deterministic record of which pages need OCR sat unread in the Document
manifest the CLI itself produced. A gate that reads the agent's own label is asking the subject
where it was standing.

The page is now derived from the manifest — a text span by walking `page_map`, a visual region by
matching the render digest, never from `locator["page"]`, which the agent also writes. The manifest
can only ever *add* candidates, so an honest `ocr_required` declaration still counts.

When the gate fired, a two-key JSON object in `amendments/` cleared it: `_amendments` did not filter
on `schema_name`, and amendments were absent from `check_artifacts_conform`, so `validate_artifact`
never ran on one — while the Amendment schema has always required `target_artifact_hash`,
`changed_fields`, `reason` and `human`. Amendments are now filtered and validated like every other
artifact, and a verification must name **the version it checked**: an amendment carrying a
`target_artifact_hash` that no longer matches the evidence does not clear the gate, so "a human
checked this" cannot outlive the thing they checked.

### What is still self-reported

`visual_interpretation_certain` reads `interpretation_status`, written by the agent, and there is no
deterministic record to cross-check it against — the CLI cannot know whether an agent read a figure
correctly. What is enforced is the amendment discipline above. Stated here rather than left to be
discovered.

**Decided 2026-07-31:** `created_by.actor_type == "human"` **is** required for
`human_ocr_verification` and `human_visual_verification`. The gate names a human; an agent recording
one about its own evidence is the self-attestation the gate exists to refuse. Ordinary amendment
types — a locator correction, a metadata fix — may still come from an agent.

**Also decided:** visual evidence must declare `interpretation_status`. An absent field read as
`clear`, so the gate never fired for evidence that simply did not answer the question. The CLI still
cannot judge whether a figure was read correctly; it can insist the agent say how sure it was.

## The verdict is bound to the artifacts it was computed over

`report_eligible` used to be a boolean in a file. `research report` read it, then re-read `claims/`
and `evidence/` fresh from disk — nothing connected the two. **A claim written after `research
validate` was published having never been validated**, and one deleted afterwards vanished from a
report that still asserted it rested on that evidence. No tampering was required; a new file was
enough.

A `ValidationResult` now carries `validated_inputs`: the sorted `(artifact_id, artifact_hash)` pairs
of every artifact `build_context` loaded, the load-error count, and a digest over both. Publication
rebuilds that roster and compares. A difference refuses with exit 5 and names it — *added*,
*removed*, or *re-stamped*, by id.

Three consequences worth stating:

- **Re-stamping is not a way around it.** A correctly re-hashed edit is a valid artifact; it is just
  not the one that was judged.
- **It is a binding, not a lock.** Re-run `research validate` and the run as it now stands can
  publish.
- **`--draft` is exempt.** A draft is explicitly a picture of the run as it stands, and says so.

In the same last mile, a second citation review could **erase** the first: verdicts were folded into
one dict, last-write-wins in filename sort order, so re-reviewing until the answer was acceptable
worked and depended on what the files were called. Verdicts are now collected per claim; disagreement
is `not_evaluated` naming the reviews that disagree. `not_checked` no longer counts as a verdict — it
is a value meaning *not assessed*, and treating it as one let an unjudged claim skip the unjudged
path.

## Attested independence, and what it is worth

`reviewer_independence_sufficient` reads a boolean the host wrote about itself. Every other check
here decides by inspecting something. That gap was not theoretical: during the Claude Code
conformance run the primary agent leaked its own `support_classification` into the independent-review
packet, and nothing in the CLI could have detected it.

So the strongest status now costs something. To declare `confirmed_independent`, a host writes a
`ReviewContext` artifact to `runs/<run-id>/review-contexts/` holding the **verbatim** text it gave
the reviewer, with `attestation.complete = true`. `check_independence_attested` then scans it, using
material drawn from the run's own artifacts, under three rules:

1. **A labelled grade** — `support classification: conflicting_evidence`, the shape of the real leak
   and the shape raw claim JSON takes.
2. **An excluded field in key position** — `"primary_rationale": "…"`. Skipped where the surrounding
   lines are prohibition language, so a packet that *lists* its own exclusions is not flagged.
3. **A prior review's conclusion, near-verbatim** — eight-token containment against the citation,
   methodology and contradiction reviews.

`procedurally_isolated` is unchanged: it needs no attestation, is accepted by non-high-risk profiles,
and must be disclosed in the report. It was always the honest option for a host that cannot prove
more.

### What a pass does not mean

It means the host's account of what it sent contains no leak of a detectable shape. A host that sends
a leaky context and attests a clean one passes, and no local artifact can prevent that. Stated
precisely:

- **Before** — a leak was undetectable, and an honest host had no way to demonstrate it had not
  leaked.
- **After** — an accidental leak is caught mechanically, and a deliberate one requires falsifying a
  hashed record rather than merely omitting one.

That second line was weaker than it read when written. The `ReviewContext`'s `content_sha256` is an
ordinary field of an artifact whose own `artifact_hash` validation never checked, so editing two
fields defeated it for the cost of one plain `sha256`. Hash verification on load closes that, and
the claim now holds — but only in the sense a hash can hold it: **an artifact hash detects an edit
made outside the process, not a host that writes a false artifact and stamps it correctly.** See
`docs/security-model.md`.

Known gaps, each pinned by a test in `tests/unit/test_independence.py` so they stay honest:

- a grade disclosed **without a label** ("the team already thinks the sources conflict") is missed —
  flagging bare words like *verified* would make the check unusable;
- a prior-review conclusion shorter than eight tokens, or paraphrased, is missed;
- prefixing a leak with prohibition language suppresses rule 2 — bounded by rule 1, which has no
  such exemption.

## Human review

Human review is a **result**, not an error. It is recorded, disclosed in the report, and blocks
publication until resolved through an `Amendment` — which records what changed, why, by whom, and
which artifact hash it supersedes. Historical artifacts are never edited in place.

Triggers are listed in the active research profile; see `src/research/profiles/`.

## Profiles

A profile customises validation rules, never the artifact model or the stage order (spec §27). The
run manifest records which profile a run was created under, and validation loads that file:

| Key | Effect |
|---|---|
| `risk: high` | tightens the independence bar and marks the run high-risk |
| `reviewer_independence.minimum` | the weakest independence status this profile accepts |
| `reviewer_independence.disclose_when_below` | acceptable but weaker than ideal — the report must say so |
| `prohibited_confidence` | classifications refused outright, whatever the evidence |
| `human_review_triggers` | which detectable conditions force human review |

`src/research/schemas/` and `src/research/profiles/` ship inside the package; `research init` copies
the profiles into the workspace, where a local edit overrides the packaged file.

**A key is honoured or it is declared unimplemented, with the reason.** Loading rejects anything
else, and a `human_review_triggers` entry no check can fire is rejected too. This exists because the
profile files previously shipped, were documented, were a ticked release task — and **no code read
them**; `medicine.yaml` promised `prohibited_confidence`, three methodology requirements and seven
triggers, and delivered one hard-coded independence bar it happened to agree with.

Currently declared unimplemented, and why:

- `methodology_review.require_*` — judging study design means reading the source, which is the host
  agent's job. Real enforcement needs the methodology review to record a per-item assessment whose
  *presence* the validator can check.
- `contradiction_review` — already required and already instructed for every profile, so these keys
  cannot tighten anything. Kept so a profile trying to loosen them is visibly rejected.
- `report_sections` — the report template is fixed; profile-driven sections would let a profile drop
  `contradictions` or `limitations`.
- `advisory_human_review_triggers` — conditions no code can detect, such as "any claim bearing on
  patient care". Recorded so the intent survives; nothing fires them.

A profile that omits a trigger is deliberately choosing not to require review for it. Both shipped
profiles list all six detectable triggers, and a test pins that.
