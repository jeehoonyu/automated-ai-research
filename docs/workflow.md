# Research workflow

The canonical sequence is planning, retrieval, evidence extraction, synthesis, contradiction review,
citation review, methodology review, independent review, final validation, and report rendering.

`research run` creates one typed packet per stage. A host agent reads only allowed inputs, produces
candidate JSON in the named response directory, and invokes `research validate <run-id> --stage ...`.
Validation calculates the canonical hash, checks the schema and semantic constraints, promotes the
artifact immutably, and advances the lifecycle.

Claims begin at version 1. Citation, contradiction, and methodology review stages may emit a new claim
version whose `artifact_id` is `<claim-id>-vN` and whose `supersedes` points to version N-1. Reviews
refer to the stable claim ID.

Independent review receives claim text and evidence but excludes primary rationale, primary confidence,
prior reviews, suggested wording, and hidden reasoning. The declaration distinguishes host-confirmed
fresh context from procedural packet isolation. The reviewer emits only a typed `Review`; after that
artifact validates, the CLI deterministically creates the superseding claim version containing the
review-derived lifecycle and independence fields. This prevents the reviewer from needing the excluded
primary classification merely to copy it forward.

When a human action is needed, submit typed artifacts under `responses/human_review/` or
`responses/amendment/`, validate that supplemental stage, then re-run full validation.
