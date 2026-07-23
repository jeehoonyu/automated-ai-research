from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from research.artifacts import artifact_base
from research.canonical import finalize_artifact, prefixed_sha256
from research.identifiers import derived_identifier, generated_identifier
from research.ingestion import import_sources
from research.inspection import inspect_artifact
from research.io import iter_json, write_json_atomic
from research.reporting import generate_report
from research.runs import create_run, load_run, promote_stage, run_status
from research.validation import validate_run


def test_complete_agent_artifact_flow(workspace: Path, tmp_path: Path) -> None:
    source = tmp_path / "study.md"
    source.write_text(
        "# Results\n\nThe measured configuration used 120 samples and reported lower data movement.\n",
        encoding="utf-8",
    )
    imported = import_sources(workspace, [source])
    assert imported["failed_count"] == 0
    run = create_run(workspace, "What did the study report?", "default", host="codex")
    run_id = run["run_id"]
    run_dir = Path(run["run_path"])

    plan = _artifact(
        "ResearchPlan",
        generated_identifier("PLAN"),
        run_id=run_id,
        main_question="What did the study report?",
        subquestions=["What sample count was reported?"],
        definitions=[],
        scope={"documents": "local corpus"},
        inclusion_criteria=["direct statements"],
        exclusion_criteria=["unsupported interpretation"],
        search_terms=["samples", "data movement"],
        evidence_requirements=["exact text locator"],
        validation_criteria=["citation review"],
        expected_limitations=["single synthetic source"],
        high_risk_classifications=[],
        insufficient_evidence_conditions=["no exact supporting passage"],
    )
    _submit(run_dir, "planning", run_id, [plan])
    promote_stage(workspace, run_id, "planning")

    retrieval = _artifact(
        "RetrievalResult",
        generated_identifier("RET"),
        run_id=run_id,
        queries=[{"query": "samples data movement"}],
        ranked_chunk_ids=[],
        coverage_notes=["All local documents searched"],
    )
    _submit(run_dir, "retrieval", run_id, [retrieval])
    promote_stage(workspace, run_id, "retrieval")

    chunk = next(item for item in iter_json(workspace / "documents" / "chunks"))
    retrieval["ranked_chunk_ids"] = [chunk["chunk_id"]]
    locator = {
        "type": "text_span",
        "page": None,
        "source_line_start": chunk["source_line_start"],
        "source_line_end": chunk["source_line_end"],
        "section_path": chunk["section_path"],
        "chunk_id": chunk["chunk_id"],
        "start_offset": 0,
        "end_offset": len(chunk["exact_text"]),
        "span_sha256": prefixed_sha256(chunk["exact_text"].encode("utf-8")),
    }
    evidence_id = derived_identifier(
        "EVD",
        {
            "document_version_id": chunk["document_version_id"],
            "locator": locator,
            "exact_evidence_content": chunk["exact_text"],
            "extraction_type": "direct_statement",
        },
    )
    evidence = _artifact(
        "Evidence",
        evidence_id,
        evidence_id=evidence_id,
        document_id=chunk["document_id"],
        document_version_id=chunk["document_version_id"],
        evidence_type="direct_statement",
        locator=locator,
        exact_text=chunk["exact_text"],
        context_before="",
        context_after="",
        extraction_method="normalized_markdown",
        extraction_status="extracted",
        human_review_required=False,
    )
    _submit(run_dir, "evidence_extraction", run_id, [evidence])
    promote_stage(workspace, run_id, "evidence_extraction")

    claim_id = f"CLM-{uuid.uuid4()}"
    claim = _claim(claim_id, 1, evidence_id)
    _submit(run_dir, "synthesis", run_id, [claim])
    promote_stage(workspace, run_id, "synthesis")

    review_specs = [
        ("contradiction_review", "contradiction_review", "passed", "none"),
        ("citation_review", "citation_review", "passed", "passed"),
        ("methodology_review", "methodology_review", "adequate", "passed"),
        ("independent_review", "independent_review", "adequate", "passed"),
    ]
    previous = claim
    for version_number, (stage, review_type, methodology, citation) in enumerate(
        review_specs, start=2
    ):
        review = _review(run_id, claim_id, review_type)
        updated = _claim(
            claim_id,
            version_number,
            evidence_id,
            supersedes=previous["artifact_id"],
            citation_status=citation,
            methodology_status=methodology,
            contradiction_status="none",
            independent_review_status=(
                "procedurally_isolated" if stage == "independent_review" else "pending"
            ),
            claim_status=(
                "independently_reviewed" if stage == "independent_review" else "evidence_linked"
            ),
        )
        submitted = [review] if stage == "independent_review" else [review, updated]
        _submit(run_dir, stage, run_id, submitted)
        promoted = promote_stage(workspace, run_id, stage)
        if stage == "independent_review":
            previous = max(
                (
                    item
                    for item in iter_json(run_dir / "claims")
                    if item.get("claim_id") == claim_id
                ),
                key=lambda item: int(item["claim_version"]),
            )
            assert previous["claim_version"] == version_number
            assert previous["claim_status"] == "independently_reviewed"
            assert previous["created_by"]["host"] == "research-cli"
            assert any("claims" in path for path in promoted["promoted_artifacts"])
        else:
            previous = updated

    validation, exit_code = validate_run(workspace, run_id)
    assert exit_code == 0, validation
    assert validation["report_eligible"] is True
    _, manifest = load_run(workspace, run_id)
    assert manifest["phase"] == "report_eligible"

    report = generate_report(workspace, run_id)
    assert Path(report["report_path"]).is_file()
    assert "report-eligible" not in Path(report["report_path"]).read_text(encoding="utf-8")
    _, manifest = load_run(workspace, run_id)
    assert manifest["phase"] == "published"

    current_claim = max(
        (item for item in iter_json(run_dir / "claims") if item.get("schema_name") == "Claim"),
        key=lambda item: int(item["claim_version"]),
    )
    replacement = finalize_artifact(
        _claim(
            claim_id,
            6,
            evidence_id,
            supersedes=current_claim["artifact_id"],
            citation_status="passed",
            methodology_status="adequate",
            contradiction_status="none",
            independent_review_status="procedurally_isolated",
            claim_status="independently_reviewed",
        )
    )
    amendment_id = generated_identifier("AMD")
    amendment = _artifact(
        "Amendment",
        amendment_id,
        amendment_id=amendment_id,
        target_artifact_id=current_claim["artifact_id"],
        target_artifact_hash=current_claim["artifact_hash"],
        amendment_type="claim_rewording",
        changed_fields=["limitations"],
        reason="Clarify that the source is a single study",
        human_identity={"name": "Test reviewer"},
        replacement_artifact_id=replacement["artifact_id"],
        replacement_artifact_hash=replacement["artifact_hash"],
        review_required=True,
    )
    _submit(run_dir, "amendment", run_id, [replacement, amendment])
    amended = promote_stage(workspace, run_id, "amendment")
    assert amended["revalidation_required"] is True

    human_review = _review(run_id, claim_id, "human_review")
    human_review["reviewed_artifact_ids"] = [amendment_id]
    human_review["claim_assessments"] = []
    _submit(run_dir, "human_review", run_id, [human_review])
    promote_stage(workspace, run_id, "human_review")
    revalidation, exit_code = validate_run(workspace, run_id)
    assert exit_code == 0, revalidation
    second_report = generate_report(workspace, run_id)
    assert second_report["report_sha256"]
    status = run_status(workspace, run_id)
    assert status["phase"] == "published"
    assert status["report_eligibility"] is True
    inspected_evidence = inspect_artifact(workspace, evidence_id)
    assert inspected_evidence["integrity"]["valid"] is True
    assert inspected_evidence["context"]["chunk_id"] == chunk["chunk_id"]
    inspected_claim = inspect_artifact(workspace, claim_id)
    assert inspected_claim["context"]["supporting_evidence"]
    inspected_document = inspect_artifact(workspace, chunk["document_id"])
    assert inspected_document["context"]["import_aliases"]


def _artifact(schema_name: str, artifact_id: str, **values: Any) -> dict[str, Any]:
    result = artifact_base(
        schema_name,
        artifact_id,
        {"actor_type": "host_agent", "host": "codex", "model_identifier": "test"},
    )
    result.update(values)
    return result


def _claim(
    claim_id: str,
    version_number: int,
    evidence_id: str,
    *,
    supersedes: str | None = None,
    citation_status: str = "pending",
    methodology_status: str = "pending",
    contradiction_status: str = "pending",
    independent_review_status: str = "pending",
    claim_status: str = "evidence_linked",
) -> dict[str, Any]:
    result = _artifact(
        "Claim",
        f"{claim_id}-v{version_number}",
        claim_id=claim_id,
        claim_version=version_number,
        claim="The study directly reported a 120-sample configuration and lower data movement.",
        claim_type="descriptive_result",
        claim_status=claim_status,
        support_classification="moderately_supported",
        supporting_evidence_ids=[evidence_id],
        contradicting_evidence_ids=[],
        assumptions=[],
        scope={"source": "single study"},
        limitations=["single source"],
        citation_status=citation_status,
        contradiction_status=contradiction_status,
        methodology_status=methodology_status,
        independent_review_status=independent_review_status,
        human_review_required=False,
        factors={
            "evidence_directness": "high",
            "source_quality": "medium",
            "source_independence": "high",
            "methodology_quality": "medium",
            "contradictory_evidence": "low",
            "evidence_coverage": "medium",
            "citation_validity": "high",
            "reviewer_agreement": "high",
            "reviewer_independence": "medium",
            "visual_certainty": "not_applicable",
            "ocr_dependency": "not_applicable",
        },
        supersedes=supersedes,
    )
    return result


def _review(run_id: str, claim_id: str, review_type: str) -> dict[str, Any]:
    review_id = generated_identifier("REV")
    return _artifact(
        "Review",
        review_id,
        run_id=run_id,
        review_id=review_id,
        review_type=review_type,
        reviewed_artifact_ids=[claim_id],
        reviewer_identity={"host": "codex", "agent": review_type},
        reviewer_independence_status=(
            "procedurally_isolated" if review_type == "independent_review" else "not_applicable"
        ),
        review_independence={
            "primary_rationale_excluded": review_type == "independent_review",
            "primary_confidence_excluded": review_type == "independent_review",
            "prior_review_conclusions_excluded": review_type == "independent_review",
            "fresh_agent_context_requested": review_type == "independent_review",
            "host_confirmed_fresh_context": False,
            "status": "procedurally_isolated"
            if review_type == "independent_review"
            else "not_applicable",
        },
        decision="passed",
        claim_assessments=[
            {
                "claim_id": claim_id,
                "assessment": "required review completed",
                "citation_support": "supports"
                if review_type == "citation_review"
                else "not_applicable",
                "contradiction_search_performed": review_type == "contradiction_review",
                "material_contradictions": [],
                "methodology_quality": "medium"
                if review_type == "methodology_review"
                else "not_applicable",
                "support_assessment": "supports"
                if review_type == "independent_review"
                else "not_applicable",
            }
        ],
        findings=[{"summary": "Required review completed"}],
        blocking_issues=[],
        warnings=[],
        required_amendments=[],
    )


def _submit(run_dir: Path, stage: str, run_id: str, artifacts: list[dict[str, Any]]) -> None:
    response = _artifact(
        "StageResponse",
        generated_identifier("STG"),
        run_id=run_id,
        stage=stage,
        outcome="completed",
        artifact_ids=[str(item["artifact_id"]) for item in artifacts],
        notes=[],
    )
    directory = run_dir / "responses" / stage
    for index, artifact in enumerate([*artifacts, response]):
        write_json_atomic(directory / f"candidate-{index}.json", artifact)
