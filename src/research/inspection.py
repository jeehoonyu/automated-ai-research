from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from research.canonical import verify_artifact_hash
from research.errors import ResearchError
from research.io import iter_json
from research.schema_registry import SchemaRegistry


def inspect_artifact(workspace: Path, artifact_id: str) -> dict[str, Any]:
    matches: list[tuple[Path, dict[str, Any]]] = []
    roots = [workspace / "documents", workspace / "indexes" / "manifests", workspace / "runs"]
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.json"), key=lambda item: item.as_posix()):
            if root == workspace / "runs" and "responses" in path.relative_to(root).parts:
                continue
            try:
                with path.open("r", encoding="utf-8") as handle:
                    value = json.load(handle)
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(value, dict):
                continue
            identifiers = {
                value.get("artifact_id"),
                value.get("document_id"),
                value.get("document_version_id"),
                value.get("chunk_id"),
                value.get("evidence_id"),
                value.get("claim_id"),
                value.get("review_id"),
                value.get("validation_result_id"),
            }
            if value.get("schema_name") == "DocumentVersion":
                version_id = str(value.get("document_version_id", ""))
                for page in value.get("pages", []):
                    page_number = page.get("page")
                    render = page.get("render", {})
                    identifiers.update(
                        {
                            render.get("sha256"),
                            f"{version_id}/page/{page_number}",
                        }
                    )
                    for region in page.get("visual_regions", []):
                        region_id = region.get("region_id")
                        identifiers.update(
                            {
                                region_id,
                                f"{version_id}/region/{region_id}",
                            }
                        )
            if artifact_id in identifiers:
                matches.append((path, value))
    if not matches:
        raise ResearchError(f"Artifact not found: {artifact_id}", category="artifact_not_found")
    exact_matches = [pair for pair in matches if pair[1].get("artifact_id") == artifact_id]
    path, artifact = max(
        exact_matches or matches,
        key=lambda pair: str(pair[1].get("created_at", "")),
    )
    integrity_errors: list[str] = []
    try:
        SchemaRegistry().validate(artifact)
    except ResearchError as exc:
        integrity_errors.append(str(exc))
    if not verify_artifact_hash(artifact):
        integrity_errors.append("artifact hash does not match content")
    context: dict[str, Any] = {}
    if artifact.get("schema_name") == "Evidence":
        context = _evidence_context(workspace, artifact)
    elif artifact.get("schema_name") == "DocumentVersion":
        selected_page = _selected_page_lookup(artifact, artifact_id)
        selected_region = _selected_region_lookup(artifact, artifact_id)
        context = {
            "normalized_path": str(workspace / str(artifact.get("normalized_path", ""))),
            "page_renders": [
                {
                    "page": page.get("page"),
                    "path": str(workspace / str(page.get("render", {}).get("path", ""))),
                    "sha256": page.get("render", {}).get("sha256"),
                }
                for page in artifact.get("pages", [])
            ],
            "selected_page": selected_page,
            "selected_visual_region": selected_region,
        }
    elif artifact.get("schema_name") == "Document":
        context = {
            "original_path": str(workspace / str(artifact.get("original_storage_path", ""))),
            "import_aliases": _import_aliases(workspace, str(artifact["document_id"])),
        }
    elif artifact.get("schema_name") == "Claim":
        context = {
            "supporting_evidence": _resolve_ids(
                workspace, set(artifact.get("supporting_evidence_ids", []))
            ),
            "contradicting_evidence": _resolve_ids(
                workspace, set(artifact.get("contradicting_evidence_ids", []))
            ),
            "reviews": _reviews_for(workspace, str(artifact["claim_id"])),
        }
    elif artifact.get("schema_name") == "Review":
        context = {
            "reviewed_artifacts": _resolve_ids(
                workspace, set(artifact.get("reviewed_artifact_ids", []))
            )
        }
    return {
        "artifact_id": artifact_id,
        "artifact_path": str(path),
        "artifact": artifact,
        "context": context,
        "integrity": {"valid": not integrity_errors, "errors": integrity_errors},
    }


def _selected_page_lookup(version: dict[str, Any], lookup: str) -> dict[str, Any] | None:
    version_id = str(version.get("document_version_id", ""))
    for page in version.get("pages", []):
        render = page.get("render", {})
        if lookup in {render.get("sha256"), f"{version_id}/page/{page.get('page')}"}:
            return {
                "page": page.get("page"),
                "render": render,
                "ocr_required": page.get("ocr_required"),
                "extraction_status": page.get("extraction_status"),
            }
    return None


def _selected_region_lookup(version: dict[str, Any], lookup: str) -> dict[str, Any] | None:
    version_id = str(version.get("document_version_id", ""))
    for page in version.get("pages", []):
        for region in page.get("visual_regions", []):
            region_id = region.get("region_id")
            if lookup in {region_id, f"{version_id}/region/{region_id}"}:
                return {"page": page.get("page"), **region}
    return None


def _evidence_context(workspace: Path, evidence: dict[str, Any]) -> dict[str, Any]:
    locator = evidence.get("locator", {})
    context: dict[str, Any] = {
        "exact_text": evidence.get("exact_text"),
        "context_before": evidence.get("context_before"),
        "context_after": evidence.get("context_after"),
    }
    if locator.get("type") == "text_span":
        chunk_id = locator.get("chunk_id")
        chunk = next(
            (
                item
                for item in iter_json(workspace / "documents" / "chunks")
                if item.get("chunk_id") == chunk_id
            ),
            None,
        )
        if chunk:
            start = max(0, int(locator.get("start_offset", 0)) - 240)
            end = min(len(chunk["exact_text"]), int(locator.get("end_offset", 0)) + 240)
            context["resolved_chunk_context"] = chunk["exact_text"][start:end]
            context["chunk_id"] = chunk_id
    elif locator.get("type") == "visual_region":
        context.update(
            {
                "page": locator.get("page"),
                "render_sha256": locator.get("render_sha256"),
                "bounding_box": locator.get("bounding_box"),
                "page_render_path": _find_render(workspace, evidence, locator),
            }
        )
    return context


def _find_render(workspace: Path, evidence: dict[str, Any], locator: dict[str, Any]) -> str | None:
    version_id = evidence.get("document_version_id")
    for version in iter_json(workspace / "documents" / "versions"):
        if version.get("document_version_id") != version_id:
            continue
        page = next(
            (item for item in version.get("pages", []) if item.get("page") == locator.get("page")),
            None,
        )
        if page:
            return str(workspace / str(page.get("render", {}).get("path", "")))
    return None


def _import_aliases(workspace: Path, document_id: str) -> list[str]:
    path = workspace / "imports" / "import-events.jsonl"
    if not path.is_file():
        return []
    aliases: list[str] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("document_id") == document_id and isinstance(
                event.get("source_path"), str
            ):
                aliases.append(event["source_path"])
    return sorted(set(aliases))


def _resolve_ids(workspace: Path, identifiers: set[str]) -> list[dict[str, Any]]:
    if not identifiers:
        return []
    resolved: list[dict[str, Any]] = []
    for root in (workspace / "documents", workspace / "runs"):
        for value in iter_json(root):
            values = {
                value.get("artifact_id"),
                value.get("document_id"),
                value.get("document_version_id"),
                value.get("chunk_id"),
                value.get("evidence_id"),
                value.get("claim_id"),
                value.get("review_id"),
            }
            if identifiers.intersection(item for item in values if isinstance(item, str)):
                resolved.append(
                    {
                        "artifact_id": value.get("artifact_id"),
                        "schema_name": value.get("schema_name"),
                        "artifact_hash": value.get("artifact_hash"),
                    }
                )
    return resolved


def _reviews_for(workspace: Path, claim_id: str) -> list[dict[str, Any]]:
    return [
        {
            "review_id": value.get("review_id"),
            "review_type": value.get("review_type"),
            "decision": value.get("decision"),
            "reviewer_independence_status": value.get("reviewer_independence_status"),
        }
        for value in iter_json(workspace / "runs")
        if value.get("schema_name") == "Review"
        and claim_id in value.get("reviewed_artifact_ids", [])
    ]
