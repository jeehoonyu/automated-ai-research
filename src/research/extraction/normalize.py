"""Normalization: one canonical text per document version, with a page map.

THE CONTRACT. Every text locator in this platform is a pair of **Python Unicode code-point offsets
into the exact normalized text stored for that document version** (spec §20). That text is written to
disk and hashed. Resolving a citation is therefore a slice, not a search — which is what makes
"does this quote actually appear at this location" a decidable question rather than a fuzzy one.

Two consequences that drive the design:

1. **Normalization must be versioned.** Changing it changes every offset. `normalization_version`
   feeds `document_version_id`, so a normalization change produces a NEW document version and old
   evidence keeps pointing at the text it was actually read from. Evidence never silently moves.

2. **Normalization must be conservative.** Every transformation is a chance to alter meaning inside
   a quote. What is deliberately NOT done is listed in `NOT_PERFORMED` and recorded in the artifact,
   because a reviewer comparing a quote against the original PDF needs to know what was changed.

PAGE ATTRIBUTION. A PDF's normalized text is the concatenation of its page texts, and the page map
records the offset span of each page. A global offset resolves to exactly one page. Chunks never
straddle a page boundary, so every chunk has an unambiguous page number — required for citations
that must name a page.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Any

from ..hashing import sha256_text

# Recorded in the artifact so a reviewer knows what a quote has and has not been through.
NOT_PERFORMED = [
    "de-hyphenation of words broken across lines (would change the characters inside a quote)",
    "multi-column reading-order reconstruction (pypdf emits text in its own order)",
    "ligature expansion beyond what NFC already performs",
    "header/footer removal (a running header remains part of its page's text)",
    "OCR of any kind",
]

PAGE_SEPARATOR = "\n\n"


@dataclass
class PageSpan:
    page_number: int
    start_offset: int      # inclusive, code points into the normalized text
    end_offset: int        # exclusive
    extraction_status: str


@dataclass
class SectionSpan:
    title: str
    path: list[str]
    level: int
    start_offset: int
    end_offset: int
    page: int | None = None
    line_start: int | None = None
    line_end: int | None = None


@dataclass
class NormalizedDocument:
    text: str
    text_sha256: str
    page_map: list[PageSpan] = field(default_factory=list)
    sections: list[SectionSpan] = field(default_factory=list)
    line_starts: list[int] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def page_for_offset(self, offset: int) -> int | None:
        for span in self.page_map:
            if span.start_offset <= offset < span.end_offset:
                return span.page_number
        return None

    def line_for_offset(self, offset: int) -> int | None:
        """1-based source line. Markdown locators use line ranges instead of pages (spec §18)."""
        if not self.line_starts:
            return None
        lo, hi = 0, len(self.line_starts) - 1
        while lo <= hi:
            mid = (lo + hi) // 2
            if self.line_starts[mid] <= offset:
                lo = mid + 1
            else:
                hi = mid - 1
        return max(1, lo)

    def section_for_offset(self, offset: int) -> list[str]:
        """Deepest section containing the offset; [] when the text has no headings."""
        best: SectionSpan | None = None
        for sec in self.sections:
            if sec.start_offset <= offset < sec.end_offset:
                if best is None or sec.level > best.level:
                    best = sec
        return best.path if best else []


def normalize_text(raw: str) -> str:
    """Conservative, deterministic, and reversible enough to stay honest.

    NFC composition means a quote copied from a rendered page compares equal to the stored text even
    when one side used decomposed accents. Line endings are unified so an offset does not depend on
    whether the source used CRLF. Trailing whitespace is stripped per line because it is invisible in
    a quote and would otherwise cause spurious mismatches.
    """
    text = raw.replace("\x00", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = unicodedata.normalize("NFC", text)
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    return text


def _line_starts(text: str) -> list[int]:
    starts = [0]
    for i, ch in enumerate(text):
        if ch == "\n":
            starts.append(i + 1)
    return starts


def normalize_pdf(pages: list[dict[str, Any]], page_texts: dict[int, str]) -> NormalizedDocument:
    """Build the canonical text for a PDF from its per-page texts."""
    parts: list[str] = []
    page_map: list[PageSpan] = []
    cursor = 0
    warnings: list[str] = []

    for page in sorted(pages, key=lambda p: p["page_number"]):
        number = page["page_number"]
        text = normalize_text(page_texts.get(number, ""))
        start = cursor
        parts.append(text)
        cursor += len(text)
        page_map.append(PageSpan(page_number=number, start_offset=start, end_offset=cursor,
                                 extraction_status=page["extraction_status"]))
        parts.append(PAGE_SEPARATOR)
        cursor += len(PAGE_SEPARATOR)

    if parts:
        parts.pop()                       # no trailing separator after the final page
        cursor -= len(PAGE_SEPARATOR)

    text = "".join(parts)
    empty = [p.page_number for p in page_map if p.end_offset == p.start_offset]
    if empty:
        warnings.append(
            f"{len(empty)} page(s) contributed no text to the normalized document: {empty}. "
            f"Their content is only available through the page renders.")

    return NormalizedDocument(
        text=text, text_sha256=sha256_text(text), page_map=page_map,
        sections=_pdf_sections(text, page_map), line_starts=_line_starts(text),
        warnings=warnings)


def _pdf_sections(text: str, page_map: list[PageSpan]) -> list[SectionSpan]:
    """Heading detection for PDFs is heuristic, so it stays deliberately shallow.

    A line that looks like a numbered heading ("4 Results", "4.2 Evaluation") becomes a section. No
    attempt is made to infer hierarchy from font size — that information is not available from the
    text layer, and guessing it would produce a section path that looks authoritative and is not.
    A wrong section path is worse than no section path, because citations quote it.
    """
    import re

    heading = re.compile(r"^(?P<num>\d+(?:\.\d+)*)\s+(?P<title>[^\n]{2,80})$")
    sections: list[SectionSpan] = []
    offset = 0
    pending: list[tuple[int, str, list[str]]] = []

    for line in text.split("\n"):
        m = heading.match(line.strip())
        if m:
            depth = m.group("num").count(".") + 1
            title = f"{m.group('num')} {m.group('title')}".strip()
            while pending and pending[-1][0] >= depth:
                start_depth, start_title, path = pending.pop()
                sections.append(SectionSpan(title=start_title, path=path, level=start_depth,
                                            start_offset=_find_start(sections, start_title, offset),
                                            end_offset=offset))
            parent = pending[-1][2] if pending else []
            pending.append((depth, title, [*parent, title]))
            sections.append(SectionSpan(title=title, path=[*parent, title], level=depth,
                                        start_offset=offset, end_offset=len(text)))
        offset += len(line) + 1

    for sec in sections:
        sec.page = next((p.page_number for p in page_map
                         if p.start_offset <= sec.start_offset < p.end_offset), None)
    return sections


def _find_start(sections: list[SectionSpan], title: str, fallback: int) -> int:
    for sec in sections:
        if sec.title == title:
            return sec.start_offset
    return fallback


def normalize_markdown(raw_text: str, sections: list[dict[str, Any]]) -> NormalizedDocument:
    """Markdown normalization keeps line structure, since its locators are line ranges."""
    text = normalize_text(raw_text)
    starts = _line_starts(text)

    def offset_of_line(line_no: int) -> int:
        idx = max(0, min(line_no - 1, len(starts) - 1))
        return starts[idx]

    spans: list[SectionSpan] = []
    for sec in sections:
        start = offset_of_line(int(sec["line_start"]))
        end_line = int(sec["line_end"])
        end = starts[end_line] if end_line < len(starts) else len(text)
        spans.append(SectionSpan(
            title=sec["title"], path=list(sec["path"]), level=int(sec["level"]),
            start_offset=start, end_offset=end,
            line_start=int(sec["line_start"]), line_end=end_line))

    return NormalizedDocument(text=text, text_sha256=sha256_text(text), page_map=[],
                              sections=spans, line_starts=starts, warnings=[])
