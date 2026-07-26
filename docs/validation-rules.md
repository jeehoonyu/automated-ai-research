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

Each has a benchmark case naming the specific check that must catch it — see
`benchmark/expected/cases.json`. Asserting only "publication was blocked" would pass when the
wrong gate fired.

## The checks

| Check | What it establishes |
|---|---|
| `artifacts_conform_to_schema` | every run artifact validates; an unreadable one is `not_evaluated`, not skipped |
| `source_hashes_match` | stored originals still hash to their recorded value |
| `evidence_references_resolve` | evidence points at a document version this workspace holds |
| `text_locators_resolve` | offsets re-slice to the recorded span, and `exact_text` matches it |
| `visual_locators_resolve` | the named page render exists |
| `claims_reference_evidence` | no claim without evidence; no dangling evidence id |
| `citations_support_their_claims` | citation review judged every claim, and none rests on a related-but-non-supporting source |
| `contradiction_review_complete` | the review exists and did not fail |
| `citation_review_complete` | as above |
| `methodology_review_complete` | as above |
| `independent_review_complete` | as above |
| `reviewer_independence_sufficient` | independence declared and meeting the profile's bar |
| `ocr_evidence_human_verified` | OCR-dependent evidence has a recorded human verification amendment |
| `visual_interpretation_certain` | uncertain visual readings were human-verified |
| `contradictions_disclosed` | no claim carries an unresolved contradiction |
| `support_classifications_earned` | `verified` has a passed independent review; `strongly_supported` has multiple evidence records |
| `source_independence_established` | strongly-supported claims rest on genuinely independent sources; unknown independence is never promoted |
| `lifecycle_transitions_valid` | the event log replays as a legal sequence |

## Human review

Human review is a **result**, not an error. It is recorded, disclosed in the report, and blocks
publication until resolved through an `Amendment` — which records what changed, why, by whom, and
which artifact hash it supersedes. Historical artifacts are never edited in place.

Triggers are listed in the active research profile; see `research_profiles/`.
