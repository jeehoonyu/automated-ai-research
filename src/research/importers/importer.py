"""Import orchestration: preserve originals, deduplicate by content, extract, record.

THE INVARIANT. Original bytes are never modified and never re-derived. They are copied once into
content-addressed storage and everything afterwards refers to them by hash. If that invariant holds,
a citation made today still resolves in five years against provably identical bytes; if it breaks,
every downstream guarantee is decoration.

DEDUPLICATION IS BY CONTENT, NOT BY NAME. The same paper saved under three filenames is ONE document
with three import aliases. Getting this wrong would let one source masquerade as three independent
ones — which is exactly the mistake spec §24 exists to prevent, arriving through the back door.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..artifacts.io import append_event, make_artifact, read_artifact, write_artifact
from ..config import Workspace
from ..errors import SourceProcessingError, UnsafePathError
from ..extraction.markdown import extract_markdown
from ..extraction.pdf import extract_pdf
from ..extraction.status import ExtractionStatus
from ..hashing import sha256_file, sha256_text
from ..identifiers import document_id, document_version_id
from ..security.paths import (
    atomic_write_bytes,
    content_address_path,
    reject_symlink,
    safe_join,
    sanitize_filename,
)

MEDIA_TYPES = {".pdf": "application/pdf", ".md": "text/markdown", ".markdown": "text/markdown"}


@dataclass
class ImportOutcome:
    path: str
    document_id: str | None = None
    document_version_id: str | None = None
    manifest_path: str | None = None
    duplicate: bool = False
    extraction_status: str | None = None
    warnings: list[str] = field(default_factory=list)
    error: str | None = None


def discover_sources(paths: list[str | Path]) -> tuple[list[Path], list[ImportOutcome]]:
    """Expand directories to supported files. Unsupported extensions are reported, not ignored."""
    found: list[Path] = []
    skipped: list[ImportOutcome] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            for child in sorted(p.rglob("*")):
                if child.is_file():
                    (found if child.suffix.lower() in MEDIA_TYPES else skipped).append(
                        child if child.suffix.lower() in MEDIA_TYPES
                        else ImportOutcome(path=str(child),
                                           extraction_status=ExtractionStatus.UNSUPPORTED_FORMAT,
                                           error=f"unsupported extension {child.suffix!r}"))
        elif p.is_file():
            if p.suffix.lower() in MEDIA_TYPES:
                found.append(p)
            else:
                skipped.append(ImportOutcome(
                    path=str(p), extraction_status=ExtractionStatus.UNSUPPORTED_FORMAT,
                    error=f"unsupported extension {p.suffix!r}"))
        else:
            skipped.append(ImportOutcome(path=str(p), error="path does not exist"))
    return found, skipped


def import_one(ws: Workspace, source: Path) -> ImportOutcome:
    """Import a single file. Returns an outcome; only genuinely unexpected failures raise."""
    outcome = ImportOutcome(path=str(source))
    try:
        source = reject_symlink(source)
    except UnsafePathError as exc:
        outcome.error = exc.message
        outcome.extraction_status = ExtractionStatus.PROCESSING_FAILED
        return outcome

    max_bytes = int(ws.get("extraction.max_file_bytes", 250 * 1024 * 1024))
    size = source.stat().st_size
    if size > max_bytes:
        outcome.error = f"file is {size} bytes, over the configured limit of {max_bytes}"
        outcome.extraction_status = ExtractionStatus.PROCESSING_FAILED
        return outcome

    source_hash = sha256_file(source)
    doc_id = document_id(source_hash)
    outcome.document_id = doc_id

    # ---- preserve originals, content-addressed ----
    stored = content_address_path(ws.root, source_hash)
    already_stored = stored.exists()
    if not already_stored:
        atomic_write_bytes(stored, source.read_bytes(), root=ws.root)

    manifest_path = safe_join(ws.root, "documents", "manifests",
                              f"{doc_id.replace(':', '_')}.json")

    # A file already imported under a different name is the SAME document with a new alias.
    if manifest_path.exists():
        existing = read_artifact(manifest_path, expect_schema="Document")
        aliases = list(existing.get("original_filename_aliases", []))
        alias = source.name
        if alias not in aliases:
            aliases.append(alias)
            existing["original_filename_aliases"] = sorted(aliases)
            write_artifact(manifest_path, existing, root=ws.root)
        _record_import_event(ws, doc_id, source, source_hash, duplicate=True)
        outcome.duplicate = True
        outcome.manifest_path = str(manifest_path)
        outcome.document_version_id = existing.get("document_version_id")
        outcome.extraction_status = existing.get("extraction_status")
        return outcome

    media_type = MEDIA_TYPES[source.suffix.lower()]
    dver = document_version_id(
        document_id_=doc_id,
        extraction_config_hash=ws.extraction_config_hash(),
        toolchain_version=str(ws.get("extraction.toolchain_version")),
        normalization_version=str(ws.get("extraction.normalization_version")),
    )
    outcome.document_version_id = dver

    if media_type == "application/pdf":
        body = _import_pdf(ws, source, doc_id, dver)
    else:
        body = _import_markdown(ws, source, doc_id, dver)

    body.update({
        "document_id": doc_id,
        "document_version_id": dver,
        "source_sha256": source_hash,
        "media_type": media_type,
        "file_size_bytes": size,
        "original_filename_aliases": [sanitize_filename(source.name)],
        "stored_original": str(stored.relative_to(ws.root)).replace("\\", "/"),
        "extraction_config_hash": ws.extraction_config_hash(),
    })

    artifact = make_artifact(schema_name="Document", artifact_id=doc_id, body=body,
                             actor_type="cli")
    write_artifact(manifest_path, artifact, root=ws.root)
    _record_import_event(ws, doc_id, source, source_hash, duplicate=False)

    outcome.manifest_path = str(manifest_path)
    outcome.extraction_status = body["extraction_status"]
    outcome.warnings = list(body.get("extraction_warnings", []))
    return outcome


def _import_pdf(ws: Workspace, source: Path, doc_id: str, dver: str) -> dict[str, Any]:
    render_dir = safe_join(ws.root, "documents", "renders", doc_id.replace(":", "_"))
    result = extract_pdf(
        source,
        render_dir=render_dir,
        dpi=int(ws.get("render.dpi", 150)),
        min_usable_chars=int(ws.get("extraction.min_usable_chars_per_page", 120)),
    )

    pages_dir = safe_join(ws.root, "documents", "pages", doc_id.replace(":", "_"))
    page_records: list[dict[str, Any]] = []
    for page in result.pages:
        if page.text:
            atomic_write_bytes(pages_dir / f"page-{page.page_number:04d}.txt",
                               page.text.encode("utf-8"), root=ws.root)
        page_records.append({
            "page_number": page.page_number,
            "char_count": page.char_count,
            "text_sha256": sha256_text(page.text),
            "extraction_status": str(page.status),
            "render": None if not page.render_sha256 else {
                "path": f"documents/renders/{doc_id.replace(':', '_')}/{page.render_path}",
                "sha256": page.render_sha256,
                "width": page.render_width,
                "height": page.render_height,
                "dpi": int(ws.get("render.dpi", 150)),
                "renderer": str(ws.get("render.renderer", "pypdfium2")),
                "format": str(ws.get("render.format", "png")),
            },
            "warnings": page.warnings,
        })

    ocr_pages = [p.page_number for p in result.pages if p.status is ExtractionStatus.OCR_REQUIRED]
    return {
        "page_count": result.page_count,
        "pages": page_records,
        "ocr_required_pages": ocr_pages,
        "metadata": result.metadata,
        "extraction_status": str(result.status),
        "extraction_toolchain": result.toolchain,
        "extraction_warnings": result.warnings,
        "tables_status": str(result.tables_status),
        "figures_status": str(result.figures_status),
        "rendered_page_count": sum(1 for p in result.pages if p.render_sha256),
    }


def _import_markdown(ws: Workspace, source: Path, doc_id: str, dver: str) -> dict[str, Any]:
    result = extract_markdown(source)
    norm_dir = safe_join(ws.root, "documents", "normalized")
    atomic_write_bytes(norm_dir / f"{doc_id.replace(':', '_')}.md",
                       result.text.encode("utf-8"), root=ws.root)
    return {
        "page_count": None,           # Markdown has no pages; locators use source line ranges
        "line_count": result.line_count,
        "sections": [{"level": s.level, "title": s.title, "path": s.path,
                      "line_start": s.line_start, "line_end": s.line_end}
                     for s in result.sections],
        # Recorded as metadata and NEVER followed (spec §5, §18).
        "links": result.links,
        "links_followed": False,
        "code_block_lines": result.code_block_lines,
        "table_row_lines": result.table_row_lines,
        "ocr_required_pages": [],
        "metadata": {},
        "extraction_status": str(result.status),
        "extraction_toolchain": result.toolchain,
        "extraction_warnings": result.warnings,
        "normalized_path": f"documents/normalized/{doc_id.replace(':', '_')}.md",
        "text_sha256": sha256_text(result.text),
    }


def _record_import_event(ws: Workspace, doc_id: str, source: Path, source_hash: str, *,
                         duplicate: bool) -> None:
    """Append-only. The original absolute path is provenance, not a place to read from later."""
    append_event(
        ws.root / "imports" / "import-events.jsonl",
        {
            "event": "import",
            "document_id": doc_id,
            "source_sha256": source_hash,
            "original_path": str(source),
            "original_filename": source.name,
            "duplicate": duplicate,
        },
        root=ws.root,
    )


def import_paths(ws: Workspace, paths: list[str | Path]) -> dict[str, Any]:
    """Import many sources and summarize honestly.

    The summary separates imported / duplicate / failed / needs-review so the caller can set a
    status that does not present partial processing as complete success (spec §34).
    """
    sources, skipped = discover_sources(paths)
    if not sources and not skipped:
        raise SourceProcessingError("no importable files found",
                                    detail={"paths": [str(p) for p in paths]})

    outcomes = [import_one(ws, s) for s in sources] + skipped

    def _failed(o: ImportOutcome) -> bool:
        """A document whose bytes were preserved but whose extraction FAILED is not an import
        success. Counting it as imported would present a document nobody could read as one that was
        successfully ingested — the precise wording spec §8.2 forbids ("must not claim successful
        extraction merely because a source file was copied successfully")."""
        if o.error is not None:
            return True
        return bool(o.extraction_status and ExtractionStatus(o.extraction_status).is_failure)

    duplicates = [o for o in outcomes if o.duplicate]
    failed = [o for o in outcomes if not o.duplicate and _failed(o)]
    imported = [o for o in outcomes if not o.duplicate and not _failed(o)]
    needs_review = [
        o for o in imported
        if o.extraction_status and ExtractionStatus(o.extraction_status).needs_human_review
    ]

    return {
        "imported_count": len(imported),
        "duplicate_count": len(duplicates),
        "failed_count": len(failed),
        "warning_count": sum(len(o.warnings) for o in outcomes),
        "needs_human_review_count": len(needs_review),
        "document_ids": sorted({o.document_id for o in imported if o.document_id}),
        "manifest_paths": sorted(o.manifest_path for o in imported if o.manifest_path),
        "documents": [
            {"path": o.path, "document_id": o.document_id,
             "document_version_id": o.document_version_id,
             "extraction_status": o.extraction_status, "duplicate": o.duplicate,
             "warnings": o.warnings, "error": o.error}
            for o in outcomes
        ],
    }
