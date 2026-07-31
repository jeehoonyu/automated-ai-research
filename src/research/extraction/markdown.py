"""Markdown extraction: headings, sections, line ranges, and link destinations as inert metadata.

Markdown has no pages, so locators are 1-based SOURCE LINE RANGES rather than page numbers. That is
the whole difference from PDF; everything else about the trust model is identical.

Links are recorded and NEVER followed (spec §5, §18, §33). A Markdown file is untrusted input: a
link is a string, an HTML block is a string, and an embedded instruction is a string. Fetching a URL
found in a document would let an imported file reach the network on its own behalf, which is the
clearest possible trust-boundary violation in a platform whose core processing does no networking at
all.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .status import ExtractionStatus

_ATX = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_SETEXT = re.compile(r"^(=+|-+)\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_LINK = re.compile(r"\[(?P<text>[^\]]*)\]\((?P<dest><?[^)\s]+>?)(?:\s+\"[^\"]*\")?\)")
_AUTOLINK = re.compile(r"<((?:https?|ftp|mailto):[^>\s]+)>")
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")


@dataclass
class Section:
    level: int
    title: str
    line_start: int      # 1-based, inclusive
    line_end: int        # 1-based, inclusive
    path: list[str] = field(default_factory=list)


@dataclass
class MarkdownExtraction:
    text: str
    line_count: int
    sections: list[Section]
    links: list[dict[str, str]]
    code_block_lines: int
    table_row_lines: int
    status: ExtractionStatus
    warnings: list[str] = field(default_factory=list)
    toolchain: dict[str, str] = field(default_factory=dict)


def extract_markdown(source: str | Path, *, min_usable_chars: int = 1) -> MarkdownExtraction:
    """Parse structure without transforming content.

    The exact bytes are preserved as `text` because evidence locators are character offsets into it:
    normalizing whitespace or rewriting entities here would silently invalidate every offset a
    citation depends on.
    """
    source = Path(source)
    warns: list[str] = []
    try:
        raw = source.read_bytes()
    except Exception as exc:  # noqa: BLE001
        return MarkdownExtraction(
            text="", line_count=0, sections=[], links=[], code_block_lines=0, table_row_lines=0,
            status=ExtractionStatus.PROCESSING_FAILED,
            warnings=[f"could not read file: {type(exc).__name__}: {exc}"])

    lossy = False
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
        lossy = True
        warns.append("file is not valid UTF-8; undecodable bytes were replaced. Offsets remain "
                     "stable but quoted text may differ from the original bytes.")

    text = text.replace("\x00", "")
    lines = text.splitlines()

    sections: list[Section] = []
    links: list[dict[str, str]] = []
    stack: list[Section] = []
    in_fence = False
    code_lines = 0
    table_lines = 0

    for idx, line in enumerate(lines, start=1):
        if _FENCE.match(line):
            in_fence = not in_fence
            code_lines += 1
            continue
        if in_fence:
            code_lines += 1
            continue  # code blocks are preserved verbatim and never parsed for structure or links

        if _TABLE_ROW.match(line):
            table_lines += 1

        heading: tuple[int, str] | None = None
        m = _ATX.match(line)
        if m:
            heading = (len(m.group(1)), m.group(2).strip())
        elif idx >= 2 and _SETEXT.match(line) and lines[idx - 2].strip():
            heading = (1 if line.strip().startswith("=") else 2, lines[idx - 2].strip())

        if heading:
            level, title = heading
            while stack and stack[-1].level >= level:
                stack.pop().line_end = idx - 1
            sec = Section(level=level, title=title, line_start=idx, line_end=len(lines),
                          path=[s.title for s in stack] + [title])
            sections.append(sec)
            stack.append(sec)

        for lm in _LINK.finditer(line):
            links.append({"text": lm.group("text"), "destination": lm.group("dest").strip("<>"),
                          "line": str(idx)})
        for am in _AUTOLINK.finditer(line):
            links.append({"text": am.group(1), "destination": am.group(1), "line": str(idx)})

    while stack:
        stack.pop().line_end = len(lines)

    usable = len(text.strip())
    if usable < min_usable_chars:
        status = (ExtractionStatus.OCR_REQUIRED if usable == 0
                  else ExtractionStatus.PARTIALLY_EXTRACTED)
        warns.append(f"only {usable} usable characters in the file")
    elif lossy:
        # A LOSSY DECODE IS NOT A CLEAN EXTRACTION. This branch used to fall through to
        # `EXTRACTED` — the one status that means "usable as evidence" — while the warning above
        # said in plain words that quoted text may differ from the original bytes. A warning is not
        # a gate: nothing in validation reads `extraction_warnings`, so a document with U+FFFD
        # standing in for the very characters a citation quotes was as trustworthy as any other.
        # `partially_extracted` is the honest status and carries `needs_human_review`.
        status = ExtractionStatus.PARTIALLY_EXTRACTED
    else:
        status = ExtractionStatus.EXTRACTED

    return MarkdownExtraction(
        text=text, line_count=len(lines), sections=sections, links=links,
        code_block_lines=code_lines, table_row_lines=table_lines, status=status,
        warnings=warns, toolchain={"markdown_parser": "builtin-1.0.0"})
