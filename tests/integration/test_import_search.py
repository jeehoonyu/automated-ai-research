from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from PIL import Image
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from research.errors import ResearchError
from research.indexing import build_index, search_index
from research.ingestion import import_sources
from research.inspection import inspect_artifact
from research.io import iter_json
from research.runs import create_run
from research.validation import validate_run


def test_markdown_import_duplicate_index_and_search(workspace: Path, tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    source.write_text(
        "# Result\n\nThe partitioned cache reduced data movement by 18 percent.\n",
        encoding="utf-8",
    )
    first = import_sources(workspace, [source])
    second = import_sources(workspace, [source])
    assert first["imported_count"] == 1
    assert first["failed_count"] == 0
    assert second["duplicate_count"] == 1
    assert first["documents"][0]["document_id"] == second["documents"][0]["document_id"]

    with pytest.raises(ResearchError) as missing_index:
        create_run(workspace, "Should a stale corpus be frozen?", "default")
    assert missing_index.value.category == "index_not_found"

    first_index = build_index(workspace)
    second_index = build_index(workspace)
    assert first_index["logical_index_hash"] == second_index["logical_index_hash"]
    result = search_index(workspace, "data movement")
    assert result["results"]
    assert result["results"][0]["locator"]["span_sha256"].startswith("sha256:")
    assert result["results"][0]["rank"] == 1

    database = workspace / "indexes" / "research.sqlite3"
    database.write_bytes(database.read_bytes() + b"tampered")
    with pytest.raises(ResearchError) as error:
        search_index(workspace, "data movement")
    assert error.value.category == "index_hash_mismatch"


def test_chunking_change_rechunks_without_changing_document_version(
    workspace: Path, tmp_path: Path
) -> None:
    source = tmp_path / "long.md"
    source.write_text("# Section\n\n" + ("evidence text " * 200), encoding="utf-8")
    first = import_sources(workspace, [source])
    first_version = first["documents"][0]["document_version_id"]
    config_path = workspace / "research.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["chunking"]["max_characters"] = 200
    config["chunking"]["overlap_characters"] = 20
    config_path.write_text(yaml.safe_dump(config, sort_keys=True), encoding="utf-8")

    second = import_sources(workspace, [source])
    outcome = second["documents"][0]
    assert outcome["duplicate"] is True
    assert outcome["processing_action"] == "rechunked"
    assert outcome["document_version_id"] == first_version
    assert outcome["chunk_count"] > first["documents"][0]["chunk_count"]


def test_run_scoped_search_rejects_a_rebuilt_different_index(
    workspace: Path, tmp_path: Path
) -> None:
    first_source = tmp_path / "first.md"
    first_source.write_text("# First\n\nFrozen retrieval evidence.\n", encoding="utf-8")
    import_sources(workspace, [first_source])
    build_index(workspace)
    run = create_run(workspace, "What was frozen?", "default")

    second_source = tmp_path / "second.md"
    second_source.write_text("# Second\n\nNew retrieval evidence.\n", encoding="utf-8")
    import_sources(workspace, [second_source])
    build_index(workspace)
    with pytest.raises(ResearchError) as error:
        search_index(workspace, "evidence", run_id=run["run_id"])
    assert error.value.category == "index_snapshot_mismatch"


def test_equal_bm25_scores_use_document_id_tie_breaking(workspace: Path, tmp_path: Path) -> None:
    first = tmp_path / "first.md"
    second = tmp_path / "second.md"
    first.write_text("# A\n\nsharedterm neutral words here.\n", encoding="utf-8")
    second.write_text("# B\n\nsharedterm neutral words here.\n", encoding="utf-8")
    imported = import_sources(workspace, [first, second])
    assert imported["imported_count"] == 2
    build_index(workspace)
    result = search_index(workspace, "sharedterm")
    assert len(result["results"]) == 2
    assert result["results"][0]["native_bm25_score"] == result["results"][1]["native_bm25_score"]
    document_ids = [item["document_id"] for item in result["results"]]
    assert document_ids == sorted(document_ids)
    filtered = search_index(workspace, "sharedterm", document_id=document_ids[1])
    assert [item["document_id"] for item in filtered["results"]] == [document_ids[1]]

    secret_query = "token=sharedterm"
    search_index(workspace, secret_query)
    event = json.loads(
        (workspace / "logs" / "search-events.jsonl").read_text(encoding="utf-8").splitlines()[-1]
    )
    assert secret_query not in event["query"]
    assert "[REDACTED]" in event["query"]
    assert event["query_sha256"].startswith("sha256:")


def test_pdf_rendering_visual_candidates_and_ocr_flag(workspace: Path, tmp_path: Path) -> None:
    pdf_path = tmp_path / "visual.pdf"
    image_path = tmp_path / "scan.png"
    Image.new("RGB", (300, 200), "white").save(image_path)
    pdf = canvas.Canvas(str(pdf_path))
    pdf.drawString(
        72, 750, "Synthetic study with enough extracted text for reliable page processing."
    )
    pdf.drawString(72, 730, "Figure 1. Vector comparison of methods")
    pdf.rect(100, 400, 300, 200)
    pdf.line(100, 400, 400, 600)
    pdf.showPage()
    pdf.drawImage(ImageReader(str(image_path)), 100, 400, width=300, height=200)
    pdf.showPage()
    pdf.save()

    result = import_sources(workspace, [pdf_path])
    assert result["imported_count"] == 1
    version = next(
        item
        for item in iter_json(workspace / "documents" / "versions")
        if item.get("schema_name") == "DocumentVersion"
    )
    assert len(version["pages"]) == 2
    assert all((workspace / page["render"]["path"]).is_file() for page in version["pages"])
    assert version["pages"][1]["ocr_required"] is True
    assert version["pages"][0]["visual_regions"]
    assert any(item.get("caption") for item in version["pages"][0]["visual_regions"])
    render_lookup = inspect_artifact(workspace, version["pages"][0]["render"]["sha256"])
    assert render_lookup["context"]["selected_page"]["page"] == 1
    region_id = version["pages"][0]["visual_regions"][0]["region_id"]
    region_lookup = inspect_artifact(
        workspace, f"{version['document_version_id']}/region/{region_id}"
    )
    assert region_lookup["context"]["selected_visual_region"]["region_id"] == region_id

    build_index(workspace)
    run = create_run(workspace, "Does every page render retain integrity?", "default")
    render_path = workspace / version["pages"][0]["render"]["path"]
    render_path.write_bytes(render_path.read_bytes() + b"tampered")
    validation, _ = validate_run(workspace, run["run_id"])
    assert any(
        item["code"] == "page_render_hash_mismatch" for item in validation["blocking_errors"]
    )


def test_markdown_and_pdf_tables_preserve_reproducible_artifacts(
    workspace: Path, tmp_path: Path
) -> None:
    markdown = tmp_path / "table.md"
    markdown.write_text(
        "# Measurements\n\n| Method | Value |\n| --- | ---: |\n| A | 18 |\n\n"
        "```python\nprint('preserved, never executed')\n```\n\n"
        "[external metadata only](https://example.invalid/source)\n",
        encoding="utf-8",
    )
    pdf_path = tmp_path / "table.pdf"
    pdf = canvas.Canvas(str(pdf_path))
    for x in (72, 220, 360):
        pdf.line(x, 640, x, 730)
    for y in (640, 685, 730):
        pdf.line(72, y, 360, y)
    pdf.drawString(82, 700, "Method")
    pdf.drawString(230, 700, "Value")
    pdf.drawString(82, 655, "A")
    pdf.drawString(230, 655, "18 percent reduction")
    pdf.save()

    imported = import_sources(workspace, [markdown, pdf_path])
    assert imported["failed_count"] == 0
    versions = list(iter_json(workspace / "documents" / "versions"))
    markdown_version = next(item for item in versions if item["metadata"].get("source_line_count"))
    normalized_markdown = (workspace / markdown_version["normalized_path"]).read_text(
        encoding="utf-8"
    )
    assert "| Method | Value |" in normalized_markdown
    assert "print('preserved, never executed')" in normalized_markdown
    assert markdown_version["metadata"]["link_destinations"] == ["https://example.invalid/source"]

    pdf_version = next(item for item in versions if item["metadata"].get("page_count") == 1)
    page = pdf_version["pages"][0]
    assert page["table_detection_status"] == "extracted"
    assert page["tables"]
    table_path = workspace / page["tables"][0]["path"]
    assert table_path.is_file()
    assert page["tables"][0]["sha256"].startswith("sha256:")


def test_multi_column_pdf_preserves_page_aware_text(workspace: Path, tmp_path: Path) -> None:
    pdf_path = tmp_path / "columns.pdf"
    pdf = canvas.Canvas(str(pdf_path))
    pdf.drawString(72, 750, "Left column experimental setup.")
    pdf.drawString(330, 750, "Right column measured outcome.")
    pdf.drawString(72, 730, "Left continuation sample count.")
    pdf.drawString(330, 730, "Right continuation limitation.")
    pdf.save()

    imported = import_sources(workspace, [pdf_path])
    assert imported["failed_count"] == 0
    version = next(iter_json(workspace / "documents" / "versions"))
    normalized = (workspace / version["normalized_path"]).read_text(encoding="utf-8")
    assert "Left column experimental setup" in normalized
    assert "Right column measured outcome" in normalized
    assert version["pages"][0]["page"] == 1


def test_active_extraction_configuration_selects_matching_version_after_rollback(
    workspace: Path, tmp_path: Path
) -> None:
    pdf_path = tmp_path / "versioned.pdf"
    pdf = canvas.Canvas(str(pdf_path))
    pdf.drawString(72, 750, "Enough stable text to create a searchable deterministic PDF chunk.")
    pdf.showPage()
    pdf.save()

    first = import_sources(workspace, [pdf_path])["documents"][0]
    config_path = workspace / "research.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["pdf"]["render_dpi"] = 96
    config_path.write_text(yaml.safe_dump(config, sort_keys=True), encoding="utf-8")
    second = import_sources(workspace, [pdf_path])["documents"][0]
    assert second["document_version_id"] != first["document_version_id"]

    config["pdf"]["render_dpi"] = 150
    config_path.write_text(yaml.safe_dump(config, sort_keys=True), encoding="utf-8")
    third = import_sources(workspace, [pdf_path])["documents"][0]
    assert third["document_version_id"] == first["document_version_id"]

    build_index(workspace)
    run = create_run(workspace, "Which extraction version is frozen?", "default")
    snapshot = run["run_path"]
    manifest = next(
        item
        for item in iter_json(Path(snapshot) / "manifest.json")
        if item.get("schema_name") == "RunManifest"
    )
    assert manifest["source_snapshot"][0]["document_version_id"] == first["document_version_id"]
