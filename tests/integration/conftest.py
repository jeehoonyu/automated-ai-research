"""Shared fixtures for the integration suite.

`complete_run` lives here rather than in test_validation.py because several suites need it.
Importing a fixture across test modules works, but every use then shadows the import — a real
warning about a real hazard, not noise.

IT WALKS THE WORKFLOW. The fixture used to write canonical artifacts straight into `evidence/`,
`claims/` and `reviews/` and leave the run at phase `initialized` forever. That was the only way to
build a run when this was written, because stage acceptance did not exist — but it meant the suite
never exercised the loop the documentation describes, and a run could be "complete" without a single
lifecycle event. It now writes each stage's response and calls `research validate --stage`, which is
what a host is told to do.

The promoted filenames are chosen by the CLI, so `meta` carries the real paths. Tests that want to
seed a defect edit `meta["claim_path"]`, not a name they guessed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fixtures.make_fixtures import build  # noqa: E402

from research.artifacts.io import make_artifact  # noqa: E402
from research.config import load_workspace  # noqa: E402
from research.hashing import stamp_artifact_hash  # noqa: E402
from research.identifiers import claim_id, evidence_id, review_id  # noqa: E402
from research.importers.importer import import_paths  # noqa: E402
from research.indexing.builder import build_index  # noqa: E402
from research.runs.lifecycle import Stage  # noqa: E402
from research.runs.manager import create_run  # noqa: E402
from research.runs.promotion import promote_stage  # noqa: E402
from research.search.engine import record_retrieval, search  # noqa: E402
from research.workspace import init_workspace  # noqa: E402


def _accept(ws, rid, run_dir: Path, stage: Stage, filename: str, payload) -> list[str]:
    """Write a stage response and accept it, the way a host is instructed to."""
    (run_dir / "responses" / filename).write_text(json.dumps(payload), encoding="utf-8")
    result = promote_stage(ws, rid, stage)
    assert result["accepted"], (stage, result["problems"])
    return result["promoted"]


def re_review(meta: dict) -> None:
    """Represent the reviewers reading the claim AGAIN, after it changed.

    Tests that edit a canonical claim in place are seeding a scenario, not simulating tampering —
    but since `reviews_bind_to_reviewed_bytes` exists, an edited claim leaves every review pointing
    at bytes that are gone, and the run correctly stops being publishable. A test whose subject is
    some other check has to say which of the two it means. Calling this says: the reviewers saw
    this version. Not calling it says: they did not, and the run should block.

    Deliberately NOT a fixture and deliberately not automatic. "Make the reviews agree with
    whatever is on disk" is exactly the operation that must never be available outside a test.
    """
    claim = json.loads(meta["claim_path"].read_text(encoding="utf-8"))
    for path in meta["review_paths"].values():
        review = json.loads(path.read_text(encoding="utf-8"))
        review["reviewed_artifact_hashes"] = {
            k: claim["artifact_hash"] for k in review["reviewed_artifact_ids"]}
        path.write_text(json.dumps(stamp_artifact_hash(review)), encoding="utf-8")


@pytest.fixture
def complete_run(tmp_path: Path):
    """A run with a full, valid set of agent artifacts — the only state that should be eligible."""
    sources = build(tmp_path / "sources")
    init_workspace(tmp_path / "ws")
    ws = load_workspace(tmp_path / "ws")
    import_paths(ws, [sources["text_pdf"], sources["markdown"]])
    build_index(ws)
    run = create_run(ws, question="Does process-in-memory reduce data movement?")
    rid = run["run_id"]
    run_dir = ws.root / "runs" / rid

    # Real evidence, built from a real search hit so its locator genuinely resolves — and the
    # search is RECORDED, because retrieval provenance is what spec §29 asks for and a fixture that
    # skips it cannot exercise the check.
    found = search(ws, "process-in-memory data movement")
    record_retrieval(ws, rid, found)
    hit = found["results"][0]
    doc_path = next(p for p in (ws.root / "documents" / "manifests").glob("*.json")
                    if json.loads(p.read_text(encoding="utf-8"))["document_id"]
                    == hit["document_id"])
    doc = json.loads(doc_path.read_text(encoding="utf-8"))
    text = (ws.root / doc["normalized_text_path"]).read_text(encoding="utf-8")
    loc = dict(hit["locator"])
    exact = text[loc["start_offset"]:loc["end_offset"]]

    _accept(ws, rid, run_dir, Stage.PLANNING, "plan.json", {
        "schema_name": "ResearchPlan", "schema_version": "1.0.0",
        "artifact_id": "PLAN-" + rid, "created_at": "2026-07-31T00:00:00Z",
        "created_by": {"actor_type": "host_agent", "host": "test"},
        "run_id": rid, "main_question": "Does process-in-memory reduce data movement?",
        "subquestions": ["what does the primary study measure?"],
        "insufficient_evidence_conditions": ["no source states a figure"]})

    _accept(ws, rid, run_dir, Stage.RETRIEVAL, "retrieval.json",
            {"queries": [found["query"]], "chunk_ids": [r["chunk_id"] for r in found["results"]]})

    eid = evidence_id(document_version_id_=hit["document_version_id"], locator=loc,
                      exact_text=exact, evidence_type="direct_statement")
    evidence_paths = _accept(ws, rid, run_dir, Stage.EVIDENCE_EXTRACTION, "evidence.json",
                             make_artifact(
                                 schema_name="Evidence", artifact_id=eid, actor_type="host_agent",
                                 body=dict(evidence_id=eid, document_id=hit["document_id"],
                                           document_version_id=hit["document_version_id"],
                                           evidence_type="direct_statement", locator=loc,
                                           exact_text=exact, extraction_status="extracted",
                                           human_review_required=False)))

    cid = claim_id()
    claim_paths = _accept(ws, rid, run_dir, Stage.SYNTHESIS, "claims.json", make_artifact(
        schema_name="Claim", artifact_id=cid, actor_type="host_agent",
        body=dict(claim_id=cid, claim="The paper reports reduced data movement.",
                  claim_type="descriptive_result", claim_status="independently_reviewed",
                  support_classification="moderately_supported", supporting_evidence_ids=[eid],
                  contradicting_evidence_ids=[], citation_status="passed",
                  contradiction_status="none_found",
                  independent_review_status="procedurally_isolated",
                  # Spec §23: a categorical classification owes explicit factor ratings.
                  # `not_applicable` here is true of this claim — one text citation, no
                  # contradicting evidence, no figure, no OCR — and `check_confidence_factors`
                  # would refute it if it were not.
                  confidence_factors={"evidence_directness": "high",
                                      "source_quality": "medium",
                                      "citation_validity": "high",
                                      "contradictory_evidence": "not_applicable",
                                      "visual_certainty": "not_applicable",
                                      "ocr_dependency": "not_applicable"},
                  human_review_required=False, run_id=rid)))

    # THE HASH THE REVIEWER READ, taken from the canonical claim as promotion stamped it — not
    # recomputed here. A fixture that computes its own hash would agree with itself even if
    # promotion stamped something else, which is the one disagreement the check exists to catch.
    claim_hash = json.loads(
        (ws.root / claim_paths[0]).read_text(encoding="utf-8"))["artifact_hash"]

    review_paths: dict[str, Path] = {}
    for stage, rtype, filename, extra in (
        (Stage.CONTRADICTION_REVIEW, "contradiction_review", "contradiction-review.json", {}),
        (Stage.CITATION_REVIEW, "citation_review", "citation-review.json",
         {"per_claim": [{"claim_id": cid, "assessment": "supports",
                         "citation_support": "passed"}]}),
        (Stage.METHODOLOGY_REVIEW, "methodology_review", "methodology-review.json", {}),
        (Stage.INDEPENDENT_REVIEW, "independent_review", "independent-review.json",
         {"review_independence": {
             "status": "procedurally_isolated", "primary_rationale_excluded": True,
             "primary_confidence_excluded": True, "prior_review_conclusions_excluded": True,
             "fresh_agent_context_requested": True, "host_confirmed_fresh_context": False}}),
    ):
        rev = review_id()
        promoted = _accept(ws, rid, run_dir, stage, filename, make_artifact(
            schema_name="Review", artifact_id=rev, actor_type="host_agent",
            body=dict(review_id=rev, review_type=rtype, run_id=rid,
                      reviewed_artifact_ids=[cid],
                      reviewed_artifact_hashes={cid: claim_hash},
                      reviewer={"actor_type": "host_agent"},
                      decision="passed", **extra)))
        review_paths[rtype] = ws.root / promoted[0]

    return ws, rid, {
        "claim_id": cid,
        "evidence_id": eid,
        "doc": doc,
        "run_dir": run_dir,
        "evidence_path": ws.root / evidence_paths[0],
        "claim_path": ws.root / claim_paths[0],
        "review_paths": review_paths,
    }
