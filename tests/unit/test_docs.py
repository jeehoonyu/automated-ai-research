"""Documentation integrity.

Docs drift ahead of code — that is the failure recorded in docs/lessons-carried-forward.md §4, where
a predecessor's append-only ledger asserted a determinism result no code had ever computed, and then
seeded the next research cycle with it.

These tests do not check prose quality. They check the two things that are mechanically checkable
and that actually bite: that a document the docs point at exists, and that a capability the docs
claim is present in code.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
DOCS = sorted([*REPO.glob("*.md"), *(REPO / "docs").glob("*.md"),
               *(REPO / "benchmark").glob("*.md"), *(REPO / "workflow").glob("*.md")])

_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
_BACKTICK_PATH = re.compile(r"`([A-Za-z0-9_./-]+\.(?:md|py|json|yaml|j2|toml))`")


def test_documentation_exists():
    assert len(DOCS) >= 9, f"expected the full doc set, found {[d.name for d in DOCS]}"


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_no_dangling_relative_links(doc: Path):
    """A link to a file that does not exist is the cheapest possible broken promise."""
    missing = []
    for target in _LINK.findall(doc.read_text(encoding="utf-8")):
        if target.startswith(("http://", "https://", "#", "mailto:")):
            continue
        path = (doc.parent / target.split("#")[0]).resolve()
        if not path.exists() and not (REPO / target.split("#")[0]).exists():
            missing.append(target)
    assert not missing, f"{doc.name} links to files that do not exist: {missing}"


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_referenced_repository_paths_exist(doc: Path):
    """Backticked paths like `benchmark/expected/cases.json` must resolve.

    Directory-ish and illustrative references are skipped; this only pins concrete file paths.
    """
    text = doc.read_text(encoding="utf-8")
    missing = []
    for candidate in set(_BACKTICK_PATH.findall(text)):
        if "/" not in candidate:
            continue                                  # bare filenames may be illustrative
        if candidate.startswith(("runs/", "documents/", "indexes/", "originals/", "imports/",
                                 "schemas/v2", "reviews/", "responses/", "validation/",
                                 "report/", "evidence/", "claims/", "amendments/",
                                 "relationships/", "profiles/", "packets/")):
            continue                                  # workspace-relative, not repo paths
        if not (REPO / candidate).exists():
            missing.append(candidate)
    assert not missing, f"{doc.name} references repository paths that do not exist: {missing}"


def test_the_host_entry_files_point_at_a_document_that_ships(tmp_path: Path):
    """AGENTS.md and CLAUDE.md are the first thing a host reads. They must not dangle.

    This was a real defect: both told agents to read `workflow/canonical-workflow.md`, and no
    generated workspace contained that file.
    """
    from research.workspace import init_workspace

    init_workspace(tmp_path / "ws")
    root = tmp_path / "ws"
    for entry in ("AGENTS.md", "CLAUDE.md"):
        text = (root / entry).read_text(encoding="utf-8")
        for candidate in set(_BACKTICK_PATH.findall(text)):
            if "/" not in candidate or candidate.startswith("runs/"):
                continue
            assert (root / candidate).exists(), \
                f"{entry} points at {candidate}, which the workspace does not contain"


def test_the_canonical_workflow_is_identical_in_repo_and_package():
    """One source of truth. A drifted copy is worse than none — a host reads the stale one."""
    repo_copy = (REPO / "workflow" / "canonical-workflow.md").read_text(encoding="utf-8")
    shipped = (REPO / "src" / "research" / "assets" /
               "canonical-workflow.md").read_text(encoding="utf-8")
    assert repo_copy == shipped, \
        "workflow/canonical-workflow.md and the packaged copy have diverged; re-copy it"


def test_the_release_checklist_states_the_unmet_gate():
    """Gate 38.10 requires BOTH hosts. Claude Code has run; Codex has not.

    The checklist must record the half that is missing rather than rounding up to 'done'. This test
    is deliberately about the *substance* — that Codex is named as not run — so completing the Codex
    conformance run is what makes it fail, which is the correct time to revisit it.
    """
    text = " ".join((REPO / "docs" / "release-checklist.md")
                    .read_text(encoding="utf-8").split()).lower()
    assert "38.10" in text
    assert "codex has not been run" in text, \
        "the checklist must name Codex as the outstanding half of gate 38.10"


def test_the_readme_does_not_claim_cross_host_conformance():
    """The README must state the unmet gate, not merely omit it.

    Checks for the substance rather than one phrasing, so rewording the section does not silently
    turn this into a test of nothing.
    """
    # Normalise whitespace first: Markdown wraps prose, so a phrase can straddle a line break and a
    # naive substring check would fail on correct text. (This bit me twice.)
    text = " ".join((REPO / "README.md").read_text(encoding="utf-8").split()).lower()
    assert "not established" in text, "the README must have a 'what is not established' section"
    assert "37" in text
    assert "codex has not been run" in text, \
        "the README must state which host is still outstanding, not round the gate up to 'done'"


def test_cross_host_comparison_refuses_to_pass_with_a_missing_host():
    """Gate 38.10 must not be satisfiable by one host.

    The comparison harness returns 'cannot compare' rather than 'agree' when a host has no runs.
    An empty comparison silently reporting agreement would be the fail-open pattern this codebase
    keeps finding in itself.
    """
    sys.path.insert(0, str(REPO / "benchmark"))
    from compare_hosts import compare

    diffs, notes = compare(REPO / "benchmark" / "expected" / "claude-code",
                           REPO / "benchmark" / "expected" / "codex")
    if not (REPO / "benchmark" / "expected" / "codex").is_dir():
        assert notes, "a missing host must produce a note, not silent agreement"
        assert not diffs, "with a host absent there is nothing to differ ON — that is not agreement"


def test_the_claude_code_conformance_artifacts_are_present_and_honest():
    """The conformance claim in the README must be backed by committed artifacts.

    A README asserting 'Claude Code has completed the benchmark' with nothing on disk is precisely
    the docs-outrun-code failure this suite exists to catch.
    """
    import json

    root = REPO / "benchmark" / "expected" / "claude-code"
    assert (root / "README.md").is_file(), "the conformance run must document itself"

    results = {}
    for run in sorted(p for p in root.iterdir() if p.is_dir()):
        path = run / "validation" / "validation-result.json"
        assert path.is_file(), f"{run.name} has no validation result"
        data = json.loads(path.read_text(encoding="utf-8"))
        statuses = [c["status"] for c in data["checks"]]
        # Zero not_evaluated is the interesting property: every gate had what it needed to decide.
        assert "not_evaluated" not in statuses, \
            f"{run.name} left checks unevaluated, so it did not really complete"
        results[run.name] = data["report_eligible"]

    assert len(results) >= 2, "both the blocked and the published run must be committed"
    assert True in results.values(), "a run that reached publication must be evidenced"
    assert False in results.values(), \
        "the correctly-blocked run must be kept too — a benchmark that only shows successes is a " \
        "demo, not evidence"


def test_the_committed_conformance_runs_no_longer_earn_confirmed_independent():
    """GOAL.md G5. The rule is applied to our own evidence, not only to future runs.

    Both committed runs declare `confirmed_independent` and attest no reviewer context, because
    attestation did not exist when they ran. Under `check_independence_attested` that is
    `not_evaluated`, which blocks — so those runs would not pass today's validator on this check.

    They are recorded as downgraded rather than grandfathered. A `workflow_version` exemption for
    "runs made before the rule" is how a gate becomes decorative, and this repository already
    carries three write-ups of that pattern (docs/lessons-carried-forward.md).

    This test fails the moment someone attests those contexts or re-runs the benchmark — which is
    the correct time to revisit both the README and the release checklist.
    """
    import json

    root = REPO / "benchmark" / "expected" / "claude-code"
    downgraded = []
    for run in sorted(p for p in root.iterdir() if p.is_dir()):
        review = json.loads((run / "reviews" / "independent_review.json")
                            .read_text(encoding="utf-8"))
        status = (review.get("review_independence") or {}).get("status")
        attested = list((run / "review-contexts").glob("*.json")) \
            if (run / "review-contexts").is_dir() else []
        if status == "confirmed_independent" and not attested:
            downgraded.append(run.name)

    assert downgraded, "if the runs are now attested, update the README and release checklist"
    text = " ".join((root / "README.md").read_text(encoding="utf-8").split()).lower()
    assert "downgrad" in text, \
        "the conformance README must record that these runs no longer earn confirmed_independent"
