"""Shared fixtures for the integration suite.

`complete_run` lives here rather than in test_validation.py because two suites need it. Importing a
fixture across test modules works, but every use then shadows the import — which is a real warning
about a real hazard, not noise: the name is both a module-level symbol and a parameter. A conftest
is where pytest expects shared fixtures, and it makes `ruff check tests` clean.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fixtures.make_fixtures import build  # noqa: E402

from research.artifacts.io import make_artifact, write_artifact  # noqa: E402
from research.config import load_workspace  # noqa: E402
from research.identifiers import claim_id, evidence_id, review_id  # noqa: E402
from research.importers.importer import import_paths  # noqa: E402
from research.indexing.builder import build_index  # noqa: E402
from research.runs.manager import create_run  # noqa: E402
from research.search.engine import record_retrieval, search  # noqa: E402
from research.workspace import init_workspace  # noqa: E402


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

    eid = evidence_id(document_version_id_=hit["document_version_id"], locator=loc,
                      exact_text=exact, evidence_type="direct_statement")
    evidence = make_artifact(
        schema_name="Evidence", artifact_id=eid, actor_type="host_agent",
        body=dict(evidence_id=eid, document_id=hit["document_id"],
                  document_version_id=hit["document_version_id"],
                  evidence_type="direct_statement", locator=loc, exact_text=exact,
                  extraction_status="extracted", human_review_required=False))
    write_artifact(run_dir / "evidence" / "e1.json", evidence, root=ws.root)

    cid = claim_id()
    claim = make_artifact(
        schema_name="Claim", artifact_id=cid, actor_type="host_agent",
        body=dict(claim_id=cid, claim="The paper reports reduced data movement.",
                  claim_type="descriptive_result", claim_status="independently_reviewed",
                  support_classification="moderately_supported", supporting_evidence_ids=[eid],
                  contradicting_evidence_ids=[], citation_status="passed",
                  contradiction_status="none_found",
                  independent_review_status="procedurally_isolated",
                  human_review_required=False, run_id=rid))
    write_artifact(run_dir / "claims" / "c1.json", claim, root=ws.root)

    for rtype, extra in (
        ("contradiction_review", {}),
        ("citation_review", {"per_claim": [{"claim_id": cid, "assessment": "supports",
                                            "citation_support": "passed"}]}),
        ("methodology_review", {}),
        ("independent_review", {"review_independence": {
            "status": "procedurally_isolated", "primary_rationale_excluded": True,
            "primary_confidence_excluded": True, "prior_review_conclusions_excluded": True,
            "fresh_agent_context_requested": True, "host_confirmed_fresh_context": False}}),
    ):
        rid_ = review_id()
        review = make_artifact(
            schema_name="Review", artifact_id=rid_, actor_type="host_agent",
            body=dict(review_id=rid_, review_type=rtype, run_id=rid,
                      reviewed_artifact_ids=[cid], reviewer={"actor_type": "host_agent"},
                      decision="passed", **extra))
        write_artifact(run_dir / "reviews" / f"{rtype}.json", review, root=ws.root)

    return ws, rid, {"claim_id": cid, "evidence_id": eid, "doc": doc, "run_dir": run_dir}
