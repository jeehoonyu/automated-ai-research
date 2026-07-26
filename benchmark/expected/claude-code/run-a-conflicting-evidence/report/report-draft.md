> # ⚠ DRAFT — NOT VALIDATED
>
> This report was generated with `--draft` before validation passed. It is **not** a published
> research output, its claims have **not** cleared the report gates, and it must not be circulated
> as though they had.
>
> Publication is currently blocked by 1 gate(s):
> - `contradictions_disclosed` — failed: 1 claim(s) carry an unresolved contradiction; these must be disclosed and human-reviewed before publication

# Research report — Does process-in-memory reduce off-chip data movement?

**Research question.** Does process-in-memory reduce off-chip data movement?

- Run: `RUN-1160be7c-5c57-4e89-ba18-0bab2cf45600`
- Profile: `default`
- Status: **DRAFT (unvalidated)**
- Generated from validated JSON artifacts by `research report`. This Markdown is a *view*; the JSON
  artifacts are canonical.

## Scope

_The plan did not record an explicit scope._

## Method

Evidence was retrieved from a fixed local document collection, extracted with exact locators, and
reviewed for citation support, contradictions, methodology, and independently. No web access, model
API, or external service took part in processing. Every claim below references evidence that resolves
to immutable source bytes.


## Sources

8 document(s) were in scope for this run.

| Document | Type | Extraction | Pages |
|---|---|---|---|
| pim-industry-brief.pdf | application/pdf | `extracted` | 1 |
| pim-survey.md | text/markdown | `extracted` | — |
| pim-preliminary-note.pdf | application/pdf | `partially_extracted` | 2 |
| pim-notes-with-injection.md | text/markdown | `extracted` | — |
| unrelated-scheduling.md | text/markdown | `extracted` | — |
| pim-primary-study-copy.pdf | application/pdf | `extracted` | 2 |
| pim-replication.pdf | application/pdf | `partially_extracted` | 2 |
| pim-scanned-appendix.pdf | application/pdf | `ocr_required` | 2 |
> 3 document(s) contain pages that could not be read as text and require
> OCR or human verification. Content on those pages did not back any claim below unless a human
> verification amendment is recorded.

## Findings

### 1. The available sources disagree on the direction of the effect: the primary study reports a 41 percent reduction in off-chip data movement, while an independent replication across three platforms reports a 12 percent increase.

**Conflicting evidence — substantial evidence disagrees.**

- Classification: `conflicting_evidence` · type: `descriptive_result` ·
  status: `independently_reviewed`
- Citation review: `passed` · contradictions: `unresolved`
- Independent review: `not_yet_reviewed`
- Scope: Limited to the two studies in this corpus; no external literature was consulted.
- Assumptions:
  - Both studies measure off-chip data movement comparably.
- Limitations:
  - The primary study used one benchmark family, one platform and one seed.
  - The replication used three platforms and ten seeds, so it is the methodologically stronger of the two, but has not itself been replicated.

Supporting evidence:
- **[1]** pim-primary-study-copy.pdf — page 1, 1 Introduction. This report evaluates a process-in-memory configuration.
  > 1 Introduction. This report evaluates a process-in-memory configuration. Across the twelve evaluated workloads, the process-in-memory configuration reduced measured off-chip data movement by 41 percent relative to the baseline.
- **[2]** pim-primary-study-copy.pdf — page 2, 1 Introduction. This report evaluates a process-in-memory configuration.
  > 3 Method and limitations. All twelve workloads were drawn from a single benchmark family and executed on one hardware platform. No independent replication was performed and the evaluation used a single random seed, so the reported interval reflects run-to-run variation only.

Contradicting evidence:
- **[3]** pim-replication.pdf — page 1, 1 Replication study. In our replication across three hardware platforms, the
  > 1 Replication study. In our replication across three hardware platforms, the process-in-memory configuration increased measured off-chip data movement by 12 percent relative to the baseline, the opposite of the direction previously reported.


## Contradictions and unresolved conflicts

- **The available sources disagree on the direction of the effect: the primary study reports a 41 percent reduction in off-chip data movement, while an independent replication across three platforms reports a 12 percent increase.** — contradiction status `unresolved`
## Limitations

No limitations were recorded beyond those attached to individual claims.

## Review and human-review status

| Review | Decision |
|---|---|
| citation_review | `passed_with_warnings` |
| contradiction_review | `human_review_required` |
| independent_review | `passed_with_warnings` |
| methodology_review | `passed_with_warnings` |

**Reviewer independence: `confirmed_independent`.**
The host confirmed a fresh reviewer context with the required exclusions applied.

> **Human review is outstanding.**
> - contradiction_review_complete: 1 review(s)
> - contradictions_disclosed: 1 claim(s) carry an unresolved contradiction; these must be disclosed and human-reviewed before publication

## Validation summary

| Check | Result |
|---|---|
| artifacts_conform_to_schema | `passed` |
| source_hashes_match | `passed` |
| evidence_references_resolve | `passed` |
| text_locators_resolve | `passed` |
| visual_locators_resolve | `not_applicable` |
| claims_reference_evidence | `passed` |
| citations_support_their_claims | `passed` |
| contradiction_review_complete | `passed` |
| citation_review_complete | `passed` |
| methodology_review_complete | `passed` |
| independent_review_complete | `passed` |
| reviewer_independence_sufficient | `passed` |
| ocr_evidence_human_verified | `not_applicable` |
| visual_interpretation_certain | `passed` |
| contradictions_disclosed | `failed` |
| support_classifications_earned | `passed` |
| source_independence_established | `not_applicable` |
| lifecycle_transitions_valid | `passed` |

Report eligible: **False**. A check recorded as `not_evaluated` blocks publication
exactly as a failure does — "could not be checked" is not "fine".

## References

**[1]** pim-primary-study-copy.pdf — page 1, 1 Introduction. This report evaluates a process-in-memory configuration.
`EVD-sha256-3c57134fc16f9789506c1fde05d9715639385c659ed3b68e0cdad692e0577c39` · document `DOC-sha256-37de79c621d3efac6d05dea9154a92162429d5b26c83e145f60d055ec72359a5` · version `DVER-sha256-861883b8735efcf657b76681a42d97f7dbc980dacc2103bd9ecd2fd630aad9d5`
**[2]** pim-primary-study-copy.pdf — page 2, 1 Introduction. This report evaluates a process-in-memory configuration.
`EVD-sha256-4a85ef71ea5f62117c00d88389a8669c386e89c59408b715d984b40b226d8706` · document `DOC-sha256-37de79c621d3efac6d05dea9154a92162429d5b26c83e145f60d055ec72359a5` · version `DVER-sha256-861883b8735efcf657b76681a42d97f7dbc980dacc2103bd9ecd2fd630aad9d5`
**[3]** pim-replication.pdf — page 1, 1 Replication study. In our replication across three hardware platforms, the
`EVD-sha256-679bfe69cea5310c7b7e48ae5e4803a8dc645404f259538e546f0e12209b80b8` · document `DOC-sha256-52e2fb125a0bdfe84b081a186c3cda403c5362cabc3721e9e22aba55a1b8cd89` · version `DVER-sha256-9be289cfeabd6b4b04c11a8e69bf5a6148a714593996193d0a67c4b20a93367e`

## Provenance

- Workflow version: `1.0.0`
- Configuration hash: `sha256:7385c837ab69d4801e089242435adac148c0c04e8ffa4236d77c51bdc187996f`
- Index hash: `sha256:14a78ca6c7f3b7061b1c680781a6142363ce2b2d883163a4e7465ff38f8b1b3c`
- Validation result hash: `sha256:8c7e08dc094748b5622bb70b120eefbb89bdbc4b49e1e66186987643d2fb4588`
- Schema versions: `Claim@1.0.0`, `Evidence@1.0.0`, `Review@1.0.0`, `ValidationResult@1.0.0`- Source documents: `DOC-sha256-03abc1634d20ea28afd08aacca53013ccef4ab6a4482e9fcb25505fecff6458d`, `DOC-sha256-0d80141e0e4f317216637044b9a1e6b932642175639b28bb974f71b0d7c98128`, `DOC-sha256-1a6337a3f147aa05d62a79cd57d8cea9dc31567d7c3a3c605ced7ccfb81943c8`, `DOC-sha256-247829552ad650bd591c496d6c15c3626f5da4e4d31d94dea1fc31813b5056c9`, `DOC-sha256-2560d3c42d57e3c35b321490b4e4b15ef0c0b25e209d6bdd404786cdc0de14e6`, `DOC-sha256-37de79c621d3efac6d05dea9154a92162429d5b26c83e145f60d055ec72359a5`, `DOC-sha256-52e2fb125a0bdfe84b081a186c3cda403c5362cabc3721e9e22aba55a1b8cd89`, `DOC-sha256-967f0de878c5c0e248294759bc807cb408794a14b3986b99e442399ea486f9a5`
_Generated by `research report`. The canonical artifacts for this run are under `runs/RUN-1160be7c-5c57-4e89-ba18-0bab2cf45600/`._
