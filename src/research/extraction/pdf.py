"""PDF extraction: page-aware text, metadata, and a render of every page.

WHY EVERY PAGE IS RENDERED. Visual provenance (spec §17.1). A reviewer checking a citation must be
able to *look* at the page the quote came from, and a figure or chart can only ever be cited through
a render. Rendering only "interesting" pages would mean the pages nobody bothered to render are
exactly the ones that cannot later be checked.

WHY LOW-TEXT PAGES ARE `ocr_required` AND NOT EMPTY. A scanned page extracts as "". Without an
explicit status, "this page has no text" and "this page's text is unreadable by this toolchain" are
the same value — and a downstream agent asked "does this document discuss X?" would answer "no"
about a page it never read. No OCR ships in v1 (spec §5), so such pages become usable only through a
recorded human verification amendment.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..hashing import sha256_bytes, sha256_text
from .status import ExtractionStatus, RegionStatus, worst


@dataclass
class PageResult:
    page_number: int              # 1-based (spec: PDF pages are 1-based)
    text: str
    char_count: int
    status: ExtractionStatus
    render_path: str | None = None
    render_sha256: str | None = None
    render_width: int | None = None
    render_height: int | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class PdfExtraction:
    page_count: int
    pages: list[PageResult]
    metadata: dict[str, Any]
    status: ExtractionStatus
    warnings: list[str] = field(default_factory=list)
    tables_status: RegionStatus = RegionStatus.NOT_DETECTED
    figures_status: RegionStatus = RegionStatus.NOT_DETECTED
    toolchain: dict[str, str] = field(default_factory=dict)


def _toolchain_versions() -> dict[str, str]:
    """Recorded into document_version_id: a parser upgrade produces a NEW version rather than
    silently moving text under an existing citation."""
    import pypdf
    import pypdfium2

    versions = {"pypdf": getattr(pypdf, "__version__", "unknown"),
                "pypdfium2": getattr(pypdfium2, "V_PYPDFIUM2", "unknown")}
    try:
        import pdfplumber
        versions["pdfplumber"] = getattr(pdfplumber, "__version__", "unknown")
    except Exception:  # noqa: BLE001
        versions["pdfplumber"] = "unavailable"
    return {k: str(v) for k, v in versions.items()}


def _clean_metadata(raw: Any) -> dict[str, Any]:
    """PDF metadata is attacker-controlled. Keep it as inert strings, never as instructions."""
    out: dict[str, Any] = {}
    if not raw:
        return out
    for key in ("/Title", "/Author", "/Subject", "/Creator", "/Producer",
                "/CreationDate", "/ModDate"):
        value = raw.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            # control characters in metadata are a red flag and break downstream JSON readability
            out[key.lstrip("/").lower()] = "".join(c for c in text if c.isprintable())[:1000]
    return out


def extract_pdf(
    source: str | Path,
    *,
    render_dir: Path | None = None,
    dpi: int = 150,
    min_usable_chars: int = 120,
    max_pages: int | None = None,
) -> PdfExtraction:
    """Extract text and render pages. Never raises for a bad PDF — returns a status instead.

    A malformed or encrypted PDF is normal input, not an exceptional condition: the platform is
    explicitly required to keep the original bytes and report an honest non-success status (spec
    §8.2, release gate 38.2).
    """
    import pypdf

    source = Path(source)
    toolchain = _toolchain_versions()
    warns: list[str] = []

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            reader = pypdf.PdfReader(str(source))
            if reader.is_encrypted:
                try:
                    if reader.decrypt("") == 0:  # empty user password
                        raise ValueError("encrypted")
                except Exception:  # noqa: BLE001
                    return PdfExtraction(
                        page_count=0, pages=[], metadata={},
                        status=ExtractionStatus.UNSUPPORTED_FORMAT,
                        warnings=["PDF is encrypted and cannot be read without a password"],
                        toolchain=toolchain)
            page_count = len(reader.pages)
            metadata = _clean_metadata(reader.metadata)
    except Exception as exc:  # noqa: BLE001
        return PdfExtraction(
            page_count=0, pages=[], metadata={}, status=ExtractionStatus.PROCESSING_FAILED,
            warnings=[f"could not open PDF: {type(exc).__name__}: {exc}"], toolchain=toolchain)

    limit = min(page_count, max_pages) if max_pages else page_count
    if limit < page_count:
        warns.append(f"page limit applied: extracted {limit} of {page_count} pages")

    pages: list[PageResult] = []
    for i in range(limit):
        page_no = i + 1
        page_warnings: list[str] = []
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                text = reader.pages[i].extract_text() or ""
        except Exception as exc:  # noqa: BLE001
            text = ""
            page_warnings.append(f"text extraction failed: {type(exc).__name__}: {exc}")

        text = text.replace("\x00", "")
        usable = len(text.strip())
        if page_warnings:
            status = ExtractionStatus.PROCESSING_FAILED
        elif usable < min_usable_chars:
            status = ExtractionStatus.OCR_REQUIRED
            page_warnings.append(
                f"only {usable} usable characters (< {min_usable_chars}); page is probably "
                f"image-only and needs OCR or human verification before it can back a citation")
        else:
            status = ExtractionStatus.EXTRACTED

        pages.append(PageResult(page_number=page_no, text=text, char_count=usable,
                                status=status, warnings=page_warnings))

    if render_dir is not None:
        _render_pages(source, pages, render_dir, dpi=dpi, warns=warns)

    doc_status = worst([p.status for p in pages]) if pages else ExtractionStatus.PROCESSING_FAILED
    if limit < page_count and doc_status is ExtractionStatus.EXTRACTED:
        doc_status = ExtractionStatus.PARTIALLY_EXTRACTED

    return PdfExtraction(
        page_count=page_count, pages=pages, metadata=metadata, status=doc_status,
        warnings=warns, toolchain=toolchain,
        # Detection is not attempted in Phase 2. Reporting `not_detected` rather than `extracted`
        # keeps the claim honest; the full-page render remains available either way (spec §17).
        tables_status=RegionStatus.NOT_DETECTED,
        figures_status=RegionStatus.NOT_DETECTED,
    )


def _render_pages(source: Path, pages: list[PageResult], render_dir: Path, *,
                  dpi: int, warns: list[str]) -> None:
    """Render each page to RGB PNG and hash the result.

    The render hash is what a visual locator points at, so a re-render with different settings
    produces a different hash and cannot be mistaken for the image a reviewer actually saw.
    """
    try:
        import pypdfium2 as pdfium
    except Exception as exc:  # noqa: BLE001
        warns.append(f"page rendering unavailable: {exc}")
        return

    render_dir.mkdir(parents=True, exist_ok=True)
    scale = dpi / 72.0
    try:
        doc = pdfium.PdfDocument(str(source))
    except Exception as exc:  # noqa: BLE001
        warns.append(f"could not open PDF for rendering: {type(exc).__name__}: {exc}")
        return

    try:
        for page in pages:
            try:
                bitmap = doc[page.page_number - 1].render(scale=scale, rev_byteorder=False)
                pil = bitmap.to_pil().convert("RGB")
                out = render_dir / f"page-{page.page_number:04d}.png"
                pil.save(out, format="PNG")
                data = out.read_bytes()
                page.render_path = out.name
                page.render_sha256 = sha256_bytes(data)
                page.render_width, page.render_height = pil.size
            except Exception as exc:  # noqa: BLE001
                page.warnings.append(f"render failed: {type(exc).__name__}: {exc}")
                warns.append(f"page {page.page_number}: render failed")
    finally:
        try:
            doc.close()
        except Exception:  # noqa: BLE001
            pass


def page_text_sha256(text: str) -> str:
    return sha256_text(text)
