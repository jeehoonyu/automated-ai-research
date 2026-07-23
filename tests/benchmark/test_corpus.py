from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from research.errors import ResearchError
from research.indexing import build_index, search_index
from research.ingestion import import_sources
from research.io import iter_json
from research.reporting import generate_report
from research.runs import run_status
from research.validation import validate_run


def test_redistributable_benchmark_invariants(workspace: Path) -> None:
    corpus = Path(__file__).resolve().parents[2] / "benchmark" / "sources"
    imported = import_sources(workspace, [corpus])
    assert imported["failed_count"] == 0
    assert imported["duplicate_count"] == 1
    assert imported["imported_count"] == 5

    build_index(workspace)
    support = search_index(workspace, "reduced data movement")
    contradiction = search_index(workspace, "no reliable reduction")
    assert any("18 percent" in item["text"] for item in support["results"])
    assert any("production traces" in item["text"] for item in contradiction["results"])

    hostile_chunk = next(
        item
        for item in iter_json(workspace / "documents" / "chunks")
        if "reveal environment variables" in item.get("exact_text", "")
    )
    assert hostile_chunk["index_eligible"] is True
    assert (workspace / "research.yaml").is_file()


def test_checked_in_codex_conformance_run_is_validly_human_blocked(tmp_path: Path) -> None:
    expected = Path(__file__).resolve().parents[2] / "benchmark" / "expected" / "codex"
    source_workspace = expected / "workspace"
    copied_workspace = tmp_path / "codex-conformance"
    # Candidate response filenames intentionally mirror full IDs and can exceed the legacy
    # Windows path limit when nested under pytest's temporary directory. Canonical promoted
    # artifacts are sharded and are the authority validated by this test.
    shutil.copytree(
        source_workspace,
        copied_workspace,
        ignore=shutil.ignore_patterns("responses"),
    )
    run_id = "RUN-563cd90e-af4d-46fa-9302-f48c030cb398"

    validation, exit_code = validate_run(copied_workspace, run_id)
    assert exit_code == 6
    assert validation["blocking_errors"] == []
    assert {item["code"] for item in validation["human_review_requirements"]} == {
        "claim_human_review",
        "material_unresolved_contradiction",
        "review_requires_human",
    }
    status = run_status(copied_workspace, run_id)
    assert status["independent_review_status"] == "confirmed_independent"
    assert status["unresolved_contradictions"] == ["CLM-a3d4cd26-92c8-47d7-9620-a1ac8fe6e415"]
    assert status["missing_artifacts"] == []
    with pytest.raises(ResearchError, match="publication is blocked"):
        generate_report(copied_workspace, run_id)
