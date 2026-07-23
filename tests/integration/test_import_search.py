from __future__ import annotations

from pathlib import Path

import yaml
from PIL import Image
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from research.indexing import build_index, search_index
from research.ingestion import import_sources
from research.io import iter_json


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

    first_index = build_index(workspace)
    second_index = build_index(workspace)
    assert first_index["logical_index_hash"] == second_index["logical_index_hash"]
    result = search_index(workspace, "data movement")
    assert result["results"]
    assert result["results"][0]["locator"]["span_sha256"].startswith("sha256:")
    assert result["results"][0]["rank"] == 1


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
