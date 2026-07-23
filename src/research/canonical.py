from __future__ import annotations

import hashlib
from copy import deepcopy
from typing import Any

import rfc8785


def canonical_bytes(value: Any) -> bytes:
    """Return RFC 8785 JSON Canonicalization Scheme bytes."""
    return rfc8785.dumps(value)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def prefixed_sha256(data: bytes) -> str:
    return f"sha256:{sha256_bytes(data)}"


def canonical_sha256(value: Any) -> str:
    return prefixed_sha256(canonical_bytes(value))


def artifact_payload(artifact: dict[str, Any]) -> dict[str, Any]:
    payload = deepcopy(artifact)
    payload.pop("artifact_hash", None)
    return payload


def calculate_artifact_hash(artifact: dict[str, Any]) -> str:
    return canonical_sha256(artifact_payload(artifact))


def finalize_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(artifact)
    result["artifact_hash"] = calculate_artifact_hash(result)
    return result


def verify_artifact_hash(artifact: dict[str, Any]) -> bool:
    value = artifact.get("artifact_hash")
    return isinstance(value, str) and value == calculate_artifact_hash(artifact)
