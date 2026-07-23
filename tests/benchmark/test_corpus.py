from __future__ import annotations

import json
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


def test_checked_in_pdf_benchmark_contract(workspace: Path) -> None:
    benchmark = Path(__file__).resolve().parents[2] / "benchmark"
    contract = json.loads(
        (benchmark / "expected" / "fixture-contract.json").read_text(encoding="utf-8")
    )
    imported = import_sources(workspace, [benchmark / "fixtures"])
    assert imported["imported_count"] == 2
    assert imported["failed_count"] == 0

    documents = {
        str(item["metadata"]["original_filename"]): item
        for item in iter_json(workspace / "documents" / "manifests")
    }
    versions = {
        str(item["document_id"]): item for item in iter_json(workspace / "documents" / "versions")
    }
    for expected in contract["fixtures"]:
        filename = Path(expected["path"]).name
        document = documents[filename]
        assert document["source_sha256"] == expected["source_sha256"]
        version = versions[document["document_id"]]
        assert len(version["pages"]) == expected["page_count"]
        assert all((workspace / page["render"]["path"]).is_file() for page in version["pages"])
        assert all(page["render"]["sha256"].startswith("sha256:") for page in version["pages"])
        if "ocr_required_pages" in expected:
            assert version["metadata"]["ocr_required_pages"] == expected["ocr_required_pages"]
            region_contract = expected["visual_region"]
            page = version["pages"][region_contract["page"] - 1]
            assert any(
                region.get("coordinate_system") == region_contract["coordinate_system"]
                and region_contract["caption_contains"] in str(region.get("caption"))
                for region in page["visual_regions"]
            )
        if "table_pages" in expected:
            for page_number in expected["table_pages"]:
                page = version["pages"][page_number - 1]
                assert page["table_detection_status"] == "extracted"
                assert page["tables"]


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
