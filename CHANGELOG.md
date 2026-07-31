# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[semantic versioning](https://semver.org/).

## [Unreleased]

### Fixed — nine defects from a sweep for restated vocabularies
The UI's worst defect was a *shape*, not a typo: a template restated a schema enum from memory and
lost. There are 53 enums across the 15 shipped schemas, and Python throughout the package restated
slices of them. A five-lens sweep asked one question of each — **what does a value this vocabulary
does not list do?** — and the answer was reliably "the reassuring thing". Nine findings survived
adversarial refutation; one was refuted. Every fix was mutation-tested.

- **`check_ocr_evidence` asked about 1 of the 7 extraction statuses.** Evidence labelled `ambiguous`,
  `partially_extracted` or `human_review_required` returned `not_applicable` — which does not block
  — and published. `Evidence.human_review_required`, a **required** field in the schema, was read by
  nothing anywhere in `src/research`. The asymmetry is what made it bad: the flattering label
  (`extracted`) was correctly distrusted and overridden from the Document manifest, while the
  self-incriminating labels were discarded, so an agent that wrote down the truth about its own
  extraction got the same green verdict as one that did not. Now asks
  `ExtractionStatus.needs_human_review` and honours the schema's own boolean.
- **`research validate` crashed on any run that had once been flagged.** `_record_verdict` attempted
  `independently_reviewed → validation_passed` on a run whose disposition was
  `human_review_required`, which the state machine forbids, so the ordinary "fix what was flagged,
  validate again" loop raised `LifecycleError` — *after* writing the verdict artifact to disk. The
  disposition was consulted by nothing in validation at all, so a run parked at
  `human_review_required` could have every check pass and be recorded `report_eligible: true` while
  `research status` called it blocked and `research report` published it. `check_run_progressed` now
  blocks a run whose disposition forbids advancing, and `_record_verdict` cannot raise.
- **`causal_claim_from_correlational_evidence` was a trigger nothing could fire.** It sat in
  `KNOWN_TRIGGERS` — whose comment says these are "triggers the validator can actually detect" — and
  both shipped profiles asked for it, but no check ever passed that string to `forces_human_review`.
  The detection already existed in `reporting.language`; it ran only at report time, after the gate
  it should have informed.
- **Causal wording was checked against 3 of the 11 claim types.** "The treatment causes X" typed as
  an `interpretation` or `hypothesis` sailed through while the identical sentence typed as a
  descriptive result was caught. Inverted to name the one exempt type, so a claim type added later
  is suspect by default.
- **The report disclosed 2 of the 7 extraction statuses.** A source that failed to parse outright,
  or was an unsupported format, appeared in the Sources table with no disclosure whatsoever — the
  narrowest slice of the enum producing the most reassuring report. The disclosure now names each
  document and its status.
- **A lossy UTF-8 decode was stamped `extracted`**, the one status meaning "usable as evidence",
  while the warning beside it said in plain words that quoted text may differ from the original
  bytes. Nothing in validation reads `extraction_warnings`; a warning is not a gate. Now
  `partially_extracted`.
- **`PRIOR_REVIEW_TYPES` listed 3 of the 5 review types** and omitted `human_review` — whose
  conclusions are exactly the prior judgement an independent reviewer must not see. Derived by
  subtraction now, so a review type added later is excluded by default.
- **`prohibited_confidence` was the one profile-supplied vocabulary loaded verbatim** while its
  three neighbours all rejected unknown values. A typo prohibited nothing, so the profile read as
  tighter than the default while being exactly the default.
- **`docs/validation-rules.md` claimed each of the eleven spec §8.8 blocking conditions had a
  benchmark case naming its check.** Six do. Deleting any of the other 19 checks from `CHECKS`
  leaves the benchmark fully green, and `benchmark/README.md` asserted the stronger claim that
  deleting *any single check* must break an assertion. Both corrected, and
  `tests/unit/test_vocabularies.py` now pins the corrected claim against `cases.json`.

### Added — `schema_enum()`, so Python can ask instead of restating
- `artifacts.registry.schema_enum("Claim", "support_classification")` reads the permitted values
  from the shipped schema. A restatement stays right where the code needs a *judgement* about a
  subset — which relationships establish independence, which statuses block — because those are
  decisions and belong in code with the reason beside them. This is for the other case.
- `tests/unit/test_vocabularies.py` checks every domain vocabulary in the package against the schema
  or `StrEnum` that defines it, in one file. It states plainly what it cannot do: coverage is not
  correctness. `not_confirmed` was mis-*filed*, not missing, and no schema-derived test would have
  caught it.

### Added — `research ui`, a read-only local web view
- A tenth command, and the first that is **not** in the specification. Everything it shows is
  already available from the CLI; what a browser adds is following a chain — claim → evidence →
  locator → the source text it resolves to — without copying identifiers between commands.
- **It never writes.** No route mutates a workspace; every method but `GET` and `HEAD` is answered
  `405` before a workspace is even opened. `/search` deliberately does *not* record a retrieval log:
  `research search --run` does that on purpose, and a page load is not retrieval. Asserted two ways
  — a unit test greps the package for every write entry point, and an integration test hashes every
  file in a workspace, browses every page, and re-hashes.
- **It cannot round a gate up.** Whether a check blocks is answered by `CheckResult.blocks` itself
  rather than by a mapping restated in the UI, so `not_evaluated` is painted exactly as `failed` and
  labelled *"nobody looked — blocks publication exactly as a failure does"*. A status the build does
  not recognise — these are read from JSON on disk — is treated as blocking rather than as a calm
  grey. A run page re-derives the artifact roster and says loudly when the stored verdict no longer
  describes the files on disk.
- **Document text stays data.** Autoescaping is unconditional (not `select_autoescape`, which
  decides by filename), every response carries `Content-Security-Policy: default-src 'none'`, and
  the interface ships no JavaScript at all. An integration test imports a document containing
  `<script>`, `<img onerror=…>` and an attribute break and asserts what comes back over the wire.
- Binds to loopback and refuses anything else without `--allow-remote`; a request whose `Host`
  header is not loopback is answered `421`, which is what closes DNS rebinding.
- No new dependencies: `http.server` and the Jinja2 already used by the report renderer.
- Refusing a non-loopback bind exits `7 UNSAFE_PATH_OR_SECURITY` via the new `UnsafeExposureError`,
  not `1 GENERAL_FAILURE` — §34 gives security refusals their own code so automation can tell one
  from a crash. `--json` on a command that serves until interrupted exits `2 INVALID_ARGUMENTS`
  rather than printing an envelope that looks like a completed command.
- `allow_reuse_address` is not set on Windows, where it means something different from POSIX: it
  lets a second process bind a port another is actively listening on, so `research ui --port 8787`
  against a port already serving *another workspace* started cleanly and showed pages from the wrong
  corpus. Windows now asks for `SO_EXCLUSIVEADDRUSE` and the second bind fails with a clear message.
- Five deliberate mutations — autoescape off, `not_evaluated` painted neutral, the `Host` check
  removed, the staleness comparison skipped, write methods answered instead of refused — were each
  confirmed to turn a test red.

### Fixed — six defects the UI's own adversarial audit found, in the UI
Five lenses over the new code, each finding verified by a skeptic instructed to refute it. Nine
confirmed findings deduplicated to six defects; one was refuted. Every fix below was then confirmed
by re-introducing the defect and watching a test go red.

- **A claim that had never been independently reviewed got a green chip.** Found by three lenses
  independently, and the exact failure the UI was written to avoid. The chip class was decided by a
  Jinja expression restating the Claim schema's enum from memory — in two templates, both wrong the
  same way. They blocked on `unknown`, which is **not in the enum at all**, and let `not_confirmed`
  and `not_yet_reviewed` fall through to the green used for `confirmed_independent`. Worse, because
  the field is optional, *omitting* it rendered the blocking "not recorded" chip while honestly
  recording `not_yet_reviewed` rendered green — writing the truth down looked better than writing
  nothing. Classification now lives in `views.claim_chips`, mirrors `check_support_classifications`
  and `check_contradictions_disclosed`, and is pinned against the shipped schema so a new enum member
  is a test failure rather than a green chip. A test asserts no template inspects these fields at all.
- **`support_classification` is no longer painted as a verdict.** `unsupported`,
  `conflicting_evidence` and `unable_to_determine` are legitimate research outcomes; colouring them
  red editorializes about findings, and colouring `verified` green implies the classification was
  earned, which is `support_classifications_earned`'s decision and not this page's.
- **`/runs/<uuid>` without the `RUN-` prefix showed "Report eligible" and zero artifacts.** The id
  was normalised at the `inspect` call only, so the manifest and verdict came from the canonical run
  while `claims/`, `evidence/` and `reviews/` were read from a directory that does not exist. An
  empty directory rendered as "No claims. A run with no claims has produced no findings" — about a
  run that has one. Normalised once, up front.
- **The "Report eligible" banner never checked the checks printed beneath it.** `report_eligible` is
  a boolean stored beside the check list; flipping it and re-stamping produced a green "every gate
  cleared" directly above ten blocking rows. Neither guard covers this — a re-stamped result is
  internally consistent, and a validation result is not part of its own artifact roster, so it reads
  as perfectly fresh. The page now re-derives eligibility from the checks and says loudly when the
  stored verdict disagrees with them. The overview chip had the same defect.
- **A POST body was parsed as the next request.** `protocol_version = "HTTP/1.1"` makes every
  connection keep-alive and nothing read the request body, so `POST / Host: attacker.example` with a
  well-formed `GET / Host: localhost` in its body returned **two** responses: the 405, then the full
  workspace page that the Host check had just refused. Bodies are drained, and a refusal closes the
  connection. Mutation testing showed the first test pinned only the close, so a second test covers
  a body on an *accepted* GET — the case only the drain catches.
- **A request with no `Host` header skipped the loopback check entirely.** `... and host and not
  is_loopback(host)` short-circuited, so an absent or empty header was served in full — a fail-open
  answer to a security question, in the same file that argues against exactly that for the bind
  check. Not reachable from a browser (`Host` is a forbidden header name), but the docstring claimed
  a property the code did not have.
- **`check_blocks` failed open on an unrecognised status while `status_class` failed closed**, so a
  validation result carrying a word this build does not know rendered every row red and then
  reported "0 blocking" above them. Both now fail closed, and a test asserts they cannot disagree.

### Fixed — `research status` invented an unvalidated response for every validated run
- `_stage_artifact_present` counted a stage's `required_outputs` wherever they lived.
  `final_validation` declares `validation/validation-result.json`, which `research validate` writes
  itself, so the moment a run was validated `status` reported that `final_validation` had a response
  awaiting acceptance — including a run still at `initialized` that had produced nothing at all —
  and then advised `research validate <run> --stage final_validation`, which the one-step state
  machine could not perform. Only files under `responses/` are agent output, and only those count
  now. Found by the new UI, which draws its stage list from this predicate.

### Fixed — the four deferred questions, decided
- **`research status` and `research validate` disagreed about report eligibility.**
  `Phase.REPORT_ELIGIBLE` and `Phase.PUBLISHED` were compared against in `status` and set by
  nothing; `Phase.VALIDATION_PASSED` was referenced nowhere and `Disposition.VALIDATION_FAILED`
  never assigned. `status` therefore answered `report_eligible: False` for every run ever created.
  `validate` now records its verdict in the lifecycle, `report` records publication, and the new
  `run_reached_a_publishable_phase` check blocks a run that never walked the stages.
- **Visual evidence must declare `interpretation_status`.** An absent field was indistinguishable
  from `clear`, so the visual-certainty gate never fired for evidence that did not answer.
- **`human_ocr_verification` and `human_visual_verification` require `actor_type == "human"`.**
- **`methodology_review.require_*` is honoured** by the new `methodology_items_assessed` check —
  presence of an assessment, never its correctness.
- The suite's `complete_run` fixture now walks the workflow through `research validate --stage`
  instead of writing canonical artifacts directly. It had never exercised the documented loop.

### Fixed — the assertions that guard everything else can now fail
- `compare_hosts.py`, the harness that decides gate 38.10, reduced each host's claims to three
  *independently sorted* lists — throwing away which value belonged to which claim, so two hosts
  that swapped verdicts compared as identical — and collected `claim_types` without ever comparing
  it. Verdicts are now compared per claim, anchored to the content-derived evidence ids the claim
  rests on, which is the only key stable across hosts (claim ids are UUIDs; §37 permits differing
  prose). Six mutation tests, including a control that identical copies agree.
- `test_every_registered_schema_loads_and_is_wellformed` asserted `is_valid(...) in (True, False)`.
  It now validates each schema against the Draft 2020-12 meta-schema.
- The OCR disclosure is asserted present in a report with an unreadable page and absent in one
  without.
- CI lints `benchmark/` and `tools/`, which ship and were never linted.

### Added — retrieval provenance is persisted (spec §29)
- `research search` computed the entire retrieval record and a stable `retrieval_log_hash` — under
  a docstring calling the log "reproducible and auditable" — and discarded it. Nothing recorded
  which queries produced the evidence a run rests on.
- New `RetrievalLog` artifact and `RTL-sha256-` identifier, content-derived including the
  `index_hash`. `research search --run <run-id>` records it.
- New check `retrieval_provenance_recorded`: `not_evaluated` when a run has evidence and no record
  (evidence can arrive through `inspect`, so "unknown" is the honest verdict), `failed` when a
  recorded search ran against an index the run did not pin. The report manifest names the hashes.

### Fixed — the read surface answers from the artifacts
- `research status` hardcoded `unresolved_contradictions: []` and `superseded_artifacts: []` under
  the comments "populated by validation in Phase 7" and "populated by amendments in Phase 6". Both
  phases had shipped. They are now computed, and `unchecked_contradictions` is reported separately
  because "nobody looked" is not "none found".
- `research inspect` refused `EVD-`, `CLM-` and `REV-` ids with "arrives with Phase 6 artifacts" —
  the three classes spec §8.7 most requires. Evidence inspection re-slices the stored normalized
  text, reports any divergence from `exact_text` instead of hiding it, and names the claims and
  reviews that rely on it.
- Payloads carrying document-derived text now carry an explicit untrusted-content note. The
  trusted/untrusted separation the security model relies on existed only as three constants in
  `packets.py` that never wrapped anything.

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
