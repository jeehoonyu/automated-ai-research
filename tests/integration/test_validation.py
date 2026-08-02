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
from research.hashing import sha256_text, stamp_artifact_hash  # noqa: E402
from research.identifiers import (  # noqa: E402
    amendment_id,
    evidence_id,
    review_id,
)
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


def test_every_check_a_run_emits_is_named_in_the_validation_rules_document(complete_run):
    """A gate nobody outside the code knows exists.

    Asserted against the ids a REAL run emits, not against the check functions' names — the two are
    different strings (`check_claims_have_evidence` emits `claims_reference_evidence`), and four of
    the checks are lambdas that build their id from the review type they take. Deriving the id from
    the function would test the derivation rather than the documentation.

    `docs/validation-rules.md` is the file the README points a reader at to find out what blocks.
    """
    ws, rid, _ = complete_run
    result = validate_run(ws, rid)
    doc = (Path(__file__).resolve().parents[2] / "docs" / "validation-rules.md").read_text(
        encoding="utf-8")

    emitted = sorted({str(c["check"]) for c in result["checks"]})
    assert len(emitted) == len(result["checks"]), "two checks share an id"
    missing = [name for name in emitted if f"`{name}`" not in doc]
    assert not missing, f"checks the documentation does not name: {missing}"


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
    path = meta["claim_path"]
    claim = json.loads(path.read_text(encoding="utf-8"))
    claim["supporting_evidence_ids"] = []
    # Re-stamped, not tampered: this simulates a run an agent legitimately produced in this
    # state, rather than a hand edit — which validation now catches as tampering.
    path.write_text(json.dumps(stamp_artifact_hash(claim)), encoding="utf-8")

    result = validate_run(ws, rid)
    assert result["report_eligible"] is False
    assert _status(result, "claims_reference_evidence") == "failed"


def test_a_dangling_evidence_reference_blocks_publication(complete_run):
    ws, rid, meta = complete_run
    path = meta["claim_path"]
    claim = json.loads(path.read_text(encoding="utf-8"))
    claim["supporting_evidence_ids"] = ["EVD-sha256-" + "f" * 64]
    path.write_text(json.dumps(stamp_artifact_hash(claim)), encoding="utf-8")

    result = validate_run(ws, rid)
    assert _status(result, "claims_reference_evidence") == "failed"
    assert result["report_eligible"] is False


def test_an_unresolvable_locator_blocks_publication(complete_run):
    """The citation points at offsets that no longer contain what it claims."""
    ws, rid, meta = complete_run
    path = meta["evidence_path"]
    ev = json.loads(path.read_text(encoding="utf-8"))
    ev["locator"]["start_offset"] = 999_999
    ev["locator"]["end_offset"] = 1_000_099
    path.write_text(json.dumps(stamp_artifact_hash(ev)), encoding="utf-8")

    result = validate_run(ws, rid)
    assert _status(result, "text_locators_resolve") == "failed"
    assert result["report_eligible"] is False


def test_a_paraphrased_exact_text_blocks_publication(complete_run):
    """exact_text must be the passage at those offsets, not a tidied version of it."""
    ws, rid, meta = complete_run
    path = meta["evidence_path"]
    ev = json.loads(path.read_text(encoding="utf-8"))
    ev["exact_text"] = "a paraphrase the reviewer would have to take on trust"
    path.write_text(json.dumps(stamp_artifact_hash(ev)), encoding="utf-8")

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
    (meta["review_paths"][missing]).unlink()

    result = validate_run(ws, rid)
    assert _status(result, f"{missing}_complete") == "not_evaluated"
    assert result["report_eligible"] is False


def test_a_failed_review_blocks_publication(complete_run):
    ws, rid, meta = complete_run
    path = meta["review_paths"]["citation_review"]
    review = json.loads(path.read_text(encoding="utf-8"))
    review["decision"] = "failed"
    review["blocking_issues"] = ["the cited passage does not mention the claimed result"]
    path.write_text(json.dumps(stamp_artifact_hash(review)), encoding="utf-8")

    result = validate_run(ws, rid)
    assert _status(result, "citation_review_complete") == "failed"
    assert result["report_eligible"] is False


def test_a_related_but_non_supporting_citation_blocks_publication(complete_run):
    """Spec §38.5 — the failure mode where a plausible source is nonetheless not support."""
    ws, rid, meta = complete_run
    path = meta["review_paths"]["citation_review"]
    review = json.loads(path.read_text(encoding="utf-8"))
    review["per_claim"][0]["citation_support"] = "related_not_supporting"
    path.write_text(json.dumps(stamp_artifact_hash(review)), encoding="utf-8")

    result = validate_run(ws, rid)
    assert _status(result, "citations_support_their_claims") == "failed"
    assert result["report_eligible"] is False


def test_an_unassessed_claim_is_not_evaluated_rather_than_assumed_fine(complete_run):
    ws, rid, meta = complete_run
    path = meta["review_paths"]["citation_review"]
    review = json.loads(path.read_text(encoding="utf-8"))
    review["per_claim"] = []
    path.write_text(json.dumps(stamp_artifact_hash(review)), encoding="utf-8")

    result = validate_run(ws, rid)
    assert _status(result, "citations_support_their_claims") == "not_evaluated"
    assert result["report_eligible"] is False


def test_insufficient_reviewer_independence_blocks_publication(complete_run):
    ws, rid, meta = complete_run
    path = meta["review_paths"]["independent_review"]
    review = json.loads(path.read_text(encoding="utf-8"))
    review["review_independence"]["status"] = "not_independent"
    path.write_text(json.dumps(stamp_artifact_hash(review)), encoding="utf-8")

    result = validate_run(ws, rid)
    assert _status(result, "reviewer_independence_sufficient") == "failed"
    assert result["report_eligible"] is False


def test_undeclared_independence_is_not_evaluated(complete_run):
    ws, rid, meta = complete_run
    path = meta["review_paths"]["independent_review"]
    review = json.loads(path.read_text(encoding="utf-8"))
    del review["review_independence"]
    path.write_text(json.dumps(stamp_artifact_hash(review)), encoding="utf-8")

    result = validate_run(ws, rid)
    assert _status(result, "reviewer_independence_sufficient") == "not_evaluated"


def test_ocr_evidence_without_human_verification_blocks_publication(complete_run):
    """Spec §26: no OCR ships in v1, so such a page is readable only via a human amendment."""
    ws, rid, meta = complete_run
    path = meta["evidence_path"]
    ev = json.loads(path.read_text(encoding="utf-8"))
    ev["extraction_status"] = "ocr_required"
    ev["human_review_required"] = True
    path.write_text(json.dumps(stamp_artifact_hash(ev)), encoding="utf-8")

    result = validate_run(ws, rid)
    assert _status(result, "ocr_evidence_human_verified") == "failed"
    assert result["report_eligible"] is False
    assert result["human_review_required"] is True


def test_a_recorded_human_verification_amendment_clears_the_ocr_gate(complete_run):
    """The sanctioned route forward must actually work, or the gate is a dead end."""
    ws, rid, meta = complete_run
    path = meta["evidence_path"]
    ev = json.loads(path.read_text(encoding="utf-8"))
    ev["extraction_status"] = "ocr_required"
    ev["human_review_required"] = True
    # `stamp_artifact_hash` returns a COPY, so the amendment must name the hash of what actually
    # lands on disk. Naming `ev["artifact_hash"]` here points at the pre-edit version — which the
    # staleness rule now rejects, correctly: a verification must name the version it checked.
    ev = stamp_artifact_hash(ev)
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
    path = meta["claim_path"]
    claim = json.loads(path.read_text(encoding="utf-8"))
    claim["contradiction_status"] = "unresolved"
    path.write_text(json.dumps(stamp_artifact_hash(claim)), encoding="utf-8")

    result = validate_run(ws, rid)
    assert _status(result, "contradictions_disclosed") == "failed"
    assert result["human_review_required"] is True


def test_verified_without_a_passed_independent_review_blocks_publication(complete_run):
    """The schema constrains the claim's shape; validation checks the run actually earned it."""
    ws, rid, meta = complete_run
    meta["review_paths"]["independent_review"].unlink()
    path = meta["claim_path"]
    claim = json.loads(path.read_text(encoding="utf-8"))
    claim["claim_type"] = "direct_fact"
    claim["support_classification"] = "verified"
    claim["independent_review_status"] = "not_yet_reviewed"
    path.write_text(json.dumps(stamp_artifact_hash(claim)), encoding="utf-8")

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
    path = meta["claim_path"]
    claim = json.loads(path.read_text(encoding="utf-8"))
    claim["claim_type"] = "direct_fact"
    claim["support_classification"] = "verified"
    claim["independent_review_status"] = "confirmed_independent"
    path.write_text(json.dumps(stamp_artifact_hash(claim)), encoding="utf-8")

    result = validate_run(ws, rid)
    assert _status(result, "source_independence_established") == "not_applicable"
    assert _status(result, "support_classifications_earned") == "passed"
    assert result["report_eligible"] is True, result["blocking_errors"]


def test_strongly_supported_still_requires_more_than_one_source(complete_run):
    """The other half of the same rule: corroboration is exactly what this label means."""
    ws, rid, meta = complete_run
    path = meta["claim_path"]
    claim = json.loads(path.read_text(encoding="utf-8"))
    claim["support_classification"] = "strongly_supported"
    path.write_text(json.dumps(stamp_artifact_hash(claim)), encoding="utf-8")

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
    path = meta["claim_path"]
    claim = json.loads(path.read_text(encoding="utf-8"))
    claim["support_classification"] = "definitely_true"       # not in the enum
    path.write_text(json.dumps(stamp_artifact_hash(claim)), encoding="utf-8")

    result = validate_run(ws, rid)
    assert _status(result, "artifacts_conform_to_schema") == "failed"
    assert result["report_eligible"] is False


def test_high_risk_profiles_demand_confirmed_independence(complete_run):
    """procedurally_isolated is acceptable by default, not for a high-risk profile (spec §13).

    The manifest is re-stamped rather than hand-edited: `load_run` verifies artifact_hash, so an
    edited manifest is rejected as tampering before the profile rule is ever reached. Re-stamping
    simulates a run legitimately created under the medicine profile.
    """
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


def _set_independence(path: Path, status: str) -> str:
    """Takes the promoted path, not a guessed filename: the CLI chooses names now."""
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
    _set_independence(meta["review_paths"]["independent_review"], "confirmed_independent")

    result = validate_run(ws, rid)
    assert _status(result, "independence_context_attested") == "not_evaluated"
    assert _status(result, "reviewer_independence_sufficient") == "passed", \
        "the declaration itself is still well-formed — it is the evidence for it that is missing"
    assert result["report_eligible"] is False


def test_confirmed_independent_with_a_clean_attested_context_passes(complete_run):
    ws, rid, meta = complete_run
    review = _set_independence(meta["review_paths"]["independent_review"], "confirmed_independent")
    _attest(ws, meta["run_dir"], rid, review, CLEAN_CONTEXT)

    result = validate_run(ws, rid)
    assert _status(result, "independence_context_attested") == "passed"
    assert result["report_eligible"] is True, result["blocking_errors"]


def test_the_real_historical_leak_in_an_attested_context_fails_the_run(complete_run):
    """End to end, with the verbatim sentence that got past every gate in the conformance run."""
    ws, rid, meta = complete_run
    review = _set_independence(meta["review_paths"]["independent_review"], "confirmed_independent")
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
    review = _set_independence(meta["review_paths"]["independent_review"], "confirmed_independent")
    _attest(ws, meta["run_dir"], rid, review, CLEAN_CONTEXT, complete=False)

    result = validate_run(ws, rid)
    assert _status(result, "independence_context_attested") == "not_evaluated"
    assert result["report_eligible"] is False


def test_an_attested_context_that_does_not_match_its_own_hash_fails(complete_run):
    """Content-addressing is the reason the artifact is worth more than the boolean it replaces.
    An attestation edited after the fact must not be scannable into a pass."""
    from research.hashing import sha256_text

    ws, rid, meta = complete_run
    review = _set_independence(meta["review_paths"]["independent_review"], "confirmed_independent")
    _attest(ws, meta["run_dir"], rid, review, CLEAN_CONTEXT,
            recorded_hash=sha256_text("something else entirely"))

    result = validate_run(ws, rid)
    assert _status(result, "independence_context_attested") == "failed"
    assert result["report_eligible"] is False


# --------------------------------------------------------------- artifacts are verified on load
#
# `_load_json_dir` was a bare `json.load`. `read_artifact` verifies hashes; this loader is what
# validation actually uses, and it did not — so every artifact an untrusted host agent produces
# could be edited after the fact with nothing noticing. Note how many tests above had to start
# re-stamping once it did: they were all relying on the absence of this check.


def test_a_hand_edited_review_is_caught_as_tampering(complete_run):
    """One word, and `citations_support_their_claims` flips from failed to passed."""
    ws, rid, meta = complete_run
    path = meta["review_paths"]["citation_review"]
    review = json.loads(path.read_text(encoding="utf-8"))
    review["per_claim"][0]["citation_support"] = "related_not_supporting"
    path.write_text(json.dumps(review), encoding="utf-8")     # hash deliberately NOT re-stamped

    result = validate_run(ws, rid)
    assert _status(result, "artifacts_conform_to_schema") == "not_evaluated"
    assert result["report_eligible"] is False
    assert any("artifact_hash" in e["detail"] for e in result["blocking_errors"])


def test_a_hand_edited_claim_is_caught_as_tampering(complete_run):
    ws, rid, meta = complete_run
    path = meta["claim_path"]
    claim = json.loads(path.read_text(encoding="utf-8"))
    claim["claim"] = "Process-in-memory eliminates off-chip data movement entirely."
    path.write_text(json.dumps(claim), encoding="utf-8")

    result = validate_run(ws, rid)
    assert result["report_eligible"] is False
    assert _status(result, "artifacts_conform_to_schema") == "not_evaluated"


def test_a_stray_file_in_reviews_is_reported_not_a_crash(complete_run):
    """It used to reach a check that reads `review_type` and die with KeyError. A validator that
    raises tells the caller nothing about the run; `not_evaluated` tells it the truth."""
    ws, rid, meta = complete_run
    (meta["run_dir"] / "reviews" / "notes.json").write_text(
        json.dumps({"note": "scratch"}), encoding="utf-8")

    result = validate_run(ws, rid)
    assert _status(result, "artifacts_conform_to_schema") == "not_evaluated"
    assert result["report_eligible"] is False


# ------------------------------------------------ "nobody looked" is not "none found"


def test_an_unchecked_contradiction_status_blocks(complete_run):
    """`not_checked` used to return passed, "none unresolved" — a clean bill of health for a
    question nobody asked, from the check whose module docstring says not_evaluated blocks."""
    ws, rid, meta = complete_run
    path = meta["claim_path"]
    claim = json.loads(path.read_text(encoding="utf-8"))
    claim["contradiction_status"] = "not_checked"
    path.write_text(json.dumps(stamp_artifact_hash(claim)), encoding="utf-8")

    result = validate_run(ws, rid)
    assert _status(result, "contradictions_disclosed") == "not_evaluated"
    assert result["report_eligible"] is False


# --------------------------------------------------------------- independence must be asserted


def _relationship(ws, run_dir, rid, docs, kind):
    art = make_artifact(
        schema_name="SourceRelationship", artifact_id=amendment_id(), actor_type="host_agent",
        body=dict(source_document_id=docs[0], related_document_id=docs[1],
                  relationship_type=kind, confidence="high",
                  detected_by="agent_review"))
    write_artifact(run_dir / "relationships" / "r1.json", art, root=ws.root)


@pytest.mark.parametrize("kind,expected", [
    ("unknown", "not_evaluated"),
    ("cites", "not_evaluated"),
    ("duplicate", "failed"),
    ("independent", "passed"),
])
def test_only_a_positive_assertion_of_independence_clears_the_gate(
        complete_run, kind, expected, tmp_path):
    """The gate was inverted: recording NOTHING blocked, recording `unknown` — the same statement,
    written down — passed. `independent` did not exist in the enum at all, so the passing verdict
    was unearnable honestly.
    """
    ws, rid, meta = complete_run
    run_dir = meta["run_dir"]

    # A second document and a second evidence record, so the claim rests on two sources.
    other_doc = next(d for d in
                     (json.loads(p.read_text(encoding="utf-8"))
                      for p in (ws.root / "documents" / "manifests").glob("*.json"))
                     if d["document_id"] != meta["doc"]["document_id"])
    text = (ws.root / other_doc["normalized_text_path"]).read_text(encoding="utf-8")
    loc = {"type": "text_span", "start_offset": 0, "end_offset": 40,
           "span_sha256": sha256_text(text[:40])}
    eid = evidence_id(document_version_id_=other_doc["document_version_id"], locator=loc,
                      exact_text=text[:40], evidence_type="direct_statement")
    write_artifact(run_dir / "evidence" / "e2.json", make_artifact(
        schema_name="Evidence", artifact_id=eid, actor_type="host_agent",
        body=dict(evidence_id=eid, document_id=other_doc["document_id"],
                  document_version_id=other_doc["document_version_id"],
                  evidence_type="direct_statement", locator=loc, exact_text=text[:40],
                  extraction_status="extracted", human_review_required=False)), root=ws.root)

    path = meta["claim_path"]
    claim = json.loads(path.read_text(encoding="utf-8"))
    claim["support_classification"] = "strongly_supported"
    claim["supporting_evidence_ids"] = [meta["evidence_id"], eid]
    path.write_text(json.dumps(stamp_artifact_hash(claim)), encoding="utf-8")

    _relationship(ws, run_dir, rid, [meta["doc"]["document_id"], other_doc["document_id"]], kind)

    result = validate_run(ws, rid)
    assert _status(result, "source_independence_established") == expected


# ------------------------------------------------ the bytes citations actually resolve against
#
# `source_hashes_match` re-hashes `originals/` and its docstring says "evidence rests on those
# bytes". It does not: a text locator is an offset pair into `normalized_text_path`, a derived and
# mutable file that nothing re-hashed. `span_sha256` does not close this, because the span hash
# lives in the locator the agent writes — so an agent with workspace write access can alter the
# normalized text and mint evidence that agrees with it, and every locator check passes.


def test_a_self_consistent_fabrication_is_caught_by_the_document_hash(complete_run):
    """The span hash cannot catch this; the document hash can.

    Rewrite the cited span in the normalized text and mint evidence that matches it exactly. Every
    locator resolves — the fabrication agrees with itself — and only re-hashing the derived text
    against what extraction recorded shows the document is not the one that was extracted.
    """
    ws, rid, meta = complete_run
    doc = meta["doc"]
    text_path = ws.root / doc["normalized_text_path"]
    original = text_path.read_text(encoding="utf-8")

    ev_path = meta["evidence_path"]
    ev = json.loads(ev_path.read_text(encoding="utf-8"))
    start, end = ev["locator"]["start_offset"], ev["locator"]["end_offset"]

    # Same length, so every other offset in the document still lands where it did.
    fabricated = "X" * (end - start)
    text_path.write_text(original[:start] + fabricated + original[end:], encoding="utf-8")

    ev["exact_text"] = fabricated
    ev["locator"]["span_sha256"] = sha256_text(fabricated)
    ev_path.write_text(json.dumps(stamp_artifact_hash(ev)), encoding="utf-8")

    result = validate_run(ws, rid)
    assert _status(result, "text_locators_resolve") == "passed", \
        "the fabrication is self-consistent — this is exactly why the span hash is not enough"
    assert _status(result, "derived_text_hashes_match") == "failed"
    assert result["report_eligible"] is False


def test_a_document_without_a_recorded_text_digest_blocks(complete_run):
    """An older manifest that cannot be checked must block, not pass quietly."""
    ws, rid, meta = complete_run
    path = next(p for p in (ws.root / "documents" / "manifests").glob("*.json")
                if json.loads(p.read_text(encoding="utf-8"))["document_id"]
                == meta["doc"]["document_id"])
    doc = json.loads(path.read_text(encoding="utf-8"))
    del doc["normalized_text_sha256"]
    path.write_text(json.dumps(stamp_artifact_hash(doc)), encoding="utf-8")

    result = validate_run(ws, rid)
    assert _status(result, "derived_text_hashes_match") == "not_evaluated"
    assert result["report_eligible"] is False


# ------------------------------------------------ a second review cannot erase the first
#
# `judged[claim_id] = verdict` inside a loop over every citation review meant the LAST file in
# filename sort order won. Re-reviewing until the answer is acceptable is exactly what a citation
# gate exists to prevent, and it required no tampering at all.


def _citation_review(ws, run_dir, rid, cid, verdict, filename):
    rev = review_id()
    art = make_artifact(
        schema_name="Review", artifact_id=rev, actor_type="host_agent",
        body=dict(review_id=rev, review_type="citation_review", run_id=rid,
                  reviewed_artifact_ids=[cid], reviewer={"actor_type": "host_agent"},
                  decision="passed",
                  per_claim=[{"claim_id": cid, "assessment": "checked",
                              "citation_support": verdict}]))
    write_artifact(run_dir / "reviews" / filename, art, root=ws.root)


@pytest.mark.parametrize("first,second", [
    ("aaa-citation_review.json", "zzz-citation_review.json"),
    ("zzz-citation_review.json", "aaa-citation_review.json"),
])
def test_conflicting_citation_verdicts_are_undecided_in_either_file_order(
        complete_run, first, second):
    """Order-dependence was the bug; the parametrisation is the point of the test."""
    ws, rid, meta = complete_run
    cid = meta["claim_id"]
    meta["review_paths"]["citation_review"].unlink()
    _citation_review(ws, meta["run_dir"], rid, cid, "related_not_supporting", first)
    _citation_review(ws, meta["run_dir"], rid, cid, "passed", second)

    result = validate_run(ws, rid)
    assert _status(result, "citations_support_their_claims") == "not_evaluated"
    assert result["report_eligible"] is False


def test_a_not_checked_citation_verdict_counts_as_unjudged(complete_run):
    """`not_checked` is truthy, so it used to register as a verdict and skip the unjudged path."""
    ws, rid, meta = complete_run
    cid = meta["claim_id"]
    meta["review_paths"]["citation_review"].unlink()
    _citation_review(ws, meta["run_dir"], rid, cid, "not_checked", "citation_review.json")

    result = validate_run(ws, rid)
    assert _status(result, "citations_support_their_claims") == "not_evaluated"
    assert result["report_eligible"] is False


def test_two_reviews_agreeing_still_pass(complete_run):
    """Agreement is not a conflict — the fix must not block honest re-review."""
    ws, rid, meta = complete_run
    cid = meta["claim_id"]
    meta["review_paths"]["citation_review"].unlink()
    _citation_review(ws, meta["run_dir"], rid, cid, "passed", "aaa-citation_review.json")
    _citation_review(ws, meta["run_dir"], rid, cid, "passed", "zzz-citation_review.json")

    result = validate_run(ws, rid)
    assert _status(result, "citations_support_their_claims") == "passed"


# ------------------------------------------------ human verification reads the record
#
# The OCR gate selected candidates purely by `extraction_status` on the AGENT-authored Evidence
# artifact, so writing `extracted` on evidence taken from a scanned page cleared it — while the
# deterministic record of which pages need OCR sat unread in the Document manifest the CLI wrote.
# And when the gate did fire, a two-key JSON blob in amendments/ cleared it.


def _ocr_run(ws, rid, meta, tmp_path, *, declare):
    """Import the image-only PDF and point new evidence at a page the manifest flags ocr_required.

    The base fixture's corpus has no such page, so the interesting case was unreachable from it —
    which is its own small lesson about fixtures that make a gate untestable.
    """
    import_paths(ws, [build(tmp_path / "ocr-src")["low_text_pdf"]])
    doc_path = next(p for p in (ws.root / "documents" / "manifests").glob("*.json")
                    if json.loads(p.read_text(encoding="utf-8")).get("ocr_required_pages"))
    doc = json.loads(doc_path.read_text(encoding="utf-8"))
    page_no = doc["ocr_required_pages"][0]
    span = next(s for s in doc["page_map"] if s["page_number"] == page_no)
    text = (ws.root / doc["normalized_text_path"]).read_text(encoding="utf-8")
    start = span["start_offset"]
    end = min(span["end_offset"], start + 30)
    exact = text[start:end]

    loc = {"type": "text_span", "start_offset": start, "end_offset": end,
           "span_sha256": sha256_text(exact)}
    eid = evidence_id(document_version_id_=doc["document_version_id"], locator=loc,
                      exact_text=exact, evidence_type="direct_statement")
    ev = make_artifact(
        schema_name="Evidence", artifact_id=eid, actor_type="host_agent",
        body=dict(evidence_id=eid, document_id=doc["document_id"],
                  document_version_id=doc["document_version_id"],
                  evidence_type="direct_statement", locator=loc, exact_text=exact,
                  extraction_status=declare,
                  human_review_required=(declare == "ocr_required")))
    write_artifact(meta["run_dir"] / "evidence" / "e-ocr.json", ev, root=ws.root)

    path = meta["claim_path"]
    claim = json.loads(path.read_text(encoding="utf-8"))
    claim["supporting_evidence_ids"] = [meta["evidence_id"], eid]
    path.write_text(json.dumps(stamp_artifact_hash(claim)), encoding="utf-8")
    return eid


def test_the_ocr_gate_ignores_the_agents_label_on_its_own_evidence(complete_run, tmp_path):
    """The manifest says the page needs OCR. The evidence says it does not. The manifest wins."""
    ws, rid, meta = complete_run
    eid = _ocr_run(ws, rid, meta, tmp_path, declare="extracted")

    result = validate_run(ws, rid)
    assert _status(result, "ocr_evidence_human_verified") == "failed"
    assert eid in result["blocking_errors"][0]["artifact_ids"] or any(
        eid in e.get("artifact_ids", []) for e in result["blocking_errors"])
    assert result["report_eligible"] is False


def _reword_claim(meta, text: str, claim_type: str | None = None):
    path = meta["claim_path"]
    claim = json.loads(path.read_text(encoding="utf-8"))
    claim["claim"] = text
    if claim_type:
        claim["claim_type"] = claim_type
    path.write_text(json.dumps(stamp_artifact_hash(claim)), encoding="utf-8")


def test_the_causal_human_review_trigger_can_actually_fire(complete_run):
    """A trigger nothing could fire, requested by both shipped profiles.

    `causal_claim_from_correlational_evidence` sat in `KNOWN_TRIGGERS` — the set whose comment says
    these are "triggers the validator can actually detect" — and `default.yaml` and `medicine.yaml`
    both listed it, but no check ever passed that string to `forces_human_review`. So a profile
    asking for a human whenever a causal reading is drawn from non-causal evidence got nothing, and
    `research validate` reported it in green. The detection already existed in `reporting.language`;
    it ran only at report time, after the gate it should have informed.
    """
    ws, rid, meta = complete_run
    _reword_claim(meta, "Process-in-memory causes a reduction in off-chip traffic.",
                  claim_type="descriptive_result")

    result = validate_run(ws, rid)
    assert result["human_review_required"] is True
    assert any("causal" in r for r in result["human_review_reasons"]), \
        result["human_review_reasons"]
    assert result["report_eligible"] is False


CAUSAL_SENTENCE = "The measured slowdown is caused by memory pressure."


@pytest.mark.parametrize("claim_type", ["interpretation", "hypothesis", "direct_fact",
                                        "methodological_claim"])
def test_causal_wording_is_flagged_on_claim_types_the_old_set_omitted(complete_run,
                                                                     claim_type: str):
    """The set named the three "correlational" types, so the other eight were exempt by omission.

    `interpretation` and `hypothesis` were the sharpest: "the treatment causes X" typed as an
    interpretation sailed through, while the identical sentence typed as a descriptive result was
    caught.
    """
    ws, rid, meta = complete_run
    _reword_claim(meta, CAUSAL_SENTENCE, claim_type=claim_type)
    assert validate_run(ws, rid)["human_review_required"] is True


def test_causal_wording_on_a_causal_claim_is_not_flagged(complete_run):
    """The exemption, on its own run.

    It has to be a fresh run: once a validation raises human review the disposition holds, and
    clearing it needs a recorded human amendment rather than another validation pass — which is the
    point of the disposition and not something a test should route around.
    """
    ws, rid, meta = complete_run
    _reword_claim(meta, CAUSAL_SENTENCE, claim_type="causal_claim")
    result = validate_run(ws, rid)
    assert result["human_review_required"] is False
    assert result["report_eligible"] is True


def test_a_run_in_human_review_is_not_report_eligible_and_validate_does_not_crash(complete_run):
    """Re-validating a flagged run used to raise `LifecycleError` out of `research validate`.

    `_record_verdict` attempted `independently_reviewed -> validation_passed` on a run whose
    disposition was `human_review_required`, which the state machine forbids — so the ordinary
    "fix what was flagged, validate again" loop crashed on any run that had ever been flagged, after
    the verdict artifact was already written to disk.
    """
    ws, rid, meta = complete_run
    _reword_claim(meta, CAUSAL_SENTENCE, claim_type="interpretation")
    assert validate_run(ws, rid)["human_review_required"] is True

    # Fix the wording. Validation must run, must not raise, and must still refuse to publish —
    # because the disposition is cleared by a human amendment, not by a second opinion from itself.
    _reword_claim(meta, "The measured slowdown coincided with memory pressure.",
                  claim_type="interpretation")
    result = validate_run(ws, rid)
    assert _status(result, "run_reached_a_publishable_phase") == "failed"
    assert result["report_eligible"] is False
    assert "human_review_required" in str(result["blocking_errors"])


def _relabel_evidence(meta, **fields):
    """Rewrite fields on the fixture's promoted Evidence record and re-stamp it."""
    path = meta["evidence_path"]
    ev = json.loads(path.read_text(encoding="utf-8"))
    ev.update(fields)
    path.write_text(json.dumps(stamp_artifact_hash(ev)), encoding="utf-8")


@pytest.mark.parametrize("declared", ["ambiguous", "human_review_required", "partially_extracted",
                                      "a_status_this_build_has_never_heard_of"])
def test_evidence_that_declares_an_unreliable_extraction_needs_a_human(complete_run, declared):
    """The gate asked about ONE of the seven extraction statuses.

    `== "ocr_required"` meant evidence labelled `ambiguous`, `partially_extracted` or
    `human_review_required` returned `not_applicable` — which does not block — and published. The
    asymmetry is what made it bad: the flattering label `extracted` was correctly distrusted and
    overridden from the Document manifest, while the self-incriminating labels were thrown away, so
    an agent that wrote down the truth about its own extraction got the same green verdict as one
    that did not.
    """
    ws, rid, meta = complete_run
    _relabel_evidence(meta, extraction_status=declared)

    result = validate_run(ws, rid)
    assert _status(result, "ocr_evidence_human_verified") == "failed"
    assert result["report_eligible"] is False


def test_evidence_that_asks_for_human_review_in_the_schemas_own_field_gets_it(complete_run):
    """`Evidence.human_review_required` is a REQUIRED field in the schema, and was read by nothing
    anywhere in the package — not one line in `src/research`."""
    ws, rid, meta = complete_run
    _relabel_evidence(meta, human_review_required=True)

    result = validate_run(ws, rid)
    assert _status(result, "ocr_evidence_human_verified") == "failed"
    assert result["report_eligible"] is False


def test_a_human_amendment_actually_unblocks_an_ocr_blocked_run(complete_run, tmp_path):
    """The end-to-end proof that the documented way forward exists.

    `docs/release-checklist.md` has always said `ocr_required` content becomes usable *only through
    a recorded human amendment*. There was no way to record one: no stage declared `Amendment`, a
    schema-less stage silently discarded it, and a completed stage could not be re-promoted. A
    corpus with one scanned page was a dead end — the gate fired correctly and the only sanctioned
    remedy did not exist.
    """
    from research.runs.amendments import record_amendment

    ws, rid, meta = complete_run
    eid = _ocr_run(ws, rid, meta, tmp_path, declare="ocr_required")

    blocked = validate_run(ws, rid)
    assert _status(blocked, "ocr_evidence_human_verified") == "failed"
    assert blocked["report_eligible"] is False

    result = record_amendment(
        ws, rid, amendment_type="human_ocr_verification", target_artifact_id=eid,
        reason="Read the scanned page myself; the quoted sentence is what it says.",
        human_identifier="j.yu", human_role="reviewer")

    assert result["target_artifact_hash"], "the amendment must be bound to a version"
    assert "cannot verify" in result["attestation_note"]

    after = validate_run(ws, rid)
    assert _status(after, "ocr_evidence_human_verified") == "passed", \
        "the documented remedy did not clear the gate it is documented to clear"


def test_the_amendment_is_bound_to_the_version_that_was_checked(complete_run, tmp_path):
    """A human verification must not outlive the artifact it verified."""
    from research.hashing import stamp_artifact_hash
    from research.runs.amendments import record_amendment

    ws, rid, meta = complete_run
    eid = _ocr_run(ws, rid, meta, tmp_path, declare="ocr_required")
    record_amendment(ws, rid, amendment_type="human_ocr_verification", target_artifact_id=eid,
                     reason="checked", human_identifier="j.yu")
    assert _status(validate_run(ws, rid), "ocr_evidence_human_verified") == "passed"

    # Edit the evidence after the verification. The amendment now names a version that is gone.
    path = meta["run_dir"] / "evidence" / "e-ocr.json"
    evidence = json.loads(path.read_text(encoding="utf-8"))
    evidence["exact_text"] = evidence["exact_text"] + " (edited afterwards)"
    path.write_text(json.dumps(stamp_artifact_hash(evidence)), encoding="utf-8")

    assert _status(validate_run(ws, rid), "ocr_evidence_human_verified") == "failed", \
        "a verification of an older version must not clear the gate for the current one"


def test_amending_something_that_does_not_exist_is_refused(complete_run):
    from research.errors import InvalidArguments
    from research.runs.amendments import record_amendment

    ws, rid, _meta = complete_run
    with pytest.raises(InvalidArguments) as exc:
        record_amendment(ws, rid, amendment_type="human_ocr_verification",
                         target_artifact_id="EVD-sha256-" + "0" * 64,
                         reason="checked", human_identifier="j.yu")
    assert "no artifact" in exc.value.message


@pytest.mark.parametrize(("field", "value"), [("reason", "   "), ("human_identifier", "")])
def test_an_amendment_must_say_why_and_who(complete_run, field: str, value: str):
    """Both are required by the schema, and both are the point: a verification nobody is named for,
    or with no stated reason, documents nothing."""
    from research.errors import InvalidArguments
    from research.runs.amendments import record_amendment

    ws, rid, meta = complete_run
    kwargs = {"reason": "checked", "human_identifier": "j.yu", field: value}
    with pytest.raises(InvalidArguments):
        record_amendment(ws, rid, amendment_type="human_ocr_verification",
                         target_artifact_id=meta["evidence_id"], **kwargs)


def test_a_verification_does_not_mark_its_target_superseded(complete_run, tmp_path):
    """The schema requires every non-withdrawal amendment to name a replacement, so a verification
    names its own target. `research status` reads replacement != target as superseded, and a
    verified artifact has not been replaced by anything."""
    from research.runs.amendments import record_amendment
    from research.runs.manager import status

    ws, rid, meta = complete_run
    eid = _ocr_run(ws, rid, meta, tmp_path, declare="ocr_required")
    record_amendment(ws, rid, amendment_type="human_ocr_verification", target_artifact_id=eid,
                     reason="checked", human_identifier="j.yu")

    assert eid not in status(ws, rid)["superseded_artifacts"]


def test_a_replacing_amendment_must_name_what_replaces_it(complete_run):
    from research.errors import InvalidArguments
    from research.runs.amendments import record_amendment

    ws, rid, meta = complete_run
    with pytest.raises(InvalidArguments) as exc:
        record_amendment(ws, rid, amendment_type="claim_rewording",
                         target_artifact_id=meta["claim_id"],
                         reason="the wording overreached", human_identifier="j.yu")
    assert "must name what replaces it" in exc.value.message


def test_a_two_key_amendment_stub_does_not_clear_the_ocr_gate(complete_run, tmp_path):
    """It used to. `_amendments` did not filter on schema_name, and amendments were absent from
    `check_artifacts_conform`, so `validate_artifact` never ran on one."""
    ws, rid, meta = complete_run
    eid = _ocr_run(ws, rid, meta, tmp_path, declare="ocr_required")

    stub = stamp_artifact_hash({
        "amendment_type": "human_ocr_verification",
        "target_artifact_id": eid,
    })
    (meta["run_dir"] / "amendments" / "stub.json").write_text(
        json.dumps(stub), encoding="utf-8")

    result = validate_run(ws, rid)
    assert _status(result, "ocr_evidence_human_verified") == "failed"
    assert result["report_eligible"] is False


def test_a_verification_of_a_different_version_does_not_clear_the_gate(complete_run, tmp_path):
    """"A human checked this" must not outlive the thing they checked."""
    ws, rid, meta = complete_run
    eid = _ocr_run(ws, rid, meta, tmp_path, declare="ocr_required")

    aid = amendment_id()
    amendment = make_artifact(
        schema_name="Amendment", artifact_id=aid, actor_type="human",
        body=dict(amendment_id=aid, run_id=rid, target_artifact_id=eid,
                  target_artifact_hash="sha256:" + "0" * 64,      # some other version
                  amendment_type="human_ocr_verification",
                  changed_fields=["extraction_status"], reason="checked against the render",
                  human={"identifier": "tester"}, requires_revalidation=True,
                  replacement_artifact_id=eid,
                  replacement_artifact_hash="sha256:" + "0" * 64))
    write_artifact(meta["run_dir"] / "amendments" / "a-stale.json", amendment, root=ws.root)

    result = validate_run(ws, rid)
    assert _status(result, "ocr_evidence_human_verified") == "failed"
    assert "different version" in result["blocking_errors"][0]["detail"] or any(
        "different version" in e.get("detail", "") for e in result["blocking_errors"])


def test_a_markdown_only_run_still_validates(complete_run):
    """Markdown has an empty page_map and no pages. That is a document without pages, not a
    failure to locate one — the OCR derivation must not block every non-paginated run."""
    ws, rid, _ = complete_run
    result = validate_run(ws, rid)
    assert _status(result, "ocr_evidence_human_verified") in ("not_applicable", "passed")
    assert result["report_eligible"] is True, result["blocking_errors"]
