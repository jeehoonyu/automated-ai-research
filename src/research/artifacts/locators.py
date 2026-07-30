"""Text and visual locators, and their resolution.

A locator is the load-bearing link between a claim and immutable source bytes. Everything else in
this platform is bookkeeping around this question: *does the passage this citation names actually
exist, at that place, saying that?*

TEXT LOCATORS carry a `span_sha256` over the exact substring they name. Resolution slices the stored
normalized text and compares. That turns citation checking into an equality test with three
distinguishable outcomes rather than two:

    resolved            the span exists and hashes to what was recorded
    span_mismatch       the offsets exist but the text there has changed
    out_of_range        the offsets do not exist in this document version

`span_mismatch` is the interesting one. Without the hash, an offset drift caused by re-extraction
would silently return *different words* at the same coordinates, and the citation would appear to
resolve. That is a quote that has moved under a claim without anyone noticing.

VISUAL LOCATORS name a page render hash plus a normalized bounding box. The render hash matters for
the same reason: it pins the citation to the exact image a reviewer looked at, so re-rendering at a
different DPI cannot quietly change what a figure citation points to.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from ..hashing import sha256_file, sha256_text


class Resolution(StrEnum):
    RESOLVED = "resolved"
    SPAN_MISMATCH = "span_mismatch"
    OUT_OF_RANGE = "out_of_range"
    MISSING_DOCUMENT = "missing_document"
    MISSING_RENDER = "missing_render"
    # The render exists at the recorded path but its bytes are not the ones cited. Distinct from
    # MISSING_RENDER on purpose: a missing file is an accident, a changed file is a different image
    # under someone's existing citation.
    RENDER_MISMATCH = "render_mismatch"
    INVALID = "invalid"

    @property
    def is_resolved(self) -> bool:
        return self is Resolution.RESOLVED


@dataclass
class ResolutionResult:
    status: Resolution
    text: str | None = None
    detail: str = ""
    page: int | None = None
    section_path: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status.is_resolved


def make_text_locator(
    *,
    normalized_text: str,
    start_offset: int,
    end_offset: int,
    page: int | None = None,
    section_path: list[str] | None = None,
    chunk_id: str | None = None,
    line_start: int | None = None,
    line_end: int | None = None,
) -> dict[str, Any]:
    """Build a text locator, hashing the exact span it names."""
    if not (0 <= start_offset < end_offset <= len(normalized_text)):
        raise ValueError(
            f"span [{start_offset}, {end_offset}) is not inside a text of length "
            f"{len(normalized_text)}")
    span = normalized_text[start_offset:end_offset]
    return {
        "type": "text_span",
        "page": page,
        "section_path": list(section_path or []),
        "chunk_id": chunk_id,
        "start_offset": start_offset,
        "end_offset": end_offset,
        "source_line_start": line_start,
        "source_line_end": line_end,
        "span_sha256": sha256_text(span),
    }


def resolve_text_locator(locator: dict[str, Any], normalized_text: str) -> ResolutionResult:
    """Resolve a text locator against the normalized text it was built from."""
    if locator.get("type") != "text_span":
        return ResolutionResult(Resolution.INVALID,
                                detail=f"not a text_span: {locator.get('type')!r}")
    try:
        start = int(locator["start_offset"])
        end = int(locator["end_offset"])
    except (KeyError, TypeError, ValueError):
        return ResolutionResult(Resolution.INVALID, detail="missing or non-integer offsets")

    if start < 0 or end > len(normalized_text) or start >= end:
        return ResolutionResult(
            Resolution.OUT_OF_RANGE,
            detail=f"span [{start}, {end}) does not exist in a text of length "
                   f"{len(normalized_text)}")

    span = normalized_text[start:end]
    recorded = locator.get("span_sha256")
    if recorded and sha256_text(span) != recorded:
        return ResolutionResult(
            Resolution.SPAN_MISMATCH, text=span,
            detail="the offsets exist but the text there no longer matches the recorded span hash; "
                   "this citation points at different words than when it was created")
    return ResolutionResult(Resolution.RESOLVED, text=span,
                            page=locator.get("page"),
                            section_path=list(locator.get("section_path") or []))


def make_visual_locator(
    *,
    page: int,
    render_sha256: str,
    bounding_box: dict[str, float],
    render_width: int,
    render_height: int,
) -> dict[str, Any]:
    """Build a visual-region locator with a normalized top-left bounding box (spec §21)."""
    validate_bounding_box(bounding_box)
    return {
        "type": "visual_region",
        "page": page,
        "render_sha256": render_sha256,
        "coordinate_system": "normalized_top_left_0_to_1",
        "bounding_box": {k: float(bounding_box[k]) for k in ("x", "y", "width", "height")},
        "render_width": int(render_width),
        "render_height": int(render_height),
    }


def validate_bounding_box(box: dict[str, Any]) -> None:
    """x, y, width, height in [0,1], and the box must stay inside the page.

    Normalized coordinates mean the citation survives a re-render at a different DPI: the region is
    a fraction of the page, not a pixel rectangle that silently means something else at 300 DPI.
    """
    for key in ("x", "y", "width", "height"):
        if key not in box:
            raise ValueError(f"bounding box is missing {key!r}")
        value = float(box[key])
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"bounding box {key}={value} is outside [0, 1]")
    if float(box["width"]) <= 0 or float(box["height"]) <= 0:
        raise ValueError("bounding box width and height must be positive")
    if float(box["x"]) + float(box["width"]) > 1.0 + 1e-9:
        raise ValueError("bounding box extends past the right edge of the page")
    if float(box["y"]) + float(box["height"]) > 1.0 + 1e-9:
        raise ValueError("bounding box extends past the bottom edge of the page")


def resolve_visual_locator(locator: dict[str, Any], workspace_root: str | Path,
                           render_index: dict[str, str]) -> ResolutionResult:
    """Confirm the named render exists and still hashes to the recorded value.

    `render_index` maps render sha256 -> workspace-relative path.

    That first sentence used to be false. The index is built FROM the document manifest, so looking
    a digest up in it proves only that the manifest claims that digest — the bytes on disk were
    never read, and `path.is_file()` was the whole check. Replacing a page render with a different
    image left every visual citation resolving cleanly, under a report that tells the reader
    evidence resolves to immutable source bytes. The file is hashed now.
    """
    if locator.get("type") != "visual_region":
        return ResolutionResult(Resolution.INVALID,
                                detail=f"not a visual_region: {locator.get('type')!r}")
    try:
        validate_bounding_box(locator.get("bounding_box") or {})
    except ValueError as exc:
        return ResolutionResult(Resolution.INVALID, detail=str(exc))

    digest = locator.get("render_sha256")
    rel = render_index.get(digest or "")
    if not rel:
        return ResolutionResult(
            Resolution.MISSING_RENDER,
            detail=f"no page render in this workspace hashes to {digest!r}; the citation names an "
                   f"image that is not present")
    path = Path(workspace_root) / rel
    if not path.is_file():
        return ResolutionResult(Resolution.MISSING_RENDER, detail=f"render file is missing: {rel}")
    actual = sha256_file(path)
    if actual != digest:
        return ResolutionResult(
            Resolution.RENDER_MISMATCH,
            detail=f"{rel} no longer hashes to {digest!r} (found {actual!r}); the image cited is "
                   f"not the image on disk")
    return ResolutionResult(Resolution.RESOLVED, page=locator.get("page"), detail=rel)
