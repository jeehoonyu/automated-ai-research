# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[semantic versioning](https://semver.org/).

## [Unreleased]

### Added — stage acceptance (`research validate --stage`)
- `docs/architecture.md`, `workflow/canonical-workflow.md` and `validator.py`'s own docstring all
  said agents write to `responses/` and that validation promotes a response only after it validates.
  **Nothing read `runs/<id>/responses/`**, though eight of ten packets named a `responses/*.json`
  path as their required output, and `--stage` — the command every packet names as its judge — was
  accepted and silently ignored (`--stage bogus_nonsense` gave byte-identical output to no flag).
- `src/research/runs/promotion.py` implements it: validate every artifact a stage produced, stamp
  the hash of what was validated, promote into `evidence/` / `claims/` / `reviews/` / `plan.json`,
  advance exactly one phase. All or nothing. A supplied-but-wrong hash is refused rather than
  re-stamped. Unknown stage names and the two CLI-performed stages are refused by name.
- This makes hosts able to write plain JSON: since validation began verifying `artifact_hash`, an
  agent writing straight into a canonical directory had to produce an RFC 8785 digest by hand.
- `runs.manager.transition()` had no caller in `src/`, so `is_valid_transition` had never run on a
  real workspace and `check_lifecycle` reported "event log replays cleanly" about a log with
  nothing in it. Stage acceptance calls it; skipping stages is now refused. `check_lifecycle` also
  cross-checks the manifest's `phase` against the end of the log.

### Fixed — human verification reads the record, not the label
- `ocr_evidence_human_verified` selected candidates purely by `extraction_status` on the
  agent-authored Evidence artifact, so an agent cleared it by labelling its own evidence
  `extracted` while the CLI-written Document manifest recorded which pages need OCR. The page is
  now derived from the manifest — `page_map` for a text span, the render digest for a visual
  region — never from `locator["page"]`, which the agent also writes.
- A two-key JSON object in `amendments/` cleared both human-verification gates: `_amendments` did
  not filter on `schema_name` and amendments were absent from `check_artifacts_conform`, so
  `validate_artifact` never ran on one. Now filtered and validated, and a verification must carry
  the `target_artifact_hash` of the version it checked — so it cannot outlive that version.
- `docs/validation-rules.md` records what remains self-reported (`interpretation_status`) and calls
  out the undecided question of whether `actor_type == "human"` should be required.

### Fixed — the publication verdict is bound to the artifacts it was computed over
- `ValidationResult` gains required `validated_inputs`: sorted `(artifact_id, artifact_hash)` pairs
  for every artifact `build_context` loaded, the load-error count, and a digest over both.
  `research report` rebuilds the roster and refuses to publish when it differs, naming what was
  added, removed or re-stamped. `report_eligible` was previously a boolean the renderer read before
  re-reading `claims/` and `evidence/` from disk — **a claim written after `validate` was published
  having never been validated**, and one deleted afterwards vanished from a report still asserting
  it. `--draft` is exempt; re-running `validate` restores publication.
- A second citation review can no longer erase the first. Per-claim verdicts were folded into one
  dict, last-write-wins in filename sort order, so re-reviewing until the answer was acceptable
  worked. Verdicts are now collected per claim and disagreement is `not_evaluated` naming the
  reviews involved. `not_checked` no longer registers as a verdict.
- Relationships and amendments are loaded once in `build_context` instead of lazily, so a malformed
  one becomes a blocking load error rather than a silent drop.
- Removed a dead ternary in the report manifest whose two branches were identical.

### Fixed — the bytes citations actually resolve against are now re-hashed
- `source_hashes_match` re-hashes `originals/` and claims "evidence rests on those bytes". It does
  not: a text locator is an offset pair into `normalized_text_path`, a derived and mutable file that
  nothing re-hashed, and page renders were trusted by path while
  `resolve_visual_locator`'s docstring claimed a re-hash it never performed. `span_sha256` did not
  close it, because the span hash lives in the locator the agent writes — so the normalized text and
  the evidence could be made to agree with each other and disagree with what was extracted.
  New check `derived_text_hashes_match` (22 total); `resolve_visual_locator` now hashes the file and
  reports a new `render_mismatch` outcome. A document recording no `normalized_text_sha256` returns
  `not_evaluated` rather than being skipped.

### Fixed — three gates that reported "no problems" for what they never inspected
Found by a twelve-agent audit across five independent lenses (37 findings, six survived adversarial
refutation), each confirmed by executing the check rather than reading it.
- **Artifacts are now hash-verified where it counts.** Validation loaded evidence, claims, reviews,
  relationships and amendments through a bare `json.load`; `read_artifact` verifies hashes but this
  loader is the one validation uses. A hand edit that stayed schema-valid was invisible, and one
  word changed in a citation review flipped `citations_support_their_claims` from failed to passed
  and `report_eligible` to True. A mismatch is now a load error, which forces a blocking
  `not_evaluated`. This also stops a stray blob in `reviews/` from crashing `validate_run` with a
  `KeyError` instead of reporting `not_evaluated`.
- **`contradiction_status: not_checked` no longer passes.** The check asked only whether any claim
  was `unresolved`, so a run where nobody had looked returned "none unresolved". Now
  `not_evaluated`.
- **`unknown` no longer clears the source-independence gate that recording nothing blocks.** The
  enum had no value meaning independent, so the only way to reach `passed` was to record every pair
  as `cites` or `unknown` — neither of which asserts independence — while the honest answer of
  recording nothing correctly blocked. `independent` added to `SourceRelationship`; absent,
  `unknown` and `cites` now all block.

### Fixed — the installed package did not work
- **Canonical schemas now ship.** `SCHEMA_ROOT` was `parents[3] / "schemas"` — the repository root —
  so no wheel ever contained a schema. Because validation happens on write, an installed copy could
  run `--version` and `init` and **nothing else**. Schemas moved to `src/research/schemas/`, which
  is also now their single home, so the repository copy and the packaged copy cannot drift.
- **The CI wheel job can now fail.** It ran `--version`, `init` and one `test -f` — exactly the
  subset that worked. It now drives import → index → search → run → validate and asserts the gating
  exit code. `tests/unit/test_packaging.py` catches the same class without CI, a build, or a
  network: every runtime data directory must resolve inside the package and be covered by a
  `package-data` glob.

### Fixed — research profiles were never read
- `research_profiles/*.yaml` shipped, were documented and were a ticked release task while **no code
  loaded them**. The entire feature was one hard-coded set, `{"medicine", "finance"}`;
  `medicine.yaml`'s `prohibited_confidence: [verified]`, three methodology requirements and seven
  human-review triggers did nothing. `risk`, `reviewer_independence`, `prohibited_confidence` and
  `human_review_triggers` are now loaded and applied, profiles ship in the package, and
  `research init` copies them into the workspace where a local edit overrides the packaged file.
- A profile key must be honoured or declared in `NOT_IMPLEMENTED` with its reason; anything else is
  a load error, and a `human_review_triggers` entry no check can fire is rejected. Four keys are
  currently declared unimplemented.
- Two new checks: `profile_rules_loaded` (a profile that will not load blocks, rather than falling
  back to defaults the manifest does not name) and `profile_confidence_permitted`.

### Fixed — exit code 6 was unreachable
- Spec §34 defines `6 HUMAN_REVIEW_REQUIRED` as "an expected workflow state that automation still
  needs to detect", but it was only derivable from `errors` and `human_review_required` was only
  ever emitted as a warning. An import whose own summary read `failed 0` exited `4`,
  `SOURCE_PROCESSING_FAILURE`. A `human_review` envelope status now distinguishes "a source broke"
  from "a human must look at this", and `validate` separates a failed gate (5) from a run awaiting
  review (6). `test_every_declared_exit_code_is_reachable` enumerates `ExitCode` and produces each.

### Added
- **Attested reviewer independence.** `confirmed_independent` now requires a `ReviewContext`
  artifact recording the verbatim text the host attests it gave the independent reviewer. The new
  `independence_context_attested` check scans it for excluded material drawn from the run's own
  artifacts: a labelled support classification, an excluded field in key position, or a prior
  review's conclusion repeated near-verbatim. Closes the gap found by the Claude Code conformance
  run, where the primary agent leaked its own classification into a review packet and **nothing in
  the CLI could detect it**. See `GOAL.md`.
- `ReviewContext` schema (14 total) and `CTX-sha256-` content-derived identifiers.

### Changed
- The independent-review packet now allows `claim_statements` rather than `claims`, and explicitly
  excludes the primary agent's grading fields. The previous contract allowed `claims` while
  excluding `primary_confidence` — and a stored `Claim` carries `support_classification`, so handing
  over raw claim JSON satisfied the allow-list and defeated the exclusion in the same act.

### Deprecated / downgraded
- Both committed Claude Code conformance runs declare `confirmed_independent` with no attested
  context and are **recorded as downgraded**, not grandfathered. Under the current validator they
  are `not_evaluated` on the new check, which blocks. Gate 38.6's discovery evidence and both runs'
  verdicts are unaffected. Pinned by `tests/unit/test_docs.py`.

### Fixed
- `ruff check src tests` (102 findings) and `mypy --strict src/research` (17 errors) both pass.
  Neither had ever executed — CI was configured but never billed a minute — so the pipeline would
  have failed at the lint step on its first successful run. Two of the type errors were real
  readability defects: a doubly-bound `rel` in `check_source_independence`, and a two-ternary
  destination/value choice in `discover_sources`.
- The shared `complete_run` fixture moved to `tests/integration/conftest.py` instead of being
  imported across test modules, where every use shadowed the import.

### Added (earlier in Unreleased)
- Canonical workflow document, now copied into every generated workspace so `AGENTS.md` and
  `CLAUDE.md` do not point at a file the workspace lacks.
- Research profiles (`default`, `medicine`) — profiles customise validation rules, never the
  artifact model or stage order.
- Architecture, security-model, and validation-rules documentation.
- `SECURITY.md`, `CONTRIBUTING.md`, this changelog, and a release checklist.

## [0.1.0] — unreleased

First implementation of the MVP specification in `PROJECT_GOAL.md`.

### Added
- **Foundation** — RFC 8785 canonical JSON, SHA-256 content addressing, `artifact_hash` computed
  with the hash field omitted, content-derived identifiers, UUIDv7 with an intra-millisecond
  counter, path containment, atomic writes, versioned result envelope, stable exit codes 0-8.
- **Import** — content-addressed originals, PDF and Markdown importers, deduplication by content
  with filename aliases, seven extraction statuses, page rendering with per-render hashes,
  OCR-required detection, append-only import events.
- **Normalization and chunking** — one canonical normalized text per document version, page maps,
  section extraction, chunks that never straddle a page boundary, text locators carrying a span
  hash, normalized-bounding-box visual locators.
- **Indexing and search** — SQLite FTS5 over index-eligible chunks only, reproducible
  `index_hash` over logical rows, deterministic tie-breaking, literal-only query normalization,
  results carrying resolvable locators and no evidence-quality field.
- **Run management** — run manifests pinning the source collection, two-field lifecycle
  (`phase` + `disposition`), enforced one-step transitions, work packets, append-only lifecycle
  events, `status` and `inspect`.
- **Artifacts** — 13 versioned JSON schemas, registry, validation on write.
- **Validation** — 18 checks with four statuses, where `not_evaluated` blocks exactly as `failed`
  does.
- **Reporting** — deterministic Markdown from validated JSON, citation index, report manifest and
  hash, `--draft` mode, claim-wording checked against validated classification.
- **Benchmark** — synthesized nine-document corpus and ten cases, each naming the specific gate
  that must catch it.

### Known limitations
- Cross-host conformance (spec 37) is **not** demonstrated: the benchmark simulates agent stages.
- Table and figure detection reports `not_detected`; it is not implemented.
- No OCR engine. `ocr_required` content becomes usable only through a human amendment.
- PDF parsing is not sandboxed.
