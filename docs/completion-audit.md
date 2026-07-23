# MVP completion audit

This audit records what is demonstrated by the current repository state and keeps external release
gates distinct from local implementation evidence. The MVP must not be described as fully released
until every open gate below has direct evidence.

## Verified locally on 2026-07-23

- Python 3.12.10 passes Ruff formatting and lint, strict mypy, compilation, and all 18 checked-in
  JSON Schema parses.
- The full test suite passes with 40 tests and 86% statement coverage. Two Windows symlink tests are
  skipped because the current process lacks symlink privileges; the same tests remain enabled on
  hosts where symlink creation is permitted.
- A clean wheel build installs in an isolated virtual environment, exposes `research --help`, and
  initializes a workspace from the packaged schema catalog. The verified wheel SHA-256 is
  `8e5b9b9bfbe304829bf973afedd360bd0a9d768fc52d2fbee608abc9c2653e50`.
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
- Rule tests reject unsupported `verified` claims, related-but-non-supporting citations, dependent
  strong-support sources, missing source-relationship assessments, invalid human attestations, and
  unsafe paths. A reviewed `unable_to_determine` claim is accepted as a valid research outcome.
- The checked-in Codex conformance run validates with zero structural errors and is truthfully blocked
  by its unresolved material contradiction and required human review. Publication is refused.

## Open release gates

- The configured GitHub Actions matrix has not been observed running on Linux, macOS, and Windows for
  this exact revision.
- Claude Code conformance has not run because the installed CLI reports `loggedIn: false`. The prepared
  checked-in workspace contains no fabricated Claude-authored artifacts. Both checked-in host
  conformance results require a fresh execution using the current two-question/PDF preparation before
  outcome parity can pass; setup parity itself is now tested.
- A real human has not resolved the Codex benchmark's mandatory material-contradiction review. Agent
  output cannot impersonate this action.
- This local repository has no Git remote, so no GitHub repository, tag, or release publication is
  evidenced here.

See [release-checklist.md](release-checklist.md) for the normative release gates.
