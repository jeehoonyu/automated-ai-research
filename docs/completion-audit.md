# MVP completion audit

This audit records what is demonstrated by the current repository state and keeps external release
gates distinct from local implementation evidence. The MVP must not be described as fully released
until every open gate below has direct evidence.

## Verified locally and in CI on 2026-07-23

- Python 3.12.10 passes Ruff formatting and lint, strict mypy, compilation, and all 18 checked-in
  JSON Schema parses.
- The full test suite passes with 40 tests and 86% statement coverage. Two Windows symlink tests are
  skipped because the current process lacks symlink privileges; the same tests remain enabled on
  hosts where symlink creation is permitted.
- A clean wheel build installs in an isolated virtual environment, exposes `research --help`, and
  initializes a workspace from the packaged schema catalog. The verified wheel SHA-256 is
  `6b62d4bd1df5740bfa94cca8b79e115748022189b42481a80bb557cf09cce521`.
- GitHub Actions run
  [30063073784](https://github.com/jeehoonyu/automated-ai-research/actions/runs/30063073784)
  passes the complete lint, formatting, typing, deterministic-fixture, test, wheel-install, and CLI
  smoke matrix on Ubuntu, macOS, and Windows for implementation revision `ac51972`.
- The project is published as the public GitHub repository
  [jeehoonyu/automated-ai-research](https://github.com/jeehoonyu/automated-ai-research), with `main`
  as its default branch.
- Integration tests exercise duplicate Markdown imports, aliases, tables, fenced code, inert links,
  multi-column and table PDFs, raster and vector visual candidates, captions, full-page renders,
  OCR-required pages, malformed/encrypted PDFs, source/render/index/search-log tampering, deterministic
  FTS ordering, frozen index/config snapshots, the complete stage lifecycle, amendments, report
  publication, and publication invalidation.
- Human visual verification is exercised as an immutable same-ID Evidence replacement bound to exact
  target/replacement hashes, an explicit amendment, and a separately attested human review. Blocked
  supplemental stages cannot promote partial artifacts.
- The redistributable benchmark now includes byte-stable synthetic PDF fixtures and an expected
  contract covering a PDF table, vector region and caption, every-page rendering, raster content, and
  an image-only OCR-required page.
- A tested conformance preparer clones one canonical source/index base for Codex and Claude Code,
  creates both conflicting-evidence and `unable_to_determine` runs, and hash-verifies normalized work
  packet parity including independent-review exclusions and validation commands.
- A tested conformance checker refuses untouched prepared runs, applies the normal validation and
  publication gates to all four host/case combinations, checks the seeded expected outcomes, and
  records its result in a canonically hashed manifest.
- Rule tests reject unsupported `verified` claims, related-but-non-supporting citations, dependent
  strong-support sources, missing source-relationship assessments, invalid human attestations, and
  unsafe paths. A reviewed `unable_to_determine` claim is accepted as a valid research outcome.
- The checked-in Codex conformance run validates with zero structural errors and is truthfully blocked
  by its unresolved material contradiction and required human review. Publication is refused.

## Open release gates

- Claude Code conformance has not run because the installed CLI reports `loggedIn: false`. The prepared
  checked-in workspace contains no fabricated Claude-authored artifacts. Both checked-in host
  conformance results require a fresh execution using the current two-question/PDF preparation before
  outcome parity can pass; setup parity itself is now tested.
- A real human has not resolved the Codex benchmark's mandatory material-contradiction review. Agent
  output cannot impersonate this action.

See [release-checklist.md](release-checklist.md) for the normative release gates.
