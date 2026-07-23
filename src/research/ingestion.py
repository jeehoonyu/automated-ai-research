from __future__ import annotations

import io
import re
import unicodedata
from collections.abc import Iterable
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import pdfplumber
import pypdfium2 as pdfium
import yaml
from pypdf import PdfReader

from research import __version__
from research.artifacts import artifact_base, store_artifact
from research.canonical import prefixed_sha256, verify_artifact_hash
from research.config import config_hash, load_config
from research.constants import CHUNKING_VERSION, NORMALIZATION_VERSION
from research.errors import ResearchError
from research.identifiers import content_identifier, derived_identifier, generated_identifier
from research.io import (
    append_jsonl,
    file_sha256,
    utc_now,
    write_bytes_atomic,
    write_json_atomic,
    write_text_atomic,
)
from research.security import (
    ensure_no_symlink_components,
    ensure_workspace_write,
    sanitize_filename,
    validate_import_source,
)

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_FIGURE_CAPTION = re.compile(r"^\s*(figure|fig\.)\s*\d+", re.IGNORECASE)


def import_sources(workspace: Path, inputs: Iterable[Path]) -> dict[str, Any]:
    config = load_config(workspace)
    candidates = _discover_inputs(inputs)
    imported: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for candidate in candidates:
        try:
            outcome = _import_one(workspace, candidate, config)
            if outcome["extraction_status"] == "processing_failed":
                failures.append(
                    {
                        "path": str(candidate),
                        "document_id": outcome["document_id"],
                        "category": "processing_failed",
                        "message": "Original was preserved but extraction failed",
                    }
                )
                warnings.extend(outcome.get("warnings", []))
                continue
            if outcome["duplicate"]:
                duplicates.append(outcome)
            else:
                imported.append(outcome)
            warnings.extend(outcome.get("warnings", []))
        except ResearchError as exc:
            failures.append(
                {
                    "path": str(candidate),
                    "category": exc.category,
                    "message": str(exc),
                    "details": exc.details,
                }
            )
        except Exception as exc:  # parser failures must become explicit source failures
            failures.append(
                {
                    "path": str(candidate),
                    "category": "processing_failed",
                    "message": f"{type(exc).__name__}: {exc}",
                }
            )
    partial_documents = [
        item for item in [*imported, *duplicates] if item.get("extraction_status") != "extracted"
    ]
    status = (
        "failed"
        if failures and not imported and not duplicates
        else "partial"
        if failures or partial_documents
        else "success"
    )
    return {
        "status": status,
        "imported_count": len(imported),
        "duplicate_count": len(duplicates),
        "warning_count": len(warnings),
        "failed_count": len(failures),
        "partial_count": len(partial_documents),
        "documents": imported + duplicates,
        "warnings": warnings,
        "failures": failures,
    }


def _discover_inputs(inputs: Iterable[Path]) -> list[Path]:
    result: list[Path] = []
    for supplied in inputs:
        path = supplied.expanduser()
        if path.is_symlink():
            result.append(path)
        elif path.is_dir():
            result.extend(item for item in path.rglob("*") if item.is_file() or item.is_symlink())
        else:
            result.append(path)
    return sorted(
        set(result), key=lambda item: unicodedata.normalize("NFC", str(item.resolve(strict=False)))
    )


def _import_one(workspace: Path, source: Path, config: dict[str, Any]) -> dict[str, Any]:
    source = validate_import_source(source, int(config["imports"]["max_file_bytes"]))
    suffix = source.suffix.lower()
    media_type = {
        ".pdf": "application/pdf",
        ".md": "text/markdown",
        ".markdown": "text/markdown",
    }.get(suffix)
    if media_type is None:
        raise ResearchError(
            f"Unsupported source format: {source.suffix or '<none>'}",
            category="unsupported_format",
        )
    source_hex = file_sha256(source)
    source_hash = f"sha256:{source_hex}"
    document_id = content_identifier("DOC", source_hex)
    original_relative = Path("originals") / "sha256" / source_hex[:2] / source_hex[2:4] / source_hex
    original_path = workspace / original_relative
    ensure_workspace_write(workspace, original_path)
    ensure_no_symlink_components(workspace, original_path)
    existing_documents = [
        item
        for item in _iter_document_manifests(workspace)
        if item.get("document_id") == document_id
    ]
    duplicate = bool(existing_documents)
    if original_path.exists():
        if not original_path.is_file() or file_sha256(original_path) != source_hex:
            raise ResearchError(
                f"Content-addressed original is missing or has been modified: {original_path}",
                category="source_hash_mismatch",
            )
    else:
        write_bytes_atomic(original_path, source.read_bytes(), root=workspace)
    event = {
        "event_id": generated_identifier("IMP"),
        "timestamp": utc_now(),
        "document_id": document_id,
        "source_sha256": source_hash,
        "source_path": str(source),
        "source_filename": sanitize_filename(source.name),
        "duplicate": duplicate,
    }
    append_jsonl(workspace / "imports" / "import-events.jsonl", event, root=workspace)
    if duplicate:
        stored_document = max(existing_documents, key=lambda item: str(item["created_at"]))
        desired_version_id = document_version_id_for(stored_document, config)
        existing_versions = [
            item
            for item in _iter_document_versions(workspace)
            if item.get("document_version_id") == desired_version_id
        ]
        if existing_versions:
            existing_version = max(existing_versions, key=lambda item: str(item["created_at"]))
            expected_chunking_hash = config_hash(config["chunking"])
            existing_chunks = [
                item
                for item in _iter_chunks(workspace)
                if item.get("document_version_id") == desired_version_id
                and item.get("chunking_configuration_hash") == expected_chunking_hash
            ]
            if not existing_chunks:
                chunks = _rechunk_existing_version(
                    workspace, stored_document, existing_version, config
                )
                rechunk_paths: list[str] = []
                for chunk in chunks:
                    _, path = store_artifact(workspace, chunk)
                    rechunk_paths.append(str(path.relative_to(workspace)))
                return {
                    "document_id": document_id,
                    "document_version_id": desired_version_id,
                    "duplicate": True,
                    "extraction_status": existing_version["extraction_status"],
                    "processing_action": "rechunked",
                    "chunk_count": len(chunks),
                    "manifest_paths": rechunk_paths,
                    "warnings": [],
                }
            return {
                "document_id": document_id,
                "document_version_id": desired_version_id,
                "duplicate": True,
                "extraction_status": existing_version["extraction_status"],
                "processing_action": "duplicate",
                "manifest_paths": [],
                "warnings": [],
            }
        from research.artifacts import immutable_artifact_path

        document_path = immutable_artifact_path(workspace, stored_document)
    else:
        document = artifact_base("Document", document_id)
        document.update(
            {
                "document_id": document_id,
                "source_sha256": source_hash,
                "media_type": media_type,
                "file_size": source.stat().st_size,
                "original_storage_path": original_relative.as_posix(),
                "import_aliases": [str(source)],
                "metadata": {"original_filename": source.name},
            }
        )
        stored_document, document_path = store_artifact(workspace, document)
    try:
        if media_type == "application/pdf":
            version_artifact, chunks, extraction_warnings = _extract_pdf(
                workspace, original_path, stored_document, config
            )
        else:
            version_artifact, chunks, extraction_warnings = _extract_markdown(
                workspace, original_path, stored_document, config
            )
    except Exception as exc:
        failed_version = _failed_document_version(stored_document, config, exc)
        version_artifact, version_path = store_artifact(workspace, failed_version)
        return {
            "document_id": document_id,
            "document_version_id": version_artifact["document_version_id"],
            "duplicate": duplicate,
            "extraction_status": "processing_failed",
            "manifest_paths": [
                str(document_path.relative_to(workspace)),
                str(version_path.relative_to(workspace)),
            ],
            "warnings": version_artifact["warnings"],
        }
    stored_version, version_path = store_artifact(workspace, version_artifact)
    chunk_paths: list[str] = []
    for chunk in chunks:
        _, path = store_artifact(workspace, chunk)
        chunk_paths.append(str(path.relative_to(workspace)))
    return {
        "document_id": document_id,
        "document_version_id": stored_version["document_version_id"],
        "duplicate": duplicate,
        "extraction_status": stored_version["extraction_status"],
        "chunk_count": len(chunks),
        "manifest_paths": [
            str(document_path.relative_to(workspace)),
            str(version_path.relative_to(workspace)),
            *chunk_paths,
        ],
        "warnings": extraction_warnings,
    }


def _tool_version(package: str) -> str:
    try:
        return version(package)
    except PackageNotFoundError:
        return "unknown"


def _toolchain(media_type: str) -> dict[str, str]:
    tools = {"research": __version__}
    if media_type == "application/pdf":
        tools.update(
            {
                "pypdf": _tool_version("pypdf"),
                "pdfplumber": _tool_version("pdfplumber"),
                "pypdfium2": _tool_version("pypdfium2"),
            }
        )
    return tools


def document_version_id_for(document: dict[str, Any], config: dict[str, Any]) -> str:
    """Return the extraction version selected by the active deterministic configuration."""
    media_type = str(document["media_type"])
    composite = {
        "source_sha256": document["source_sha256"],
        "extraction_configuration_hash": extraction_configuration_hash_for(document, config),
        "toolchain": _toolchain(media_type),
        "normalization_version": NORMALIZATION_VERSION,
    }
    return derived_identifier("DVER", composite)


def extraction_configuration_for(
    document: dict[str, Any], config: dict[str, Any]
) -> dict[str, Any]:
    if document["media_type"] == "application/pdf":
        return dict(config["pdf"])
    return {
        "encoding": "utf-8-sig-with-utf-8-replacement-fallback",
        "unicode_normalization": "NFC",
        "newline_normalization": "LF",
    }


def extraction_configuration_hash_for(document: dict[str, Any], config: dict[str, Any]) -> str:
    return config_hash(
        {
            "extraction": extraction_configuration_for(document, config),
            "media_type": document["media_type"],
        }
    )


def _failed_document_version(
    document: dict[str, Any], config: dict[str, Any], error: Exception
) -> dict[str, Any]:
    document_version_id = document_version_id_for(document, config)
    extraction_configuration = extraction_configuration_for(document, config)
    result = artifact_base("DocumentVersion", document_version_id)
    result.update(
        {
            "document_version_id": document_version_id,
            "document_id": document["document_id"],
            "source_sha256": document["source_sha256"],
            "extraction_status": "processing_failed",
            "toolchain": _toolchain(str(document["media_type"])),
            "extraction_configuration": extraction_configuration,
            "extraction_configuration_hash": extraction_configuration_hash_for(document, config),
            "normalization_version": NORMALIZATION_VERSION,
            "normalized_path": "",
            "pages": [],
            "warnings": [
                {"category": "processing_failed", "message": f"{type(error).__name__}: {error}"}
            ],
        }
    )
    return result


def _extract_markdown(
    workspace: Path,
    source: Path,
    document: dict[str, Any],
    config: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    warnings: list[dict[str, Any]] = []
    raw = source.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
        status = "extracted"
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
        status = "partially_extracted"
        warnings.append(
            {"category": "encoding_replacement", "message": "Invalid UTF-8 bytes were replaced"}
        )
    normalized = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    markdown_metadata = _markdown_metadata(normalized)
    document_version_id = document_version_id_for(document, config)
    extraction_configuration = extraction_configuration_for(document, config)
    relative = Path("documents") / "normalized" / document_version_id / "document.md"
    write_text_atomic(workspace / relative, normalized, root=workspace)
    sections = _markdown_sections(normalized)
    chunks = _make_chunks(
        document,
        document_version_id,
        normalized,
        sections,
        config,
    )
    artifact = artifact_base("DocumentVersion", document_version_id)
    artifact.update(
        {
            "document_version_id": document_version_id,
            "document_id": document["document_id"],
            "source_sha256": document["source_sha256"],
            "extraction_status": status,
            "toolchain": _toolchain("text/markdown"),
            "extraction_configuration": extraction_configuration,
            "extraction_configuration_hash": extraction_configuration_hash_for(document, config),
            "normalization_version": NORMALIZATION_VERSION,
            "normalized_path": relative.as_posix(),
            "normalized_sha256": f"sha256:{file_sha256(workspace / relative)}",
            "pages": [],
            "metadata": {
                "source_line_count": len(normalized.splitlines()),
                **markdown_metadata,
            },
            "warnings": warnings,
        }
    )
    return artifact, chunks, warnings


def _markdown_sections(text: str) -> list[dict[str, Any]]:
    lines = text.splitlines(keepends=True)
    headings: list[str] = []
    sections: list[dict[str, Any]] = []
    offset = 0
    current_start = 0
    current_line = 1
    current_path: list[str] = []
    for number, line in enumerate(lines, start=1):
        match = _HEADING.match(line.rstrip("\n"))
        if match:
            if offset > current_start:
                sections.append(
                    {
                        "start": current_start,
                        "end": offset,
                        "line_start": current_line,
                        "line_end": number - 1,
                        "section_path": list(current_path),
                        "page": None,
                    }
                )
            level = len(match.group(1))
            headings = headings[: level - 1]
            headings.append(match.group(2).strip())
            current_path = list(headings)
            current_start = offset
            current_line = number
        offset += len(line)
    if offset > current_start or not sections:
        sections.append(
            {
                "start": current_start,
                "end": len(text),
                "line_start": current_line,
                "line_end": max(current_line, len(lines)),
                "section_path": list(current_path),
                "page": None,
            }
        )
    return sections


def _markdown_metadata(text: str) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        try:
            closing = next(
                index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"
            )
            frontmatter = yaml.safe_load("\n".join(lines[1:closing]))
            if isinstance(frontmatter, dict):
                for key in (
                    "title",
                    "author",
                    "authors",
                    "organization",
                    "publication_date",
                    "date",
                    "language",
                    "doi",
                    "arxiv_id",
                    "isbn",
                    "source_url",
                    "dataset_id",
                    "version_of",
                ):
                    if key in frontmatter and isinstance(frontmatter[key], (str, int, float, list)):
                        metadata[key] = frontmatter[key]
        except (StopIteration, yaml.YAMLError):
            metadata["frontmatter_status"] = "ambiguous"
    metadata["link_destinations"] = sorted(set(re.findall(r"\[[^\]]*\]\(([^)]+)\)", text)))
    return metadata


def _extract_pdf(
    workspace: Path,
    source: Path,
    document: dict[str, Any],
    config: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    warnings: list[dict[str, Any]] = []
    if not source.read_bytes()[:5].startswith(b"%PDF-"):
        raise ValueError("File does not have a PDF signature")
    reader = PdfReader(str(source))
    if reader.is_encrypted:
        raise ValueError("Encrypted PDFs are unsupported in the MVP")
    document_version_id = document_version_id_for(document, config)
    extraction_configuration = extraction_configuration_for(document, config)
    dpi = int(config["pdf"]["render_dpi"])
    minimum_chars = int(config["pdf"]["minimum_usable_characters"])
    pdf_document = pdfium.PdfDocument(str(source))
    page_records: list[dict[str, Any]] = []
    sections: list[dict[str, Any]] = []
    normalized_parts: list[str] = []
    with pdfplumber.open(str(source)) as plumber:
        page_count = max(len(reader.pages), len(plumber.pages), len(pdf_document))
        if page_count > int(config["pdf"]["maximum_pages"]):
            raise ValueError(
                f"PDF has {page_count} pages; configured maximum is {config['pdf']['maximum_pages']}"
            )
        for page_index in range(page_count):
            page_number = page_index + 1
            marker = f"<!-- page: {page_number} -->\n\n"
            part_start = sum(len(item) for item in normalized_parts)
            normalized_parts.append(marker)
            page_text = ""
            page_warnings: list[dict[str, Any]] = []
            tables: list[Any] = []
            regions: list[dict[str, Any]] = []
            headings: list[str] = []
            width = 0.0
            height = 0.0
            if page_index < len(plumber.pages):
                page = plumber.pages[page_index]
                width, height = float(page.width), float(page.height)
                try:
                    page_text = page.extract_text() or ""
                except Exception as exc:
                    page_warnings.append(
                        {"category": "text_extraction_failed", "message": str(exc)}
                    )
                try:
                    tables = page.extract_tables() or []
                except Exception as exc:
                    page_warnings.append(
                        {"category": "table_extraction_failed", "message": str(exc)}
                    )
                regions.extend(_visual_regions(page, page_text, page_number))
                headings = _pdf_heading_candidates(page)
                try:
                    regions.extend(_table_regions(page, page_number))
                except Exception as exc:
                    page_warnings.append(
                        {"category": "table_region_detection_failed", "message": str(exc)}
                    )
            estimated_pixels = max(width, 612.0) * dpi / 72.0 * max(height, 792.0) * dpi / 72.0
            if estimated_pixels > int(config["pdf"]["maximum_render_pixels_per_page"]):
                raise ValueError(f"Page {page_number} exceeds the configured render pixel limit")
            normalized_page = unicodedata.normalize("NFC", page_text.replace("\r", ""))
            normalized_parts.append(normalized_page + "\n\n")
            text_start = part_start + len(marker)
            sections.append(
                {
                    "start": text_start,
                    "end": text_start + len(normalized_page),
                    "line_start": None,
                    "line_end": None,
                    "section_path": headings[:1] or [f"Page {page_number}"],
                    "page": page_number,
                }
            )
            render_record = _render_pdf_page(
                workspace, pdf_document, document_version_id, page_index, page_number, dpi
            )
            table_records: list[dict[str, Any]] = []
            for table_index, table in enumerate(tables, start=1):
                relative_table = (
                    Path("documents")
                    / "tables"
                    / document_version_id
                    / f"page-{page_number:05d}-table-{table_index:03d}.json"
                )
                write_json_atomic(
                    workspace / relative_table,
                    {"page": page_number, "rows": table},
                    root=workspace,
                )
                table_records.append(
                    {
                        "path": relative_table.as_posix(),
                        "sha256": f"sha256:{file_sha256(workspace / relative_table)}",
                        "extraction_status": "extracted",
                    }
                )
            usable_characters = sum(1 for char in normalized_page if not char.isspace())
            ocr_required = usable_characters < minimum_chars
            if ocr_required:
                page_warnings.append(
                    {
                        "category": "ocr_required",
                        "message": f"Page has {usable_characters} usable extracted characters",
                    }
                )
            page_records.append(
                {
                    "page": page_number,
                    "text_character_count": len(normalized_page),
                    "usable_character_count": usable_characters,
                    "extraction_status": "ocr_required" if ocr_required else "extracted",
                    "ocr_required": ocr_required,
                    "render": render_record,
                    "page_dimensions_points": {"width": width, "height": height},
                    "tables": table_records,
                    "table_detection_status": "extracted" if tables else "not_detected",
                    "visual_regions": regions,
                    "figure_detection_status": (
                        "ambiguous"
                        if any("figure" in item["region_type"] for item in regions)
                        else "not_detected"
                    ),
                    "detected_headings": headings,
                    "warnings": page_warnings,
                }
            )
            warnings.extend({**warning, "page": page_number} for warning in page_warnings)
    normalized = "".join(normalized_parts)
    normalized_relative = Path("documents") / "normalized" / document_version_id / "document.md"
    write_text_atomic(workspace / normalized_relative, normalized, root=workspace)
    chunks = _make_chunks(document, document_version_id, normalized, sections, config)
    ocr_pages = [record["page"] for record in page_records if record["ocr_required"]]
    if ocr_pages and len(ocr_pages) == len(page_records):
        status = "ocr_required"
    elif ocr_pages or warnings:
        status = "partially_extracted"
    else:
        status = "extracted"
    metadata: dict[str, Any] = dict(reader.metadata or {})
    artifact = artifact_base("DocumentVersion", document_version_id)
    artifact.update(
        {
            "document_version_id": document_version_id,
            "document_id": document["document_id"],
            "source_sha256": document["source_sha256"],
            "extraction_status": status,
            "toolchain": _toolchain("application/pdf"),
            "extraction_configuration": extraction_configuration,
            "extraction_configuration_hash": extraction_configuration_hash_for(document, config),
            "normalization_version": NORMALIZATION_VERSION,
            "normalized_path": normalized_relative.as_posix(),
            "normalized_sha256": f"sha256:{file_sha256(workspace / normalized_relative)}",
            "pages": page_records,
            "metadata": {
                "title": metadata.get("/Title"),
                "author": metadata.get("/Author"),
                "subject": metadata.get("/Subject"),
                "page_count": len(page_records),
                "ocr_required_pages": ocr_pages,
            },
            "render_configuration": {"dpi": dpi, "format": "png", "color_mode": "RGB"},
            "warnings": warnings,
        }
    )
    return artifact, chunks, warnings


def _render_pdf_page(
    workspace: Path,
    pdf_document: Any,
    document_version_id: str,
    page_index: int,
    page_number: int,
    dpi: int,
) -> dict[str, Any]:
    page = pdf_document[page_index]
    bitmap = page.render(scale=dpi / 72.0)
    image = bitmap.to_pil().convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=False)
    data = buffer.getvalue()
    relative = Path("documents") / "renders" / document_version_id / f"page-{page_number:05d}.png"
    write_bytes_atomic(workspace / relative, data, root=workspace)
    return {
        "path": relative.as_posix(),
        "sha256": prefixed_sha256(data),
        "width": image.width,
        "height": image.height,
        "dpi": dpi,
        "format": "png",
        "renderer": "pypdfium2",
        "renderer_version": _tool_version("pypdfium2"),
    }


def _visual_regions(page: Any, text: str, page_number: int) -> list[dict[str, Any]]:
    regions: list[dict[str, Any]] = []
    width = float(page.width) or 1.0
    height = float(page.height) or 1.0
    for image_index, image in enumerate(page.images, start=1):
        x0 = max(0.0, float(image.get("x0", 0.0)))
        x1 = min(width, float(image.get("x1", width)))
        top = max(0.0, float(image.get("top", 0.0)))
        bottom = min(height, float(image.get("bottom", height)))
        regions.append(
            {
                "region_id": f"page-{page_number}-image-{image_index}",
                "region_type": "figure_candidate",
                "bounding_box": {
                    "x": x0 / width,
                    "y": top / height,
                    "width": max(0.0, x1 - x0) / width,
                    "height": max(0.0, bottom - top) / height,
                },
                "coordinate_system": "normalized_top_left_0_to_1",
                "detection_status": "ambiguous",
                "caption": None,
            }
        )
    drawings = [
        *getattr(page, "rects", []),
        *getattr(page, "curves", []),
        *getattr(page, "lines", []),
    ]
    drawing_boxes: list[tuple[float, float, float, float]] = []
    for drawing in drawings:
        try:
            x0 = max(0.0, float(drawing.get("x0", 0.0)))
            x1 = min(width, float(drawing.get("x1", width)))
            top = max(0.0, float(drawing.get("top", 0.0)))
            bottom = min(height, float(drawing.get("bottom", height)))
        except (TypeError, ValueError):
            continue
        if x1 > x0 or bottom > top:
            drawing_boxes.append((x0, top, x1, bottom))
    if drawing_boxes:
        x0 = min(item[0] for item in drawing_boxes)
        top = min(item[1] for item in drawing_boxes)
        x1 = max(item[2] for item in drawing_boxes)
        bottom = max(item[3] for item in drawing_boxes)
        area_ratio = max(0.0, x1 - x0) * max(0.0, bottom - top) / (width * height)
        if 0.01 <= area_ratio <= 0.95:
            regions.append(
                {
                    "region_id": f"page-{page_number}-drawing-region",
                    "region_type": "vector_figure_candidate",
                    "bounding_box": {
                        "x": x0 / width,
                        "y": top / height,
                        "width": (x1 - x0) / width,
                        "height": (bottom - top) / height,
                    },
                    "coordinate_system": "normalized_top_left_0_to_1",
                    "detection_status": "ambiguous",
                    "caption": None,
                }
            )
    captions = [line.strip() for line in text.splitlines() if _FIGURE_CAPTION.match(line)]
    if captions and not regions:
        regions.append(
            {
                "region_id": f"page-{page_number}-vector-figure-candidate",
                "region_type": "vector_figure_candidate",
                "bounding_box": {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0},
                "coordinate_system": "normalized_top_left_0_to_1",
                "detection_status": "ambiguous",
                "caption": captions[0],
            }
        )
    elif captions:
        for region, caption in zip(regions, captions, strict=False):
            region["caption"] = caption
    return regions


def _table_regions(page: Any, page_number: int) -> list[dict[str, Any]]:
    width = float(page.width) or 1.0
    height = float(page.height) or 1.0
    regions: list[dict[str, Any]] = []
    for index, table in enumerate(page.find_tables() or [], start=1):
        x0, top, x1, bottom = (float(value) for value in table.bbox)
        regions.append(
            {
                "region_id": f"page-{page_number}-table-{index}",
                "region_type": "table_candidate",
                "bounding_box": {
                    "x": max(0.0, x0) / width,
                    "y": max(0.0, top) / height,
                    "width": max(0.0, min(width, x1) - max(0.0, x0)) / width,
                    "height": max(0.0, min(height, bottom) - max(0.0, top)) / height,
                },
                "coordinate_system": "normalized_top_left_0_to_1",
                "detection_status": "ambiguous",
                "caption": None,
            }
        )
    return regions


def _pdf_heading_candidates(page: Any) -> list[str]:
    characters = [item for item in page.chars if isinstance(item.get("size"), (int, float))]
    if not characters:
        return []
    sizes = sorted(float(item["size"]) for item in characters)
    median = sizes[len(sizes) // 2]
    large = [item for item in characters if float(item["size"]) >= median * 1.2]
    lines: dict[int, list[dict[str, Any]]] = {}
    for item in large:
        lines.setdefault(round(float(item.get("top", 0.0))), []).append(item)
    headings: list[str] = []
    for top in sorted(lines):
        ordered = sorted(lines[top], key=lambda value: float(value.get("x0", 0.0)))
        cleaned = " ".join("".join(str(item.get("text", "")) for item in ordered).split())
        if 2 <= len(cleaned) <= 160:
            headings.append(cleaned)
    return headings[:10]


def _make_chunks(
    document: dict[str, Any],
    document_version_id: str,
    normalized: str,
    sections: list[dict[str, Any]],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    maximum = int(config["chunking"]["max_characters"])
    overlap = int(config["chunking"]["overlap_characters"])
    if maximum <= 0 or overlap < 0 or overlap >= maximum:
        raise ResearchError("Invalid chunking configuration", category="invalid_config")
    chunks: list[dict[str, Any]] = []
    for section in sections:
        position = int(section["start"])
        end = int(section["end"])
        first_in_section = True
        while position < end:
            proposed = min(position + maximum, end)
            if proposed < end:
                break_at = normalized.rfind("\n", position + maximum // 2, proposed)
                if break_at > position:
                    proposed = break_at + 1
            exact = normalized[position:proposed]
            if exact.strip():
                identity = {
                    "document_version_id": document_version_id,
                    "page": section["page"],
                    "section_path": section["section_path"],
                    "start_offset": position,
                    "end_offset": proposed,
                    "chunking_configuration": config["chunking"],
                }
                chunk_id = derived_identifier("CHK", identity)
                chunk = artifact_base("Chunk", chunk_id)
                line_start = section["line_start"]
                line_end = section["line_end"]
                if section["page"] is None:
                    line_start = normalized.count("\n", 0, position) + 1
                    line_end = normalized.count("\n", 0, proposed) + 1
                chunk.update(
                    {
                        "chunk_id": chunk_id,
                        "document_id": document["document_id"],
                        "document_version_id": document_version_id,
                        "page": section["page"],
                        "source_line_start": line_start,
                        "source_line_end": line_end,
                        "section_path": section["section_path"],
                        "start_offset": position,
                        "end_offset": proposed,
                        "exact_text": exact,
                        "text_sha256": prefixed_sha256(exact.encode("utf-8")),
                        "context_boundaries": {
                            "section_start": section["start"],
                            "section_end": section["end"],
                        },
                        "chunking_version": CHUNKING_VERSION,
                        "chunking_configuration": dict(config["chunking"]),
                        "chunking_configuration_hash": config_hash(config["chunking"]),
                        "overlap_characters": 0 if first_in_section else overlap,
                        "index_eligible": True,
                        "warnings": [],
                    }
                )
                chunks.append(chunk)
                first_in_section = False
            if proposed >= end:
                break
            position = max(position + 1, proposed - overlap)
    return chunks


def _iter_document_manifests(workspace: Path) -> list[dict[str, Any]]:
    from research.io import iter_json
    from research.schema_registry import SchemaRegistry

    result = list(iter_json(workspace / "documents" / "manifests"))
    registry = SchemaRegistry()
    for artifact in result:
        registry.validate(artifact)
        if not verify_artifact_hash(artifact):
            raise ResearchError("Stored Document artifact hash does not match")
    return result


def _iter_document_versions(workspace: Path) -> list[dict[str, Any]]:
    from research.io import iter_json
    from research.schema_registry import SchemaRegistry

    result = list(iter_json(workspace / "documents" / "versions"))
    registry = SchemaRegistry()
    for artifact in result:
        registry.validate(artifact)
        if not verify_artifact_hash(artifact):
            raise ResearchError("Stored DocumentVersion artifact hash does not match")
    return result


def _iter_chunks(workspace: Path) -> list[dict[str, Any]]:
    from research.io import iter_json
    from research.schema_registry import SchemaRegistry

    result = list(iter_json(workspace / "documents" / "chunks"))
    registry = SchemaRegistry()
    for artifact in result:
        registry.validate(artifact)
        if not verify_artifact_hash(artifact):
            raise ResearchError("Stored Chunk artifact hash does not match")
    return result


def _rechunk_existing_version(
    workspace: Path,
    document: dict[str, Any],
    version_artifact: dict[str, Any],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    normalized_path = workspace / str(version_artifact["normalized_path"])
    normalized = normalized_path.read_text(encoding="utf-8")
    if document["media_type"] == "text/markdown":
        sections = _markdown_sections(normalized)
    else:
        sections = _pdf_sections_from_normalized(normalized, version_artifact.get("pages", []))
    return _make_chunks(
        document,
        str(version_artifact["document_version_id"]),
        normalized,
        sections,
        config,
    )


def _pdf_sections_from_normalized(
    normalized: str, pages: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    markers = list(re.finditer(r"<!-- page: (\d+) -->\n\n", normalized))
    sections: list[dict[str, Any]] = []
    for index, marker in enumerate(markers):
        page_number = int(marker.group(1))
        start = marker.end()
        end = markers[index + 1].start() if index + 1 < len(markers) else len(normalized)
        page = next((item for item in pages if item.get("page") == page_number), {})
        headings = page.get("detected_headings", [])
        sections.append(
            {
                "start": start,
                "end": end,
                "line_start": None,
                "line_end": None,
                "section_path": headings[:1] or [f"Page {page_number}"],
                "page": page_number,
            }
        )
    return sections
