"""Phase 6: canonical artifact schemas.

These prove that spec rules are ENFORCED, not merely documented. Each test names the rule it pins.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fixtures.make_fixtures import build  # noqa: E402

from research.artifacts.io import make_artifact, write_artifact  # noqa: E402
from research.artifacts.registry import (  # noqa: E402
    SCHEMA_FILES,
    is_valid,
    known_schemas,
    validate_artifact,
)
from research.config import load_workspace  # noqa: E402
from research.errors import SchemaValidationError, UnsupportedVersionError  # noqa: E402
from research.importers.importer import import_paths  # noqa: E402
from research.indexing.builder import build_index  # noqa: E402
from research.runs.manager import create_run  # noqa: E402
from research.workspace import init_workspace  # noqa: E402

RUN = "RUN-" + "0" * 8 + "-0000-4000-8000-" + "0" * 12
CLAIM = "CLM-" + "0" * 8 + "-0000-7000-8000-" + "0" * 12
REVIEW = "REV-" + "0" * 8 + "-0000-7000-8000-" + "0" * 12
AMD = "AMD-" + "0" * 8 + "-0000-7000-8000-" + "0" * 12
EVD = "EVD-sha256-" + "a" * 64
DOC = "DOC-sha256-" + "a" * 64
DVER = "DVER-sha256-" + "b" * 64
SHA = "sha256:" + "c" * 64


def artifact(schema_name: str, **body):
    return make_artifact(schema_name=schema_name, artifact_id=body.get("artifact_id", "X"),
                         body=body, actor_type="host_agent")


def claim(**over):
    base = dict(claim_id=CLAIM, claim="A stated fact.", claim_type="direct_fact",
                claim_status="draft", support_classification="moderately_supported",
                supporting_evidence_ids=[EVD], citation_status="not_checked",
                contradiction_status="not_checked", human_review_required=False)
    base.update(over)
    return artifact("Claim", **base)


# --------------------------------------------------------------- registry


def test_every_registered_schema_loads_and_is_wellformed():
    for name in known_schemas():
        assert is_valid(artifact(name), schema_name=name) in (True, False)  # loads without raising
    assert len(SCHEMA_FILES) >= 13


def test_unknown_artifact_type_is_rejected():
    with pytest.raises(SchemaValidationError):
        validate_artifact({"schema_name": "Nonsense", "schema_version": "1.0.0"})


def test_unsupported_schema_version_fails_clearly():
    """Spec §30: unsupported schema versions must fail clearly, not be coerced."""
    bad = claim()
    bad["schema_version"] = "2.0.0"
    with pytest.raises(UnsupportedVersionError):
        validate_artifact(bad)


def test_validation_errors_name_the_spec_rule():
    """A jsonschema message alone does not tell an agent WHY the rule exists."""
    with pytest.raises(SchemaValidationError) as exc:
        validate_artifact(claim(support_classification="verified", claim_type="causal_claim",
                                citation_status="passed",
                                contradiction_status="none_found"))
    rules = " ".join(str(p.get("rule")) for p in exc.value.detail["problems"])
    assert "23.1" in rules or "directly checkable" in rules


# --------------------------------------------------------------- claim rules


def test_verified_is_refused_for_a_causal_claim():
    """Spec §23.1: broader theoretical or causal conclusions can never be `verified`."""
    for kind in ("causal_claim", "interpretation", "hypothesis", "recommendation",
                 "correlational_claim"):
        assert not is_valid(claim(claim_type=kind, support_classification="verified",
                                  citation_status="passed",
                                  contradiction_status="none_found")), kind


def test_verified_is_allowed_for_a_directly_checkable_fact():
    assert is_valid(claim(claim_type="direct_fact", support_classification="verified",
                          citation_status="passed", contradiction_status="none_found"))


def test_verified_requires_a_passed_citation_and_no_open_contradiction():
    assert not is_valid(claim(support_classification="verified", citation_status="not_checked",
                              contradiction_status="none_found"))
    assert not is_valid(claim(support_classification="verified", citation_status="passed",
                              contradiction_status="unresolved"))


def test_strongly_supported_requires_multiple_evidence_records():
    """Spec §23.2: 'multiple relevant evidence records', not one read twice."""
    assert not is_valid(claim(support_classification="strongly_supported",
                              supporting_evidence_ids=[EVD], citation_status="passed"))
    two = [EVD, "EVD-sha256-" + "d" * 64]
    assert is_valid(claim(support_classification="strongly_supported",
                          supporting_evidence_ids=two, citation_status="passed"))


def test_a_claim_without_evidence_is_rejected():
    """Spec §38.5: every report claim references evidence."""
    assert not is_valid(claim(supporting_evidence_ids=[]))


def test_an_insufficient_evidence_finding_needs_no_evidence_but_cannot_claim_support():
    assert is_valid(claim(claim_type="insufficient_evidence_finding",
                          supporting_evidence_ids=[],
                          support_classification="unable_to_determine"))
    assert not is_valid(claim(claim_type="insufficient_evidence_finding",
                              supporting_evidence_ids=[],
                              support_classification="strongly_supported"))


@pytest.mark.parametrize("field", ["confidence_score", "confidence", "certainty_score"])
def test_numeric_confidence_is_forbidden_outright(field):
    """Spec §23: no aggregate numeric confidence score in v1."""
    assert not is_valid(claim(**{field: 0.87}))


def test_categorical_confidence_factors_are_accepted():
    assert is_valid(claim(confidence_factors={"evidence_directness": "high",
                                              "source_independence": "unknown"}))
    assert not is_valid(claim(confidence_factors={"evidence_directness": 0.9}))
    assert not is_valid(claim(confidence_factors={"made_up_factor": "high"}))


# --------------------------------------------------------------- evidence rules


def text_locator(**over):
    base = {"type": "text_span", "start_offset": 0, "end_offset": 10, "span_sha256": SHA}
    base.update(over)
    return base


def evidence(**over):
    base = dict(evidence_id=EVD, document_id=DOC, document_version_id=DVER,
                evidence_type="direct_statement", locator=text_locator(),
                exact_text="the exact passage", extraction_status="extracted",
                human_review_required=False)
    base.update(over)
    return artifact("Evidence", **base)


def test_text_evidence_must_carry_the_exact_passage():
    assert is_valid(evidence())
    assert not is_valid(evidence(exact_text=""))


def test_ocr_required_evidence_must_demand_human_review():
    """Spec §26: no OCR ships in v1, so that page's text is not readable."""
    assert not is_valid(evidence(extraction_status="ocr_required", human_review_required=False))
    assert is_valid(evidence(extraction_status="ocr_required", human_review_required=True))


def test_visual_evidence_must_declare_how_certain_the_reading_is():
    """Spec §12.3: visual content must never be silently inferred."""
    visual = {"type": "visual_region", "page": 3, "render_sha256": SHA,
              "coordinate_system": "normalized_top_left_0_to_1",
              "bounding_box": {"x": 0.1, "y": 0.1, "width": 0.5, "height": 0.5},
              "render_width": 1600, "render_height": 2200}
    assert not is_valid(evidence(locator=visual, exact_text=""))
    assert is_valid(evidence(locator=visual, exact_text="",
                             interpretation_status="human_review_required"))


def test_a_bounding_box_outside_the_page_is_rejected():
    visual = {"type": "visual_region", "page": 1, "render_sha256": SHA,
              "coordinate_system": "normalized_top_left_0_to_1",
              "bounding_box": {"x": 0.1, "y": 0.1, "width": 1.4, "height": 0.5},
              "render_width": 100, "render_height": 100}
    assert not is_valid(evidence(locator=visual, interpretation_status="clear"))


def test_a_text_locator_without_a_span_hash_is_rejected():
    """Without the span hash, a moved quote is indistinguishable from a correct one."""
    loc = text_locator()
    del loc["span_sha256"]
    assert not is_valid(evidence(locator=loc))


# --------------------------------------------------------------- review rules


def review(**over):
    base = dict(review_id=REVIEW, review_type="citation_review", run_id=RUN,
                reviewed_artifact_ids=[CLAIM], reviewer={"actor_type": "host_agent"},
                decision="passed")
    base.update(over)
    return artifact("Review", **base)


def test_an_independent_review_must_declare_its_independence():
    """Spec §13: otherwise 'independent' is asserted rather than auditable."""
    assert not is_valid(review(review_type="independent_review"))
    assert is_valid(review(review_type="independent_review",
                           review_independence={"status": "procedurally_isolated",
                                                "primary_rationale_excluded": True}))


def test_independence_status_must_be_one_of_the_four_defined_values():
    assert not is_valid(review(review_type="independent_review",
                               review_independence={"status": "pretty_independent"}))


def test_a_failed_review_must_say_what_blocked_it():
    assert not is_valid(review(decision="failed"))
    assert is_valid(review(decision="failed", blocking_issues=["locator does not resolve"]))


# --------------------------------------------------------------- validation result


def validation(**over):
    base = dict(run_id=RUN, report_eligible=False, human_review_required=False,
                checks=[{"check": "schema", "status": "passed"}])
    base.update(over)
    return artifact("ValidationResult", **base)


def test_report_eligibility_cannot_coexist_with_blocking_errors():
    assert not is_valid(validation(report_eligible=True,
                                   blocking_errors=[{"category": "dangling_reference"}]))
    assert is_valid(validation(report_eligible=True, blocking_errors=[]))


def test_report_eligibility_cannot_coexist_with_outstanding_human_review():
    assert not is_valid(validation(report_eligible=True, human_review_required=True))


def test_checks_record_not_evaluated_as_a_distinct_status():
    """docs/lessons-carried-forward.md §6b: 'could not look' must not read as 'fine'."""
    assert is_valid(validation(checks=[{"check": "locators", "status": "not_evaluated",
                                        "detail": "no evidence records yet"}]))
    assert not is_valid(validation(checks=[{"check": "locators", "status": "probably_ok"}]))


def test_a_validation_result_must_record_at_least_one_check():
    assert not is_valid(validation(checks=[]))


# --------------------------------------------------------------- amendment


def amendment(**over):
    base = dict(amendment_id=AMD, target_artifact_id=CLAIM, target_artifact_hash=SHA,
                amendment_type="claim_rewording", changed_fields=["claim"],
                reason="clarified scope", human={"identifier": "jeehoon"},
                requires_revalidation=True, replacement_artifact_id=CLAIM,
                replacement_artifact_hash=SHA)
    base.update(over)
    return artifact("Amendment", **base)


def test_an_amendment_must_name_what_it_replaces():
    """Spec §31: history stays intact because the replacement is recorded, not swapped in."""
    a = amendment()
    del a["replacement_artifact_id"]
    assert not is_valid(a)
    assert is_valid(amendment())


def test_a_withdrawal_needs_no_replacement():
    a = amendment(amendment_type="withdrawal")
    del a["replacement_artifact_id"]
    del a["replacement_artifact_hash"]
    assert is_valid(a)


def test_an_amendment_must_identify_the_human_and_the_reason():
    assert not is_valid(amendment(human={}))
    assert not is_valid(amendment(reason=""))


# --------------------------------------------------------------- source independence


def test_a_heuristic_relationship_cannot_be_high_confidence():
    """Spec §24: only hashes and explicit identifiers are definitive."""
    def rel(**over):
        base = dict(source_document_id=DOC, related_document_id="DOC-sha256-" + "e" * 64,
                    relationship_type="republication", confidence="high",
                    detected_by="hash_identity")
        base.update(over)
        return artifact("SourceRelationship", **base)

    assert is_valid(rel())
    assert not is_valid(rel(detected_by="heuristic", confidence="high"))
    assert is_valid(rel(detected_by="heuristic", confidence="medium",
                        human_review_status="required"))


# --------------------------------------------------------------- write-time enforcement


def test_write_artifact_refuses_to_persist_an_invalid_artifact(tmp_path: Path):
    """Validation at WRITE time: an artifact on disk has already been counted."""
    bad = claim(supporting_evidence_ids=[])
    with pytest.raises(SchemaValidationError):
        write_artifact(tmp_path / "bad.json", bad)
    assert not (tmp_path / "bad.json").exists(), "an invalid artifact must not reach disk"


def test_hidden_reasoning_traces_are_refused():
    """Spec §14/§29: never record hidden chain-of-thought."""
    c = claim()
    c["created_by"]["reasoning_trace"] = "step 1... step 2..."
    assert not is_valid(c)


# --------------------------------------------------------------- everything the CLI emits


def test_every_artifact_the_pipeline_produces_validates(tmp_path: Path):
    """The end-to-end proof that the schemas describe what the code actually writes."""
    sources = build(tmp_path / "sources")
    init_workspace(tmp_path / "ws")
    ws = load_workspace(tmp_path / "ws")
    import_paths(ws, [sources["text_pdf"], sources["markdown"], sources["low_text_pdf"]])
    build_index(ws)
    create_run(ws, question="Does process-in-memory reduce data movement?")

    import json as _json
    checked = 0
    for path in sorted(ws.root.rglob("*.json")):
        with open(path, encoding="utf-8") as fh:
            data = _json.load(fh)
        if isinstance(data, dict) and data.get("schema_name") in SCHEMA_FILES:
            validate_artifact(data, path=path)
            checked += 1
    assert checked >= 15, f"expected many artifacts, validated only {checked}"
