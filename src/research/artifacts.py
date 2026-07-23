from __future__ import annotations

from pathlib import Path
from typing import Any

from research.canonical import finalize_artifact, sha256_bytes, verify_artifact_hash
from research.constants import EXIT_SCHEMA, SCHEMA_VERSION
from research.errors import ResearchError
from research.io import read_json, utc_now, write_json_atomic
from research.schema_registry import SchemaRegistry
from research.security import ensure_workspace_write

ARTIFACT_DIRECTORIES = {
    "Document": "documents/manifests",
    "DocumentVersion": "documents/versions",
    "Chunk": "documents/chunks",
    "ResearchPlan": "plan",
    "RetrievalResult": "retrieval",
    "Evidence": "evidence",
    "Claim": "claims",
    "Review": "reviews",
    "ValidationResult": "validation",
    "Amendment": "amendments",
    "SourceRelationship": "relationships",
    "StageResponse": "stage-responses",
    "IndexManifest": "indexes/manifests",
    "ReportManifest": "report/manifests",
    "LifecycleEvent": "events",
    "WorkPacket": "packets",
}


def actor(
    actor_type: str = "system", host: str = "research-cli", model: str | None = None
) -> dict[str, Any]:
    return {
        "actor_type": actor_type,
        "host": host,
        "model_identifier": model,
    }


def artifact_base(
    schema_name: str,
    artifact_id: str,
    created_by: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_name": schema_name,
        "schema_version": SCHEMA_VERSION,
        "artifact_id": artifact_id,
        "artifact_hash": "",
        "created_at": utc_now(),
        "created_by": created_by or actor(),
    }


def immutable_artifact_path(base: Path, artifact: dict[str, Any]) -> Path:
    schema_name = str(artifact["schema_name"])
    artifact_id = str(artifact["artifact_id"])
    artifact_hash = str(artifact["artifact_hash"]).removeprefix("sha256:")
    relative = ARTIFACT_DIRECTORIES.get(schema_name, "artifacts")
    # Full IDs and hashes remain in JSON. Short sharded paths avoid Windows MAX_PATH failures;
    # any truncated-path collision is detected by comparing the complete stored artifact.
    id_digest = sha256_bytes(artifact_id.encode("utf-8"))
    return base / relative / id_digest[:2] / id_digest[2:14] / f"{artifact_hash[:32]}.json"


def store_artifact(
    base: Path,
    artifact: dict[str, Any],
    *,
    registry: SchemaRegistry | None = None,
) -> tuple[dict[str, Any], Path]:
    finalized = finalize_artifact(artifact)
    active_registry = registry or SchemaRegistry()
    active_registry.validate(finalized)
    path = ensure_workspace_write(base, immutable_artifact_path(base, finalized))
    if path.exists():
        existing = read_json(path)
        if existing != finalized:
            raise ResearchError(
                f"Artifact hash collision at {path}", category="artifact_hash_collision"
            )
        return finalized, path
    write_json_atomic(path, finalized, root=base)
    return finalized, path


def load_and_verify_artifact(path: Path, registry: SchemaRegistry | None = None) -> dict[str, Any]:
    artifact = read_json(path)
    active_registry = registry or SchemaRegistry()
    active_registry.validate(artifact)
    if not verify_artifact_hash(artifact):
        raise ResearchError(
            f"Artifact hash does not match content: {path}",
            category="artifact_hash_mismatch",
            exit_code=EXIT_SCHEMA,
        )
    return artifact
