# Research report — What evaluation scope did the primary process-in-memory study use?

**Research question.** What evaluation scope did the primary process-in-memory study use?

- Run: `RUN-7eb7704a-e2b4-42fd-b1f9-9abb2dab282a`
- Profile: `default`
- Status: **published**
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

### 1. The primary study evaluated twelve workloads drawn from a single benchmark family on one hardware platform using a single random seed, and performed no independent replication.

**Verified — directly checkable against the cited source.**

- Classification: `verified` · type: `direct_fact` ·
  status: `independently_reviewed`
- Citation review: `passed` · contradictions: `none_found`
- Independent review: `confirmed_independent`
- Scope: A statement about what the primary study reports of its own design.
- Limitations:
  - Reports the study's self-description; no external verification of its methods was possible from this corpus.

Supporting evidence:
- **[1]** pim-primary-study-copy.pdf — page 2, 1 Introduction. This report evaluates a process-in-memory configuration.
  > 3 Method and limitations. All twelve workloads were drawn from a single benchmark family and executed on one hardware platform. No independent replication was performed and the evaluation used a single random seed, so the reported interval reflects run-to-run variation only.


## Contradictions and unresolved conflicts

No unresolved contradictions were recorded against the claims above.

## Limitations

No limitations were recorded beyond those attached to individual claims.

## Review and human-review status

| Review | Decision |
|---|---|
| citation_review | `passed` |
| contradiction_review | `passed` |
| independent_review | `passed` |
| methodology_review | `passed_with_warnings` |

**Reviewer independence: `confirmed_independent`.**
The host confirmed a fresh reviewer context with the required exclusions applied.


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
| contradictions_disclosed | `passed` |
| support_classifications_earned | `passed` |
| source_independence_established | `not_applicable` |
| lifecycle_transitions_valid | `passed` |

Report eligible: **True**. A check recorded as `not_evaluated` blocks publication
exactly as a failure does — "could not be checked" is not "fine".

## References

**[1]** pim-primary-study-copy.pdf — page 2, 1 Introduction. This report evaluates a process-in-memory configuration.
`EVD-sha256-a460a2a10e9576135a184c4036d1b1686848fda59a2ed8decee2df44f637a12f` · document `DOC-sha256-37de79c621d3efac6d05dea9154a92162429d5b26c83e145f60d055ec72359a5` · version `DVER-sha256-861883b8735efcf657b76681a42d97f7dbc980dacc2103bd9ecd2fd630aad9d5`

## Provenance

- Workflow version: `1.0.0`
- Configuration hash: `sha256:7385c837ab69d4801e089242435adac148c0c04e8ffa4236d77c51bdc187996f`
- Index hash: `sha256:14a78ca6c7f3b7061b1c680781a6142363ce2b2d883163a4e7465ff38f8b1b3c`
- Validation result hash: `sha256:c16d0dad5e21129a784b40082e92c87a3bff020bf5b8a66284f76fe8fc5d6f17`
- Schema versions: `Claim@1.0.0`, `Evidence@1.0.0`, `Review@1.0.0`, `ValidationResult@1.0.0`- Source documents: `DOC-sha256-03abc1634d20ea28afd08aacca53013ccef4ab6a4482e9fcb25505fecff6458d`, `DOC-sha256-0d80141e0e4f317216637044b9a1e6b932642175639b28bb974f71b0d7c98128`, `DOC-sha256-1a6337a3f147aa05d62a79cd57d8cea9dc31567d7c3a3c605ced7ccfb81943c8`, `DOC-sha256-247829552ad650bd591c496d6c15c3626f5da4e4d31d94dea1fc31813b5056c9`, `DOC-sha256-2560d3c42d57e3c35b321490b4e4b15ef0c0b25e209d6bdd404786cdc0de14e6`, `DOC-sha256-37de79c621d3efac6d05dea9154a92162429d5b26c83e145f60d055ec72359a5`, `DOC-sha256-52e2fb125a0bdfe84b081a186c3cda403c5362cabc3721e9e22aba55a1b8cd89`, `DOC-sha256-967f0de878c5c0e248294759bc807cb408794a14b3986b99e442399ea486f9a5`
_Generated by `research report`. The canonical artifacts for this run are under `runs/RUN-7eb7704a-e2b4-42fd-b1f9-9abb2dab282a/`._
