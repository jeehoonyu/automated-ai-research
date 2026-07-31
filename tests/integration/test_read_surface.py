"""`research status` and `research inspect` — the read surface (GOAL.md Theme 4).

`status` hardcoded `unresolved_contradictions: []` and `superseded_artifacts: []` under the comments
*"populated by validation in Phase 7"* and *"populated by amendments in Phase 6"*. Both phases
shipped; the lists stayed empty, so `status` reported a clean run to anyone who asked.

`inspect` refused evidence, claim and review ids with *"arrives with Phase 6 artifacts"* — the three
classes spec §8.7 most requires, because they are what a reviewer needs in order to check anything.

Nothing here needed a new capability. It needed the commands to answer from the artifacts.
"""

from __future__ import annotations

import json

import pytest

from research.errors import InvalidArguments
from research.hashing import stamp_artifact_hash
from research.runs.inspector import inspect
from research.runs.manager import status

# --------------------------------------------------------------- status answers from artifacts


def test_status_reports_a_real_unresolved_contradiction(complete_run):
    ws, rid, meta = complete_run
    path = meta["claim_path"]
    claim = json.loads(path.read_text(encoding="utf-8"))
    claim["contradiction_status"] = "unresolved"
    path.write_text(json.dumps(stamp_artifact_hash(claim)), encoding="utf-8")

    assert status(ws, rid)["unresolved_contradictions"] == [meta["claim_id"]]


def test_status_distinguishes_unchecked_from_none_found(complete_run):
    """"Nobody looked" and "none found" are different answers, here as everywhere else."""
    ws, rid, meta = complete_run
    path = meta["claim_path"]
    claim = json.loads(path.read_text(encoding="utf-8"))
    claim["contradiction_status"] = "not_checked"
    path.write_text(json.dumps(stamp_artifact_hash(claim)), encoding="utf-8")

    result = status(ws, rid)
    assert result["unchecked_contradictions"] == [meta["claim_id"]]
    assert result["unresolved_contradictions"] == []


def test_status_reports_superseded_artifacts(complete_run):
    ws, rid, meta = complete_run
    path = meta["claim_path"]
    claim = json.loads(path.read_text(encoding="utf-8"))
    claim["supersedes"] = "CLM-00000000-0000-7000-8000-000000000000"
    path.write_text(json.dumps(stamp_artifact_hash(claim)), encoding="utf-8")

    assert status(ws, rid)["superseded_artifacts"] == [
        "CLM-00000000-0000-7000-8000-000000000000"]


def test_a_clean_run_reports_empty_lists_because_it_looked(complete_run):
    """The lists were `[]` before too. The difference is that they are now computed."""
    ws, rid, _ = complete_run
    result = status(ws, rid)
    assert result["unresolved_contradictions"] == []
    assert result["superseded_artifacts"] == []


# --------------------------------------------------------------- inspect resolves run artifacts


def test_inspect_evidence_re_resolves_rather_than_reprinting(complete_run):
    ws, _, meta = complete_run
    out = inspect(ws, meta["evidence_id"])
    assert out["kind"] == "evidence"
    assert out["resolves"] is True
    assert out["text_matches_source"] is True
    assert out["resolved_text"] == out["stored_exact_text"]
    assert meta["claim_id"] in out["referenced_by_claims"]
    assert out["context_before"] or out["context_after"], "context is what makes it verifiable"


def test_inspect_evidence_reports_a_divergence_instead_of_hiding_it(complete_run):
    """An inspector that trusts the artifact it is inspecting cannot detect the failure that
    matters."""
    ws, _, meta = complete_run
    path = meta["evidence_path"]
    ev = json.loads(path.read_text(encoding="utf-8"))
    ev["exact_text"] = "a tidied-up version of the passage"
    path.write_text(json.dumps(stamp_artifact_hash(ev)), encoding="utf-8")

    out = inspect(ws, meta["evidence_id"])
    assert out["text_matches_source"] is False
    assert out["resolved_text"] != out["stored_exact_text"]


def test_inspect_claim_shows_its_evidence_and_its_verdicts(complete_run):
    ws, _, meta = complete_run
    out = inspect(ws, meta["claim_id"])
    assert out["kind"] == "claim"
    assert [e["evidence_id"] for e in out["supporting_evidence"]] == [meta["evidence_id"]]
    assert all(e["present"] for e in out["supporting_evidence"])
    assert any(v["review_type"] == "citation_review" for v in out["review_verdicts"])


def test_inspect_review_shows_what_it_decided(complete_run):
    ws, _, meta = complete_run
    review = json.loads(meta["review_paths"]["independent_review"]
                        .read_text(encoding="utf-8"))
    out = inspect(ws, review["review_id"])
    assert out["kind"] == "review"
    assert out["review_type"] == "independent_review"
    assert out["review_independence"]["status"]


def test_document_derived_text_is_labelled_as_untrusted(complete_run):
    """The security model's trusted/untrusted split existed only as three constants in packets.py
    that never wrapped anything. Every payload carrying imported bytes now says what it is."""
    ws, _, meta = complete_run
    for artifact_id in (meta["evidence_id"], meta["claim_id"]):
        note = inspect(ws, artifact_id)["untrusted_content_note"]
        assert "DATA, never instructions" in note
        assert "prompt injection" in note


def test_an_unknown_prefix_still_refuses_clearly(complete_run):
    ws, _, _ = complete_run
    with pytest.raises(InvalidArguments) as exc:
        inspect(ws, "WAT-12345")
    assert "EVD-sha256-" in str(exc.value.detail["supported_prefixes"])
