"""Chunk generation.

A chunk is a RETRIEVAL unit, not evidence (spec §19). Search returns chunks; evidence is a passage a
human or agent selected *within* a chunk and pinned with an exact locator. Keeping those separate is
what stops "the search engine ranked this highly" from turning into "this supports the claim".

THREE RULES THAT MATTER

1. **Chunks never straddle a page boundary.** Otherwise a chunk has two page numbers and every
   citation derived from it is ambiguous about which page to name.

2. **Offsets are absolute into the normalized document text.** A chunk records where it came from,
   so evidence inside it resolves without needing the chunk itself. Chunk boundaries must not
   destroy the ability to resolve evidence back to the source (spec §19).

3. **A chunk from an `ocr_required` page is stored but NOT index-eligible.** No OCR ships in v1, so
   that page's text is whatever the extractor scraped from an image — usually noise. Letting it into
   search would let a claim cite text nobody could read. It is retained rather than dropped so
   `research inspect` can still show that the page exists and needs human verification.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..hashing import canonical_json, sha256_text
from ..identifiers import chunk_id as make_chunk_id
from .normalize import NormalizedDocument
from .status import ExtractionStatus

# Prefer to break at the strongest boundary available, in this order.
_BREAKS = ("\n\n", "\n", ". ", " ")


@dataclass
class Chunk:
    chunk_id: str
    document_id: str
    document_version_id: str
    text: str
    text_sha256: str
    start_offset: int
    end_offset: int
    page: int | None
    line_start: int | None
    line_end: int | None
    section_path: list[str]
    index_eligible: bool
    extraction_status: str
    overlap_before: int = 0
    overlap_after: int = 0
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "document_version_id": self.document_version_id,
            "text": self.text,
            "text_sha256": self.text_sha256,
            "start_offset": self.start_offset,
            "end_offset": self.end_offset,
            "page": self.page,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "section_path": self.section_path,
            "index_eligible": self.index_eligible,
            "extraction_status": self.extraction_status,
            "overlap_before": self.overlap_before,
            "overlap_after": self.overlap_after,
            "warnings": self.warnings,
        }


def chunking_config_hash(config: dict[str, Any]) -> str:
    return sha256_text(canonical_json(config))


def _split_points(text: str, start: int, end: int, target: int) -> int:
    """Choose the end of a chunk: the latest strong boundary within the window.

    Falling back through paragraph → line → sentence → word means a chunk ends somewhere a human
    would recognise, which matters because a search snippet that begins mid-word reads as noise and
    invites the reader to guess at the surrounding meaning.
    """
    hard = min(start + target, end)
    if hard >= end:
        return end
    window_start = start + max(1, int(target * 0.5))
    for token in _BREAKS:
        idx = text.rfind(token, window_start, hard)
        if idx != -1:
            return idx + len(token)
    return hard


def chunk_document(
    doc: NormalizedDocument,
    *,
    document_id: str,
    document_version_id: str,
    config: dict[str, Any],
    page_statuses: dict[int, str] | None = None,
) -> list[Chunk]:
    """Split a normalized document into chunks, respecting page boundaries."""
    target = int(config.get("target_chars", 1800))
    overlap = int(config.get("overlap_chars", 200))
    cfg_hash = chunking_config_hash(config)
    statuses = page_statuses or {}

    # Segment by page for PDFs; a single whole-document segment for Markdown.
    segments: list[tuple[int, int, int | None]]
    if doc.page_map:
        segments = [(p.start_offset, p.end_offset, p.page_number) for p in doc.page_map]
    else:
        segments = [(0, len(doc.text), None)]

    chunks: list[Chunk] = []
    for seg_start, seg_end, page in segments:
        if seg_end <= seg_start:
            continue
        page_status = statuses.get(page, ExtractionStatus.EXTRACTED) if page is not None \
            else ExtractionStatus.EXTRACTED
        eligible = ExtractionStatus(page_status).is_usable_as_evidence

        cursor = seg_start
        while cursor < seg_end:
            end = _split_points(doc.text, cursor, seg_end, target)
            if end <= cursor:
                end = min(cursor + target, seg_end)
            text = doc.text[cursor:end]
            if not text.strip():
                cursor = end
                continue

            back = min(overlap, cursor - seg_start)
            fwd = min(overlap, seg_end - end)
            cid = make_chunk_id(
                document_version_id_=document_version_id,
                page=page,
                section_path=doc.section_for_offset(cursor),
                start_offset=cursor,
                end_offset=end,
                chunking_config_hash=cfg_hash,
            )
            warnings: list[str] = []
            if not eligible:
                warnings.append(
                    f"page {page} extraction status is {page_status}; this chunk is retained for "
                    f"inspection but is NOT index-eligible and cannot back a citation without a "
                    f"recorded human verification amendment")

            chunks.append(Chunk(
                chunk_id=cid, document_id=document_id, document_version_id=document_version_id,
                text=text, text_sha256=sha256_text(text),
                start_offset=cursor, end_offset=end, page=page,
                line_start=doc.line_for_offset(cursor) if page is None else None,
                line_end=doc.line_for_offset(max(cursor, end - 1)) if page is None else None,
                section_path=doc.section_for_offset(cursor),
                index_eligible=eligible, extraction_status=str(page_status),
                overlap_before=back, overlap_after=fwd, warnings=warnings))
            cursor = end

    return chunks
