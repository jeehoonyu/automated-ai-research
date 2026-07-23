from __future__ import annotations

from pathlib import Path

import pytest

from research.artifacts import artifact_base
from research.canonical import calculate_artifact_hash, finalize_artifact, verify_artifact_hash
from research.errors import ResearchError
from research.identifiers import content_identifier, derived_identifier, run_identifier, uuid7
from research.io import write_text_atomic
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


def test_common_artifact_metadata_requires_rfc3339_and_structured_actor() -> None:
    artifact = finalize_artifact(
        {
            "schema_name": "StageResponse",
            "schema_version": "1.0.0",
            "artifact_id": "STG-test",
            "artifact_hash": "",
            "created_at": "tomorrow",
            "created_by": {
                "actor_type": "host_agent",
                "host": "codex",
                "model_identifier": "test",
            },
            "run_id": "RUN-test",
            "stage": "planning",
            "outcome": "blocked",
            "artifact_ids": [],
            "notes": [],
        }
    )
    with pytest.raises(ResearchError) as timestamp_error:
        SchemaRegistry().validate(artifact)
    assert timestamp_error.value.category == "schema_validation_failure"

    artifact["created_at"] = "2026-07-23T12:00:00Z"
    artifact["created_by"] = {}
    artifact = finalize_artifact(artifact)
    with pytest.raises(ResearchError) as actor_error:
        SchemaRegistry().validate(artifact)
    assert actor_error.value.category == "schema_validation_failure"


def test_unsupported_schema_version_fails_with_stable_exit_category() -> None:
    artifact = artifact_base("StageResponse", "STG-unsupported")
    artifact.update(
        {
            "schema_version": "2.0.0",
            "run_id": "RUN-test",
            "stage": "planning",
            "outcome": "blocked",
            "artifact_ids": [],
            "notes": [],
        }
    )
    artifact = finalize_artifact(artifact)
    with pytest.raises(ResearchError) as error:
        SchemaRegistry().validate(artifact)
    assert error.value.category == "unsupported_schema_version"
    assert error.value.exit_code == 8


def test_atomic_write_failure_preserves_existing_file_and_removes_temporary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "artifact.json"
    write_text_atomic(target, "original\n", root=tmp_path)

    def fail_replace(source: str, destination: Path) -> None:
        raise OSError(f"simulated replacement failure for {destination}")

    monkeypatch.setattr("research.io.os.replace", fail_replace)
    with pytest.raises(OSError, match="simulated replacement failure"):
        write_text_atomic(target, "replacement\n", root=tmp_path)
    assert target.read_text(encoding="utf-8") == "original\n"
    assert list(tmp_path.glob(".tmp-*")) == []
