from __future__ import annotations

from research.artifacts import artifact_base
from research.canonical import calculate_artifact_hash, finalize_artifact, verify_artifact_hash
from research.identifiers import content_identifier, derived_identifier, run_identifier, uuid7
from research.schema_registry import SchemaRegistry


def test_artifact_hash_ignores_hash_field_and_is_stable() -> None:
    artifact = artifact_base("StageResponse", "STG-test")
    artifact.update(
        {
            "run_id": "RUN-00000000-0000-4000-8000-000000000000",
            "stage": "planning",
            "outcome": "completed",
            "artifact_ids": [],
            "notes": [],
        }
    )
    first = finalize_artifact(artifact)
    second = dict(first)
    second["artifact_hash"] = "sha256:" + "0" * 64
    assert calculate_artifact_hash(first) == calculate_artifact_hash(second)
    assert verify_artifact_hash(first)
    SchemaRegistry().validate(first)


def test_identifiers_keep_full_hashes_and_valid_uuid_variants() -> None:
    assert content_identifier("DOC", "a" * 64) == f"DOC-sha256-{'a' * 64}"
    assert derived_identifier("CHK", {"value": 1}).startswith("CHK-sha256-")
    assert uuid7().version == 7
    assert run_identifier().startswith("RUN-")
