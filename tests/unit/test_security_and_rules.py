from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from research.config import load_config
from research.errors import ResearchError
from research.io import write_text_atomic
from research.security import ensure_workspace_write, redact_secrets, validate_import_source
from research.validation import _check_claim, _check_reviews


def test_workspace_write_containment_and_secret_redaction(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with pytest.raises(ResearchError) as error:
        ensure_workspace_write(workspace, tmp_path / "outside.json")
    assert error.value.category == "unsafe_path"
    assert "super-secret" not in redact_secrets("api_key=super-secret")


def test_invalid_config_fails_before_processing(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "research.yaml").write_text(
        yaml.safe_dump({"pdf": {"render_dpi": "fast"}}), encoding="utf-8"
    )
    with pytest.raises(ResearchError) as error:
        load_config(workspace)
    assert error.value.category == "invalid_config"
    assert "pdf.render_dpi" in str(error.value)


def test_import_symlink_is_rejected_when_platform_supports_it(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    source.write_text("safe", encoding="utf-8")
    link = tmp_path / "linked.md"
    try:
        link.symlink_to(source)
    except OSError:
        pytest.skip("Creating symlinks requires unavailable platform privileges")
    with pytest.raises(ResearchError) as error:
        validate_import_source(link, 1024)
    assert error.value.category == "unsafe_path"


def test_generated_write_rejects_symlink_redirection_when_supported(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    redirected = workspace / "result.txt"
    try:
        redirected.symlink_to(outside)
    except OSError:
        pytest.skip("Creating symlinks requires unavailable platform privileges")
    with pytest.raises(ResearchError) as error:
        write_text_atomic(redirected, "must not escape", root=workspace)
    assert error.value.category == "unsafe_path"
    assert outside.read_text(encoding="utf-8") == "outside"


def test_verified_causal_claim_and_non_supporting_citation_are_rejected() -> None:
    claim = {
        "claim_id": "CLM-test",
        "claim_type": "causal_claim",
        "support_classification": "verified",
        "supporting_evidence_ids": ["EVD-test"],
        "contradicting_evidence_ids": [],
        "contradiction_status": "none",
        "citation_status": "passed",
        "human_review_required": False,
        "factors": {
            "evidence_directness": "high",
            "source_quality": "high",
            "source_independence": "high",
            "methodology_quality": "high",
            "contradictory_evidence": "low",
            "evidence_coverage": "high",
            "citation_validity": "high",
            "reviewer_agreement": "high",
            "reviewer_independence": "high",
            "visual_certainty": "not_applicable",
            "ocr_dependency": "not_applicable",
        },
    }
    errors: list[dict[str, object]] = []
    warnings: list[dict[str, object]] = []
    human: list[dict[str, object]] = []
    _check_claim(
        claim,
        {"EVD-test": {"evidence_id": "EVD-test"}},
        [],
        [],
        {},
        errors,
        warnings,
        human,
    )
    assert any(item["code"] == "verified_scope_violation" for item in errors)

    profile = {
        "required_review_types": ["citation_review"],
        "minimum_independence": "procedurally_isolated",
    }
    review = {
        "created_at": "2026-01-01T00:00:00Z",
        "review_type": "citation_review",
        "reviewed_artifact_ids": ["CLM-test"],
        "decision": "passed",
        "claim_assessments": [
            {
                "claim_id": "CLM-test",
                "assessment": "topically related only",
                "citation_support": "related_not_supporting",
            }
        ],
    }
    review_errors: list[dict[str, object]] = []
    _check_reviews([review], {"CLM-test": claim}, profile, review_errors, [])
    assert any(item["code"] == "citation_not_supporting" for item in review_errors)


def test_review_human_decision_creates_resolvable_requirement_not_structural_error() -> None:
    claim = {"claim_id": "CLM-test", "independent_review_status": "confirmed_independent"}
    profile = {
        "required_review_types": ["independent_review"],
        "minimum_independence": "procedurally_isolated",
    }
    review = {
        "created_at": "2026-01-01T00:00:00Z",
        "review_type": "independent_review",
        "reviewed_artifact_ids": ["CLM-test"],
        "reviewer_independence_status": "confirmed_independent",
        "review_independence": {
            "primary_rationale_excluded": True,
            "primary_confidence_excluded": True,
            "prior_review_conclusions_excluded": True,
            "fresh_agent_context_requested": True,
            "host_confirmed_fresh_context": True,
            "status": "confirmed_independent",
        },
        "decision": "human_review_required",
        "claim_assessments": [
            {
                "claim_id": "CLM-test",
                "assessment": "support is bounded but a material conflict remains",
                "support_assessment": "supports",
            }
        ],
    }
    errors: list[dict[str, object]] = []
    human: list[dict[str, object]] = []
    _check_reviews([review], {"CLM-test": claim}, profile, errors, human)
    assert not any(item["code"] == "review_not_passed" for item in errors)
    assert any(item["code"] == "review_requires_human" for item in human)


def test_strong_support_rejects_dependent_sources_and_requires_relationship_assessment() -> None:
    claim = {
        "claim_id": "CLM-test",
        "claim_type": "comparative_result",
        "claim_status": "independently_reviewed",
        "support_classification": "strongly_supported",
        "supporting_evidence_ids": ["EVD-one", "EVD-two"],
        "contradicting_evidence_ids": [],
        "contradiction_status": "none",
        "citation_status": "passed",
        "methodology_status": "adequate",
        "human_review_required": False,
        "factors": {
            "evidence_directness": "high",
            "source_quality": "high",
            "source_independence": "high",
            "methodology_quality": "high",
            "contradictory_evidence": "low",
            "evidence_coverage": "high",
            "citation_validity": "high",
            "reviewer_agreement": "high",
            "reviewer_independence": "high",
            "visual_certainty": "not_applicable",
            "ocr_dependency": "not_applicable",
        },
    }
    evidence = {
        "EVD-one": {"evidence_id": "EVD-one", "document_id": "DOC-one"},
        "EVD-two": {"evidence_id": "EVD-two", "document_id": "DOC-two"},
    }
    dependent = {
        "source_document_id": "DOC-one",
        "related_document_id": "DOC-two",
        "relationship_type": "shares_primary_dataset",
        "confidence": "high",
        "human_review_status": "reviewed",
    }
    errors: list[dict[str, object]] = []
    human: list[dict[str, object]] = []
    _check_claim(claim, evidence, [], [dependent], {}, errors, [], human)
    assert any(item["code"] == "strong_support_dependent_sources" for item in errors)

    unassessed_errors: list[dict[str, object]] = []
    unassessed_human: list[dict[str, object]] = []
    _check_claim(claim, evidence, [], [], {}, unassessed_errors, [], unassessed_human)
    assert any(item["code"] == "unassessed_source_relationship" for item in unassessed_human)


def test_unable_to_determine_is_a_valid_reviewed_claim_outcome() -> None:
    claim = {
        "claim_id": "CLM-insufficient",
        "claim_type": "insufficient_evidence_finding",
        "claim_status": "independently_reviewed",
        "support_classification": "unable_to_determine",
        "supporting_evidence_ids": ["EVD-scope"],
        "contradicting_evidence_ids": [],
        "contradiction_status": "none",
        "citation_status": "passed",
        "methodology_status": "not_applicable",
        "human_review_required": False,
        "factors": {
            "evidence_directness": "medium",
            "source_quality": "medium",
            "source_independence": "not_applicable",
            "methodology_quality": "not_applicable",
            "contradictory_evidence": "low",
            "evidence_coverage": "low",
            "citation_validity": "high",
            "reviewer_agreement": "high",
            "reviewer_independence": "medium",
            "visual_certainty": "not_applicable",
            "ocr_dependency": "not_applicable",
        },
    }
    errors: list[dict[str, object]] = []
    warnings: list[dict[str, object]] = []
    human: list[dict[str, object]] = []
    _check_claim(
        claim,
        {"EVD-scope": {"evidence_id": "EVD-scope", "document_id": "DOC-scope"}},
        [],
        [],
        {},
        errors,
        warnings,
        human,
    )
    assert errors == []
    assert human == []
    assert any(item["code"] == "limited_conclusion" for item in warnings)
