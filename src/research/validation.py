from __future__ import annotations

from pathlib import Path
from typing import Any

from research.artifacts import artifact_base, store_artifact
from research.canonical import prefixed_sha256, verify_artifact_hash
from research.constants import EXIT_REPORT_GATE, PHASES
from research.errors import ResearchError
from research.identifiers import generated_identifier
from research.io import file_sha256, iter_json
from research.runs import load_profile, load_run, transition_after_validation
from research.schema_registry import SchemaRegistry
from research.security import is_within

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

    artifacts = _current_run_artifacts(run_dir)
    workspace_artifacts = _workspace_artifacts(workspace)
    all_by_id = {**workspace_artifacts, **_all_run_artifacts_by_id(run_dir)}

    _check_artifacts(artifacts, registry, errors, checks)
    _check_artifacts(list(workspace_artifacts.values()), registry, errors, checks)
    _check_source_hashes(workspace, workspace_artifacts.values(), errors, checks)
    _check_source_snapshot(manifest, workspace_artifacts, errors, checks)

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
    source_snapshot = {
        str(entry["document_id"]): entry for entry in manifest.get("source_snapshot", [])
    }

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
    for claim in claims.values():
        _check_claim(claim, evidence, reviews, profile, errors, warnings, human_requirements)
    _check_reviews(reviews, claims, profile, errors, human_requirements)
    _check_amendments(amendments, all_by_id, reviews, errors, human_requirements)
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
    validated_hashes = sorted(
        str(item["artifact_hash"])
        for item in artifacts
        if isinstance(item.get("artifact_hash"), str)
    )
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
        if not is_within(workspace, path):
            errors.append(
                _issue(
                    "unsafe_original_path",
                    "Document original path escapes the workspace",
                    str(document["document_id"]),
                )
            )
        elif not path.is_file() or file_sha256(path) != expected:
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


def _check_source_snapshot(
    manifest: dict[str, Any],
    workspace_artifacts: dict[str, dict[str, Any]],
    errors: list[dict[str, Any]],
    checks: list[dict[str, Any]],
) -> None:
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
                item["code"] in {"source_snapshot_mismatch", "version_snapshot_mismatch"}
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
        if not render_path.is_file() or f"sha256:{file_sha256(render_path)}" != locator.get(
            "render_sha256"
        ):
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
        if factors.get("visual_certainty") in {"low", "unknown"} or factors.get(
            "ocr_dependency"
        ) not in {"not_applicable", "low"}:
            errors.append(
                _issue(
                    "verified_uncertain_source",
                    "Verified claim depends on uncertain visual or OCR evidence",
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


def _check_reviews(
    reviews: list[dict[str, Any]],
    claims: dict[str, dict[str, Any]],
    profile: dict[str, Any],
    errors: list[dict[str, Any]],
    human: list[dict[str, Any]],
) -> None:
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
    artifacts: dict[str, dict[str, Any]],
    reviews: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    human: list[dict[str, Any]],
) -> None:
    for amendment in amendments:
        amendment_id = str(amendment["amendment_id"])
        target = artifacts.get(str(amendment["target_artifact_id"]))
        replacement = artifacts.get(str(amendment["replacement_artifact_id"]))
        if target is None or target.get("artifact_hash") != amendment.get("target_artifact_hash"):
            errors.append(
                _issue(
                    "invalid_amendment_target", "Amendment target does not resolve", amendment_id
                )
            )
        if replacement is None or replacement.get("artifact_hash") != amendment.get(
            "replacement_artifact_hash"
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


def _deduplicate_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique = {(item["code"], item["message"], item["artifact_id"]): item for item in issues}
    return [unique[key] for key in sorted(unique)]
