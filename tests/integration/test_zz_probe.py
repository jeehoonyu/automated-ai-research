"""Probe: does `report` gate on a ValidationResult bound to the artifacts it validated?"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(r"C:/Users/jeehoon/Code/automated-ai-research/tests")))

from research.artifacts.io import make_artifact, read_artifact, write_artifact  # noqa: E402
from research.identifiers import claim_id  # noqa: E402
from research.reporting.renderer import render_report  # noqa: E402
from research.validation.validator import validate_run  # noqa: E402
from research.hashing import stamp_artifact_hash  # noqa: E402


def test_claim_added_after_validate(complete_run):
    ws, rid, meta = complete_run
    res = validate_run(ws, rid)
    assert res["report_eligible"] is True
    vhash_before = res["validation_result_hash"]

    # A brand-new claim written AFTER validate: no evidence, unchecked citations,
    # strongest classification, and absolutist wording.
    cid = claim_id()
    claim = make_artifact(
        schema_name="Claim", artifact_id=cid, actor_type="host_agent",
        body=dict(claim_id=cid,
                  claim="Process-in-memory conclusively eliminates all data movement.",
                  claim_type="direct_fact", claim_status="independently_reviewed",
                  support_classification="verified",
                  supporting_evidence_ids=[meta["evidence_id"]],
                  contradicting_evidence_ids=[], citation_status="passed",
                  contradiction_status="none_found",
                  independent_review_status="confirmed_independent",
                  human_review_required=False, run_id=rid))
    write_artifact(meta["run_dir"] / "claims" / "c2-smuggled.json", claim, root=ws.root)

    # No re-validation. Publish (non-draft).
    result = render_report(ws, rid)
    body = Path(result.report_path).read_text(encoding="utf-8")
    print("PUBLISHED:", Path(result.report_path).name, "draft=", result.draft)
    print("claim_count:", result.claim_count)
    print("smuggled text present:", "conclusively eliminates all data movement" in body)
    manifest = read_artifact(result.manifest_path, expect_schema="ReportManifest")
    print("manifest claim_ids:", manifest["claim_ids"])
    print("manifest validation_result_hash == pre-edit hash:",
          manifest["validation_result_hash"] == vhash_before)
    print("disclosures:", manifest["disclosures"])
    print("overstatements:", result.overstatements)

    # What does validate say if you DO re-run it?
    res2 = validate_run(ws, rid)
    print("re-validate eligible:", res2["report_eligible"])
    print("re-validate blocking:", [b["check"] for b in res2["blocking_errors"]])


def test_claim_edited_after_validate_rehashed(complete_run):
    ws, rid, meta = complete_run
    assert validate_run(ws, rid)["report_eligible"] is True
    p = meta["run_dir"] / "claims" / "c1.json"
    claim = json.loads(p.read_text(encoding="utf-8"))
    claim["claim"] = "Data movement is always eliminated entirely."
    claim["support_classification"] = "verified"
    p.write_text(json.dumps(stamp_artifact_hash(claim)), encoding="utf-8")

    result = render_report(ws, rid)
    body = Path(result.report_path).read_text(encoding="utf-8")
    print("EDITED-published:", Path(result.report_path).name, "draft=", result.draft)
    print("edited text present:", "always eliminated entirely" in body)


def test_claim_edited_without_rehash(complete_run):
    ws, rid, meta = complete_run
    assert validate_run(ws, rid)["report_eligible"] is True
    p = meta["run_dir"] / "claims" / "c1.json"
    claim = json.loads(p.read_text(encoding="utf-8"))
    claim["claim"] = "Tampered without rehash."
    p.write_text(json.dumps(claim), encoding="utf-8")

    result = render_report(ws, rid)
    body = Path(result.report_path).read_text(encoding="utf-8")
    print("TAMPERED-published:", Path(result.report_path).name, "draft=", result.draft)
    print("claim_count:", result.claim_count)
    print("tampered text present:", "Tampered without rehash" in body)
