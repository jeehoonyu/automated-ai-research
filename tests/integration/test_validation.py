"""Phase 7: validation and report gating.

The suite builds one COMPLETE, valid run and then seeds each defect the spec says must block
publication (§8.8), asserting that the specific gate fires. A test that only checks "eligible is
False" would pass even if the wrong gate caught it — or if everything failed for an unrelated
reason.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fixtures.make_fixtures import build  # noqa: E402

from research.artifacts.io import make_artifact, write_artifact  # noqa: E402
from research.artifacts.registry import validate_artifact  # noqa: E402
from research.config import load_workspace  # noqa: E402
from research.identifiers import amendment_id  # noqa: E402
from research.importers.importer import import_paths  # noqa: E402
from research.indexing.builder import build_index  # noqa: E402
from research.runs.manager import create_run  # noqa: E402
from research.validation.validator import validate_run  # noqa: E402
from research.workspace import init_workspace  # noqa: E402


def _status(result, check: str) -> str:
    return next(c["status"] for c in result["checks"] if c["check"] == check)




# --------------------------------------------------------------- the happy path


def test_a_complete_valid_run_is_report_eligible(complete_run):
    ws, rid, _ = complete_run
    result = validate_run(ws, rid)
    assert result["report_eligible"] is True, result["blocking_errors"]
    assert result["failed"] == 0 and result["not_evaluated"] == 0


def test_validation_result_is_itself_a_valid_artifact(complete_run):
    ws, rid, meta = complete_run
    validate_run(ws, rid)
    path = meta["run_dir"] / "validation" / "validation-result.json"
    validate_artifact(json.loads(path.read_text(encoding="utf-8")), path=path)


def test_checks_record_what_ran_not_only_what_failed(complete_run):
    """Spec §8.8 + lessons §6b: the result must show which checks were evaluated."""
    ws, rid, _ = complete_run
    result = validate_run(ws, rid)
    assert len(result["checks"]) >= 15
    assert {c["status"] for c in result["checks"]} <= {"passed", "failed", "not_evaluated",
                                                       "not_applicable"}


# --------------------------------------------------------------- not_evaluated blocks


def test_an_empty_run_is_blocked_by_not_evaluated_not_by_silence(tmp_path: Path):
    """The failure mode this platform exists to prevent: 'no problems found' about a run nobody
    looked at."""
    sources = build(tmp_path / "sources")
    init_workspace(tmp_path / "ws")
    ws = load_workspace(tmp_path / "ws")
    import_paths(ws, [sources["markdown"]])
    build_index(ws)
    rid = create_run(ws, question="anything")["run_id"]

    result = validate_run(ws, rid)
    assert result["report_eligible"] is False
    assert result["failed"] == 0, "nothing actually failed — it could not be evaluated"
    assert result["not_evaluated"] > 0
    assert all(e["status"] == "not_evaluated" for e in result["blocking_errors"])


# --------------------------------------------------------------- seeded defects


def test_a_claim_without_evidence_blocks_publication(complete_run):
    ws, rid, meta = complete_run
    path = meta["run_dir"] / "claims" / "c1.json"
    claim = json.loads(path.read_text(encoding="utf-8"))
    claim["supporting_evidence_ids"] = []
    path.write_text(json.dumps(claim), encoding="utf-8")   # bypass write validation deliberately

    result = validate_run(ws, rid)
    assert result["report_eligible"] is False
    assert _status(result, "claims_reference_evidence") == "failed"


def test_a_dangling_evidence_reference_blocks_publication(complete_run):
    ws, rid, meta = complete_run
    path = meta["run_dir"] / "claims" / "c1.json"
    claim = json.loads(path.read_text(encoding="utf-8"))
    claim["supporting_evidence_ids"] = ["EVD-sha256-" + "f" * 64]
    path.write_text(json.dumps(claim), encoding="utf-8")

    result = validate_run(ws, rid)
    assert _status(result, "claims_reference_evidence") == "failed"
    assert result["report_eligible"] is False


def test_an_unresolvable_locator_blocks_publication(complete_run):
    """The citation points at offsets that no longer contain what it claims."""
    ws, rid, meta = complete_run
    path = meta["run_dir"] / "evidence" / "e1.json"
    ev = json.loads(path.read_text(encoding="utf-8"))
    ev["locator"]["start_offset"] = 999_999
    ev["locator"]["end_offset"] = 1_000_099
    path.write_text(json.dumps(ev), encoding="utf-8")

    result = validate_run(ws, rid)
    assert _status(result, "text_locators_resolve") == "failed"
    assert result["report_eligible"] is False


def test_a_paraphrased_exact_text_blocks_publication(complete_run):
    """exact_text must be the passage at those offsets, not a tidied version of it."""
    ws, rid, meta = complete_run
    path = meta["run_dir"] / "evidence" / "e1.json"
    ev = json.loads(path.read_text(encoding="utf-8"))
    ev["exact_text"] = "a paraphrase the reviewer would have to take on trust"
    path.write_text(json.dumps(ev), encoding="utf-8")

    result = validate_run(ws, rid)
    assert _status(result, "text_locators_resolve") == "failed"


def test_a_tampered_original_blocks_publication(complete_run):
    """Evidence rests on immutable bytes; if they changed, everything above them is void."""
    ws, rid, meta = complete_run
    stored = ws.root / meta["doc"]["stored_original"]
    stored.write_bytes(stored.read_bytes() + b"\n% appended after import\n")

    result = validate_run(ws, rid)
    assert _status(result, "source_hashes_match") == "failed"
    assert result["report_eligible"] is False


@pytest.mark.parametrize("missing", ["contradiction_review", "citation_review",
                                     "methodology_review", "independent_review"])
def test_each_required_review_is_individually_required(complete_run, missing):
    ws, rid, meta = complete_run
    (meta["run_dir"] / "reviews" / f"{missing}.json").unlink()

    result = validate_run(ws, rid)
    assert _status(result, f"{missing}_complete") == "not_evaluated"
    assert result["report_eligible"] is False


def test_a_failed_review_blocks_publication(complete_run):
    ws, rid, meta = complete_run
    path = meta["run_dir"] / "reviews" / "citation_review.json"
    review = json.loads(path.read_text(encoding="utf-8"))
    review["decision"] = "failed"
    review["blocking_issues"] = ["the cited passage does not mention the claimed result"]
    path.write_text(json.dumps(review), encoding="utf-8")

    result = validate_run(ws, rid)
    assert _status(result, "citation_review_complete") == "failed"
    assert result["report_eligible"] is False


def test_a_related_but_non_supporting_citation_blocks_publication(complete_run):
    """Spec §38.5 — the failure mode where a plausible source is nonetheless not support."""
    ws, rid, meta = complete_run
    path = meta["run_dir"] / "reviews" / "citation_review.json"
    review = json.loads(path.read_text(encoding="utf-8"))
    review["per_claim"][0]["citation_support"] = "related_not_supporting"
    path.write_text(json.dumps(review), encoding="utf-8")

    result = validate_run(ws, rid)
    assert _status(result, "citations_support_their_claims") == "failed"
    assert result["report_eligible"] is False


def test_an_unassessed_claim_is_not_evaluated_rather_than_assumed_fine(complete_run):
    ws, rid, meta = complete_run
    path = meta["run_dir"] / "reviews" / "citation_review.json"
    review = json.loads(path.read_text(encoding="utf-8"))
    review["per_claim"] = []
    path.write_text(json.dumps(review), encoding="utf-8")

    result = validate_run(ws, rid)
    assert _status(result, "citations_support_their_claims") == "not_evaluated"
    assert result["report_eligible"] is False


def test_insufficient_reviewer_independence_blocks_publication(complete_run):
    ws, rid, meta = complete_run
    path = meta["run_dir"] / "reviews" / "independent_review.json"
    review = json.loads(path.read_text(encoding="utf-8"))
    review["review_independence"]["status"] = "not_independent"
    path.write_text(json.dumps(review), encoding="utf-8")

    result = validate_run(ws, rid)
    assert _status(result, "reviewer_independence_sufficient") == "failed"
    assert result["report_eligible"] is False


def test_undeclared_independence_is_not_evaluated(complete_run):
    ws, rid, meta = complete_run
    path = meta["run_dir"] / "reviews" / "independent_review.json"
    review = json.loads(path.read_text(encoding="utf-8"))
    del review["review_independence"]
    path.write_text(json.dumps(review), encoding="utf-8")

    result = validate_run(ws, rid)
    assert _status(result, "reviewer_independence_sufficient") == "not_evaluated"


def test_ocr_evidence_without_human_verification_blocks_publication(complete_run):
    """Spec §26: no OCR ships in v1, so such a page is readable only via a human amendment."""
    ws, rid, meta = complete_run
    path = meta["run_dir"] / "evidence" / "e1.json"
    ev = json.loads(path.read_text(encoding="utf-8"))
    ev["extraction_status"] = "ocr_required"
    ev["human_review_required"] = True
    path.write_text(json.dumps(ev), encoding="utf-8")

    result = validate_run(ws, rid)
    assert _status(result, "ocr_evidence_human_verified") == "failed"
    assert result["report_eligible"] is False
    assert result["human_review_required"] is True


def test_a_recorded_human_verification_amendment_clears_the_ocr_gate(complete_run):
    """The sanctioned route forward must actually work, or the gate is a dead end."""
    ws, rid, meta = complete_run
    path = meta["run_dir"] / "evidence" / "e1.json"
    ev = json.loads(path.read_text(encoding="utf-8"))
    ev["extraction_status"] = "ocr_required"
    ev["human_review_required"] = True
    path.write_text(json.dumps(ev), encoding="utf-8")

    aid = amendment_id()
    amendment = make_artifact(
        schema_name="Amendment", artifact_id=aid, actor_type="human",
        body=dict(amendment_id=aid, run_id=rid, target_artifact_id=meta["evidence_id"],
                  target_artifact_hash=ev["artifact_hash"],
                  amendment_type="human_ocr_verification",
                  changed_fields=["extraction_status"],
                  reason="page read manually against the render; text confirmed",
                  human={"identifier": "jeehoon"}, requires_revalidation=True,
                  replacement_artifact_id=meta["evidence_id"],
                  replacement_artifact_hash=ev["artifact_hash"]))
    write_artifact(meta["run_dir"] / "amendments" / "a1.json", amendment, root=ws.root)

    result = validate_run(ws, rid)
    assert _status(result, "ocr_evidence_human_verified") == "passed"


def test_an_unresolved_contradiction_blocks_publication(complete_run):
    ws, rid, meta = complete_run
    path = meta["run_dir"] / "claims" / "c1.json"
    claim = json.loads(path.read_text(encoding="utf-8"))
    claim["contradiction_status"] = "unresolved"
    path.write_text(json.dumps(claim), encoding="utf-8")

    result = validate_run(ws, rid)
    assert _status(result, "contradictions_disclosed") == "failed"
    assert result["human_review_required"] is True


def test_verified_without_a_passed_independent_review_blocks_publication(complete_run):
    """The schema constrains the claim's shape; validation checks the run actually earned it."""
    ws, rid, meta = complete_run
    (meta["run_dir"] / "reviews" / "independent_review.json").unlink()
    path = meta["run_dir"] / "claims" / "c1.json"
    claim = json.loads(path.read_text(encoding="utf-8"))
    claim["claim_type"] = "direct_fact"
    claim["support_classification"] = "verified"
    claim["independent_review_status"] = "not_yet_reviewed"
    path.write_text(json.dumps(claim), encoding="utf-8")

    result = validate_run(ws, rid)
    assert _status(result, "support_classifications_earned") == "failed"
    assert result["report_eligible"] is False


def test_verified_does_not_require_multiple_sources(complete_run):
    """Spec §23.1: `verified` turns on DIRECT CHECKABILITY, not on source count.

    Its own examples — a paper's stated publication date, a directly reported sample size, a
    documented configuration value — have exactly one authoritative source. Requiring corroboration
    would make `verified` unreachable for the facts it exists to describe.

    Regression: the source-independence check originally demanded independence for `verified` as
    well as `strongly_supported`, and refused a correctly-scoped single-source fact. A real
    conformance run caught it.
    """
    ws, rid, meta = complete_run
    path = meta["run_dir"] / "claims" / "c1.json"
    claim = json.loads(path.read_text(encoding="utf-8"))
    claim["claim_type"] = "direct_fact"
    claim["support_classification"] = "verified"
    claim["independent_review_status"] = "confirmed_independent"
    path.write_text(json.dumps(claim), encoding="utf-8")

    result = validate_run(ws, rid)
    assert _status(result, "source_independence_established") == "not_applicable"
    assert _status(result, "support_classifications_earned") == "passed"
    assert result["report_eligible"] is True, result["blocking_errors"]


def test_strongly_supported_still_requires_more_than_one_source(complete_run):
    """The other half of the same rule: corroboration is exactly what this label means."""
    ws, rid, meta = complete_run
    path = meta["run_dir"] / "claims" / "c1.json"
    claim = json.loads(path.read_text(encoding="utf-8"))
    claim["support_classification"] = "strongly_supported"
    path.write_text(json.dumps(claim), encoding="utf-8")

    result = validate_run(ws, rid)
    assert _status(result, "source_independence_established") == "failed"
    assert result["report_eligible"] is False


def test_an_unreadable_artifact_is_not_evaluated_rather_than_skipped(complete_run):
    ws, rid, meta = complete_run
    (meta["run_dir"] / "claims" / "broken.json").write_text("{not json", encoding="utf-8")

    result = validate_run(ws, rid)
    assert _status(result, "artifacts_conform_to_schema") == "not_evaluated"
    assert result["report_eligible"] is False


def test_a_schema_invalid_artifact_blocks_publication(complete_run):
    ws, rid, meta = complete_run
    path = meta["run_dir"] / "claims" / "c1.json"
    claim = json.loads(path.read_text(encoding="utf-8"))
    claim["support_classification"] = "definitely_true"       # not in the enum
    path.write_text(json.dumps(claim), encoding="utf-8")

    result = validate_run(ws, rid)
    assert _status(result, "artifacts_conform_to_schema") == "failed"
    assert result["report_eligible"] is False


def test_high_risk_profiles_demand_confirmed_independence(complete_run):
    """procedurally_isolated is acceptable by default, not for a high-risk profile (spec §13).

    The manifest is re-stamped rather than hand-edited: `load_run` verifies artifact_hash, so an
    edited manifest is rejected as tampering before the profile rule is ever reached. Re-stamping
    simulates a run legitimately created under the medicine profile.
    """
    from research.hashing import stamp_artifact_hash

    ws, rid, meta = complete_run
    manifest_path = meta["run_dir"] / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["profile"] = "medicine"
    manifest_path.write_text(json.dumps(stamp_artifact_hash(manifest)), encoding="utf-8")

    result = validate_run(ws, rid)
    assert _status(result, "reviewer_independence_sufficient") == "failed"
    assert result["report_eligible"] is False


def test_a_hand_edited_run_manifest_is_rejected_as_tampering(complete_run):
    """The behaviour the previous test had to work around is itself a guarantee worth pinning."""
    ws, rid, meta = complete_run
    manifest_path = meta["run_dir"] / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["profile"] = "medicine"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")   # hash NOT re-stamped

    from research.errors import SchemaValidationError
    with pytest.raises(SchemaValidationError):
        validate_run(ws, rid)


# --------------------------------------------------------------- attested independence (GOAL.md)
#
# `reviewer_independence_sufficient` reads a boolean the host wrote about itself. It was the one
# purely self-reported gate in the system, and a real conformance run leaked `primary_confidence`
# into an independent-review packet without a single check noticing. These tests pin the cost that
# `confirmed_independent` now carries.

THE_REAL_LEAK = "submitted with support classification: conflicting_evidence"

CLEAN_CONTEXT = (
    "TRUSTED WORKFLOW INSTRUCTIONS\n"
    "Assess whether the cited passage supports the claim below. Decide for yourself.\n\n"
    "Question: does process-in-memory reduce off-chip data movement?\n"
    "Claim: the paper reports reduced data movement.\n"
    "Evidence: quoted passage with a resolvable locator.\n"
)


def _set_independence(run_dir: Path, status: str) -> str:
    from research.hashing import stamp_artifact_hash

    path = run_dir / "reviews" / "independent_review.json"
    review = json.loads(path.read_text(encoding="utf-8"))
    review["review_independence"]["status"] = status
    review["review_independence"]["host_confirmed_fresh_context"] = (
        status == "confirmed_independent")
    path.write_text(json.dumps(stamp_artifact_hash(review)), encoding="utf-8")
    return review["review_id"]


def _attest(ws, run_dir: Path, run: str, review: str, content: str, *,
            complete: bool = True, recorded_hash: str | None = None) -> None:
    from research.hashing import sha256_text
    from research.identifiers import review_context_id

    ctx = review_context_id(content)
    artifact = make_artifact(
        schema_name="ReviewContext", artifact_id=ctx, actor_type="host_agent",
        body=dict(context_id=ctx, run_id=run, review_id=review, stage="independent_review",
                  content=content, content_sha256=recorded_hash or sha256_text(content),
                  transmitted_to={"actor_type": "host_agent", "host": "test"},
                  attestation={"complete": complete,
                               "method": "verbatim_transcript" if complete else "partial"}))
    write_artifact(run_dir / "review-contexts" / "independent.json", artifact, root=ws.root)


def test_procedurally_isolated_needs_no_attestation(complete_run):
    """The weaker status was always the honest option for a host that cannot prove more, and it
    still is. Making it cost something too would just push hosts to overclaim."""
    ws, rid, _ = complete_run
    result = validate_run(ws, rid)
    assert _status(result, "independence_context_attested") == "not_applicable"
    assert result["report_eligible"] is True, result["blocking_errors"]


def test_confirmed_independent_without_an_attested_context_blocks(complete_run):
    """The gate this whole exercise exists to close: the strongest status is no longer free."""
    ws, rid, meta = complete_run
    _set_independence(meta["run_dir"], "confirmed_independent")

    result = validate_run(ws, rid)
    assert _status(result, "independence_context_attested") == "not_evaluated"
    assert _status(result, "reviewer_independence_sufficient") == "passed", \
        "the declaration itself is still well-formed — it is the evidence for it that is missing"
    assert result["report_eligible"] is False


def test_confirmed_independent_with_a_clean_attested_context_passes(complete_run):
    ws, rid, meta = complete_run
    review = _set_independence(meta["run_dir"], "confirmed_independent")
    _attest(ws, meta["run_dir"], rid, review, CLEAN_CONTEXT)

    result = validate_run(ws, rid)
    assert _status(result, "independence_context_attested") == "passed"
    assert result["report_eligible"] is True, result["blocking_errors"]


def test_the_real_historical_leak_in_an_attested_context_fails_the_run(complete_run):
    """End to end, with the verbatim sentence that got past every gate in the conformance run."""
    ws, rid, meta = complete_run
    review = _set_independence(meta["run_dir"], "confirmed_independent")
    _attest(ws, meta["run_dir"], rid, review, CLEAN_CONTEXT + f"\nNote: {THE_REAL_LEAK}.\n")

    result = validate_run(ws, rid)
    assert _status(result, "independence_context_attested") == "failed"
    assert result["report_eligible"] is False
    assert result["human_review_required"] is True
    assert any("conflicting_evidence" in e["detail"]
               for e in result["blocking_errors"] if e["check"] == "independence_context_attested")


def test_a_partial_context_cannot_establish_independence(complete_run):
    """A clean scan of an incomplete record proves nothing — the leak may be in the unrecorded part.
    Reporting that as a pass is the fail-open shape exactly (lessons §6b)."""
    ws, rid, meta = complete_run
    review = _set_independence(meta["run_dir"], "confirmed_independent")
    _attest(ws, meta["run_dir"], rid, review, CLEAN_CONTEXT, complete=False)

    result = validate_run(ws, rid)
    assert _status(result, "independence_context_attested") == "not_evaluated"
    assert result["report_eligible"] is False


def test_an_attested_context_that_does_not_match_its_own_hash_fails(complete_run):
    """Content-addressing is the reason the artifact is worth more than the boolean it replaces.
    An attestation edited after the fact must not be scannable into a pass."""
    from research.hashing import sha256_text

    ws, rid, meta = complete_run
    review = _set_independence(meta["run_dir"], "confirmed_independent")
    _attest(ws, meta["run_dir"], rid, review, CLEAN_CONTEXT,
            recorded_hash=sha256_text("something else entirely"))

    result = validate_run(ws, rid)
    assert _status(result, "independence_context_attested") == "failed"
    assert result["report_eligible"] is False
