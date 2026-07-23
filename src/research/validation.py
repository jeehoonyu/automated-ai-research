from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from research.artifacts import artifact_base, store_artifact
from research.canonical import canonical_sha256, prefixed_sha256, verify_artifact_hash
from research.config import config_hash, load_config
from research.constants import DISPOSITIONS, EXIT_REPORT_GATE, PHASES, STAGE_PHASES
from research.errors import ResearchError
from research.identifiers import (
    derived_identifier,
    generated_identifier,
    identifier_has_uuid_version,
)
from research.io import file_sha256, iter_json, read_json
from research.runs import (
    STAGE_REQUIREMENTS,
    load_profile,
    load_run,
    transition_after_validation,
)
from research.schema_registry import SchemaRegistry
from research.security import ensure_no_symlink_components, is_within

FACTOR_NAMES = (
    "evidence_directness",
    "source_quality",
    "source_independence",
    "methodology_quality",
    "contradictory_evidence",
    "evidence_coverage",
    "citation_validity",
    "reviewer_agreement",
    "reviewer_independence",
    "visual_certainty",
    "ocr_dependency",
)
FACTOR_VALUES = {"high", "medium", "low", "unknown", "not_applicable"}
DIRECTLY_VERIFIABLE_TYPES = {"direct_fact", "definition", "descriptive_result"}
PASSING_REVIEW_DECISIONS = {"passed", "passed_with_warnings"}
INDEPENDENCE_RANK = {
    "not_independent": 0,
    "not_confirmed": 1,
    "procedurally_isolated": 2,
    "confirmed_independent": 3,
}


def validate_run(workspace: Path, run_id: str) -> tuple[dict[str, Any], int]:
    run_dir, manifest = load_run(workspace, run_id)
    profile = load_profile(workspace, str(manifest["profile"]))
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    human_requirements: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    registry = SchemaRegistry()

    raw_artifacts = _current_run_artifacts(run_dir)
    raw_workspace_artifacts = _workspace_artifacts(workspace)
    _audit_canonical_json(workspace, run_dir, registry, errors, checks)
    artifacts = [item for item in raw_artifacts if _artifact_is_valid(item, registry)]
    workspace_artifacts = {
        key: item
        for key, item in raw_workspace_artifacts.items()
        if _artifact_is_valid(item, registry)
    }
    run_artifacts_by_id = {
        key: item
        for key, item in _all_run_artifacts_by_id(run_dir).items()
        if _artifact_is_valid(item, registry)
    }
    all_by_id = {
        **workspace_artifacts,
        **run_artifacts_by_id,
    }
    artifacts_by_hash = {
        str(item["artifact_hash"]): item
        for item in [*workspace_artifacts.values(), *_all_run_artifact_versions(run_dir)]
        if _artifact_is_valid(item, registry) and isinstance(item.get("artifact_hash"), str)
    }
    _check_generated_identifier_versions(manifest, artifacts, errors, warnings, checks)
    _check_run_artifact_identities(run_artifacts_by_id.values(), errors, checks)
    _check_workspace_artifact_identities(workspace_artifacts, errors, warnings, checks)
    _check_source_hashes(workspace, workspace_artifacts.values(), errors, checks)
    _check_source_snapshot(manifest, workspace_artifacts, errors, checks)
    _check_index_snapshot(workspace, manifest, errors, checks)
    _check_configuration_snapshot(workspace, manifest, warnings, errors, checks)
    _check_lifecycle(run_dir, manifest, errors, checks)
    _check_work_packets(run_dir, manifest, errors, checks)

    chunks = {
        key: value
        for key, value in workspace_artifacts.items()
        if value.get("schema_name") == "Chunk"
    }
    versions = {
        key: value
        for key, value in workspace_artifacts.items()
        if value.get("schema_name") == "DocumentVersion"
    }
    _check_document_version_derivatives(workspace, versions.values(), errors, warnings, checks)
    evidence = {
        str(item["evidence_id"]): item
        for item in artifacts
        if item.get("schema_name") == "Evidence"
    }
    claims: dict[str, dict[str, Any]] = {}
    for item in artifacts:
        if item.get("schema_name") != "Claim":
            continue
        claim_id = str(item["claim_id"])
        if claim_id not in claims or int(item["claim_version"]) > int(
            claims[claim_id]["claim_version"]
        ):
            claims[claim_id] = item
    reviews = [item for item in artifacts if item.get("schema_name") == "Review"]
    amendments = [item for item in artifacts if item.get("schema_name") == "Amendment"]
    relationships = [item for item in artifacts if item.get("schema_name") == "SourceRelationship"]
    plans = [item for item in artifacts if item.get("schema_name") == "ResearchPlan"]
    retrieval_results = [item for item in artifacts if item.get("schema_name") == "RetrievalResult"]
    source_snapshot = {
        str(entry["document_id"]): entry for entry in manifest.get("source_snapshot", [])
    }

    _check_plan(plans, manifest, errors, checks)
    for item in evidence.values():
        _check_evidence(workspace, item, chunks, versions, errors, human_requirements, checks)
        source_entry = source_snapshot.get(str(item["document_id"]))
        if source_entry is None:
            errors.append(
                _issue(
                    "evidence_outside_source_snapshot",
                    "Evidence uses a document that was not frozen into the run",
                    str(item["evidence_id"]),
                )
            )
        elif source_entry.get("document_version_id") != item.get("document_version_id"):
            errors.append(
                _issue(
                    "evidence_version_outside_snapshot",
                    "Evidence uses a document version outside the run snapshot",
                    str(item["evidence_id"]),
                )
            )
    _check_retrieval(
        workspace,
        manifest,
        retrieval_results,
        chunks,
        source_snapshot,
        evidence,
        errors,
        warnings,
        checks,
    )
    for claim in claims.values():
        _check_claim(
            claim,
            evidence,
            reviews,
            relationships,
            profile,
            errors,
            warnings,
            human_requirements,
        )
    _check_review_references(reviews, all_by_id, claims, evidence, errors, checks)
    valid_search_event_ids = {
        str(item["event_id"])
        for item in _load_search_events(workspace, run_id, errors)
        if item.get("event_id")
    }
    _check_reviews(
        reviews,
        claims,
        profile,
        errors,
        human_requirements,
        require_modern_contracts=isinstance(manifest.get("configuration_snapshot"), dict),
        valid_search_event_ids=valid_search_event_ids,
    )
    _check_amendments(amendments, artifacts_by_hash, reviews, errors, human_requirements)
    _check_source_relationships(
        relationships,
        {
            str(item["document_id"])
            for item in workspace_artifacts.values()
            if item.get("schema_name") == "Document"
        },
        errors,
        checks,
    )

    if PHASES.index(str(manifest["phase"])) < PHASES.index("independently_reviewed"):
        errors.append(
            _issue(
                "workflow_incomplete",
                f"Run phase {manifest['phase']} has not completed independent review",
                run_id,
            )
        )
    if not claims:
        errors.append(_issue("missing_claims", "Run contains no canonical Claim artifacts", run_id))

    human_requirements = [
        issue
        for issue in human_requirements
        if not _human_requirement_resolved(issue, amendments, reviews)
    ]
    errors = _deduplicate_issues(errors)
    warnings = _deduplicate_issues(warnings)
    human_requirements = _deduplicate_issues(human_requirements)
    passed = not errors and not human_requirements
    report_eligible = passed
    validation_id = generated_identifier("VAL")
    validated_hashes = validation_input_artifact_hashes(workspace, run_dir, manifest)
    result = artifact_base("ValidationResult", validation_id)
    result.update(
        {
            "validation_result_id": validation_id,
            "run_id": run_id,
            "passed": passed,
            "report_eligible": report_eligible,
            "blocking_errors": errors,
            "warnings": warnings,
            "human_review_requirements": human_requirements,
            "validated_artifact_hashes": validated_hashes,
            "checks": checks,
            "semantic_validation_boundary": (
                "The CLI validated review artifacts and gates; host reviewers supplied semantic judgments."
            ),
        }
    )
    stored, path = store_artifact(run_dir, result)
    updated = transition_after_validation(
        run_dir,
        manifest,
        passed=passed,
        report_eligible=report_eligible,
        human_review_required=bool(human_requirements),
        validation_id=validation_id,
        artifact_hashes=[stored["artifact_hash"]],
    )
    data = {
        "run_id": run_id,
        "validation_result_id": validation_id,
        "validation_result_path": str(path.relative_to(run_dir)),
        "passed": passed,
        "report_eligible": report_eligible,
        "blocking_errors": errors,
        "warnings": warnings,
        "human_review_requirements": human_requirements,
        "phase": updated["phase"],
        "disposition": updated["disposition"],
    }
    if human_requirements and not errors:
        return data, 6
    if not passed:
        return data, EXIT_REPORT_GATE
    return data, 0


def validation_input_artifact_hashes(
    workspace: Path,
    run_dir: Path,
    manifest: dict[str, Any] | None = None,
) -> list[str]:
    """Return the exact canonical artifact set whose integrity gates publication."""
    active_manifest = manifest or load_run(workspace, str(run_dir.name))[1]
    snapshot_document_ids = {
        str(item["document_id"]) for item in active_manifest.get("source_snapshot", [])
    }
    snapshot_version_ids = {
        str(item["document_version_id"])
        for item in active_manifest.get("source_snapshot", [])
        if item.get("document_version_id")
    }
    index_snapshot = active_manifest.get("index_snapshot")
    frozen_index_hashes: set[str] = set()
    if isinstance(index_snapshot, dict):
        index_manifest = next(
            (
                item
                for item in iter_json(workspace / "indexes" / "manifests")
                if item.get("index_id") == index_snapshot.get("index_id")
            ),
            None,
        )
        if index_manifest:
            frozen_index_hashes = {
                str(item) for item in index_manifest.get("input_artifact_hashes", [])
            }
    hashes = {
        str(item["artifact_hash"])
        for item in _current_run_artifacts(run_dir)
        if isinstance(item.get("artifact_hash"), str)
    }
    for item in _workspace_artifacts(workspace).values():
        is_snapshot_document = (
            item.get("schema_name") == "Document"
            and item.get("document_id") in snapshot_document_ids
        )
        is_snapshot_version_artifact = (
            item.get("schema_name") == "DocumentVersion"
            and item.get("document_version_id") in snapshot_version_ids
        )
        is_frozen_index_chunk = (
            item.get("schema_name") == "Chunk" and item.get("artifact_hash") in frozen_index_hashes
        )
        if is_snapshot_document or is_snapshot_version_artifact or is_frozen_index_chunk:
            hashes.add(str(item["artifact_hash"]))
    return sorted(hashes)


def publication_integrity_errors(
    workspace: Path, run_dir: Path, manifest: dict[str, Any]
) -> list[dict[str, Any]]:
    """Recheck mutable source/render bytes immediately before publication."""
    errors: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    registry = SchemaRegistry()
    _audit_canonical_json(workspace, run_dir, registry, errors, checks)
    _check_lifecycle(run_dir, manifest, errors, checks)
    _check_work_packets(run_dir, manifest, errors, checks)
    _check_configuration_snapshot(workspace, manifest, warnings, errors, checks)
    _check_index_snapshot(workspace, manifest, errors, checks)
    workspace_artifacts = {
        key: item
        for key, item in _workspace_artifacts(workspace).items()
        if _artifact_is_valid(item, registry)
    }
    snapshot_ids = {str(item["document_id"]) for item in manifest.get("source_snapshot", [])}
    selected = [
        item
        for item in workspace_artifacts.values()
        if item.get("schema_name") == "Document" and item.get("document_id") in snapshot_ids
    ]
    _check_source_hashes(workspace, selected, errors, checks)
    _check_source_snapshot(manifest, workspace_artifacts, errors, checks)
    current_artifacts = [
        item for item in _current_run_artifacts(run_dir) if _artifact_is_valid(item, registry)
    ]
    evidence = {
        str(item["evidence_id"]): item
        for item in current_artifacts
        if item.get("schema_name") == "Evidence"
    }
    retrieval_results = [
        item for item in current_artifacts if item.get("schema_name") == "RetrievalResult"
    ]
    chunks = {
        key: value
        for key, value in workspace_artifacts.items()
        if value.get("schema_name") == "Chunk"
    }
    versions = {
        key: value
        for key, value in workspace_artifacts.items()
        if value.get("schema_name") == "DocumentVersion"
    }
    _check_document_version_derivatives(workspace, versions.values(), errors, warnings, checks)
    source_snapshot = {
        str(entry["document_id"]): entry for entry in manifest.get("source_snapshot", [])
    }
    _check_retrieval(
        workspace,
        manifest,
        retrieval_results,
        chunks,
        source_snapshot,
        evidence,
        errors,
        warnings,
        checks,
    )
    for item in evidence.values():
        transient_human: list[dict[str, Any]] = []
        _check_evidence(workspace, item, chunks, versions, errors, transient_human, checks)
    return _deduplicate_issues(errors)


def current_run_artifact_hashes(run_dir: Path) -> list[str]:
    return sorted(
        str(item["artifact_hash"])
        for item in _current_run_artifacts(run_dir)
        if isinstance(item.get("artifact_hash"), str)
    )


def _current_run_artifacts(run_dir: Path) -> list[dict[str, Any]]:
    included = (
        "plan",
        "retrieval",
        "evidence",
        "claims",
        "reviews",
        "amendments",
        "relationships",
        "stage-responses",
    )
    by_id: dict[str, dict[str, Any]] = {}
    for name in included:
        for value in iter_json(run_dir / name):
            artifact_id = value.get("artifact_id")
            if not isinstance(artifact_id, str):
                continue
            existing = by_id.get(artifact_id)
            if existing is None or str(value.get("created_at", "")) > str(
                existing.get("created_at", "")
            ):
                by_id[artifact_id] = value
    superseded = {
        str(item["supersedes"])
        for item in by_id.values()
        if isinstance(item.get("supersedes"), str)
    }
    return [value for key, value in by_id.items() if key not in superseded]


def _workspace_artifacts(workspace: Path) -> dict[str, dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for relative in ("documents/manifests", "documents/versions", "documents/chunks"):
        for value in iter_json(workspace / relative):
            artifact_id = value.get("artifact_id")
            if not isinstance(artifact_id, str):
                continue
            existing = by_id.get(artifact_id)
            if existing is None or str(value.get("created_at", "")) > str(
                existing.get("created_at", "")
            ):
                by_id[artifact_id] = value
    return by_id


def _all_run_artifacts_by_id(run_dir: Path) -> dict[str, dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for relative in (
        "plan",
        "retrieval",
        "evidence",
        "claims",
        "reviews",
        "amendments",
        "relationships",
        "stage-responses",
    ):
        for value in iter_json(run_dir / relative):
            artifact_id = value.get("artifact_id")
            if isinstance(artifact_id, str):
                by_id[artifact_id] = value
    return by_id


def _all_run_artifact_versions(run_dir: Path) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for relative in (
        "plan",
        "retrieval",
        "evidence",
        "claims",
        "reviews",
        "amendments",
        "relationships",
        "stage-responses",
    ):
        values.extend(iter_json(run_dir / relative))
    return values


def _audit_canonical_json(
    workspace: Path,
    run_dir: Path,
    registry: SchemaRegistry,
    errors: list[dict[str, Any]],
    checks: list[dict[str, Any]],
) -> None:
    files: set[Path] = set()
    for relative in (
        "documents/manifests",
        "documents/versions",
        "documents/chunks",
        "indexes/manifests",
    ):
        root = workspace / relative
        if root.exists():
            files.update(root.rglob("*.json"))
    current_index = workspace / "indexes" / "index-manifest.json"
    if current_index.is_file():
        files.add(current_index)
    for relative in (
        "manifest-history",
        "packets",
        "plan",
        "retrieval",
        "evidence",
        "claims",
        "reviews",
        "validation",
        "amendments",
        "relationships",
        "stage-responses",
        "events",
        "report/manifests",
    ):
        root = run_dir / relative
        if root.exists():
            files.update(root.rglob("*.json"))
    files.add(run_dir / "manifest.json")
    valid = 0
    for path in sorted(files, key=lambda item: item.as_posix()):
        artifact_id = str(path.relative_to(workspace))
        try:
            artifact = read_json(path)
            artifact_id = str(artifact.get("artifact_id", artifact_id))
            registry.validate(artifact)
            if not verify_artifact_hash(artifact):
                raise ValueError("artifact hash mismatch")
            if artifact.get("schema_name") == "ReportManifest":
                _check_report_manifest_file(run_dir, artifact, errors)
            valid += 1
        except (OSError, ValueError, json.JSONDecodeError, ResearchError) as exc:
            errors.append(_issue("invalid_artifact", str(exc), artifact_id))
    checks.append(
        {
            "check": "all_canonical_json_schema_and_hash",
            "passed": valid == len(files),
            "count": len(files),
        }
    )


def _artifact_is_valid(artifact: dict[str, Any], registry: SchemaRegistry) -> bool:
    try:
        registry.validate(artifact)
    except ResearchError:
        return False
    return verify_artifact_hash(artifact)


def _check_report_manifest_file(
    run_dir: Path, manifest: dict[str, Any], errors: list[dict[str, Any]]
) -> None:
    manifest_id = str(manifest["artifact_id"])
    expected_id = derived_identifier(
        "RPT",
        {
            "run_id": manifest.get("run_id"),
            "draft": manifest.get("draft"),
            "report_sha256": manifest.get("report_sha256"),
            "inputs": manifest.get("input_artifact_hashes", []),
        },
    )
    if manifest_id != expected_id or manifest.get("report_manifest_id") != expected_id:
        errors.append(
            _issue(
                "invalid_report_manifest_identity",
                "Report manifest ID is not derived from report bytes and canonical inputs",
                manifest_id,
            )
        )
    path = run_dir / str(manifest.get("report_path", ""))
    if not _safe_workspace_file(run_dir, path):
        errors.append(
            _issue("missing_report_file", "Report manifest path does not resolve", manifest_id)
        )
        return
    if f"sha256:{file_sha256(path)}" != manifest.get("report_sha256"):
        errors.append(
            _issue("report_hash_mismatch", "Rendered report bytes do not match", manifest_id)
        )


def _check_configuration_snapshot(
    workspace: Path,
    manifest: dict[str, Any],
    warnings: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    checks: list[dict[str, Any]],
) -> None:
    snapshot = manifest.get("configuration_snapshot")
    if not isinstance(snapshot, dict):
        warnings.append(
            _issue(
                "configuration_snapshot_missing",
                "Legacy run records only a configuration hash; preserve research.yaml for replay",
                str(manifest["run_id"]),
            )
        )
        snapshot = load_config(workspace)
    if config_hash(snapshot) != manifest.get("configuration_hash"):
        errors.append(
            _issue(
                "configuration_snapshot_mismatch",
                "Frozen configuration does not match the run configuration hash",
                str(manifest["run_id"]),
            )
        )
    checks.append(
        {
            "check": "configuration_snapshot",
            "passed": not any(item["code"] == "configuration_snapshot_mismatch" for item in errors),
        }
    )


def _check_index_snapshot(
    workspace: Path,
    manifest: dict[str, Any],
    errors: list[dict[str, Any]],
    checks: list[dict[str, Any]],
) -> None:
    snapshot = manifest.get("index_snapshot")
    if not isinstance(snapshot, dict):
        errors.append(
            _issue(
                "missing_index_snapshot",
                "Run did not freeze a reproducible index manifest",
                str(manifest["run_id"]),
            )
        )
        return
    matching = next(
        (
            item
            for item in iter_json(workspace / "indexes" / "manifests")
            if item.get("schema_name") == "IndexManifest"
            and item.get("index_id") == snapshot.get("index_id")
        ),
        None,
    )
    if (
        matching is None
        or matching.get("artifact_hash") != snapshot.get("artifact_hash")
        or matching.get("logical_index_hash") != snapshot.get("logical_index_hash")
    ):
        errors.append(
            _issue(
                "index_snapshot_mismatch",
                "Frozen run index manifest no longer resolves",
                str(manifest["run_id"]),
            )
        )
    elif matching.get(
        "index_id"
    ) != f"IDX-sha256-{str(matching.get('logical_index_hash')).removeprefix('sha256:')}" or (
        isinstance(manifest.get("configuration_snapshot"), dict)
        and list(matching.get("input_artifact_hashes", []))
        != sorted(set(matching.get("input_artifact_hashes", [])))
    ):
        errors.append(
            _issue(
                "invalid_index_manifest_identity",
                "Index ID or sorted canonical input hash set is inconsistent",
                str(matching.get("index_id", manifest["run_id"])),
            )
        )
    checks.append(
        {
            "check": "index_snapshot",
            "passed": not any(
                item["code"]
                in {
                    "missing_index_snapshot",
                    "index_snapshot_mismatch",
                    "invalid_index_manifest_identity",
                }
                for item in errors
            ),
        }
    )


def _check_lifecycle(
    run_dir: Path,
    manifest: dict[str, Any],
    errors: list[dict[str, Any]],
    checks: list[dict[str, Any]],
) -> None:
    log_path = run_dir / str(manifest.get("event_log", ""))
    run_id = str(manifest["run_id"])
    if not _safe_workspace_file(run_dir, log_path):
        errors.append(_issue("missing_lifecycle_log", "Lifecycle event log is missing", run_id))
        return
    canonical_events = {
        str(item["event_id"]): item
        for item in iter_json(run_dir / "events")
        if item.get("schema_name") == "LifecycleEvent"
    }
    logged: list[dict[str, Any]] = []
    with log_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            try:
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError("event must be an object")
                logged.append(value)
            except (json.JSONDecodeError, ValueError) as exc:
                errors.append(
                    _issue(
                        "invalid_lifecycle_log",
                        f"Lifecycle event line {line_number} is invalid: {exc}",
                        run_id,
                    )
                )
    previous_phase: str | None = None
    previous_disposition: str | None = None
    logged_ids: set[str] = set()
    for index, event in enumerate(logged):
        event_id = str(event.get("event_id", f"line-{index + 1}"))
        logged_ids.add(event_id)
        canonical = canonical_events.get(event_id)
        if canonical is None or canonical != event:
            errors.append(
                _issue(
                    "lifecycle_event_mismatch",
                    "Logged lifecycle event does not match its immutable artifact",
                    event_id,
                )
            )
        if event.get("run_id") != run_id:
            errors.append(
                _issue("lifecycle_run_mismatch", "Event belongs to another run", event_id)
            )
        if (
            event.get("previous_phase") != previous_phase
            or event.get("previous_disposition") != previous_disposition
        ):
            errors.append(
                _issue(
                    "lifecycle_chain_mismatch",
                    "Lifecycle event does not continue the preceding state",
                    event_id,
                )
            )
        new_phase = str(event.get("new_phase", ""))
        new_disposition = str(event.get("new_disposition", ""))
        if new_phase not in PHASES or new_disposition not in DISPOSITIONS:
            errors.append(_issue("invalid_lifecycle_state", "Event has an unknown state", event_id))
        elif previous_phase is not None:
            delta = PHASES.index(new_phase) - PHASES.index(previous_phase)
            if delta not in {0, 1}:
                errors.append(
                    _issue(
                        "invalid_lifecycle_transition",
                        f"Lifecycle event moves {previous_phase} -> {new_phase}",
                        event_id,
                    )
                )
        previous_phase = new_phase
        previous_disposition = new_disposition
    if set(canonical_events) != logged_ids:
        errors.append(
            _issue(
                "lifecycle_event_set_mismatch",
                "Canonical lifecycle events and append-only log entries differ",
                run_id,
            )
        )
    recorded_artifact_hashes = {
        str(item)
        for event in logged
        for item in event.get("artifact_hashes", [])
        if isinstance(item, str)
    }
    lifecycle_managed = [
        item
        for relative in (
            "plan",
            "retrieval",
            "evidence",
            "claims",
            "reviews",
            "validation",
            "amendments",
            "relationships",
            "stage-responses",
        )
        for item in iter_json(run_dir / relative)
    ]
    for artifact in lifecycle_managed:
        artifact_hash = artifact.get("artifact_hash")
        if isinstance(artifact_hash, str) and artifact_hash not in recorded_artifact_hashes:
            errors.append(
                _issue(
                    "unrecorded_canonical_artifact",
                    "Canonical artifact is not attached to an append-only lifecycle event",
                    str(artifact.get("artifact_id", "unknown")),
                )
            )
    if (
        not logged
        or previous_phase != manifest.get("phase")
        or previous_disposition != manifest.get("disposition")
    ):
        errors.append(
            _issue(
                "lifecycle_manifest_mismatch",
                "Current run manifest does not match the final lifecycle event",
                run_id,
            )
        )
    responses = [
        item
        for item in iter_json(run_dir / "stage-responses")
        if item.get("schema_name") == "StageResponse"
    ]
    phase_index = PHASES.index(str(manifest["phase"]))
    for stage, target_phase in STAGE_PHASES.items():
        if stage not in STAGE_REQUIREMENTS or PHASES.index(target_phase) > phase_index:
            continue
        if not any(
            item.get("stage") == stage
            and item.get("outcome") in {"completed", "insufficient_evidence"}
            for item in responses
        ):
            errors.append(
                _issue(
                    "missing_completed_stage_response",
                    f"Lifecycle phase requires a completed {stage} StageResponse",
                    run_id,
                )
            )
    checks.append(
        {
            "check": "append_only_lifecycle",
            "passed": not any(
                item["code"].startswith("lifecycle_")
                or item["code"] == "unrecorded_canonical_artifact"
                for item in errors
            ),
            "event_count": len(logged),
        }
    )


def _check_work_packets(
    run_dir: Path,
    manifest: dict[str, Any],
    errors: list[dict[str, Any]],
    checks: list[dict[str, Any]],
) -> None:
    packets = [
        item for item in iter_json(run_dir / "packets") if item.get("schema_name") == "WorkPacket"
    ]
    expected_stages = {*STAGE_PHASES, "final_validation", "report", "human_review", "amendment"}
    for stage in expected_stages:
        matching = [item for item in packets if item.get("stage") == stage]
        if len(matching) != 1:
            errors.append(
                _issue(
                    "work_packet_cardinality",
                    f"Run requires exactly one immutable {stage} work packet",
                    str(manifest["run_id"]),
                )
            )
    independent = next(
        (item for item in packets if item.get("stage") == "independent_review"), None
    )
    prohibited = {"primary_rationale", "primary_confidence", "previous_review_conclusions"}
    if independent is None or not prohibited.issubset(set(independent.get("excluded_inputs", []))):
        errors.append(
            _issue(
                "independent_packet_exclusions_missing",
                "Independent-review packet does not exclude all prohibited primary context",
                str(manifest["run_id"]),
            )
        )
    checks.append(
        {
            "check": "work_packet_contracts",
            "passed": not any(
                item["code"] in {"work_packet_cardinality", "independent_packet_exclusions_missing"}
                for item in errors
            ),
            "count": len(packets),
        }
    )


def _load_search_events(
    workspace: Path, run_id: str, errors: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    path = workspace / "logs" / "search-events.jsonl"
    if not _safe_workspace_file(workspace, path):
        return []
    events: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            try:
                event = json.loads(line)
                if not isinstance(event, dict):
                    raise ValueError("search event must be an object")
            except (json.JSONDecodeError, ValueError) as exc:
                errors.append(
                    _issue(
                        "invalid_search_log",
                        f"Search event line {line_number} is invalid: {exc}",
                        run_id,
                    )
                )
                continue
            event_hash = event.get("event_hash")
            if event_hash is not None:
                payload = dict(event)
                payload.pop("event_hash", None)
                if canonical_sha256(payload) != event_hash:
                    errors.append(
                        _issue(
                            "search_event_hash_mismatch",
                            f"Search event line {line_number} hash does not match",
                            str(event.get("event_id", run_id)),
                        )
                    )
                    continue
            event_id = event.get("event_id")
            if event_id:
                if str(event_id) in seen_ids:
                    errors.append(
                        _issue(
                            "duplicate_search_event",
                            "Search event ID appears more than once",
                            str(event_id),
                        )
                    )
                    continue
                seen_ids.add(str(event_id))
            if event.get("run_id") == run_id:
                events.append(event)
    return events


def _check_plan(
    plans: list[dict[str, Any]],
    manifest: dict[str, Any],
    errors: list[dict[str, Any]],
    checks: list[dict[str, Any]],
) -> None:
    run_id = str(manifest["run_id"])
    if len(plans) != 1:
        errors.append(
            _issue(
                "research_plan_cardinality",
                f"Run requires exactly one current ResearchPlan, found {len(plans)}",
                run_id,
            )
        )
    elif plans[0].get("run_id") != run_id or plans[0].get("main_question") != manifest.get(
        "question"
    ):
        errors.append(
            _issue(
                "research_plan_mismatch",
                "Research plan run ID or main question differs from the frozen run",
                str(plans[0]["artifact_id"]),
            )
        )
    checks.append(
        {
            "check": "research_plan_contract",
            "passed": not any(
                item["code"] in {"research_plan_cardinality", "research_plan_mismatch"}
                for item in errors
            ),
        }
    )


def _check_retrieval(
    workspace: Path,
    manifest: dict[str, Any],
    retrieval_results: list[dict[str, Any]],
    chunks: dict[str, dict[str, Any]],
    source_snapshot: dict[str, dict[str, Any]],
    evidence: dict[str, dict[str, Any]],
    errors: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    checks: list[dict[str, Any]],
) -> None:
    search_events = _load_search_events(workspace, str(manifest["run_id"]), errors)
    search_events_by_id = {
        str(item["event_id"]): item for item in search_events if item.get("event_id")
    }
    modern_run = isinstance(manifest.get("configuration_snapshot"), dict)
    index_snapshot = manifest.get("index_snapshot")
    frozen_index_id = index_snapshot.get("index_id") if isinstance(index_snapshot, dict) else None
    frozen_index_manifest = next(
        (
            item
            for item in iter_json(workspace / "indexes" / "manifests")
            if item.get("index_id") == frozen_index_id
        ),
        None,
    )
    frozen_chunk_hashes = {
        str(item)
        for item in (
            frozen_index_manifest.get("input_artifact_hashes", []) if frozen_index_manifest else []
        )
    }
    retrieved_ids: set[str] = set()
    if len(retrieval_results) != 1:
        errors.append(
            _issue(
                "retrieval_result_cardinality",
                f"Run requires exactly one current RetrievalResult, found {len(retrieval_results)}",
                "retrieval",
            )
        )
    for result in retrieval_results:
        result_id = str(result["artifact_id"])
        expected_ranked: list[str] = []
        if not result.get("queries"):
            errors.append(
                _issue("missing_search_queries", "Retrieval recorded no queries", result_id)
            )
        for query_record in result.get("queries", []):
            query = str(query_record.get("query", ""))
            declared_ids = [str(item) for item in query_record.get("top_chunk_ids", [])]
            for chunk_id in declared_ids:
                if chunk_id not in expected_ranked:
                    expected_ranked.append(chunk_id)
            event: dict[str, Any] | None = None
            if modern_run:
                event_id = str(query_record.get("search_event_id", ""))
                event = search_events_by_id.get(event_id)
                if event is None or event.get("event_hash") != query_record.get(
                    "search_event_hash"
                ):
                    errors.append(
                        _issue(
                            "retrieval_search_event_mismatch",
                            "Retrieval query does not bind a valid immutable search event",
                            result_id,
                        )
                    )
                    continue
            else:
                event = next(
                    (
                        item
                        for item in search_events
                        if item.get("query") == query
                        and list(item.get("result_chunk_ids", []))[: len(declared_ids)]
                        == declared_ids
                    ),
                    None,
                )
                warnings.append(
                    _issue(
                        "legacy_retrieval_event_binding",
                        "Legacy retrieval query is matched by query/result content rather than event ID",
                        result_id,
                    )
                )
            if (
                event is None
                or (
                    event.get("query") != query
                    and event.get("query_sha256") != prefixed_sha256(query.encode("utf-8"))
                )
                or event.get("index_id") != frozen_index_id
                or list(event.get("result_chunk_ids", []))[: len(declared_ids)] != declared_ids
            ):
                errors.append(
                    _issue(
                        "retrieval_search_event_mismatch",
                        "Retrieval query/results differ from the recorded run-scoped search",
                        result_id,
                    )
                )
        ranked = list(result.get("ranked_chunk_ids", []))
        if ranked != expected_ranked:
            errors.append(
                _issue(
                    "retrieval_order_mismatch",
                    "Ranked chunk IDs do not match first-seen query result order",
                    result_id,
                )
            )
        if len(ranked) != len(set(ranked)):
            errors.append(
                _issue("duplicate_retrieval_reference", "Ranked chunks repeat", result_id)
            )
        for chunk_id in ranked:
            chunk = chunks.get(str(chunk_id))
            if chunk is None:
                errors.append(
                    _issue(
                        "dangling_retrieval_chunk", f"Unknown retrieved chunk {chunk_id}", result_id
                    )
                )
                continue
            if str(chunk.get("document_id")) not in source_snapshot:
                errors.append(
                    _issue(
                        "retrieval_outside_source_snapshot",
                        f"Retrieved chunk {chunk_id} is outside the frozen run sources",
                        result_id,
                    )
                )
            if chunk.get("artifact_hash") not in frozen_chunk_hashes:
                errors.append(
                    _issue(
                        "retrieval_outside_frozen_index",
                        f"Retrieved chunk {chunk_id} was not in the run's frozen index",
                        result_id,
                    )
                )
            retrieved_ids.add(str(chunk_id))
    for item in evidence.values():
        locator = item.get("locator", {})
        chunk_id = locator.get("chunk_id")
        if locator.get("type") == "text_span" and chunk_id not in retrieved_ids:
            errors.append(
                _issue(
                    "evidence_not_retrieved",
                    "Text evidence was not present in the canonical retrieval result",
                    str(item["evidence_id"]),
                )
            )
    checks.append(
        {
            "check": "retrieval_references",
            "passed": not any(
                item["code"]
                in {
                    "retrieval_result_cardinality",
                    "missing_search_queries",
                    "duplicate_retrieval_reference",
                    "retrieval_order_mismatch",
                    "dangling_retrieval_chunk",
                    "retrieval_outside_source_snapshot",
                    "retrieval_outside_frozen_index",
                    "evidence_not_retrieved",
                    "retrieval_search_event_mismatch",
                    "invalid_search_log",
                    "search_event_hash_mismatch",
                    "duplicate_search_event",
                }
                for item in errors
            ),
            "retrieved_chunk_count": len(retrieved_ids),
        }
    )


def _check_artifacts(
    artifacts: list[dict[str, Any]],
    registry: SchemaRegistry,
    errors: list[dict[str, Any]],
    checks: list[dict[str, Any]],
) -> None:
    valid = 0
    for artifact in artifacts:
        try:
            registry.validate(artifact)
            if not verify_artifact_hash(artifact):
                raise ValueError("artifact hash mismatch")
            valid += 1
        except (ResearchError, ValueError) as exc:
            errors.append(
                _issue("invalid_artifact", str(exc), str(artifact.get("artifact_id", "unknown")))
            )
    checks.append(
        {
            "check": "artifact_schema_and_hash",
            "passed": valid == len(artifacts),
            "count": len(artifacts),
        }
    )


def _check_run_artifact_identities(
    artifacts: Any,
    errors: list[dict[str, Any]],
    checks: list[dict[str, Any]],
) -> None:
    values = list(artifacts)
    claims = [item for item in values if item.get("schema_name") == "Claim"]
    claim_artifact_ids = {str(item["artifact_id"]) for item in claims}
    for claim in claims:
        claim_id = str(claim["claim_id"])
        version = int(claim["claim_version"])
        artifact_id = str(claim["artifact_id"])
        expected_id = f"{claim_id}-v{version}"
        predecessor = f"{claim_id}-v{version - 1}" if version > 1 else None
        if (
            artifact_id != expected_id
            or (version == 1 and claim.get("supersedes") is not None)
            or (
                version > 1
                and (
                    claim.get("supersedes") != predecessor or predecessor not in claim_artifact_ids
                )
            )
        ):
            errors.append(
                _issue(
                    "invalid_claim_version_chain",
                    "Claim artifact ID or superseding chain is inconsistent",
                    artifact_id,
                )
            )
    identity_fields = {
        "Evidence": "evidence_id",
        "Review": "review_id",
        "Amendment": "amendment_id",
        "SourceRelationship": "relationship_id",
        "ValidationResult": "validation_result_id",
    }
    for artifact in values:
        field = identity_fields.get(str(artifact.get("schema_name")))
        if field and artifact.get("artifact_id") != artifact.get(field):
            errors.append(
                _issue(
                    "run_artifact_identifier_mismatch",
                    f"{artifact['schema_name']} artifact_id differs from {field}",
                    str(artifact.get("artifact_id", "unknown")),
                )
            )
    checks.append(
        {
            "check": "run_artifact_identities",
            "passed": not any(
                item["code"] in {"invalid_claim_version_chain", "run_artifact_identifier_mismatch"}
                for item in errors
            ),
        }
    )


def _check_generated_identifier_versions(
    manifest: dict[str, Any],
    artifacts: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    checks: list[dict[str, Any]],
) -> None:
    run_id = str(manifest["run_id"])
    if not identifier_has_uuid_version(run_id, "RUN", 4):
        errors.append(_issue("invalid_run_identifier", "Run ID must use UUIDv4", run_id))
    modern_run = isinstance(manifest.get("configuration_snapshot"), dict)
    contracts = {
        "Claim": ("claim_id", "CLM"),
        "Review": ("review_id", "REV"),
        "Amendment": ("amendment_id", "AMD"),
    }
    legacy_violations = 0
    for artifact in artifacts:
        contract = contracts.get(str(artifact.get("schema_name")))
        if contract is None:
            continue
        field, prefix = contract
        identifier = str(artifact.get(field, ""))
        if identifier_has_uuid_version(identifier, prefix, 7):
            continue
        if modern_run:
            errors.append(
                _issue(
                    "invalid_uuid_version",
                    f"{artifact['schema_name']} identifier must use UUIDv7",
                    identifier,
                )
            )
        else:
            legacy_violations += 1
    if legacy_violations:
        warnings.append(
            _issue(
                "legacy_identifier_version",
                f"Legacy run contains {legacy_violations} claim/review/amendment IDs that are not UUIDv7",
                run_id,
            )
        )
    checks.append(
        {
            "check": "identifier_uuid_versions",
            "passed": not any(
                item["code"] in {"invalid_run_identifier", "invalid_uuid_version"}
                for item in errors
            ),
        }
    )


def _check_workspace_artifact_identities(
    artifacts: dict[str, dict[str, Any]],
    errors: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    checks: list[dict[str, Any]],
) -> None:
    documents = {
        str(item["document_id"]): item
        for item in artifacts.values()
        if item.get("schema_name") == "Document"
    }
    versions = {
        str(item["document_version_id"]): item
        for item in artifacts.values()
        if item.get("schema_name") == "DocumentVersion"
    }
    chunks = [item for item in artifacts.values() if item.get("schema_name") == "Chunk"]
    for document_id, document_item in documents.items():
        expected_id = f"DOC-sha256-{str(document_item['source_sha256']).removeprefix('sha256:')}"
        if document_id != expected_id or document_item.get("artifact_id") != expected_id:
            errors.append(
                _issue(
                    "invalid_document_identifier",
                    "Document ID is not derived from original source bytes",
                    document_id,
                )
            )
    for version_id, version_item in versions.items():
        document = documents.get(str(version_item.get("document_id")))
        if (
            version_item.get("artifact_id") != version_id
            or document is None
            or version_item.get("source_sha256") != document.get("source_sha256")
        ):
            errors.append(
                _issue(
                    "invalid_document_version_reference",
                    "Document version identity or source reference is inconsistent",
                    version_id,
                )
            )
        extraction_configuration = version_item.get("extraction_configuration")
        extraction_hash = version_item.get("extraction_configuration_hash")
        if isinstance(extraction_configuration, dict) and document is not None:
            expected_extraction_hash = config_hash(
                {
                    "extraction": extraction_configuration,
                    "media_type": document.get("media_type"),
                }
            )
            expected_version_id = derived_identifier(
                "DVER",
                {
                    "source_sha256": version_item.get("source_sha256"),
                    "extraction_configuration_hash": expected_extraction_hash,
                    "toolchain": version_item.get("toolchain"),
                    "normalization_version": version_item.get("normalization_version"),
                },
            )
            if extraction_hash != expected_extraction_hash or version_id != expected_version_id:
                errors.append(
                    _issue(
                        "invalid_document_version_identifier",
                        "Document version ID is not derived from its recorded extraction inputs",
                        version_id,
                    )
                )
        else:
            warnings.append(
                _issue(
                    "legacy_extraction_configuration",
                    "Legacy document version does not retain its extraction configuration snapshot",
                    version_id,
                )
            )
    for chunk in chunks:
        chunk_id = str(chunk["chunk_id"])
        version = versions.get(str(chunk.get("document_version_id")))
        exact_text = str(chunk.get("exact_text", ""))
        start = chunk.get("start_offset")
        end = chunk.get("end_offset")
        if (
            chunk.get("artifact_id") != chunk_id
            or version is None
            or chunk.get("document_id") != version.get("document_id")
            or prefixed_sha256(exact_text.encode("utf-8")) != chunk.get("text_sha256")
            or not isinstance(start, int)
            or not isinstance(end, int)
            or end <= start
        ):
            errors.append(
                _issue(
                    "invalid_chunk_identity",
                    "Chunk identity, source reference, offsets, or text hash is inconsistent",
                    chunk_id,
                )
            )
        chunking_configuration = chunk.get("chunking_configuration")
        if isinstance(chunking_configuration, dict):
            expected_chunking_hash = config_hash(chunking_configuration)
            expected_chunk_id = derived_identifier(
                "CHK",
                {
                    "document_version_id": chunk.get("document_version_id"),
                    "page": chunk.get("page"),
                    "section_path": chunk.get("section_path", []),
                    "start_offset": start,
                    "end_offset": end,
                    "chunking_configuration": chunking_configuration,
                },
            )
            if (
                chunk.get("chunking_configuration_hash") != expected_chunking_hash
                or chunk_id != expected_chunk_id
            ):
                errors.append(
                    _issue(
                        "invalid_chunk_identifier",
                        "Chunk ID is not derived from its recorded locator and configuration",
                        chunk_id,
                    )
                )
        else:
            warnings.append(
                _issue(
                    "legacy_chunking_configuration",
                    "Legacy chunk does not retain its full chunking configuration",
                    chunk_id,
                )
            )
    identity_codes = {
        "invalid_document_identifier",
        "invalid_document_version_reference",
        "invalid_document_version_identifier",
        "invalid_chunk_identity",
        "invalid_chunk_identifier",
    }
    checks.append(
        {
            "check": "workspace_artifact_identities",
            "passed": not any(item["code"] in identity_codes for item in errors),
            "document_count": len(documents),
            "version_count": len(versions),
            "chunk_count": len(chunks),
        }
    )


def _check_source_hashes(
    workspace: Path,
    artifacts: Any,
    errors: list[dict[str, Any]],
    checks: list[dict[str, Any]],
) -> None:
    checked = 0
    for document in artifacts:
        if document.get("schema_name") != "Document":
            continue
        checked += 1
        path = workspace / str(document["original_storage_path"])
        expected = str(document["source_sha256"]).removeprefix("sha256:")
        expected_relative = (
            Path("originals") / "sha256" / expected[:2] / expected[2:4] / expected
        ).as_posix()
        if not is_within(workspace, path):
            errors.append(
                _issue(
                    "unsafe_original_path",
                    "Document original path escapes the workspace",
                    str(document["document_id"]),
                )
            )
        elif (
            str(document.get("original_storage_path")) != expected_relative
            or not _safe_workspace_file(workspace, path)
            or file_sha256(path) != expected
            or path.stat().st_size != document.get("file_size")
        ):
            errors.append(
                _issue(
                    "source_hash_mismatch",
                    "Original source bytes do not match",
                    str(document["document_id"]),
                )
            )
    checks.append(
        {
            "check": "source_hashes",
            "passed": not any(item["code"] == "source_hash_mismatch" for item in errors),
            "count": checked,
        }
    )


def _check_document_version_derivatives(
    workspace: Path,
    versions: Any,
    errors: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    checks: list[dict[str, Any]],
) -> None:
    checked = 0
    for version in versions:
        checked += 1
        version_id = str(version["document_version_id"])
        normalized_value = str(version.get("normalized_path", ""))
        if normalized_value:
            normalized_path = workspace / normalized_value
            if not _safe_workspace_file(workspace, normalized_path):
                errors.append(
                    _issue(
                        "missing_normalized_document",
                        "Normalized document path does not resolve safely",
                        version_id,
                    )
                )
            elif version.get("normalized_sha256") is None:
                warnings.append(
                    _issue(
                        "normalized_hash_missing",
                        "Legacy document version does not record a normalized content hash",
                        version_id,
                    )
                )
            elif f"sha256:{file_sha256(normalized_path)}" != version.get("normalized_sha256"):
                errors.append(
                    _issue(
                        "normalized_hash_mismatch",
                        "Normalized document bytes do not match the version manifest",
                        version_id,
                    )
                )
        pages = list(version.get("pages", []))
        page_numbers = [item.get("page") for item in pages]
        if page_numbers and page_numbers != list(range(1, len(pages) + 1)):
            errors.append(
                _issue(
                    "noncontiguous_pdf_pages",
                    "PDF page records must be contiguous and 1-based",
                    version_id,
                )
            )
        for page in pages:
            render = page.get("render", {})
            render_path = workspace / str(render.get("path", ""))
            if not _safe_workspace_file(
                workspace, render_path
            ) or f"sha256:{file_sha256(render_path)}" != render.get("sha256"):
                errors.append(
                    _issue(
                        "page_render_hash_mismatch",
                        f"Page {page.get('page')} render does not resolve",
                        version_id,
                    )
                )
            for table in page.get("tables", []):
                table_path = workspace / str(table.get("path", ""))
                if not _safe_workspace_file(
                    workspace, table_path
                ) or f"sha256:{file_sha256(table_path)}" != table.get("sha256"):
                    errors.append(
                        _issue(
                            "table_artifact_hash_mismatch",
                            f"Page {page.get('page')} table artifact does not resolve",
                            version_id,
                        )
                    )
    derivative_codes = {
        "missing_normalized_document",
        "normalized_hash_mismatch",
        "noncontiguous_pdf_pages",
        "page_render_hash_mismatch",
        "table_artifact_hash_mismatch",
    }
    checks.append(
        {
            "check": "document_version_derivatives",
            "passed": not any(item["code"] in derivative_codes for item in errors),
            "count": checked,
        }
    )


def _check_source_snapshot(
    manifest: dict[str, Any],
    workspace_artifacts: dict[str, dict[str, Any]],
    errors: list[dict[str, Any]],
    checks: list[dict[str, Any]],
) -> None:
    snapshot_ids = [str(entry["document_id"]) for entry in manifest.get("source_snapshot", [])]
    declared_ids = [str(item) for item in manifest.get("source_document_ids", [])]
    if len(snapshot_ids) != len(set(snapshot_ids)) or sorted(snapshot_ids) != sorted(declared_ids):
        errors.append(
            _issue(
                "source_snapshot_set_mismatch",
                "Run source IDs and frozen source snapshot differ",
                str(manifest["run_id"]),
            )
        )
    for entry in manifest.get("source_snapshot", []):
        document_id = str(entry["document_id"])
        document = workspace_artifacts.get(document_id)
        version_id = entry.get("document_version_id")
        version = workspace_artifacts.get(str(version_id)) if version_id else None
        if (
            document is None
            or document.get("artifact_hash") != entry.get("document_artifact_hash")
            or document.get("source_sha256") != entry.get("source_sha256")
        ):
            errors.append(
                _issue(
                    "source_snapshot_mismatch",
                    "Run source snapshot no longer resolves to the recorded document artifact",
                    document_id,
                )
            )
        if version_id and (
            version is None
            or version.get("artifact_hash") != entry.get("document_version_artifact_hash")
        ):
            errors.append(
                _issue(
                    "version_snapshot_mismatch",
                    "Run source snapshot no longer resolves to the recorded document version",
                    str(version_id),
                )
            )
    checks.append(
        {
            "check": "source_snapshot",
            "passed": not any(
                item["code"]
                in {
                    "source_snapshot_set_mismatch",
                    "source_snapshot_mismatch",
                    "version_snapshot_mismatch",
                }
                for item in errors
            ),
            "count": len(manifest.get("source_snapshot", [])),
        }
    )


def _check_evidence(
    workspace: Path,
    evidence: dict[str, Any],
    chunks: dict[str, dict[str, Any]],
    versions: dict[str, dict[str, Any]],
    errors: list[dict[str, Any]],
    human: list[dict[str, Any]],
    checks: list[dict[str, Any]],
) -> None:
    evidence_id = str(evidence["evidence_id"])
    locator = evidence["locator"]
    expected_evidence_id = derived_identifier(
        "EVD",
        {
            "document_version_id": evidence["document_version_id"],
            "locator": locator,
            "exact_evidence_content": evidence.get("exact_text"),
            "extraction_type": evidence["evidence_type"],
        },
    )
    if evidence_id != expected_evidence_id or evidence.get("artifact_id") != expected_evidence_id:
        errors.append(
            _issue(
                "invalid_evidence_identifier",
                "Evidence identifier is not derived from its immutable content",
                evidence_id,
            )
        )
    version = versions.get(str(evidence["document_version_id"]))
    if version is None or version.get("document_id") != evidence.get("document_id"):
        errors.append(
            _issue(
                "dangling_document_version",
                "Evidence document version does not resolve",
                evidence_id,
            )
        )
        return
    version_status = version.get("extraction_status")
    referenced_page = next(
        (item for item in version.get("pages", []) if item.get("page") == locator.get("page")),
        None,
    )
    partial_source_is_relevant = locator.get("page") is None or (
        referenced_page is not None and referenced_page.get("extraction_status") != "extracted"
    )
    if version_status in {"ambiguous", "human_review_required"} or (
        version_status == "partially_extracted" and partial_source_is_relevant
    ):
        human.append(
            _issue(
                "source_extraction_review",
                f"Evidence uses a source with extraction status {version_status}",
                evidence_id,
            )
        )
    if version_status in {"processing_failed", "ocr_required"}:
        human.append(
            _issue(
                "unusable_source_extraction",
                f"Evidence uses a source with extraction status {version_status}",
                evidence_id,
            )
        )
    if locator.get("type") == "text_span":
        chunk = chunks.get(str(locator.get("chunk_id")))
        if chunk is None:
            errors.append(_issue("dangling_chunk", "Evidence chunk does not resolve", evidence_id))
            return
        if chunk.get("document_version_id") != evidence.get("document_version_id"):
            errors.append(
                _issue(
                    "locator_version_mismatch",
                    "Chunk belongs to another document version",
                    evidence_id,
                )
            )
            return
        if locator.get("page") != chunk.get("page"):
            errors.append(
                _issue("locator_page_mismatch", "Locator page differs from its chunk", evidence_id)
            )
        if locator.get("section_path") not in (None, chunk.get("section_path")):
            errors.append(
                _issue(
                    "locator_section_mismatch",
                    "Locator section path differs from its chunk",
                    evidence_id,
                )
            )
        locator_line_start = locator.get("source_line_start")
        locator_line_end = locator.get("source_line_end")
        chunk_line_start = chunk.get("source_line_start")
        chunk_line_end = chunk.get("source_line_end")
        if (locator_line_start is not None or locator_line_end is not None) and (
            not all(
                isinstance(value, int)
                for value in (
                    locator_line_start,
                    locator_line_end,
                    chunk_line_start,
                    chunk_line_end,
                )
            )
            or locator_line_start < chunk_line_start
            or locator_line_end > chunk_line_end
            or locator_line_end < locator_line_start
        ):
            errors.append(
                _issue(
                    "locator_line_mismatch",
                    "Locator source lines fall outside its chunk",
                    evidence_id,
                )
            )
        start = locator.get("start_offset")
        end = locator.get("end_offset")
        text = str(chunk.get("exact_text", ""))
        if (
            not isinstance(start, int)
            or not isinstance(end, int)
            or start < 0
            or end <= start
            or end > len(text)
        ):
            errors.append(
                _issue("invalid_text_span", "Text locator offsets are invalid", evidence_id)
            )
            return
        exact = text[start:end]
        if exact != evidence.get("exact_text"):
            errors.append(
                _issue(
                    "text_span_mismatch",
                    "Exact evidence text does not match the located span",
                    evidence_id,
                )
            )
        if prefixed_sha256(exact.encode("utf-8")) != locator.get("span_sha256"):
            errors.append(
                _issue("span_hash_mismatch", "Text span hash does not match", evidence_id)
            )
        normalized_path = workspace / str(version.get("normalized_path", ""))
        document_start = int(chunk.get("start_offset", -1))
        document_end = int(chunk.get("end_offset", -1))
        if not _safe_workspace_file(workspace, normalized_path):
            errors.append(
                _issue(
                    "missing_normalized_source",
                    "Evidence chunk has no resolvable normalized source",
                    evidence_id,
                )
            )
        else:
            normalized = normalized_path.read_text(encoding="utf-8")
            if (
                document_start < 0
                or document_end <= document_start
                or document_end > len(normalized)
                or normalized[document_start:document_end] != text
                or prefixed_sha256(text.encode("utf-8")) != chunk.get("text_sha256")
            ):
                errors.append(
                    _issue(
                        "chunk_source_mismatch",
                        "Evidence chunk does not resolve into normalized source text",
                        evidence_id,
                    )
                )
        if locator.get("page") is not None:
            page_record = referenced_page
            if page_record is None:
                errors.append(
                    _issue("invalid_text_page", "Text locator page does not resolve", evidence_id)
                )
            elif page_record.get("ocr_required"):
                human.append(
                    _issue(
                        "ocr_page_evidence",
                        "Text evidence points to an OCR-required page",
                        evidence_id,
                    )
                )
    elif locator.get("type") == "visual_region":
        page_number = locator.get("page")
        page = next(
            (item for item in version.get("pages", []) if item.get("page") == page_number), None
        )
        if page is None:
            errors.append(
                _issue("invalid_visual_page", "Visual locator page does not resolve", evidence_id)
            )
            return
        render = page.get("render", {})
        render_path = workspace / str(render.get("path", ""))
        if not _safe_workspace_file(
            workspace, render_path
        ) or f"sha256:{file_sha256(render_path)}" != locator.get("render_sha256"):
            errors.append(
                _issue(
                    "visual_render_mismatch",
                    "Visual locator render hash does not resolve",
                    evidence_id,
                )
            )
        if locator.get("render_width") != render.get("width") or locator.get(
            "render_height"
        ) != render.get("height"):
            errors.append(
                _issue(
                    "visual_render_dimensions_mismatch",
                    "Visual locator dimensions do not match the referenced render",
                    evidence_id,
                )
            )
        box = locator.get("bounding_box", {})
        values = [box.get(name) for name in ("x", "y", "width", "height")]
        if not all(isinstance(value, (int, float)) and 0 <= value <= 1 for value in values):
            errors.append(
                _issue(
                    "invalid_visual_region",
                    "Visual bounding box values must be within [0,1]",
                    evidence_id,
                )
            )
        elif (
            box["width"] <= 0
            or box["height"] <= 0
            or box["x"] + box["width"] > 1
            or box["y"] + box["height"] > 1
        ):
            errors.append(
                _issue("invalid_visual_region", "Visual bounding box exceeds the page", evidence_id)
            )
        if evidence.get("human_review_required") or evidence.get("extraction_status") in {
            "ambiguous",
            "ocr_required",
            "human_review_required",
        }:
            human.append(
                _issue(
                    "visual_or_ocr_review",
                    "Visual or OCR-dependent evidence requires human review",
                    evidence_id,
                )
            )
        if evidence.get("interpretation_status") in {
            "agent_interpreted",
            "uncertain",
            "human_review_required",
        }:
            human.append(
                _issue(
                    "visual_interpretation_review",
                    "Visual evidence interpretation is not independently or human verified",
                    evidence_id,
                )
            )
        elif evidence.get("interpretation_status") == "human_verified":
            human.append(
                _issue(
                    "human_visual_verification_provenance",
                    "Human-verified visual evidence requires a reviewed verification amendment",
                    evidence_id,
                )
            )
    else:
        errors.append(
            _issue("unsupported_locator", "Evidence locator type is unsupported", evidence_id)
        )
    checks.append(
        {
            "check": "evidence_locator",
            "artifact_id": evidence_id,
            "passed": not any(item["artifact_id"] == evidence_id for item in errors),
        }
    )


def _check_claim(
    claim: dict[str, Any],
    evidence: dict[str, dict[str, Any]],
    reviews: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
    profile: dict[str, Any],
    errors: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    human: list[dict[str, Any]],
) -> None:
    claim_id = str(claim["claim_id"])
    supporting = list(claim.get("supporting_evidence_ids", []))
    contradicting = list(claim.get("contradicting_evidence_ids", []))
    if not supporting:
        errors.append(
            _issue("claim_without_evidence", "Claim has no supporting evidence", claim_id)
        )
    for evidence_id in supporting + contradicting:
        if evidence_id not in evidence:
            errors.append(
                _issue(
                    "dangling_evidence",
                    f"Claim references missing evidence {evidence_id}",
                    claim_id,
                )
            )
    factors = claim.get("factors", {})
    for name in FACTOR_NAMES:
        if factors.get(name) not in FACTOR_VALUES:
            errors.append(
                _issue("invalid_confidence_factor", f"Missing or invalid factor {name}", claim_id)
            )
    classification = claim.get("support_classification")
    if claim.get("claim_status") not in {"independently_reviewed", "accepted"}:
        errors.append(
            _issue(
                "claim_lifecycle_incomplete",
                "Reportable claim must be independently reviewed or accepted",
                claim_id,
            )
        )
    if claim.get("citation_status") != "passed":
        errors.append(
            _issue("claim_citation_incomplete", "Claim citation status has not passed", claim_id)
        )
    if claim.get("methodology_status") in {"pending", "not_reviewed", None}:
        errors.append(
            _issue(
                "claim_methodology_incomplete",
                "Claim methodology review status is incomplete",
                claim_id,
            )
        )
    if claim.get("contradiction_status") in {"pending", "not_reviewed", None}:
        errors.append(
            _issue(
                "claim_contradiction_incomplete",
                "Claim contradiction review status is incomplete",
                claim_id,
            )
        )
    if classification == "verified":
        if claim.get("claim_type") not in DIRECTLY_VERIFIABLE_TYPES:
            errors.append(
                _issue(
                    "verified_scope_violation",
                    "Only directly checkable facts may be verified",
                    claim_id,
                )
            )
        if contradicting or claim.get("contradiction_status") not in {"passed", "none", "resolved"}:
            errors.append(
                _issue(
                    "verified_contradiction",
                    "Verified claim has unresolved contradiction",
                    claim_id,
                )
            )
        if claim.get("citation_status") != "passed":
            errors.append(
                _issue(
                    "verified_citation", "Verified claim has not passed citation review", claim_id
                )
            )
        if factors.get("visual_certainty") not in {"high", "not_applicable"} or factors.get(
            "ocr_dependency"
        ) not in {"not_applicable", "low"}:
            errors.append(
                _issue(
                    "verified_uncertain_source",
                    "Verified claim depends on uncertain visual or OCR evidence",
                    claim_id,
                )
            )
        for factor_name, allowed in {
            "evidence_directness": {"high"},
            "citation_validity": {"high"},
            "reviewer_agreement": {"high", "medium"},
            "reviewer_independence": {"high", "medium"},
        }.items():
            if factors.get(factor_name) not in allowed:
                errors.append(
                    _issue(
                        "verified_factor_insufficient",
                        f"Verified claim has insufficient {factor_name}",
                        claim_id,
                    )
                )
    if classification == "strongly_supported" and len(supporting) < 2:
        errors.append(
            _issue(
                "strong_support_insufficient",
                "Strong support requires multiple evidence records",
                claim_id,
            )
        )
    if classification == "strongly_supported":
        supporting_documents = {
            str(evidence[evidence_id]["document_id"])
            for evidence_id in supporting
            if evidence_id in evidence
        }
        if len(supporting_documents) < 2:
            errors.append(
                _issue(
                    "strong_support_source_count",
                    "Strong support requires evidence from multiple source documents",
                    claim_id,
                )
            )
        for factor_name, allowed in {
            "evidence_directness": {"high", "medium"},
            "source_quality": {"high", "medium"},
            "methodology_quality": {"high", "medium", "not_applicable"},
            "evidence_coverage": {"high", "medium"},
            "citation_validity": {"high"},
            "reviewer_agreement": {"high", "medium"},
            "reviewer_independence": {"high", "medium"},
        }.items():
            if factors.get(factor_name) not in allowed:
                errors.append(
                    _issue(
                        "strong_support_factor_insufficient",
                        f"Strong support has insufficient {factor_name}",
                        claim_id,
                    )
                )
        dependent_types = {
            "duplicate",
            "republication",
            "revision_of",
            "translation_of",
            "summarizes",
            "derived_from",
            "shares_primary_dataset",
            "shares_experimental_result",
        }
        supporting_pairs = {
            frozenset((left, right))
            for left in supporting_documents
            for right in supporting_documents
            if left < right
        }
        relationship_by_pair = {
            frozenset(
                (
                    str(item.get("source_document_id")),
                    str(item.get("related_document_id")),
                )
            ): item
            for item in relationships
        }
        if any(
            relationship_by_pair[pair].get("relationship_type") in dependent_types
            for pair in supporting_pairs
            if pair in relationship_by_pair
        ):
            errors.append(
                _issue(
                    "strong_support_dependent_sources",
                    "Strong support counts sources recorded as dependent",
                    claim_id,
                )
            )
        if any(
            pair not in relationship_by_pair
            or relationship_by_pair[pair].get("relationship_type") == "unknown"
            or relationship_by_pair[pair].get("confidence") in {"low", "unknown"}
            or relationship_by_pair[pair].get("human_review_status")
            in {"pending", "required", "unknown", "human_review_required"}
            for pair in supporting_pairs
        ):
            human.append(
                _issue(
                    "unassessed_source_relationship",
                    "Strong support uses source pairs without a relationship assessment",
                    claim_id,
                )
            )
    if classification in {"verified", "strongly_supported"} and factors.get(
        "source_independence"
    ) in {"low", "unknown"}:
        errors.append(
            _issue(
                "source_independence_insufficient",
                "High support requires assessed source independence",
                claim_id,
            )
        )
    if claim.get("claim_type") == "causal_claim" and factors.get("methodology_quality") in {
        "low",
        "unknown",
    }:
        human.append(
            _issue(
                "causal_methodology_review",
                "Causal claim lacks adequate methodology support",
                claim_id,
            )
        )
    if claim.get("contradiction_status") == "unresolved":
        human.append(
            _issue(
                "material_unresolved_contradiction", "Claim has unresolved contradictions", claim_id
            )
        )
    if claim.get("human_review_required"):
        human.append(
            _issue("claim_human_review", "Claim explicitly requires human review", claim_id)
        )
    if factors.get("source_independence") == "unknown":
        human.append(
            _issue("unknown_source_independence", "Source independence is unknown", claim_id)
        )
    if classification in {"unsupported", "unable_to_determine", "conflicting_evidence"}:
        warnings.append(
            _issue("limited_conclusion", f"Claim is classified {classification}", claim_id)
        )


def _check_review_references(
    reviews: list[dict[str, Any]],
    all_by_id: dict[str, dict[str, Any]],
    claims: dict[str, dict[str, Any]],
    evidence: dict[str, dict[str, Any]],
    errors: list[dict[str, Any]],
    checks: list[dict[str, Any]],
) -> None:
    known_ids = {*all_by_id, *claims, *evidence}
    for review in reviews:
        review_id = str(review.get("review_id", "unknown"))
        for reviewed_id in review.get("reviewed_artifact_ids", []):
            if str(reviewed_id) not in known_ids:
                errors.append(
                    _issue(
                        "dangling_review_reference",
                        f"Review references unknown artifact {reviewed_id}",
                        review_id,
                    )
                )
        for assessment in review.get("claim_assessments", []):
            claim_id = str(assessment.get("claim_id", ""))
            if claim_id not in claims:
                errors.append(
                    _issue(
                        "dangling_review_claim",
                        f"Review assessment references unknown claim {claim_id}",
                        review_id,
                    )
                )
    checks.append(
        {
            "check": "review_references",
            "passed": not any(
                item["code"] in {"dangling_review_reference", "dangling_review_claim"}
                for item in errors
            ),
        }
    )


def _check_reviews(
    reviews: list[dict[str, Any]],
    claims: dict[str, dict[str, Any]],
    profile: dict[str, Any],
    errors: list[dict[str, Any]],
    human: list[dict[str, Any]],
    *,
    require_modern_contracts: bool = False,
    valid_search_event_ids: set[str] | None = None,
) -> None:
    for review in reviews:
        if review.get("review_type") == "human_review" and (
            review.get("created_by", {}).get("actor_type") != "human"
            or not isinstance(review.get("reviewer_identity"), dict)
            or not review.get("reviewer_identity")
        ):
            errors.append(
                _issue(
                    "invalid_human_attestation",
                    "Human review lacks a non-empty identity or human actor declaration",
                    str(review.get("review_id", "unknown")),
                )
            )
    for claim_id in claims:
        claim_reviews = [
            item for item in reviews if claim_id in item.get("reviewed_artifact_ids", [])
        ]
        for required_type in profile["required_review_types"]:
            matching = [item for item in claim_reviews if item.get("review_type") == required_type]
            if not matching:
                errors.append(
                    _issue("missing_review", f"Missing required {required_type}", claim_id)
                )
                continue
            latest = max(matching, key=lambda item: str(item["created_at"]))
            decision = latest.get("decision")
            if decision == "human_review_required":
                human.append(
                    _issue(
                        "review_requires_human",
                        f"{required_type} requires human review",
                        claim_id,
                    )
                )
            elif decision not in PASSING_REVIEW_DECISIONS:
                errors.append(
                    _issue("review_not_passed", f"{required_type} did not pass", claim_id)
                )
            assessment = next(
                (
                    item
                    for item in latest.get("claim_assessments", [])
                    if item.get("claim_id") == claim_id
                ),
                None,
            )
            if assessment is None:
                errors.append(
                    _issue(
                        "missing_claim_assessment",
                        f"{required_type} has no typed assessment for the claim",
                        claim_id,
                    )
                )
                continue
            if (
                required_type == "citation_review"
                and assessment.get("citation_support") != "supports"
            ):
                errors.append(
                    _issue(
                        "citation_not_supporting",
                        f"Citation assessment is {assessment.get('citation_support', 'missing')}",
                        claim_id,
                    )
                )
            if required_type == "citation_review" and require_modern_contracts:
                evidence_assessments = {
                    str(item.get("evidence_id")): item
                    for item in assessment.get("evidence_assessments", [])
                }
                supporting_ids = set(claims[claim_id].get("supporting_evidence_ids", []))
                contradicting_ids = set(claims[claim_id].get("contradicting_evidence_ids", []))
                if set(evidence_assessments) != supporting_ids | contradicting_ids:
                    errors.append(
                        _issue(
                            "citation_evidence_coverage_missing",
                            "Citation review did not assess every cited evidence record",
                            claim_id,
                        )
                    )
                elif any(
                    evidence_assessments[evidence_id].get("citation_support") != "supports"
                    or evidence_assessments[evidence_id].get("context_preserved") is not True
                    for evidence_id in supporting_ids
                ) or any(
                    evidence_assessments[evidence_id].get("citation_support")
                    not in {"contradicts", "supports"}
                    or evidence_assessments[evidence_id].get("context_preserved") is not True
                    for evidence_id in contradicting_ids
                ):
                    errors.append(
                        _issue(
                            "citation_evidence_not_supporting",
                            "At least one evidence-level citation decision fails support or context",
                            claim_id,
                        )
                    )
            if (
                required_type == "contradiction_review"
                and assessment.get("contradiction_search_performed") is not True
            ):
                errors.append(
                    _issue(
                        "contradiction_search_missing",
                        "Contradiction review did not attest to an active search",
                        claim_id,
                    )
                )
            if required_type == "contradiction_review" and require_modern_contracts:
                contradiction_search_events = {
                    str(item) for item in assessment.get("contradiction_search_event_ids", [])
                }
                if not contradiction_search_events or not contradiction_search_events.issubset(
                    valid_search_event_ids or set()
                ):
                    errors.append(
                        _issue(
                            "contradiction_search_event_missing",
                            "Contradiction review did not bind a valid run-scoped search event",
                            claim_id,
                        )
                    )
            if required_type == "methodology_review" and assessment.get("methodology_quality") in {
                "low",
                "unknown",
                None,
            }:
                human.append(
                    _issue(
                        "methodology_review_required",
                        "Methodology quality is low or unknown",
                        claim_id,
                    )
                )
            if required_type == "independent_review" and assessment.get(
                "support_assessment"
            ) not in {"supports", "partially_supports"}:
                errors.append(
                    _issue(
                        "independent_support_failure",
                        "Independent review does not support the claim",
                        claim_id,
                    )
                )
            if required_type == "independent_review":
                minimum = str(profile["minimum_independence"])
                actual = str(latest.get("reviewer_independence_status"))
                if INDEPENDENCE_RANK.get(actual, 0) < INDEPENDENCE_RANK[minimum]:
                    human.append(
                        _issue(
                            "insufficient_reviewer_independence",
                            f"Independent review is {actual}; profile requires {minimum}",
                            claim_id,
                        )
                    )
                _check_independence_declaration(latest, claim_id, errors)
                if claims[claim_id].get("independent_review_status") != actual:
                    errors.append(
                        _issue(
                            "claim_independence_status_mismatch",
                            "Claim independence status does not match the latest review",
                            claim_id,
                        )
                    )


def _check_amendments(
    amendments: list[dict[str, Any]],
    artifacts_by_hash: dict[str, dict[str, Any]],
    reviews: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    human: list[dict[str, Any]],
) -> None:
    for amendment in amendments:
        amendment_id = str(amendment["amendment_id"])
        if (
            amendment.get("created_by", {}).get("actor_type") != "human"
            or not isinstance(amendment.get("human_identity"), dict)
            or not amendment.get("human_identity")
        ):
            errors.append(
                _issue(
                    "invalid_human_amendment",
                    "Amendment lacks a non-empty human identity or human actor declaration",
                    amendment_id,
                )
            )
        target = artifacts_by_hash.get(str(amendment["target_artifact_hash"]))
        replacement = artifacts_by_hash.get(str(amendment["replacement_artifact_hash"]))
        if target is None or target.get("artifact_id") != amendment.get("target_artifact_id"):
            errors.append(
                _issue(
                    "invalid_amendment_target", "Amendment target does not resolve", amendment_id
                )
            )
        if replacement is None or replacement.get("artifact_id") != amendment.get(
            "replacement_artifact_id"
        ):
            errors.append(
                _issue(
                    "invalid_amendment_replacement",
                    "Amendment replacement does not resolve",
                    amendment_id,
                )
            )
        if amendment.get("review_required") and not _has_passing_human_review(
            amendment_id, reviews
        ):
            human.append(
                _issue(
                    "amendment_review_required",
                    "Amendment requires a passing human review",
                    amendment_id,
                )
            )


def _check_source_relationships(
    relationships: list[dict[str, Any]],
    document_ids: set[str],
    errors: list[dict[str, Any]],
    checks: list[dict[str, Any]],
) -> None:
    for relationship in relationships:
        relationship_id = str(relationship["relationship_id"])
        source = str(relationship["source_document_id"])
        related = str(relationship["related_document_id"])
        if source not in document_ids or related not in document_ids:
            errors.append(
                _issue(
                    "dangling_source_relationship",
                    "Source relationship references a missing document",
                    relationship_id,
                )
            )
        if source == related:
            errors.append(
                _issue(
                    "self_source_relationship",
                    "A source relationship must connect distinct document identities",
                    relationship_id,
                )
            )
    checks.append(
        {
            "check": "source_relationships",
            "passed": not any(
                item["code"] in {"dangling_source_relationship", "self_source_relationship"}
                for item in errors
            ),
            "count": len(relationships),
        }
    )


def _human_requirement_resolved(
    issue: dict[str, Any],
    amendments: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
) -> bool:
    artifact_id = str(issue["artifact_id"])
    if issue["code"] in {
        "visual_or_ocr_review",
        "visual_interpretation_review",
        "human_visual_verification_provenance",
        "ocr_page_evidence",
        "unusable_source_extraction",
    }:
        allowed_types = {"human_visual_verification", "human_ocr_verification"}
        matching = [
            amendment
            for amendment in amendments
            if amendment.get("replacement_artifact_id") == artifact_id
            and amendment.get("amendment_type") in allowed_types
        ]
        return any(
            _has_passing_human_review(str(amendment["amendment_id"]), reviews)
            for amendment in matching
        )
    return _has_passing_human_review(artifact_id, reviews)


def _has_passing_human_review(artifact_id: str, reviews: list[dict[str, Any]]) -> bool:
    return any(
        item.get("review_type") == "human_review"
        and artifact_id in item.get("reviewed_artifact_ids", [])
        and item.get("decision") in PASSING_REVIEW_DECISIONS
        for item in reviews
    )


def _check_independence_declaration(
    review: dict[str, Any], claim_id: str, errors: list[dict[str, Any]]
) -> None:
    status = review.get("reviewer_independence_status")
    declaration = review.get("review_independence")
    if not isinstance(declaration, dict) or declaration.get("status") != status:
        errors.append(
            _issue(
                "invalid_independence_declaration",
                "Independent review declaration is missing or inconsistent",
                claim_id,
            )
        )
        return
    if status in {"confirmed_independent", "procedurally_isolated"}:
        required_true = (
            "primary_rationale_excluded",
            "primary_confidence_excluded",
            "prior_review_conclusions_excluded",
            "fresh_agent_context_requested",
        )
        if not all(declaration.get(key) is True for key in required_true):
            errors.append(
                _issue(
                    "independence_exclusion_failure",
                    "Independent reviewer received or may have received prohibited context",
                    claim_id,
                )
            )
    if (
        status == "confirmed_independent"
        and declaration.get("host_confirmed_fresh_context") is not True
    ):
        errors.append(
            _issue(
                "independence_confirmation_missing",
                "confirmed_independent requires host confirmation of fresh context",
                claim_id,
            )
        )


def _issue(code: str, message: str, artifact_id: str) -> dict[str, Any]:
    return {"code": code, "message": message, "artifact_id": artifact_id}


def _safe_workspace_file(root: Path, path: Path) -> bool:
    if not is_within(root, path):
        return False
    try:
        ensure_no_symlink_components(root, path)
    except (ResearchError, ValueError):
        return False
    return path.is_file()


def _deduplicate_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique = {(item["code"], item["message"], item["artifact_id"]): item for item in issues}
    return [unique[key] for key in sorted(unique)]
