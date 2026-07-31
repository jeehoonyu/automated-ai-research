"""The benchmark: does the platform catch what it is supposed to, on data built to fool it?

WHAT THIS TESTS AND WHAT IT DOES NOT. This exercises the DETERMINISTIC contract — import,
deduplication, extraction status, locator resolution, validation, gating. The agent stages are
simulated by pre-authored artifacts, because the host environment (Codex, Claude Code) is not
available inside a test run.

That means spec §37 — *both hosts complete the same benchmark* — is **not** demonstrated here. What
is demonstrated is that the contracts a host must satisfy are enforced. Cross-host conformance
sessions remain an outstanding release gate; see benchmark/README.md.

Each case asserts the SPECIFIC mechanism fires (lessons §6c). A test asserting only
`report_eligible is False` would pass when the wrong gate caught it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "benchmark"))
from build_corpus import build  # noqa: E402

from research.artifacts.io import make_artifact, write_artifact  # noqa: E402
from research.artifacts.registry import validate_artifact  # noqa: E402
from research.config import load_workspace  # noqa: E402
from research.errors import SchemaValidationError  # noqa: E402
from research.extraction.status import ExtractionStatus  # noqa: E402
from research.identifiers import claim_id, evidence_id, review_id  # noqa: E402
from research.importers.importer import import_paths  # noqa: E402
from research.indexing.builder import build_index  # noqa: E402
from research.runs.manager import create_run  # noqa: E402
from research.validation.validator import validate_run  # noqa: E402
from research.workspace import init_workspace  # noqa: E402

CASES = json.loads((REPO / "benchmark" / "expected" / "cases.json").read_text(encoding="utf-8"))


# --------------------------------------------------------------- corpus


@pytest.fixture(scope="module")
def corpus(tmp_path_factory) -> dict[str, Path]:
    return build(tmp_path_factory.mktemp("benchmark-sources"))


@pytest.fixture
def workspace(tmp_path: Path, corpus):
    init_workspace(tmp_path / "ws")
    ws = load_workspace(tmp_path / "ws")
    summary = import_paths(ws, sorted(corpus.values()))
    build_index(ws)
    return ws, summary


def _docs(ws) -> dict[str, dict]:
    out = {}
    for path in (ws.root / "documents" / "manifests").glob("*.json"):
        doc = json.loads(path.read_text(encoding="utf-8"))
        out[doc["original_filename_aliases"][0]] = doc
    return out


def test_the_corpus_is_redistributable_and_synthesized(corpus):
    """No real paper is included, so the benchmark ships under the project's own licence."""
    assert len(corpus) == 9
    for path in corpus.values():
        assert path.is_file() and path.stat().st_size > 0


def test_the_byte_identical_copy_collapses_to_one_document(workspace):
    ws, summary = workspace
    assert summary["duplicate_count"] == 1
    aliases = _docs(ws)
    primary = next(d for name, d in aliases.items() if "primary" in name)
    assert len(primary["original_filename_aliases"]) == 2, \
        "both filenames must be retained as aliases of one document"


def test_the_scanned_page_is_flagged_ocr_required(workspace):
    ws, _ = workspace
    scanned = next(d for name, d in _docs(ws).items() if "scanned" in name)
    assert scanned["ocr_required_pages"], "the image-only page must be flagged"
    assert scanned["extraction_status"] != ExtractionStatus.EXTRACTED


def test_prompt_injection_is_stored_inert_and_changes_nothing(workspace):
    """The corpus contains an instruction telling the system to mark everything verified."""
    ws, _ = workspace
    doc = next(d for name, d in _docs(ws).items() if "injection" in name)
    body = (ws.root / doc["normalized_text_path"]).read_text(encoding="utf-8")
    assert "IGNORE ALL PREVIOUS INSTRUCTIONS" in body, "content is preserved verbatim as data"
    assert doc["links_followed"] is False
    assert doc["created_by"]["actor_type"] == "cli"
    # the injected text must not have altered workspace configuration
    assert ws.get("security.network_enabled") is False
    assert ws.get("security.follow_markdown_links") is False


def test_the_related_survey_is_retrievable_for_the_same_query(workspace):
    """The hard case only exists if the non-supporting source actually competes for the query."""
    from research.search.engine import search

    ws, _ = workspace
    hits = search(ws, "process-in-memory data movement", limit=20)["results"]
    sources = {h["source"]["title"] for h in hits}
    assert any("survey" in str(s) for s in sources), \
        "the related-but-non-supporting document must rank for the query, or B3 proves nothing"


# --------------------------------------------------------------- case harness


def _evidence_from(ws, doc, run_dir, *, page: int | None = None, status: str = "extracted",
                   break_locator: bool = False):
    """Build an Evidence artifact from a real chunk of a real document."""
    chunks = json.loads((ws.root / doc["chunk_set_path"]).read_text(encoding="utf-8"))["chunks"]
    chunk = next((c for c in chunks if page is None or c["page"] == page), chunks[0])
    text = (ws.root / doc["normalized_text_path"]).read_text(encoding="utf-8")
    loc = {
        "type": "text_span", "page": chunk["page"], "section_path": chunk["section_path"],
        "chunk_id": chunk["chunk_id"], "start_offset": chunk["start_offset"],
        "end_offset": chunk["end_offset"], "source_line_start": chunk["line_start"],
        "source_line_end": chunk["line_end"], "span_sha256": chunk["text_sha256"],
    }
    exact = text[loc["start_offset"]:loc["end_offset"]]
    eid = evidence_id(document_version_id_=doc["document_version_id"], locator=loc,
                      exact_text=exact, evidence_type="experimental_result")
    if break_locator:
        loc = {**loc, "start_offset": 900_000, "end_offset": 900_100}
    art = make_artifact(schema_name="Evidence", artifact_id=eid, actor_type="host_agent",
                        body=dict(evidence_id=eid, document_id=doc["document_id"],
                                  document_version_id=doc["document_version_id"],
                                  evidence_type="experimental_result", locator=loc,
                                  exact_text=exact, extraction_status=status,
                                  human_review_required=(status == "ocr_required")))
    write_artifact(run_dir / "evidence" / f"{eid[-12:]}.json", art, root=ws.root, validate=False)
    return eid


def _reviews(ws, run_dir, rid, cid, *, citation_support="passed",
             independence="procedurally_isolated"):
    for rtype, extra in (
        ("contradiction_review", {}),
        ("citation_review", {"per_claim": [{"claim_id": cid, "assessment": "assessed",
                                            "citation_support": citation_support}]}),
        ("methodology_review", {}),
        ("independent_review", {"review_independence": {
            "status": independence, "primary_rationale_excluded": True,
            "primary_confidence_excluded": True, "prior_review_conclusions_excluded": True,
            "fresh_agent_context_requested": True, "host_confirmed_fresh_context": False}}),
    ):
        r = review_id()
        write_artifact(run_dir / "reviews" / f"{rtype}.json",
                       make_artifact(schema_name="Review", artifact_id=r, actor_type="host_agent",
                                     body=dict(review_id=r, review_type=rtype, run_id=rid,
                                               reviewed_artifact_ids=[cid],
                                               reviewer={"actor_type": "host_agent"},
                                               decision="passed", **extra)),
                       root=ws.root)


def _claim(ws, run_dir, rid, cid, **over):
    base = dict(claim_id=cid, claim="The evaluated configuration reduced measured data movement.",
                claim_type="descriptive_result", claim_status="independently_reviewed",
                support_classification="moderately_supported", supporting_evidence_ids=[],
                contradicting_evidence_ids=[], citation_status="passed",
                contradiction_status="none_found",
                independent_review_status="procedurally_isolated",
                human_review_required=False, run_id=rid)
    base.update(over)
    art = make_artifact(schema_name="Claim", artifact_id=cid, actor_type="host_agent", body=base)
    write_artifact(run_dir / "claims" / "c1.json", art, root=ws.root, validate=False)
    return art


def _relationship(ws, run_dir, a, b, kind):
    art = make_artifact(schema_name="SourceRelationship", artifact_id=f"{a[-8:]}-{b[-8:]}",
                        actor_type="host_agent",
                        body=dict(source_document_id=a, related_document_id=b,
                                  relationship_type=kind, confidence="high",
                                  detected_by="metadata_identifier",
                                  evidence_for_relationship="the brief states it summarises the "
                                                            "original study and adds no new data"))
    write_artifact(run_dir / "relationships" / "r1.json", art, root=ws.root)


def _setup(ws, question="Does process-in-memory reduce data movement?"):
    from research.search.engine import record_retrieval, search

    run = create_run(ws, question=question)
    # Record the retrieval, as spec §29 requires and `retrieval_provenance_recorded` now checks.
    # A benchmark case that skips it is not exercising the pipeline it claims to.
    record_retrieval(ws, run["run_id"], search(ws, "process-in-memory data movement", limit=20))
    return run["run_id"], ws.root / "runs" / run["run_id"]


def _check(result, name):
    return next((c["status"] for c in result["checks"] if c["check"] == name), None)


def _case(case_id):
    return next(c for c in CASES["cases"] if c["id"] == case_id)


# --------------------------------------------------------------- the cases


def test_B1_supported_claim_publishes(workspace):
    ws, _ = workspace
    rid, run_dir = _setup(ws)
    docs = _docs(ws)
    primary = next(d for n, d in docs.items() if "primary" in n)
    eid = _evidence_from(ws, primary, run_dir, page=1)
    cid = claim_id()
    _claim(ws, run_dir, rid, cid, supporting_evidence_ids=[eid])
    _reviews(ws, run_dir, rid, cid)

    result = validate_run(ws, rid)
    assert result["report_eligible"] is _case("B1")["expect_report_eligible"], \
        result["blocking_errors"]


@pytest.mark.parametrize("case_id", ["B2", "B3", "B4", "B5", "B6", "B7", "B8"])
def test_each_seeded_defect_is_caught_by_its_own_mechanism(workspace, case_id):
    ws, _ = workspace
    case = _case(case_id)
    rid, run_dir = _setup(ws)
    docs = _docs(ws)
    primary = next(d for n, d in docs.items() if "primary" in n)
    cid = claim_id()

    if case_id == "B2":
        _claim(ws, run_dir, rid, cid, supporting_evidence_ids=[])
        _reviews(ws, run_dir, rid, cid)

    elif case_id == "B3":
        survey = next(d for n, d in docs.items() if "survey" in n)
        eid = _evidence_from(ws, survey, run_dir)
        _claim(ws, run_dir, rid, cid, supporting_evidence_ids=[eid])
        _reviews(ws, run_dir, rid, cid, citation_support="related_not_supporting")

    elif case_id == "B4":
        repl = next(d for n, d in docs.items() if "replication" in n)
        eid = _evidence_from(ws, primary, run_dir, page=1)
        contra = _evidence_from(ws, repl, run_dir, page=1)
        _claim(ws, run_dir, rid, cid, supporting_evidence_ids=[eid],
               contradicting_evidence_ids=[contra], contradiction_status="unresolved")
        _reviews(ws, run_dir, rid, cid)

    elif case_id == "B5":
        brief = next(d for n, d in docs.items() if "brief" in n)
        a = _evidence_from(ws, primary, run_dir, page=1)
        b = _evidence_from(ws, brief, run_dir)
        _claim(ws, run_dir, rid, cid, supporting_evidence_ids=[a, b],
               support_classification="strongly_supported")
        _relationship(ws, run_dir, brief["document_id"], primary["document_id"], "republication")
        _reviews(ws, run_dir, rid, cid)

    elif case_id == "B6":
        weak = next(d for n, d in docs.items() if "preliminary" in n)
        a = _evidence_from(ws, primary, run_dir, page=1)
        b = _evidence_from(ws, weak, run_dir)
        _claim(ws, run_dir, rid, cid, supporting_evidence_ids=[a, b],
               support_classification="strongly_supported")
        _reviews(ws, run_dir, rid, cid)          # NO relationship recorded

    elif case_id == "B7":
        scanned = next(d for n, d in docs.items() if "scanned" in n)
        eid = _evidence_from(ws, scanned, run_dir, status="ocr_required")
        _claim(ws, run_dir, rid, cid, supporting_evidence_ids=[eid])
        _reviews(ws, run_dir, rid, cid)

    elif case_id == "B8":
        eid = _evidence_from(ws, primary, run_dir, page=1, break_locator=True)
        _claim(ws, run_dir, rid, cid, supporting_evidence_ids=[eid])
        _reviews(ws, run_dir, rid, cid)

    result = validate_run(ws, rid)
    assert result["report_eligible"] == case["expect_report_eligible"], case["name"]
    assert _check(result, case["expect_check"]) == case["expect_status"], (
        f"{case_id} ({case['name']}): expected {case['expect_check']} to be "
        f"{case['expect_status']}, got {_check(result, case['expect_check'])}")
    if case.get("expect_human_review"):
        assert result["human_review_required"] is True


def test_B9_insufficient_evidence_is_a_successful_outcome(workspace):
    """Spec §44: the platform must treat this as success, not as a failure of the process."""
    ws, _ = workspace
    rid, run_dir = _setup(ws, question="What is the optimal scheduling quantum for this workload?")
    cid = claim_id()
    _claim(ws, run_dir, rid, cid,
           claim="The available sources do not answer this question.",
           claim_type="insufficient_evidence_finding",
           support_classification="unable_to_determine",
           supporting_evidence_ids=[])
    _reviews(ws, run_dir, rid, cid)

    result = validate_run(ws, rid)
    assert result["report_eligible"] is True, result["blocking_errors"]
    assert result["failed"] == 0


def test_B10_verified_is_refused_for_a_broader_conclusion_at_the_schema_layer(workspace):
    ws, _ = workspace
    rid, run_dir = _setup(ws)
    docs = _docs(ws)
    primary = next(d for n, d in docs.items() if "primary" in n)
    eid = _evidence_from(ws, primary, run_dir, page=1)
    bad = make_artifact(
        schema_name="Claim", artifact_id=claim_id(), actor_type="host_agent",
        body=dict(claim_id=claim_id(), claim="Process-in-memory causes reduced data movement.",
                  claim_type="causal_claim", claim_status="independently_reviewed",
                  support_classification="verified", supporting_evidence_ids=[eid],
                  citation_status="passed", contradiction_status="none_found",
                  human_review_required=False, run_id=rid))
    with pytest.raises(SchemaValidationError):
        validate_artifact(bad)


# --------------------------------------------------------------- coverage of the case table


def test_every_declared_case_has_a_test():
    """The case table is the contract; a case with no test is a coverage claim that is not one."""
    declared = {c["id"] for c in CASES["cases"]}
    exercised = {"B1", "B9", "B10"} | set(
        test_each_seeded_defect_is_caught_by_its_own_mechanism.pytestmark[0].args[1])
    assert declared == exercised, f"uncovered cases: {declared - exercised}"


def test_the_report_for_a_blocked_benchmark_case_refuses_to_publish(workspace):
    """End to end: a seeded defect must stop at the report boundary, not only at validation."""
    from research.errors import ReportGatingError
    from research.reporting.renderer import render_report

    ws, _ = workspace
    rid, run_dir = _setup(ws)
    docs = _docs(ws)
    survey = next(d for n, d in docs.items() if "survey" in n)
    cid = claim_id()
    eid = _evidence_from(ws, survey, run_dir)
    _claim(ws, run_dir, rid, cid, supporting_evidence_ids=[eid])
    _reviews(ws, run_dir, rid, cid, citation_support="related_not_supporting")
    validate_run(ws, rid)

    with pytest.raises(ReportGatingError):
        render_report(ws, rid)
