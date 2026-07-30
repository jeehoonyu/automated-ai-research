"""Phase 8: report rendering and gating."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research.artifacts.io import (  # noqa: E402
    make_artifact,
    read_artifact,  # noqa: E402
    write_artifact,
)
from research.artifacts.registry import validate_artifact  # noqa: E402
from research.errors import ReportGatingError  # noqa: E402
from research.hashing import stamp_artifact_hash  # noqa: E402
from research.identifiers import claim_id  # noqa: E402
from research.reporting.language import check_claim_language  # noqa: E402
from research.reporting.renderer import render_report  # noqa: E402
from research.validation.validator import validate_run  # noqa: E402


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


# --------------------------------------------------------------- gating


def test_an_unvalidated_run_cannot_be_published(complete_run):
    ws, rid, _ = complete_run
    with pytest.raises(ReportGatingError) as exc:
        render_report(ws, rid)
    assert "has not been validated" in exc.value.message


def test_a_blocked_run_cannot_be_published(complete_run):
    """Spec §8.9: refuse publication when gating fails, and say which gates."""
    ws, rid, meta = complete_run
    (meta["run_dir"] / "reviews" / "independent_review.json").unlink()
    validate_run(ws, rid)

    with pytest.raises(ReportGatingError) as exc:
        render_report(ws, rid)
    checks = {b["check"] for b in exc.value.detail["blocking"]}
    assert "independent_review_complete" in checks
    assert "--draft" in exc.value.detail["hint"]


def test_a_validated_eligible_run_publishes(complete_run):
    ws, rid, _ = complete_run
    assert validate_run(ws, rid)["report_eligible"] is True
    result = render_report(ws, rid)
    assert result.draft is False
    assert Path(result.report_path).name == "report.md"
    assert result.report_sha256.startswith("sha256:")


def test_a_blocked_run_can_still_produce_a_visibly_marked_draft(complete_run):
    ws, rid, meta = complete_run
    (meta["run_dir"] / "reviews" / "citation_review.json").unlink()
    validate_run(ws, rid)

    result = render_report(ws, rid, draft=True)
    body = _read(result.report_path)
    assert result.draft is True
    assert Path(result.report_path).name == "report-draft.md"
    assert body.startswith("> # ⚠ DRAFT — NOT VALIDATED")
    assert "before validation passed" in body
    assert "must not be circulated" in body
    assert "citation_review_complete" in body, "a draft must name what is blocking it"


def test_a_draft_never_claims_to_be_published(complete_run):
    ws, rid, _ = complete_run
    validate_run(ws, rid)
    result = render_report(ws, rid, draft=True)
    manifest = read_artifact(result.manifest_path, expect_schema="ReportManifest")
    assert manifest["draft"] is True
    assert "DRAFT" in " ".join(manifest["disclosures"])
    assert "Status: **DRAFT (unvalidated)**" in _read(result.report_path)


# --------------------------------------------------------------- §32 language rule


@pytest.mark.parametrize("text,classification,expected", [
    ("The method proves that data movement falls.", "weakly_supported", True),
    ("The method definitively establishes the result.", "moderately_supported", True),
    ("The paper reports a reduction in data movement.", "moderately_supported", False),
    ("This conclusively confirms the mechanism.", "verified", False),   # verified may be absolute
    ("The results show a significant improvement.", "unsupported", True),
    ("Evidence is insufficient to answer this.", "unable_to_determine", False),
])
def test_wording_is_checked_against_the_validated_classification(text, classification, expected):
    """Spec §32, and the exact failure recorded in lessons §5: prose outrunning the data."""
    findings = check_claim_language({"claim_id": "CLM-x", "claim": text,
                                     "support_classification": classification,
                                     "claim_type": "direct_fact"})
    assert bool(findings) is expected, findings


def test_causal_wording_on_a_correlational_claim_is_flagged():
    findings = check_claim_language({
        "claim_id": "CLM-x", "claim": "The optimisation causes the reduction in latency.",
        "support_classification": "moderately_supported", "claim_type": "correlational_claim"})
    assert any(f.kind == "causal_language_on_a_non_causal_claim" for f in findings)


def test_an_overstated_claim_is_disclosed_in_the_report_not_silently_rendered(complete_run):
    ws, rid, meta = complete_run
    path = meta["run_dir"] / "claims" / "c1.json"
    claim = json.loads(path.read_text(encoding="utf-8"))
    claim["claim"] = "This definitively proves that data movement always falls."
    path.write_text(json.dumps(stamp_artifact_hash(claim)), encoding="utf-8")
    validate_run(ws, rid)

    result = render_report(ws, rid, draft=True)
    assert result.overstatements, "the wording must be flagged"
    body = _read(result.report_path)
    assert "Wording flagged" in body
    assert "definitively" in body   # the claim is still rendered VERBATIM, never rewritten
    manifest = read_artifact(result.manifest_path, expect_schema="ReportManifest")
    assert any("wording" in d for d in manifest["disclosures"])


def test_the_renderer_never_rewrites_a_claim(complete_run):
    """The generator has no vocabulary of its own for how well-supported something is."""
    ws, rid, meta = complete_run
    path = meta["run_dir"] / "claims" / "c1.json"
    claim = json.loads(path.read_text(encoding="utf-8"))
    original = claim["claim"]
    validate_run(ws, rid)
    body = _read(render_report(ws, rid).report_path)
    assert original in body


def test_the_qualifier_comes_from_a_fixed_table(complete_run):
    ws, rid, meta = complete_run
    path = meta["run_dir"] / "claims" / "c1.json"
    claim = json.loads(path.read_text(encoding="utf-8"))
    claim["support_classification"] = "weakly_supported"
    path.write_text(json.dumps(stamp_artifact_hash(claim)), encoding="utf-8")
    validate_run(ws, rid)

    body = _read(render_report(ws, rid, draft=True).report_path)
    assert "Weakly supported — evidence is limited or indirect." in body


# --------------------------------------------------------------- content requirements


def test_the_report_contains_every_required_section(complete_run):
    ws, rid, _ = complete_run
    validate_run(ws, rid)
    body = _read(render_report(ws, rid).report_path)
    for heading in ("Research question", "## Scope", "## Method", "## Sources", "## Findings",
                    "## Contradictions", "## Limitations", "## Review and human-review status",
                    "## Validation summary", "## References", "## Provenance"):
        assert heading in body, f"report is missing {heading}"


def test_claims_are_rendered_with_citations_that_resolve(complete_run):
    ws, rid, meta = complete_run
    validate_run(ws, rid)
    result = render_report(ws, rid)
    body = _read(result.report_path)
    assert result.citation_count >= 1
    assert "**[1]**" in body
    assert meta["evidence_id"] in body, "the citation index must name the evidence id"


def test_the_report_quotes_what_the_locator_resolves_to(complete_run):
    """Not the artifact's stored copy — reading through the locator is the guarantee."""
    ws, rid, meta = complete_run
    validate_run(ws, rid)
    body = _read(render_report(ws, rid).report_path)
    doc = meta["doc"]
    text = (ws.root / doc["normalized_text_path"]).read_text(encoding="utf-8")
    ev = json.loads((meta["run_dir"] / "evidence" / "e1.json").read_text(encoding="utf-8"))
    expected = " ".join(text[ev["locator"]["start_offset"]:ev["locator"]["end_offset"]].split())
    assert expected[:60] in body


def test_independence_status_is_disclosed(complete_run):
    """procedurally_isolated is acceptable by default but must be stated (spec §13)."""
    ws, rid, _ = complete_run
    validate_run(ws, rid)
    body = _read(render_report(ws, rid).report_path)
    assert "procedurally_isolated" in body
    assert "did not confirm a technically fresh context" in body


def test_the_report_states_that_not_evaluated_blocks(complete_run):
    ws, rid, _ = complete_run
    validate_run(ws, rid)
    body = _read(render_report(ws, rid).report_path)
    assert "not_evaluated" in body and "is not \"fine\"" in body


def test_unreadable_pages_are_disclosed(complete_run):
    ws, rid, meta = complete_run
    validate_run(ws, rid)
    render_report(ws, rid)
    # the fixture corpus has no OCR pages; assert the disclosure machinery keyed on it exists
    manifest = read_artifact(meta["run_dir"] / "report" / "report-manifest.json",
                             expect_schema="ReportManifest")
    assert isinstance(manifest["disclosures"], list)


# --------------------------------------------------------------- manifest and determinism


def test_the_report_manifest_is_a_valid_artifact_and_hashes_the_report(complete_run):
    ws, rid, _ = complete_run
    validate_run(ws, rid)
    result = render_report(ws, rid)
    manifest = read_artifact(result.manifest_path, expect_schema="ReportManifest")
    validate_artifact(manifest)

    from research.hashing import sha256_text
    assert manifest["report_sha256"] == sha256_text(_read(result.report_path))
    assert manifest["validation_result_hash"], "a published report must name its validation result"


def test_rendering_twice_produces_an_identical_report(complete_run):
    """Deterministic rendering (spec §8.9): same artifacts in, same bytes out."""
    ws, rid, _ = complete_run
    validate_run(ws, rid)
    first = render_report(ws, rid).report_sha256
    second = render_report(ws, rid).report_sha256
    assert first == second


def test_the_citation_index_lists_every_cited_evidence_id(complete_run):
    ws, rid, meta = complete_run
    validate_run(ws, rid)
    manifest = read_artifact(render_report(ws, rid).manifest_path,
                             expect_schema="ReportManifest")
    refs = {entry["evidence_id"] for entry in manifest["citation_index"]}
    assert meta["evidence_id"] in refs
    assert manifest["claim_ids"] == [meta["claim_id"]]


# --------------------------------------------------------------- the verdict binds to artifacts
#
# `report_eligible` was a boolean read out of a file while everything downstream re-read `claims/`
# and `evidence/` from disk. Nothing connected the two.


def _publishable(ws, rid):
    result = validate_run(ws, rid)
    assert result["report_eligible"] is True, result["blocking_errors"]
    return result


def test_a_claim_written_after_validate_is_not_published(complete_run):
    """The defect, end to end: no tampering, no hash edit — just a new file."""
    ws, rid, meta = complete_run
    _publishable(ws, rid)

    cid = claim_id()
    smuggled = make_artifact(
        schema_name="Claim", artifact_id=cid, actor_type="host_agent",
        body=dict(claim_id=cid, claim="Process-in-memory eliminates all data movement.",
                  claim_type="direct_fact", claim_status="independently_reviewed",
                  support_classification="verified",
                  supporting_evidence_ids=[meta["evidence_id"]],
                  contradicting_evidence_ids=[], citation_status="passed",
                  contradiction_status="none_found",
                  independent_review_status="confirmed_independent",
                  human_review_required=False, run_id=rid))
    write_artifact(meta["run_dir"] / "claims" / "c2-smuggled.json", smuggled, root=ws.root)

    with pytest.raises(ReportGatingError) as exc:
        render_report(ws, rid)
    assert any("added since validation" in d for d in exc.value.detail["differences"])
    assert cid in " ".join(exc.value.detail["differences"])


def test_a_claim_deleted_after_validate_is_not_published(complete_run):
    """The mirror image: a report that quietly drops what the verdict rested on."""
    ws, rid, meta = complete_run
    _publishable(ws, rid)
    (meta["run_dir"] / "claims" / "c1.json").unlink()

    with pytest.raises(ReportGatingError) as exc:
        render_report(ws, rid)
    assert any("removed since validation" in d for d in exc.value.detail["differences"])


def test_a_claim_re_stamped_after_validate_is_not_published(complete_run):
    """Hash verification alone does not cover this: the edit is correctly re-stamped, so it is a
    valid artifact — just not the one that was judged."""
    ws, rid, meta = complete_run
    _publishable(ws, rid)

    path = meta["run_dir"] / "claims" / "c1.json"
    claim = json.loads(path.read_text(encoding="utf-8"))
    claim["claim"] = "Data movement is always eliminated entirely."
    path.write_text(json.dumps(stamp_artifact_hash(claim)), encoding="utf-8")

    with pytest.raises(ReportGatingError) as exc:
        render_report(ws, rid)
    assert any("re-stamped since validation" in d for d in exc.value.detail["differences"])


def test_re_validating_after_the_change_restores_publication(complete_run):
    """The gate must be a binding, not a lock: validate again and the new state can publish."""
    ws, rid, meta = complete_run
    _publishable(ws, rid)
    path = meta["run_dir"] / "claims" / "c1.json"
    claim = json.loads(path.read_text(encoding="utf-8"))
    claim["claim"] = "The paper reports a reduction in data movement."
    path.write_text(json.dumps(stamp_artifact_hash(claim)), encoding="utf-8")

    with pytest.raises(ReportGatingError):
        render_report(ws, rid)

    _publishable(ws, rid)                       # re-validate the run as it now stands
    assert render_report(ws, rid).draft is False


def test_a_draft_still_renders_the_run_as_it_stands(complete_run):
    """A draft is explicitly a picture of now, and says so, so it is exempt."""
    ws, rid, meta = complete_run
    _publishable(ws, rid)
    (meta["run_dir"] / "claims" / "c1.json").unlink()

    result = render_report(ws, rid, draft=True)
    assert result.draft is True


def test_a_validation_result_naming_no_artifacts_cannot_publish(complete_run):
    """An older result predating input binding says nothing about what it judged."""
    ws, rid, meta = complete_run
    _publishable(ws, rid)

    path = meta["run_dir"] / "validation" / "validation-result.json"
    stored = json.loads(path.read_text(encoding="utf-8"))
    del stored["validated_inputs"]
    path.write_text(json.dumps(stamp_artifact_hash(stored)), encoding="utf-8")

    with pytest.raises(ReportGatingError) as exc:
        render_report(ws, rid)
    assert any("no artifact roster" in d for d in exc.value.detail["differences"])
