"""Phase 3: normalization, chunking, and locator resolution.

The property under test throughout: a locator built today must resolve to the same characters later,
and must FAIL LOUDLY rather than return different characters if anything moved.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fixtures.make_fixtures import build  # noqa: E402

from research.artifacts.io import read_artifact  # noqa: E402
from research.artifacts.locators import (  # noqa: E402
    Resolution,
    make_text_locator,
    make_visual_locator,
    resolve_text_locator,
    resolve_visual_locator,
    validate_bounding_box,
)
from research.config import load_workspace  # noqa: E402
from research.extraction.chunking import chunk_document  # noqa: E402
from research.extraction.normalize import (  # noqa: E402
    normalize_text,
)
from research.importers.importer import import_paths  # noqa: E402
from research.workspace import init_workspace  # noqa: E402


@pytest.fixture
def ws(tmp_path: Path):
    init_workspace(tmp_path / "ws")
    return load_workspace(tmp_path / "ws")


@pytest.fixture
def sources(tmp_path: Path) -> dict[str, Path]:
    return build(tmp_path / "sources")


def _chunks(ws, out) -> dict:
    manifest = read_artifact(out["manifest_paths"][0], expect_schema="Document")
    return read_artifact(ws.root / manifest["chunk_set_path"], expect_schema="ChunkSet")


# --------------------------------------------------------------- normalization


def test_normalization_is_idempotent():
    text = "a\r\nb  \r\nć\n"
    once = normalize_text(text)
    assert normalize_text(once) == once


def test_normalization_unifies_line_endings_and_composes_unicode():
    assert "\r" not in normalize_text("a\r\nb\rc")
    # NFC composes e + combining acute into a single code point, so offsets are stable
    assert len(normalize_text("é")) == 1


def test_normalized_text_is_written_and_hashed(ws, sources):
    out = import_paths(ws, [sources["text_pdf"]])
    manifest = read_artifact(out["manifest_paths"][0], expect_schema="Document")
    path = ws.root / manifest["normalized_text_path"]
    assert path.is_file()
    from research.hashing import sha256_text
    assert sha256_text(path.read_text(encoding="utf-8")) == manifest["normalized_text_sha256"]


def test_manifest_records_what_normalization_did_not_do(ws, sources):
    """A reviewer comparing a quote to the original PDF must know what was left alone."""
    out = import_paths(ws, [sources["text_pdf"]])
    manifest = read_artifact(out["manifest_paths"][0], expect_schema="Document")
    joined = " ".join(manifest["normalization_not_performed"]).lower()
    assert "de-hyphenation" in joined and "ocr" in joined


def test_page_map_covers_every_page_without_overlap(ws, sources):
    out = import_paths(ws, [sources["text_pdf"]])
    manifest = read_artifact(out["manifest_paths"][0], expect_schema="Document")
    spans = sorted(manifest["page_map"], key=lambda s: s["start_offset"])
    assert [s["page_number"] for s in spans] == [1, 2]
    for a, b in zip(spans, spans[1:], strict=False):
        assert a["end_offset"] <= b["start_offset"], "page spans must not overlap"


# --------------------------------------------------------------- chunking


def test_chunks_are_produced_and_reference_their_document(ws, sources):
    out = import_paths(ws, [sources["text_pdf"]])
    cs = _chunks(ws, out)
    assert cs["chunk_count"] > 0
    for chunk in cs["chunks"]:
        assert chunk["document_version_id"] == cs["document_version_id"]
        assert chunk["chunk_id"].startswith("CHK-sha256-")


def test_chunk_offsets_slice_back_to_the_exact_chunk_text(ws, sources):
    """The whole retrieval-to-citation chain depends on this."""
    out = import_paths(ws, [sources["text_pdf"]])
    manifest = read_artifact(out["manifest_paths"][0], expect_schema="Document")
    text = (ws.root / manifest["normalized_text_path"]).read_text(encoding="utf-8")
    for chunk in _chunks(ws, out)["chunks"]:
        assert text[chunk["start_offset"]:chunk["end_offset"]] == chunk["text"]


def test_chunks_never_straddle_a_page_boundary(ws, sources):
    """A chunk with two page numbers makes every citation from it ambiguous."""
    out = import_paths(ws, [sources["text_pdf"]])
    manifest = read_artifact(out["manifest_paths"][0], expect_schema="Document")
    spans = {s["page_number"]: s for s in manifest["page_map"]}
    for chunk in _chunks(ws, out)["chunks"]:
        page = spans[chunk["page"]]
        assert chunk["start_offset"] >= page["start_offset"]
        assert chunk["end_offset"] <= page["end_offset"]


def test_chunk_ids_are_deterministic_across_workspaces(ws, sources, tmp_path: Path):
    a = _chunks(ws, import_paths(ws, [sources["text_pdf"]]))
    init_workspace(tmp_path / "ws2")
    ws2 = load_workspace(tmp_path / "ws2")
    b = _chunks(ws2, import_paths(ws2, [sources["text_pdf"]]))
    assert [c["chunk_id"] for c in a["chunks"]] == [c["chunk_id"] for c in b["chunks"]]


def test_ocr_required_pages_produce_chunks_that_are_not_index_eligible(ws, sources):
    """Retained for inspection, excluded from search: a claim must not cite unreadable text."""
    out = import_paths(ws, [sources["low_text_pdf"]])
    cs = _chunks(ws, out)
    ineligible = [c for c in cs["chunks"] if not c["index_eligible"]]
    assert ineligible, "the low-text page should yield a non-eligible chunk"
    for chunk in ineligible:
        assert chunk["extraction_status"] == "ocr_required"
        assert any("index-eligible" in w.lower() for w in chunk["warnings"])
    assert cs["index_eligible_count"] < cs["chunk_count"]


def test_markdown_chunks_carry_line_ranges_not_pages(ws, sources):
    out = import_paths(ws, [sources["markdown"]])
    for chunk in _chunks(ws, out)["chunks"]:
        assert chunk["page"] is None
        assert chunk["line_start"] is not None and chunk["line_start"] >= 1
        assert chunk["line_end"] >= chunk["line_start"]


def test_markdown_chunks_carry_section_paths(ws, sources):
    out = import_paths(ws, [sources["markdown"]])
    paths = [tuple(c["section_path"]) for c in _chunks(ws, out)["chunks"]]
    assert any("Retrieval accuracy" in p for p in paths if p)


def test_smaller_target_produces_more_chunks(ws, sources):
    """Chunking responds to configuration, and the config is recorded in the artifact."""
    out = import_paths(ws, [sources["text_pdf"]])
    manifest = read_artifact(out["manifest_paths"][0], expect_schema="Document")
    from research.extraction.normalize import normalize_markdown
    text = (ws.root / manifest["normalized_text_path"]).read_text(encoding="utf-8")
    doc = normalize_markdown(text, [])
    big = chunk_document(doc, document_id="DOC-x", document_version_id="DVER-x",
                         config={"target_chars": 4000, "overlap_chars": 0})
    small = chunk_document(doc, document_id="DOC-x", document_version_id="DVER-x",
                           config={"target_chars": 200, "overlap_chars": 0})
    assert len(small) > len(big)


def test_chunks_cover_the_page_text_without_gaps(ws, sources):
    out = import_paths(ws, [sources["text_pdf"]])
    by_page: dict[int, list[dict]] = {}
    for chunk in _chunks(ws, out)["chunks"]:
        by_page.setdefault(chunk["page"], []).append(chunk)
    for chunks in by_page.values():
        chunks.sort(key=lambda c: c["start_offset"])
        for a, b in zip(chunks, chunks[1:], strict=False):
            assert b["start_offset"] == a["end_offset"], "chunks must tile their page contiguously"


# --------------------------------------------------------------- text locators


def test_text_locator_round_trips(ws, sources):
    out = import_paths(ws, [sources["text_pdf"]])
    manifest = read_artifact(out["manifest_paths"][0], expect_schema="Document")
    text = (ws.root / manifest["normalized_text_path"]).read_text(encoding="utf-8")
    chunk = _chunks(ws, out)["chunks"][0]
    start = chunk["start_offset"] + 5
    end = start + 40
    loc = make_text_locator(normalized_text=text, start_offset=start, end_offset=end,
                            page=chunk["page"], chunk_id=chunk["chunk_id"])
    result = resolve_text_locator(loc, text)
    assert result.ok
    assert result.text == text[start:end]


def test_locator_detects_text_that_moved_under_it():
    """The failure the span hash exists to catch: same offsets, different words."""
    original = "The measured reduction was 41 percent on the benchmark suite."
    loc = make_text_locator(normalized_text=original, start_offset=4, end_offset=30)
    edited = "The measured reduction was 94 percent on the benchmark suite."
    result = resolve_text_locator(loc, edited)
    assert result.status is Resolution.SPAN_MISMATCH
    assert "different words" in result.detail


def test_locator_detects_offsets_that_no_longer_exist():
    loc = make_text_locator(normalized_text="a" * 100, start_offset=50, end_offset=90)
    result = resolve_text_locator(loc, "a" * 20)
    assert result.status is Resolution.OUT_OF_RANGE
    assert not result.ok


def test_locator_rejects_an_impossible_span():
    with pytest.raises(ValueError):
        make_text_locator(normalized_text="short", start_offset=0, end_offset=999)
    with pytest.raises(ValueError):
        make_text_locator(normalized_text="short", start_offset=3, end_offset=3)


def test_resolution_statuses_are_distinguishable():
    """Three outcomes, not two: 'moved' must not read the same as 'missing' or 'fine'."""
    assert Resolution.RESOLVED.is_resolved
    assert not Resolution.SPAN_MISMATCH.is_resolved
    assert not Resolution.OUT_OF_RANGE.is_resolved
    assert len({Resolution.RESOLVED, Resolution.SPAN_MISMATCH, Resolution.OUT_OF_RANGE}) == 3


# --------------------------------------------------------------- visual locators


def test_visual_locator_resolves_against_a_real_render(ws, sources):
    out = import_paths(ws, [sources["text_pdf"]])
    manifest = read_artifact(out["manifest_paths"][0], expect_schema="Document")
    page = manifest["pages"][0]
    loc = make_visual_locator(
        page=page["page_number"], render_sha256=page["render"]["sha256"],
        bounding_box={"x": 0.1, "y": 0.2, "width": 0.5, "height": 0.3},
        render_width=page["render"]["width"], render_height=page["render"]["height"])
    index = {p["render"]["sha256"]: p["render"]["path"] for p in manifest["pages"] if p["render"]}
    assert resolve_visual_locator(loc, ws.root, index).ok


def test_visual_locator_fails_when_the_render_is_absent(ws, sources):
    out = import_paths(ws, [sources["text_pdf"]])
    manifest = read_artifact(out["manifest_paths"][0], expect_schema="Document")
    page = manifest["pages"][0]
    loc = make_visual_locator(
        page=1, render_sha256="sha256:" + "0" * 64,
        bounding_box={"x": 0, "y": 0, "width": 1, "height": 1},
        render_width=page["render"]["width"], render_height=page["render"]["height"])
    assert resolve_visual_locator(loc, ws.root, {}).status is Resolution.MISSING_RENDER


@pytest.mark.parametrize("box", [
    {"x": -0.1, "y": 0, "width": 0.5, "height": 0.5},
    {"x": 0, "y": 0, "width": 1.5, "height": 0.5},
    {"x": 0.8, "y": 0, "width": 0.5, "height": 0.5},     # runs past the right edge
    {"x": 0, "y": 0.9, "width": 0.5, "height": 0.5},     # runs past the bottom edge
    {"x": 0, "y": 0, "width": 0, "height": 0.5},         # zero area
    {"x": 0, "y": 0, "width": 0.5},                      # missing height
])
def test_invalid_bounding_boxes_are_rejected(box):
    with pytest.raises(ValueError):
        validate_bounding_box(box)


def test_normalized_box_is_dpi_independent():
    """The same fraction of the page at any render size — which is why it survives re-rendering."""
    box = {"x": 0.25, "y": 0.25, "width": 0.5, "height": 0.5}
    at150 = make_visual_locator(page=1, render_sha256="sha256:" + "a" * 64, bounding_box=box,
                                render_width=1275, render_height=1650)
    at300 = make_visual_locator(page=1, render_sha256="sha256:" + "a" * 64, bounding_box=box,
                                render_width=2550, render_height=3300)
    assert at150["bounding_box"] == at300["bounding_box"]


def test_visual_locator_fails_when_the_render_bytes_changed(ws, sources):
    """The render index is built FROM the manifest, so a lookup only proves the manifest claims
    that digest. `path.is_file()` was the whole check — replacing the image left every visual
    citation resolving cleanly, under a report that says evidence resolves to immutable bytes.
    """
    out = import_paths(ws, [sources["text_pdf"]])
    manifest = read_artifact(out["manifest_paths"][0], expect_schema="Document")
    page = manifest["pages"][0]
    loc = make_visual_locator(
        page=page["page_number"], render_sha256=page["render"]["sha256"],
        bounding_box={"x": 0.1, "y": 0.2, "width": 0.5, "height": 0.3},
        render_width=page["render"]["width"], render_height=page["render"]["height"])
    index = {p["render"]["sha256"]: p["render"]["path"] for p in manifest["pages"] if p["render"]}
    assert resolve_visual_locator(loc, ws.root, index).ok, "sanity: it resolves before the swap"

    # Swap the image for different bytes at the same path — the citation still names it.
    (ws.root / page["render"]["path"]).write_bytes(b"\x89PNG\r\n\x1a\n" + b"different image")

    result = resolve_visual_locator(loc, ws.root, index)
    assert result.status is Resolution.RENDER_MISMATCH, result.status
    assert not result.ok
