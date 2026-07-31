"""Retrieval provenance (GOAL.md Theme 5, spec §29).

`research search` computed the whole retrieval record and a stable `retrieval_log_hash`, under a
module docstring calling the log "reproducible and auditable" — and then discarded it. Nothing on
disk recorded which queries produced the evidence a run rests on, while reports asserted the search
was reproducible.
"""

from __future__ import annotations

import json

from research.hashing import stamp_artifact_hash
from research.search.engine import record_retrieval, search
from research.validation.validator import validate_run


def _status(result, check):
    return next(c["status"] for c in result["checks"] if c["check"] == check)


def test_a_recorded_search_satisfies_the_check(complete_run):
    ws, rid, _ = complete_run
    result = validate_run(ws, rid)
    assert _status(result, "retrieval_provenance_recorded") == "passed"
    assert result["report_eligible"] is True, result["blocking_errors"]


def test_a_run_with_evidence_and_no_retrieval_record_blocks(complete_run):
    """Not `failed` — `not_evaluated`. Evidence can legitimately arrive through `inspect`, so the
    honest verdict is "how this was found is unknown", which blocks without calling it wrong."""
    ws, rid, meta = complete_run
    for path in (meta["run_dir"] / "retrieval").glob("*.json"):
        path.unlink()

    result = validate_run(ws, rid)
    assert _status(result, "retrieval_provenance_recorded") == "not_evaluated"
    assert result["report_eligible"] is False


def test_a_search_against_a_different_corpus_fails(complete_run):
    """The same words over a different index are a different retrieval, and the point of the record
    is to say what was searched."""
    ws, rid, meta = complete_run
    path = next((meta["run_dir"] / "retrieval").glob("*.json"))
    log = json.loads(path.read_text(encoding="utf-8"))
    log["index_hash"] = "sha256:" + "b" * 64
    path.write_text(json.dumps(stamp_artifact_hash(log)), encoding="utf-8")

    result = validate_run(ws, rid)
    assert _status(result, "retrieval_provenance_recorded") == "failed"
    assert result["report_eligible"] is False


def test_a_run_without_evidence_is_not_applicable(complete_run):
    ws, rid, meta = complete_run
    for path in (meta["run_dir"] / "evidence").glob("*.json"):
        path.unlink()
    for path in (meta["run_dir"] / "retrieval").glob("*.json"):
        path.unlink()

    result = validate_run(ws, rid)
    assert _status(result, "retrieval_provenance_recorded") == "not_applicable"


def test_the_same_search_over_the_same_index_records_the_same_id(complete_run):
    """Content-derived, so re-running a query does not accumulate near-duplicate records."""
    ws, rid, _ = complete_run
    found = search(ws, "process-in-memory data movement")
    first = record_retrieval(ws, rid, found)
    second = record_retrieval(ws, rid, search(ws, "process-in-memory data movement"))
    assert first["retrieval_id"] == second["retrieval_id"]


def test_the_record_names_the_queries_and_the_chunks_they_returned(complete_run):
    ws, rid, meta = complete_run
    log = json.loads(next((meta["run_dir"] / "retrieval").glob("*.json"))
                     .read_text(encoding="utf-8"))
    assert log["query"]
    assert log["query_normalization"]["fts_expression"]
    assert log["result_count"] == len(log["results"])
    assert all(r["chunk_id"].startswith("CHK-sha256-") for r in log["results"])
    assert log["retrieval_log_hash"].startswith("sha256:")


def test_the_report_manifest_names_the_retrieval_hashes(complete_run):
    """The Provenance section asserted a reproducible search while recording nothing about it."""
    from research.artifacts.io import read_artifact
    from research.reporting.renderer import render_report

    ws, rid, _ = complete_run
    validate_run(ws, rid)
    result = render_report(ws, rid)
    manifest = read_artifact(result.manifest_path, expect_schema="ReportManifest")
    assert manifest["retrieval_log_hashes"], "a published report must name what was searched"
