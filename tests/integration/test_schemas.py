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


def artifact(schema_name: str, *, actor_type: str = "host_agent", **body):
    """`actor_type` is a keyword of its own, not a body field.

    It used to be hardcoded, so passing one landed in the artifact body as a stray property while
    `created_by.actor_type` stayed `host_agent` — which made the human-verification rule below
    untestable, and would have made it look enforced when it was not.
    """
    return make_artifact(schema_name=schema_name, artifact_id=body.get("artifact_id", "X"),
                         body=body, actor_type=actor_type)


def claim(**over):
    base = dict(claim_id=CLAIM, claim="A stated fact.", claim_type="direct_fact",
                claim_status="draft", support_classification="moderately_supported",
                supporting_evidence_ids=[EVD], citation_status="not_checked",
                contradiction_status="not_checked", human_review_required=False)
    base.update(over)
    return artifact("Claim", **base)


# --------------------------------------------------------------- registry


def test_every_registered_schema_is_a_valid_json_schema():
    """This asserted `is_valid(...) in (True, False)` — true of every boolean ever returned.

    It would have passed for a schema that accepted anything, or rejected everything, or was a
    syntactically valid JSON document with no constraints in it at all. Checking the schema against
    the Draft 2020-12 meta-schema is the assertion that was meant.
    """
    import jsonschema

    from research.artifacts.registry import _load

    for name in known_schemas():
        schema = _load(name)
        jsonschema.Draft202012Validator.check_schema(schema)
        assert schema["title"] == name, f"{name} does not name itself"
        assert schema.get("required"), f"{name} constrains nothing"
        assert schema.get("properties"), f"{name} declares no properties"
    assert len(SCHEMA_FILES) >= 15


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
    # `validated_inputs` is required: a verdict that names no artifacts is a boolean bound to
    # nothing, and `research report` re-reads the run from disk before publishing.
    base = dict(run_id=RUN, report_eligible=False, human_review_required=False,
                checks=[{"check": "schema", "status": "passed"}],
                validated_inputs={"artifacts": [], "load_error_count": 0,
                                  "inputs_hash": "sha256:" + "0" * 64})
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


def test_an_undeclared_field_is_refused_rather_than_hashed_and_ignored():
    """The schemas are CLOSED, and this is why.

    Nothing set `additionalProperties: false`, so an agent could attach whatever it liked to a
    Claim — statistics, a seed, a rationale — and the field would validate, be folded into the
    RFC 8785 canonical form, get stamped into `artifact_hash`, and be read by no check and no
    template. The worst outcome available: it LOOKS recorded. A reader finding `p_value` on a
    canonical artifact has no way to know that nothing ever verified it, and the artifact's own
    hash certifies it as part of the record.

    Refusing is the honest answer. A field this system cannot check is a field it must not carry.
    """
    c = claim()
    c["p_value"] = 0.03
    c["n"] = 5
    assert not is_valid(c), "a Claim accepted statistics no check or template would ever read"


def _generator():
    """Load `tools/generate_schemas.py` as a module. It is not importable — `tools/` is not a
    package — and a fresh module per test keeps one test's `OUT` monkeypatch out of the other's."""
    import importlib.util

    path = Path(__file__).resolve().parents[2] / "tools" / "generate_schemas.py"
    spec = importlib.util.spec_from_file_location("generate_schemas", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_checked_in_schemas_match_their_generator():
    """`AGENTS.md` lists `python tools/generate_schemas.py --check` as one of four commands that
    must pass. The flag did not exist: unrecognised arguments were ignored, so the documented
    verification step REWROTE the schemas and exited 0 — it could not fail, and it made the two
    sources of truth agree by overwriting one of them.

    Found by mutation: editing the generator changed no test result, because nothing compared its
    output to what is checked in. Running it here means the suite fails on drift even if nobody
    remembers the command.
    """
    # Explicit argv: `main()` falls back to sys.argv, which under pytest is pytest's own.
    assert _generator().main(["--check"]) == 0, (
        "the checked-in schemas differ from the generator")


def test_check_reports_drift_instead_of_silently_repairing_it(tmp_path: Path):
    """The half that matters, and the half a naive test misses.

    Asserting only that `--check` exits 0 on a clean tree passes just as well when the flag is
    ignored — because then it WRITES the schemas and exits 0, having made true the thing it was
    asked to verify. That was the shipped behaviour. So this drives it against a deliberately
    wrong file and asserts two things: it reports the drift, and the wrong file is still wrong
    afterwards. A verification that repairs what it finds cannot report anything.
    """
    module = _generator()
    module.OUT = tmp_path
    (tmp_path / "claim.schema.json").write_text('{"not": "the generated schema"}\n',
                                                encoding="utf-8")

    assert module.main(["--check"]) == 1, "drift was not reported"
    assert (tmp_path / "claim.schema.json").read_text(encoding="utf-8") == (
        '{"not": "the generated schema"}\n'), "--check rewrote the file it was asked to check"


@pytest.mark.parametrize("name", sorted(SCHEMA_FILES))
def test_every_schema_is_closed(name):
    """Set once in `tools/generate_schemas.py`'s `schema()`, so a new artifact type is closed by
    construction rather than by someone remembering. Asserted per schema so the failure names the
    one that drifted."""
    from research.artifacts.registry import _load

    assert _load(name).get("additionalProperties") is False, (
        f"{name} accepts undeclared fields")


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


# ------------------------------------------------ two questions that were left open, now decided


def test_a_human_verification_must_be_recorded_by_a_human():
    """The two gates these clear are named for the human who looked.

    An agent recording `human_ocr_verification` about its own evidence is the self-attestation
    those gates exist to refuse. This was called out as undecided rather than slipped in; the
    enforceable reading is the one the gate name already promises.
    """
    body = dict(amendment_id=AMD, run_id=RUN, target_artifact_id=EVD,
                target_artifact_hash=SHA, amendment_type="human_ocr_verification",
                changed_fields=["extraction_status"], reason="read against the render",
                human={"identifier": "someone"}, requires_revalidation=True,
                replacement_artifact_id=EVD, replacement_artifact_hash=SHA)
    assert is_valid(artifact("Amendment", actor_type="human", **body))
    assert not is_valid(artifact("Amendment", actor_type="host_agent", **body))
    assert not is_valid(artifact("Amendment", actor_type="cli", **body))


def test_an_ordinary_amendment_may_still_come_from_an_agent():
    """Only the two `human_*` types demand a human. A locator correction is ordinary maintenance."""
    assert is_valid(artifact(
        "Amendment", actor_type="host_agent",
        amendment_id=AMD, run_id=RUN, target_artifact_id=EVD, target_artifact_hash=SHA,
        amendment_type="locator_correction", changed_fields=["locator"],
        reason="offsets moved after re-extraction", human={"identifier": "n/a"},
        requires_revalidation=True, replacement_artifact_id=EVD,
        replacement_artifact_hash=SHA))


def test_visual_evidence_must_declare_its_interpretation_certainty():
    """An absent field read as 'clear', so evidence that never answered the question passed the
    visual-certainty gate. The CLI cannot check whether an agent read a figure correctly; it can
    insist the agent say how sure it was."""
    visual = {
        "type": "visual_region", "page": 1, "render_sha256": SHA,
        "coordinate_system": "normalized_top_left_0_to_1",
        "bounding_box": {"x": 0.1, "y": 0.1, "width": 0.5, "height": 0.5},
        "render_width": 800, "render_height": 1000,
    }
    body = dict(evidence_id=EVD, document_id=DOC, document_version_id=DVER,
                evidence_type="figure_observation", locator=visual,
                extraction_status="extracted", human_review_required=False)
    assert not is_valid(artifact("Evidence", **body))
    assert is_valid(artifact("Evidence", interpretation_status="clear", **body))
    assert is_valid(artifact("Evidence", interpretation_status="uncertain", **body))
