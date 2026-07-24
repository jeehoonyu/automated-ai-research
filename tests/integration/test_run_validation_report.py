from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from reportlab.pdfgen import canvas

from research.artifacts import artifact_base, store_artifact
from research.canonical import finalize_artifact, prefixed_sha256
from research.errors import ResearchError
from research.identifiers import derived_identifier, generated_identifier
from research.indexing import build_index, search_index
from research.ingestion import import_sources
from research.inspection import inspect_artifact
from research.io import iter_json, write_json_atomic
from research.reporting import generate_report
from research.runs import create_run, load_run, promote_stage, run_status
from research.validation import validate_run


def test_complete_agent_artifact_flow(workspace: Path, tmp_path: Path) -> None:
    source = tmp_path / "study.md"
    source.write_text(
        "# Results\n\nThe token 120 sample configuration reported lower data movement.\n",
        encoding="utf-8",
    )
    imported = import_sources(workspace, [source])
    assert imported["failed_count"] == 0
    build_index(workspace)
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

    search = search_index(workspace, "token=120", run_id=run_id)
    ranked_chunk_ids = [item["chunk_id"] for item in search["results"]]
    chunk = next(
        item
        for item in iter_json(workspace / "documents" / "chunks")
        if item.get("chunk_id") == ranked_chunk_ids[0]
    )
    retrieval = _artifact(
        "RetrievalResult",
        generated_identifier("RET"),
        run_id=run_id,
        queries=[
            {
                "query": "token=120",
                "top_chunk_ids": ranked_chunk_ids,
                "search_event_id": search["search_event_id"],
                "search_event_hash": search["search_event_hash"],
            }
        ],
        ranked_chunk_ids=ranked_chunk_ids,
        coverage_notes=["All local documents searched"],
    )
    _submit(run_dir, "retrieval", run_id, [retrieval])
    promote_stage(workspace, run_id, "retrieval")

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

    claim_id = generated_identifier("CLM")
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
        contradiction_search_event_ids: list[str] = []
        if stage == "contradiction_review":
            contradiction_search = search_index(workspace, "not reliable", run_id=run_id)
            contradiction_search_event_ids.append(contradiction_search["search_event_id"])
        review = _review(
            run_id,
            claim_id,
            review_type,
            evidence_id,
            contradiction_search_event_ids,
        )
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

    document = next(iter_json(workspace / "documents" / "manifests"))
    original_path = workspace / document["original_storage_path"]
    original_bytes = original_path.read_bytes()
    original_path.write_bytes(original_bytes + b"\npost-validation tamper")
    with pytest.raises(ResearchError, match="integrity changed"):
        generate_report(workspace, run_id)
    original_path.write_bytes(original_bytes)

    search_log = workspace / "logs" / "search-events.jsonl"
    search_log_text = search_log.read_text(encoding="utf-8")
    search_events = [json.loads(line) for line in search_log_text.splitlines()]
    run_event = next(item for item in search_events if item.get("run_id") == run_id)
    run_event["event_hash"] = "sha256:" + ("0" * 64)
    search_log.write_text(
        "\n".join(json.dumps(item, sort_keys=True) for item in search_events) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ResearchError, match="integrity changed"):
        generate_report(workspace, run_id)
    search_log.write_text(search_log_text, encoding="utf-8")

    report = generate_report(workspace, run_id)
    assert Path(report["report_path"]).is_file()
    report_text = Path(report["report_path"]).read_text(encoding="utf-8")
    report_manifest = next(iter_json(workspace / "runs" / run_id / "report" / "manifests"))
    assert "\\" not in report_manifest["report_path"]
    assert report_manifest["report_path"].startswith("report/")
    assert "report-eligible" not in report_text
    assert "## Supporting evidence" in report_text
    assert "## Contradictory evidence" in report_text
    assert "## Methodological limitations" in report_text
    assert "## References" in report_text
    assert "Uncertainty factors:" in report_text
    assert "evidence directness: `high`" in report_text
    assert "<script>" not in report_text
    assert "&lt;script&gt;" in report_text
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
    amendment["created_by"] = {
        "actor_type": "human",
        "host": "manual-review",
        "model_identifier": None,
    }
    _submit(run_dir, "amendment", run_id, [replacement, amendment])
    amended = promote_stage(workspace, run_id, "amendment")
    assert amended["revalidation_required"] is True

    human_review = _review(run_id, claim_id, "human_review")
    human_review["created_by"] = {
        "actor_type": "human",
        "host": "manual-review",
        "model_identifier": None,
    }
    human_review["reviewer_identity"] = {"name": "Test reviewer"}
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

    rogue_review = _review(run_id, claim_id, "citation_review", evidence_id)
    store_artifact(run_dir, rogue_review)
    lifecycle_validation, lifecycle_exit = validate_run(workspace, run_id)
    assert lifecycle_exit == 5
    assert any(
        item["code"] == "unrecorded_canonical_artifact"
        for item in lifecycle_validation["blocking_errors"]
    )


def test_human_visual_amendment_preserves_same_evidence_identity(
    workspace: Path, tmp_path: Path
) -> None:
    pdf_path = tmp_path / "image-only.pdf"
    pdf = canvas.Canvas(str(pdf_path))
    pdf.showPage()
    pdf.save()
    imported = import_sources(workspace, [pdf_path])
    assert imported["partial_count"] == 1
    build_index(workspace)
    run = create_run(workspace, "What appears on the scanned page?", "default", host="codex")
    run_id = run["run_id"]
    run_dir = Path(run["run_path"])

    plan = _artifact(
        "ResearchPlan",
        generated_identifier("PLAN"),
        run_id=run_id,
        main_question="What appears on the scanned page?",
        subquestions=["Can the visual be verified by a human?"],
        definitions=[],
        scope={"documents": "local corpus"},
        inclusion_criteria=["human-verified visual regions"],
        exclusion_criteria=["unverified OCR inference"],
        search_terms=["scanned page"],
        evidence_requirements=["page render hash and visual bounds"],
        validation_criteria=["human verification amendment"],
        expected_limitations=["image-only source"],
        high_risk_classifications=[],
        insufficient_evidence_conditions=["no human visual review"],
    )
    _submit(run_dir, "planning", run_id, [plan])
    promote_stage(workspace, run_id, "planning")

    search = search_index(workspace, "scanned", run_id=run_id)
    retrieval = _artifact(
        "RetrievalResult",
        generated_identifier("RET"),
        run_id=run_id,
        queries=[
            {
                "query": "scanned",
                "top_chunk_ids": [],
                "search_event_id": search["search_event_id"],
                "search_event_hash": search["search_event_hash"],
            }
        ],
        ranked_chunk_ids=[],
        coverage_notes=["Image-only page has no indexable extracted text"],
    )
    _submit(run_dir, "retrieval", run_id, [retrieval])
    promote_stage(workspace, run_id, "retrieval")

    version = next(iter_json(workspace / "documents" / "versions"))
    render = version["pages"][0]["render"]
    locator = {
        "type": "visual_region",
        "page": 1,
        "render_sha256": render["sha256"],
        "coordinate_system": "normalized_top_left_0_to_1",
        "bounding_box": {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0},
        "render_width": render["width"],
        "render_height": render["height"],
    }
    evidence_id = derived_identifier(
        "EVD",
        {
            "document_version_id": version["document_version_id"],
            "locator": locator,
            "exact_evidence_content": None,
            "extraction_type": "figure_observation",
        },
    )
    evidence = _artifact(
        "Evidence",
        evidence_id,
        evidence_id=evidence_id,
        document_id=version["document_id"],
        document_version_id=version["document_version_id"],
        evidence_type="figure_observation",
        locator=locator,
        exact_text=None,
        context_before=None,
        context_after=None,
        extraction_method="page_render_inspection",
        extraction_status="human_review_required",
        human_review_required=True,
        region_type="full_page",
        caption=None,
        interpretation_status="human_review_required",
    )
    _submit(run_dir, "evidence_extraction", run_id, [evidence])
    promote_stage(workspace, run_id, "evidence_extraction")
    target = next(iter_json(run_dir / "evidence"))

    replacement = dict(target)
    replacement.pop("artifact_hash")
    replacement["created_at"] = "9999-12-31T23:59:59.999999Z"
    replacement["created_by"] = {
        "actor_type": "human",
        "host": "manual-review",
        "model_identifier": None,
    }
    replacement["human_review_required"] = False
    replacement["interpretation_status"] = "human_verified"
    replacement = finalize_artifact(replacement)
    assert replacement["artifact_id"] == target["artifact_id"]
    assert replacement["artifact_hash"] != target["artifact_hash"]

    amendment_id = generated_identifier("AMD")
    amendment = _artifact(
        "Amendment",
        amendment_id,
        amendment_id=amendment_id,
        target_artifact_id=target["artifact_id"],
        target_artifact_hash=target["artifact_hash"],
        amendment_type="human_visual_verification",
        changed_fields=["human_review_required", "interpretation_status"],
        reason="A human inspected the complete immutable page render",
        human_identity={"name": "Test visual reviewer"},
        replacement_artifact_id=replacement["artifact_id"],
        replacement_artifact_hash=replacement["artifact_hash"],
        review_required=True,
    )
    amendment["created_by"] = {
        "actor_type": "human",
        "host": "manual-review",
        "model_identifier": None,
    }
    _submit(run_dir, "amendment", run_id, [replacement, amendment])
    promote_stage(workspace, run_id, "amendment")

    human_review = _review(run_id, "unused", "human_review")
    human_review["created_by"] = {
        "actor_type": "human",
        "host": "manual-review",
        "model_identifier": None,
    }
    human_review["reviewer_identity"] = {"name": "Second test reviewer"}
    human_review["reviewed_artifact_ids"] = [amendment_id]
    human_review["claim_assessments"] = []
    _submit(run_dir, "human_review", run_id, [human_review])
    promote_stage(workspace, run_id, "human_review")

    validation, exit_code = validate_run(workspace, run_id)
    assert exit_code == 5
    unresolved_codes = {item["code"] for item in validation["human_review_requirements"]}
    assert unresolved_codes.isdisjoint(
        {
            "visual_or_ocr_review",
            "visual_interpretation_review",
            "human_visual_verification_provenance",
            "ocr_page_evidence",
        }
    )
    inspected = inspect_artifact(workspace, evidence_id)
    assert inspected["artifact"]["interpretation_status"] == "human_verified"
    assert len(list(iter_json(run_dir / "evidence"))) == 2


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
        assumptions=["<script>alert('untrusted')</script>"],
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


def _review(
    run_id: str,
    claim_id: str,
    review_type: str,
    evidence_id: str | None = None,
    contradiction_search_event_ids: list[str] | None = None,
) -> dict[str, Any]:
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
                "evidence_assessments": (
                    [
                        {
                            "evidence_id": evidence_id,
                            "citation_support": "supports",
                            "context_preserved": True,
                        }
                    ]
                    if review_type == "citation_review" and evidence_id
                    else []
                ),
                "contradiction_search_performed": review_type == "contradiction_review",
                "contradiction_search_event_ids": contradiction_search_event_ids or [],
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
