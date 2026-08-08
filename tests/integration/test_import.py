"""Phase 2 integration tests: import, extraction, deduplication, and honest statuses.

These exercise the release gates in spec §38.1 (import determinism) and §38.2 (extraction
integrity).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fixtures.make_fixtures import build  # noqa: E402

from research.artifacts.io import read_artifact  # noqa: E402
from research.config import load_workspace  # noqa: E402
from research.extraction.status import ExtractionStatus, worst  # noqa: E402
from research.importers.importer import import_paths  # noqa: E402
from research.workspace import init_workspace  # noqa: E402


@pytest.fixture
def ws(tmp_path: Path):
    init_workspace(tmp_path / "ws")
    return load_workspace(tmp_path / "ws")


@pytest.fixture
def sources(tmp_path: Path) -> dict[str, Path]:
    return build(tmp_path / "sources")


# --------------------------------------------------------------- 38.1 import determinism


def test_same_bytes_produce_the_same_document_id(ws, sources, tmp_path: Path):
    a = import_paths(ws, [sources["markdown"]])
    init_workspace(tmp_path / "ws2")
    ws2 = load_workspace(tmp_path / "ws2")
    b = import_paths(ws2, [sources["markdown"]])
    assert a["document_ids"] == b["document_ids"]


def test_reimporting_the_same_file_is_a_duplicate_not_a_new_document(ws, sources):
    import_paths(ws, [sources["markdown"]])
    second = import_paths(ws, [sources["markdown"]])
    assert second["imported_count"] == 0
    assert second["duplicate_count"] == 1


def test_identical_bytes_under_a_different_name_share_identity_and_keep_the_alias(ws, sources):
    """The same paper saved twice is ONE document with two aliases — not two independent sources."""
    first = import_paths(ws, [sources["markdown"]])
    second = import_paths(ws, [sources["duplicate_md"]])
    assert second["duplicate_count"] == 1
    manifest = read_artifact(first["manifest_paths"][0], expect_schema="Document")
    assert sorted(manifest["original_filename_aliases"]) == ["notes-copy.md", "notes.md"]


def test_document_id_does_not_depend_on_the_filename(ws, sources, tmp_path: Path):
    renamed = tmp_path / "sources" / "totally-different-name.md"
    renamed.write_bytes(sources["markdown"].read_bytes())
    a = import_paths(ws, [sources["markdown"]])["document_ids"]
    ws2root = tmp_path / "ws3"
    init_workspace(ws2root)
    b = import_paths(load_workspace(ws2root), [renamed])["document_ids"]
    assert a == b


def test_originals_are_stored_content_addressed_and_unmodified(ws, sources):
    out = import_paths(ws, [sources["markdown"]])
    manifest = read_artifact(out["manifest_paths"][0], expect_schema="Document")
    stored = ws.root / manifest["stored_original"]
    assert stored.is_file()
    assert stored.read_bytes() == sources["markdown"].read_bytes()


def test_import_events_are_append_only(ws, sources):
    import_paths(ws, [sources["markdown"]])
    import_paths(ws, [sources["markdown"]])
    log = ws.root / "imports" / "import-events.jsonl"
    lines = log.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[1])["duplicate"] is True


# --------------------------------------------------------------- 38.2 extraction integrity


def test_pdf_pages_are_extracted_and_every_page_is_rendered(ws, sources):
    out = import_paths(ws, [sources["text_pdf"]])
    manifest = read_artifact(out["manifest_paths"][0], expect_schema="Document")
    assert manifest["page_count"] == 2
    assert manifest["rendered_page_count"] == 2
    for page in manifest["pages"]:
        assert page["render"] is not None, "every PDF page must have a render (spec 38.2)"
        assert page["render"]["sha256"].startswith("sha256:")
        assert (ws.root / page["render"]["path"]).is_file()
        assert page["render"]["width"] > 0 and page["render"]["height"] > 0


def test_low_text_page_is_flagged_ocr_required_not_silently_empty(ws, sources):
    """'We found nothing' and 'there is nothing to find' must not be the same value."""
    out = import_paths(ws, [sources["low_text_pdf"]])
    manifest = read_artifact(out["manifest_paths"][0], expect_schema="Document")
    statuses = [p["extraction_status"] for p in manifest["pages"]]
    assert ExtractionStatus.OCR_REQUIRED in statuses
    assert manifest["ocr_required_pages"], "the page number must be recorded"
    # a document with an unreadable page is NOT wholly extracted
    assert manifest["extraction_status"] != ExtractionStatus.EXTRACTED


def test_ocr_required_content_is_not_usable_as_evidence():
    assert ExtractionStatus.OCR_REQUIRED.is_usable_as_evidence is False
    assert ExtractionStatus.OCR_REQUIRED.needs_human_review is True
    assert ExtractionStatus.EXTRACTED.is_usable_as_evidence is True


def test_worst_status_wins_when_rolling_pages_up():
    assert worst([ExtractionStatus.EXTRACTED] * 5) is ExtractionStatus.EXTRACTED
    mixed = [ExtractionStatus.EXTRACTED, ExtractionStatus.OCR_REQUIRED]
    assert worst(mixed) is ExtractionStatus.PARTIALLY_EXTRACTED
    assert worst([]) is ExtractionStatus.PROCESSING_FAILED


def test_malformed_pdf_reports_failure_but_preserves_the_original(ws, sources):
    out = import_paths(ws, [sources["malformed_pdf"]])
    doc = out["documents"][0]
    assert doc["extraction_status"] in {
        ExtractionStatus.PROCESSING_FAILED, ExtractionStatus.UNSUPPORTED_FORMAT}
    # the bytes are still preserved even though nothing could be read from them
    stored = list((ws.root / "originals" / "sha256").rglob("*"))
    assert any(p.is_file() for p in stored)


def test_import_does_not_claim_success_for_an_unsupported_file(ws, sources):
    out = import_paths(ws, [sources["unsupported"]])
    assert out["imported_count"] == 0
    assert out["failed_count"] == 1


def test_tables_and_figures_are_not_claimed_as_extracted(ws, sources):
    """Detection is not implemented; reporting `extracted` would be a false claim (spec 17)."""
    out = import_paths(ws, [sources["text_pdf"]])
    manifest = read_artifact(out["manifest_paths"][0], expect_schema="Document")
    assert manifest["tables_status"] == "not_detected"
    assert manifest["figures_status"] == "not_detected"


# --------------------------------------------------------------- markdown


def test_markdown_sections_and_line_ranges(ws, sources):
    out = import_paths(ws, [sources["markdown"]])
    manifest = read_artifact(out["manifest_paths"][0], expect_schema="Document")
    titles = [s["title"] for s in manifest["sections"]]
    assert "Retrieval accuracy" in titles and "Method" in titles and "Limitations" in titles
    method = next(s for s in manifest["sections"] if s["title"] == "Method")
    assert method["line_start"] >= 1 and method["line_end"] >= method["line_start"]
    assert method["path"] == ["Retrieval accuracy", "Method"]


def test_headings_inside_code_blocks_are_not_parsed_as_structure(ws, sources):
    out = import_paths(ws, [sources["markdown"]])
    manifest = read_artifact(out["manifest_paths"][0], expect_schema="Document")
    assert "not a heading" not in [s["title"] for s in manifest["sections"]]


def test_markdown_links_are_recorded_but_never_followed(ws, sources):
    out = import_paths(ws, [sources["markdown"]])
    manifest = read_artifact(out["manifest_paths"][0], expect_schema="Document")
    assert manifest["links_followed"] is False
    assert any("example.invalid" in link["destination"] for link in manifest["links"])


def test_markdown_tables_are_preserved(ws, sources):
    out = import_paths(ws, [sources["markdown"]])
    manifest = read_artifact(out["manifest_paths"][0], expect_schema="Document")
    assert manifest["table_row_lines"] >= 3


# --------------------------------------------------------------- untrusted content


def test_prompt_injection_is_stored_as_inert_data(ws, sources):
    """Injected text must survive as content, and must not alter any recorded field."""
    out = import_paths(ws, [sources["injection_md"]])
    manifest = read_artifact(out["manifest_paths"][0], expect_schema="Document")
    body = (ws.root / manifest["normalized_text_path"]).read_text(encoding="utf-8")
    assert "IGNORE ALL PREVIOUS INSTRUCTIONS" in body, "content must be preserved verbatim"
    assert manifest["links_followed"] is False
    assert manifest["extraction_status"] == ExtractionStatus.EXTRACTED
    assert manifest["created_by"]["actor_type"] == "cli"


def test_a_lossy_utf8_decode_is_not_reported_as_a_clean_extraction(ws, tmp_path: Path):
    """Undecodable bytes were replaced with U+FFFD and the document stamped `extracted`.

    `extracted` is the one status that means "usable as evidence". The warning beside it said in
    plain words that quoted text may differ from the original bytes — but nothing in validation
    reads `extraction_warnings`, so a document whose citations quote replacement characters was
    exactly as trustworthy as any other. A warning is not a gate.
    """
    source = tmp_path / "latin1.md"
    source.write_bytes("# Notes\n\nMeasured at 41\xb0C in the caf\xe9.\n".encode("latin-1"))

    out = import_paths(ws, [source])
    manifest = read_artifact(out["manifest_paths"][0], expect_schema="Document")

    assert manifest["extraction_status"] == ExtractionStatus.PARTIALLY_EXTRACTED
    assert ExtractionStatus(manifest["extraction_status"]).needs_human_review
    assert any("not valid UTF-8" in w for w in manifest["extraction_warnings"])
    # The content is still preserved and still importable — the status is the disclosure, not a
    # refusal. Refusing would lose the document; mislabelling it would lose the doubt.
    body = (ws.root / manifest["normalized_text_path"]).read_text(encoding="utf-8")
    assert "�" in body


def test_symlinked_source_is_rejected(ws, sources, tmp_path: Path):
    link = tmp_path / "sources" / "link.md"
    try:
        link.symlink_to(sources["markdown"])
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation requires privileges on this platform")
    out = import_paths(ws, [link])
    assert out["failed_count"] == 1
    assert "symlink" in (out["documents"][0]["error"] or "").lower()


# --------------------------------------------------------------- artifact integrity


def test_manifest_hash_verifies_and_detects_tampering(ws, sources, tmp_path: Path):
    out = import_paths(ws, [sources["markdown"]])
    path = Path(out["manifest_paths"][0])
    read_artifact(path, expect_schema="Document")   # passes

    artifact = json.loads(path.read_text(encoding="utf-8"))
    artifact["page_count"] = 9999
    path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    from research.errors import SchemaValidationError
    with pytest.raises(SchemaValidationError):
        read_artifact(path, expect_schema="Document")


def test_mixed_import_reports_each_outcome_separately(ws, sources):
    out = import_paths(ws, [sources["markdown"], sources["unsupported"], sources["low_text_pdf"]])
    assert out["imported_count"] == 2
    assert out["failed_count"] == 1
    assert out["needs_human_review_count"] >= 1
