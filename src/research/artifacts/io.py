"""Canonical artifact read/write.

Every canonical artifact gets the common envelope (spec §14), a correct `artifact_hash`, and an
atomic write. Reading verifies the hash: an artifact whose recorded hash does not match its content
has been edited outside the amendment process, which spec §26 makes a human-review trigger — not
something to repair silently.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..errors import SchemaValidationError, UnsupportedVersionError
from ..hashing import canonical_json, stamp_artifact_hash, verify_artifact_hash
from ..security.paths import atomic_write_text

SUPPORTED_SCHEMA_MAJOR = 1


def now_rfc3339() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def make_artifact(
    *,
    schema_name: str,
    artifact_id: str,
    body: dict[str, Any],
    schema_version: str = "1.0.0",
    actor_type: str = "cli",
    host: str | None = None,
    model_identifier: str | None = None,
) -> dict[str, Any]:
    """Build a canonical artifact with its envelope and a correct hash.

    `created_by` records who produced this. `actor_type` "cli" means deterministic code produced it;
    "host_agent" means a model did. That distinction is what lets validation apply different trust
    to a locator this package computed versus a rationale an agent wrote (spec §43).
    """
    created_by: dict[str, Any] = {"actor_type": actor_type}
    if host:
        created_by["host"] = host
    if model_identifier:
        created_by["model_identifier"] = model_identifier

    artifact = {
        "schema_name": schema_name,
        "schema_version": schema_version,
        "artifact_id": artifact_id,
        "created_at": now_rfc3339(),
        "created_by": created_by,
        **body,
    }
    return stamp_artifact_hash(artifact)


def write_artifact(path: str | Path, artifact: dict[str, Any], *,
                   root: str | Path | None = None, validate: bool = True) -> Path:
    """Validate, stamp, and atomically write a canonical artifact.

    Validation happens BEFORE the write. Once an artifact is on disk it has been counted — reported
    in a summary, possibly consumed by the index — and rejecting it later leaves a workspace that is
    internally inconsistent rather than one that never accepted the bad data.

    Storing indented JSON while hashing the canonical form is the point of canonicalization: the
    file stays readable in a diff without its identity depending on layout.
    """
    if validate:
        from .registry import validate_artifact
        validate_artifact(artifact, path=path)
    if not verify_artifact_hash(artifact):
        artifact = stamp_artifact_hash(artifact)
    import json

    return atomic_write_text(
        path, json.dumps(artifact, indent=2, ensure_ascii=False) + "\n", root=root)


def read_artifact(path: str | Path, *, expect_schema: str | None = None,
                  verify_hash: bool = True) -> dict[str, Any]:
    """Read an artifact, checking schema version and content hash."""
    import json

    with open(path, encoding="utf-8") as fh:
        artifact: dict[str, Any] = json.load(fh)

    version = artifact.get("schema_version", "")
    major = version.split(".")[0] if version else ""
    if not major.isdigit() or int(major) != SUPPORTED_SCHEMA_MAJOR:
        raise UnsupportedVersionError(
            f"artifact schema_version {version!r} is not supported by this build "
            f"(supported major: {SUPPORTED_SCHEMA_MAJOR})",
            detail={"path": str(path), "found": version})

    if expect_schema and artifact.get("schema_name") != expect_schema:
        raise SchemaValidationError(
            f"expected a {expect_schema} artifact, found {artifact.get('schema_name')!r}",
            detail={"path": str(path)})

    if verify_hash and not verify_artifact_hash(artifact):
        raise SchemaValidationError(
            "artifact_hash does not match content — this artifact was modified outside the "
            "amendment process",
            detail={"path": str(path), "recorded": artifact.get("artifact_hash")})
    return artifact


def append_event(path: str | Path, event: dict[str, Any], *,
                 root: str | Path | None = None) -> None:
    """Append one canonical JSON line to an append-only log.

    Import events and lifecycle events are append-only (spec §11, §8.2). Written as JSONL and never
    rewritten, so history cannot be edited by a later run — only added to.
    """
    p = Path(path)
    if root is not None:
        from ..security.paths import assert_within
        assert_within(root, p)
    p.parent.mkdir(parents=True, exist_ok=True)
    line = canonical_json({"recorded_at": now_rfc3339(), **event})
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")
