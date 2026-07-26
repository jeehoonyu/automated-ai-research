"""Phase 5: run management, lifecycle enforcement, packets, status, inspect."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fixtures.make_fixtures import build  # noqa: E402

from research.artifacts.io import read_artifact  # noqa: E402
from research.config import load_workspace  # noqa: E402
from research.errors import InvalidArguments  # noqa: E402
from research.importers.importer import import_paths  # noqa: E402
from research.indexing.builder import build_index  # noqa: E402
from research.runs.inspector import inspect  # noqa: E402
from research.runs.lifecycle import (  # noqa: E402
    Disposition,
    LifecycleError,
    Phase,
    Stage,
    completed_stages,
    current_stage,
    is_valid_transition,
    pending_stages,
)
from research.runs.manager import RunNotFound, create_run, load_run, status, transition  # noqa: E402
from research.runs.packets import INDEPENDENCE_EXCLUSIONS  # noqa: E402
from research.workspace import init_workspace  # noqa: E402


@pytest.fixture
def ws(tmp_path: Path):
    sources = build(tmp_path / "sources")
    init_workspace(tmp_path / "ws")
    w = load_workspace(tmp_path / "ws")
    import_paths(w, [sources["text_pdf"], sources["markdown"]])
    build_index(w)
    return w


@pytest.fixture
def run(ws):
    return ws, create_run(ws, question="Does process-in-memory reduce data movement?")


# --------------------------------------------------------------- lifecycle state machine


def test_phases_advance_only_one_step():
    ok, _ = is_valid_transition(Phase.INITIALIZED, Phase.PLANNED, Disposition.ACTIVE)
    assert ok
    ok, reason = is_valid_transition(Phase.INITIALIZED, Phase.PUBLISHED, Disposition.ACTIVE)
    assert not ok and "skip" in reason


@pytest.mark.parametrize("frm,to", [
    (Phase.INITIALIZED, Phase.PUBLISHED),
    (Phase.RETRIEVED, Phase.INDEPENDENTLY_REVIEWED),
    (Phase.SYNTHESIZED, Phase.REPORT_ELIGIBLE),
])
def test_spec_listed_invalid_transitions_are_rejected(frm, to):
    ok, _ = is_valid_transition(frm, to, Disposition.ACTIVE)
    assert not ok


def test_phases_cannot_move_backwards():
    ok, reason = is_valid_transition(Phase.SYNTHESIZED, Phase.PLANNED, Disposition.ACTIVE)
    assert not ok and "backwards" in reason


def test_validation_failed_blocks_advancement():
    ok, reason = is_valid_transition(Phase.VALIDATION_PASSED, Phase.REPORT_ELIGIBLE,
                                     Disposition.VALIDATION_FAILED)
    assert not ok and "validation_failed" in reason


def test_human_review_required_needs_an_amendment_not_a_state_change():
    """Spec §11: human_review_required → report_eligible requires a human amendment."""
    frm, to = Phase.VALIDATION_PASSED, Phase.REPORT_ELIGIBLE
    ok, reason = is_valid_transition(frm, to, Disposition.HUMAN_REVIEW_REQUIRED)
    assert not ok and "amendment" in reason
    ok, _ = is_valid_transition(frm, to, Disposition.HUMAN_REVIEW_REQUIRED,
                                has_human_amendment=True)
    assert ok


@pytest.mark.parametrize("terminal", [Disposition.SUPERSEDED, Disposition.CANCELLED])
def test_terminal_dispositions_never_advance(terminal):
    ok, _ = is_valid_transition(Phase.PLANNED, Phase.RETRIEVED, terminal)
    assert not ok
    # not even with a human amendment
    ok, _ = is_valid_transition(Phase.PLANNED, Phase.RETRIEVED, terminal, has_human_amendment=True)
    assert not ok


def test_phase_and_disposition_are_independent(run):
    """A blocked run keeps its progress: that is why these are two fields, not one."""
    ws, created = run
    rid = created["run_id"]
    transition(ws, rid, to_phase=Phase.PLANNED, triggered_by="test", reason="planning done")
    transition(ws, rid, to_disposition=Disposition.HUMAN_REVIEW_REQUIRED,
               triggered_by="test", reason="ocr evidence needs verification")
    manifest = load_run(ws, rid)
    assert manifest["phase"] == Phase.PLANNED          # progress preserved
    assert manifest["disposition"] == Disposition.HUMAN_REVIEW_REQUIRED


def test_stage_and_phase_helpers_agree():
    assert completed_stages(Phase.INITIALIZED) == []
    assert current_stage(Phase.INITIALIZED) is Stage.PLANNING
    assert Stage.PLANNING in completed_stages(Phase.PLANNED)
    assert current_stage(Phase.PUBLISHED) is None
    assert len(completed_stages(Phase.PUBLISHED)) == len(list(Stage))
    assert pending_stages(Phase.PUBLISHED) == []


def test_illegal_transition_raises_through_the_manager(run):
    ws, created = run
    with pytest.raises(LifecycleError):
        transition(ws, created["run_id"], to_phase=Phase.PUBLISHED,
                   triggered_by="test", reason="attempted skip")


# --------------------------------------------------------------- run creation


def test_run_creates_manifest_packets_and_directories(run):
    ws, created = run
    assert created["packet_count"] == len(list(Stage))
    run_dir = ws.root / "runs" / created["run_id"]
    for sub in ("packets", "responses", "evidence", "claims", "reviews", "validation",
                "amendments", "report"):
        assert (run_dir / sub).is_dir()
    manifest = read_artifact(run_dir / "manifest.json", expect_schema="RunManifest")
    assert manifest["phase"] == Phase.INITIALIZED
    assert manifest["disposition"] == Disposition.ACTIVE


def test_run_pins_the_source_collection(run):
    """A run is answerable against the corpus as it stood when it started."""
    ws, created = run
    manifest = load_run(ws, created["run_id"])
    collection = manifest["source_collection"]
    assert collection["document_count"] == 2
    assert collection["index_hash"]
    for doc in collection["documents"]:
        assert doc["artifact_hash"].startswith("sha256:")


def test_run_ids_are_unique_and_not_timestamps(ws):
    a = create_run(ws, question="q1")["run_id"]
    b = create_run(ws, question="q2")["run_id"]
    assert a != b and a.startswith("RUN-")


def test_run_requires_a_question(ws):
    with pytest.raises(InvalidArguments):
        create_run(ws, question="   ")


def test_run_records_config_hash_for_provenance(run):
    ws, created = run
    assert load_run(ws, created["run_id"])["config_hash"] == ws.config_hash


# --------------------------------------------------------------- work packets


def test_every_stage_has_a_packet_with_the_required_contract_fields(run):
    ws, created = run
    packets = sorted((ws.root / "runs" / created["run_id"] / "packets").glob("*.json"))
    assert len(packets) == len(list(Stage))
    for path in packets:
        packet = read_artifact(path, expect_schema="WorkPacket")
        for field in ("packet_id", "run_id", "stage", "workflow_version", "schema_versions",
                      "allowed_inputs", "excluded_inputs", "required_outputs",
                      "completion_criteria", "failure_conditions", "human_review_triggers",
                      "validation_command"):
            assert field in packet, f"{path.name} is missing {field}"


def test_independent_review_packet_excludes_the_primary_agents_reasoning(run):
    """An 'independent' review that has seen the primary rationale is agreement with extra steps."""
    ws, created = run
    path = next((ws.root / "runs" / created["run_id"] / "packets").glob("*independent_review.json"))
    packet = read_artifact(path, expect_schema="WorkPacket")
    for excluded in INDEPENDENCE_EXCLUSIONS:
        assert excluded in packet["excluded_inputs"]
    assert packet["requires_fresh_context"] is True
    assert "primary_rationale" not in packet["allowed_inputs"]
    assert "primary_confidence" not in packet["allowed_inputs"]


def test_packets_separate_trusted_instructions_from_untrusted_content(run):
    ws, created = run
    for path in (ws.root / "runs" / created["run_id"] / "packets").glob("*.json"):
        packet = read_artifact(path, expect_schema="WorkPacket")
        assert packet["trusted_instructions_header"] == "TRUSTED WORKFLOW INSTRUCTIONS"
        assert packet["untrusted_content_header"] == "UNTRUSTED DOCUMENT CONTENT"
        assert "prompt injection" in packet["untrusted_content_policy"]


def test_packets_state_that_a_file_existing_is_not_completion(run):
    ws, created = run
    packet = read_artifact(
        next((ws.root / "runs" / created["run_id"] / "packets").glob("*planning.json")),
        expect_schema="WorkPacket")
    assert "NOT accepted because the file exists" in packet["acceptance_note"]
    assert "unable_to_determine" in packet["insufficient_evidence_note"]


# --------------------------------------------------------------- events


def test_every_transition_appends_an_event_with_the_required_fields(run):
    ws, created = run
    rid = created["run_id"]
    transition(ws, rid, to_phase=Phase.PLANNED, triggered_by="research validate",
               reason="planning validated", validation_result="passed")
    lines = (ws.root / "runs" / rid / "events.jsonl").read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
    event = json.loads(lines[-1])
    for field in ("previous_phase", "new_phase", "previous_disposition", "new_disposition",
                  "triggered_by", "actor_type", "validation_result", "artifact_hashes", "reason",
                  "recorded_at"):
        assert field in event, f"lifecycle event missing {field}"
    assert event["previous_phase"] == Phase.INITIALIZED
    assert event["new_phase"] == Phase.PLANNED


def test_events_are_append_only(run):
    ws, created = run
    rid = created["run_id"]
    for phase in (Phase.PLANNED, Phase.RETRIEVED, Phase.EVIDENCE_EXTRACTED):
        transition(ws, rid, to_phase=phase, triggered_by="test", reason=f"reached {phase}")
    lines = (ws.root / "runs" / rid / "events.jsonl").read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 4       # creation + 3 transitions; nothing rewritten
    assert json.loads(lines[1])["new_phase"] == Phase.PLANNED


# --------------------------------------------------------------- status


def test_status_reports_progress_and_what_comes_next(run):
    ws, created = run
    s = status(ws, created["run_id"])
    assert s["phase"] == Phase.INITIALIZED
    assert s["completed_stages"] == []
    assert s["next_stage"] == Stage.PLANNING
    assert s["report_eligible"] is False
    assert "00-planning.json" in s["next_packet"]


def test_status_reports_blocking_when_the_run_cannot_advance(run):
    ws, created = run
    transition(ws, created["run_id"], to_disposition=Disposition.HUMAN_REVIEW_REQUIRED,
               triggered_by="test", reason="uncertain figure reading")
    s = status(ws, created["run_id"])
    assert s["can_advance"] is False
    assert s["human_review_required"] is True
    assert any(b["category"] == Disposition.HUMAN_REVIEW_REQUIRED for b in s["blocking"])


def test_a_response_file_alone_does_not_complete_a_stage(run):
    """Spec §28: output is not accepted because the file exists."""
    ws, created = run
    rid = created["run_id"]
    (ws.root / "runs" / rid / "responses").mkdir(parents=True, exist_ok=True)
    (ws.root / "runs" / rid / "responses" / "plan.json").write_text("{}", encoding="utf-8")
    s = status(ws, rid)
    assert s["phase"] == Phase.INITIALIZED, "writing a file must not advance the lifecycle"
    assert Stage.PLANNING not in s["completed_stages"]
    assert "planning" in s["responses_awaiting_validation"]
    assert any(b["category"] == "awaiting_validation" for b in s["blocking"])


def test_status_of_an_unknown_run_is_actionable(ws):
    with pytest.raises(RunNotFound):
        status(ws, "RUN-does-not-exist")


# --------------------------------------------------------------- inspect


def test_inspect_run_shows_state_and_event_history(run):
    ws, created = run
    out = inspect(ws, created["run_id"])
    assert out["kind"] == "run"
    assert out["event_count"] >= 1
    assert out["status"]["next_stage"] == Stage.PLANNING


def test_inspect_document_shows_extraction_reality(run):
    ws, _ = run
    doc_id = load_run(ws, _["run_id"])["source_collection"]["documents"][0]["document_id"]
    out = inspect(ws, doc_id)
    assert out["kind"] == "document"
    assert "extraction_status" in out
    assert "normalization_not_performed" in out


def test_inspect_chunk_reslices_the_source_rather_than_trusting_the_artifact(ws):
    """An inspector that trusts what it is inspecting cannot detect the failure that matters."""
    from research.search.engine import search

    chunk_id = search(ws, "process-in-memory data movement")["results"][0]["chunk_id"]
    out = inspect(ws, chunk_id)
    assert out["kind"] == "chunk"
    assert out["resolves"] is True
    assert out["resolution_status"] == "resolved"
    assert out["resolved_text"]
    assert "not evidence" in out["evidence_note"]


def test_inspect_rejects_an_unknown_id_kind(ws):
    with pytest.raises(InvalidArguments):
        inspect(ws, "WAT-12345")
