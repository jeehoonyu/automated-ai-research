"""Documentation integrity.

Docs drift ahead of code — that is the failure recorded in docs/lessons-carried-forward.md §4, where
a predecessor's append-only ledger asserted a determinism result no code had ever computed, and then
seeded the next research cycle with it.

These tests do not check prose quality. They check the two things that are mechanically checkable and
that actually bite: that a document the docs point at exists, and that a capability the docs claim is
present in code.
"""

from __future__ import annotations

import re
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
    """One source of truth. A drifted copy is worse than no copy — a host would read the stale one."""
    repo_copy = (REPO / "workflow" / "canonical-workflow.md").read_text(encoding="utf-8")
    shipped = (REPO / "src" / "research" / "assets" /
               "canonical-workflow.md").read_text(encoding="utf-8")
    assert repo_copy == shipped, \
        "workflow/canonical-workflow.md and the packaged copy have diverged; re-copy it"


def test_the_release_checklist_states_the_unmet_gate():
    """Spec §37 is not demonstrated. The checklist must say so rather than quietly omit it."""
    text = (REPO / "docs" / "release-checklist.md").read_text(encoding="utf-8")
    assert "NOT MET" in text
    assert "38.10" in text and "Cross-host" in text


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
    assert "neither host has been run" in text
