"""`research inspect` — resolve an artifact id and show enough to verify it.

THE PURPOSE IS VERIFICATION, NOT DISPLAY (spec §8.7): *"For evidence inspection, the command should
show enough context to verify whether the cited passage genuinely supports the associated claim."*

So inspecting a chunk or a piece of evidence does not print what the artifact *claims* its text is —
it re-slices the stored normalized text at the recorded offsets and prints that, along with the
resolution status. If the two ever disagree, inspect says so. An inspector that trusts the artifact
it is inspecting cannot detect the one failure that matters.
"""

from __future__ import annotations

from typing import Any

from ..artifacts.io import read_artifact
from ..artifacts.locators import resolve_text_locator
from ..config import Workspace
from ..errors import InvalidArguments
from ..security.paths import safe_join

CONTEXT_CHARS = 300


def _documents(ws: Workspace) -> list[dict[str, Any]]:
    return [read_artifact(p, expect_schema="Document")
            for p in sorted(safe_join(ws.root, "documents", "manifests").glob("*.json"))]


def _find_document(ws: Workspace, document_id: str) -> dict[str, Any] | None:
    for doc in _documents(ws):
        if doc["document_id"] == document_id:
            return doc
    return None


def _normalized_text(ws: Workspace, doc: dict[str, Any]) -> str:
    path = ws.root / doc["normalized_text_path"]
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def inspect(ws: Workspace, artifact_id: str) -> dict[str, Any]:
    """Dispatch on the identifier prefix."""
    if artifact_id.startswith("DOC-sha256-"):
        return _inspect_document(ws, artifact_id)
    if artifact_id.startswith("CHK-sha256-"):
        return _inspect_chunk(ws, artifact_id)
    if artifact_id.startswith("RUN-"):
        return _inspect_run(ws, artifact_id)
    raise InvalidArguments(
        f"unrecognised artifact id: {artifact_id!r}",
        detail={"supported_prefixes": ["DOC-sha256-", "CHK-sha256-", "RUN-"],
                "note": "EVD-, CLM- and REV- inspection arrives with Phase 6 artifacts"})


def _inspect_document(ws: Workspace, document_id: str) -> dict[str, Any]:
    doc = _find_document(ws, document_id)
    if doc is None:
        raise InvalidArguments(f"no document {document_id!r} in this workspace",
                               detail={"hint": "run `research import <path>`"})
    renders = [
        {"page": p["page_number"], "render_sha256": p["render"]["sha256"],
         "path": p["render"]["path"], "width": p["render"]["width"],
         "height": p["render"]["height"]}
        for p in doc.get("pages", []) if p.get("render")
    ]
    return {
        "kind": "document",
        "document_id": doc["document_id"],
        "document_version_id": doc["document_version_id"],
        "source_sha256": doc["source_sha256"],
        "media_type": doc["media_type"],
        "aliases": doc["original_filename_aliases"],
        "extraction_status": doc["extraction_status"],
        "extraction_warnings": doc.get("extraction_warnings", []),
        "ocr_required_pages": doc.get("ocr_required_pages", []),
        "page_count": doc.get("page_count"),
        "chunk_count": doc.get("chunk_count"),
        "index_eligible_chunk_count": doc.get("index_eligible_chunk_count"),
        "normalization_not_performed": doc.get("normalization_not_performed", []),
        "stored_original": doc["stored_original"],
        "renders": renders,
        "artifact_hash": doc["artifact_hash"],
    }


def _inspect_chunk(ws: Workspace, chunk_id: str) -> dict[str, Any]:
    for doc in _documents(ws):
        rel = doc.get("chunk_set_path")
        if not rel:
            continue
        chunk_set = read_artifact(ws.root / rel, expect_schema="ChunkSet")
        for chunk in chunk_set["chunks"]:
            if chunk["chunk_id"] != chunk_id:
                continue
            text = _normalized_text(ws, doc)
            locator = {
                "type": "text_span", "page": chunk["page"],
                "section_path": chunk["section_path"], "chunk_id": chunk["chunk_id"],
                "start_offset": chunk["start_offset"], "end_offset": chunk["end_offset"],
                "source_line_start": chunk["line_start"], "source_line_end": chunk["line_end"],
                "span_sha256": chunk["text_sha256"],
            }
            # Re-slice rather than trusting the stored text: that comparison is the whole point.
            resolution = resolve_text_locator(locator, text)
            before = text[max(0, chunk["start_offset"] - CONTEXT_CHARS):chunk["start_offset"]]
            after = text[chunk["end_offset"]:chunk["end_offset"] + CONTEXT_CHARS]
            return {
                "kind": "chunk",
                "chunk_id": chunk["chunk_id"],
                "document_id": chunk["document_id"],
                "document_version_id": chunk["document_version_id"],
                "page": chunk["page"],
                "line_start": chunk["line_start"],
                "line_end": chunk["line_end"],
                "section_path": chunk["section_path"],
                "locator": locator,
                "resolution_status": str(resolution.status),
                "resolves": resolution.ok,
                "resolved_text": resolution.text,
                "context_before": before,
                "context_after": after,
                "index_eligible": chunk["index_eligible"],
                "extraction_status": chunk["extraction_status"],
                "warnings": chunk["warnings"],
                "evidence_note":
                    "A chunk is a retrieval unit, not evidence. Citing it requires an Evidence "
                    "record with its own locator and a citation review.",
            }
    raise InvalidArguments(f"no chunk {chunk_id!r} in this workspace",
                           detail={"hint": "chunk ids come from `research search`"})


def _inspect_run(ws: Workspace, run_id: str) -> dict[str, Any]:
    from .manager import load_run, status

    manifest = load_run(ws, run_id)
    events_path = safe_join(ws.root, "runs", run_id) / "events.jsonl"
    events = []
    if events_path.is_file():
        import json
        events = [json.loads(line) for line in
                  events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return {
        "kind": "run",
        "run_id": manifest["run_id"],
        "research_question": manifest["research_question"],
        "profile": manifest["profile"],
        "phase": manifest["phase"],
        "disposition": manifest["disposition"],
        "workflow_version": manifest["workflow_version"],
        "config_hash": manifest["config_hash"],
        "source_collection": manifest["source_collection"],
        "packet_paths": manifest["packet_paths"],
        "event_count": len(events),
        "events": events,
        "status": status(ws, run_id),
        "artifact_hash": manifest["artifact_hash"],
    }
