"""Stage acceptance (GOAL.md Theme 3).

`docs/architecture.md`, `workflow/canonical-workflow.md` and `validator.py`'s own docstring all say
agents write to `responses/`, that nothing there is canonical, and that validation promotes a
response only after it validates. **Nothing read `runs/<id>/responses/` at all**, while eight of ten
work packets named a `responses/*.json` path as their required output — so a host that followed the
shipped workflow produced files validation never saw, and `research validate --stage`, the command
every packet names as its judge, was accepted and ignored.

`runs.manager.transition()` had no caller in `src/` either, so the event log held only the creation
event and `is_valid_transition` had never run on a real workspace.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fixtures.make_fixtures import build  # noqa: E402

from research.config import load_workspace  # noqa: E402
from research.errors import InvalidArguments, ResearchError  # noqa: E402
from research.hashing import stamp_artifact_hash  # noqa: E402
from research.importers.importer import import_paths  # noqa: E402
from research.indexing.builder import build_index  # noqa: E402
from research.runs.lifecycle import LifecycleError, Stage  # noqa: E402
from research.runs.manager import create_run, load_run  # noqa: E402
from research.runs.promotion import parse_stage, promote_stage  # noqa: E402
from research.validation.validator import validate_run  # noqa: E402
from research.workspace import init_workspace  # noqa: E402


@pytest.fixture
def fresh_run(tmp_path: Path):
    sources = build(tmp_path / "sources")
    init_workspace(tmp_path / "ws")
    ws = load_workspace(tmp_path / "ws")
    import_paths(ws, [sources["markdown"]])
    build_index(ws)
    rid = create_run(ws, question="does it hold up?")["run_id"]
    return ws, rid, ws.root / "runs" / rid


def _plan(rid: str, **over) -> dict:
    """A plan as a HOST would write it: plain JSON, no artifact_hash.

    That is the point of promotion. Since validation began verifying hashes, an agent writing
    straight into a canonical directory must produce an RFC 8785 digest by hand or have its work
    rejected as tampering.
    """
    body = {
        "schema_name": "ResearchPlan", "schema_version": "1.0.0",
        "artifact_id": "PLAN-" + rid,
        "created_at": "2026-07-31T00:00:00Z",
        "created_by": {"actor_type": "host_agent", "host": "test"},
        "run_id": rid,
        "main_question": "does it hold up?",
        "subquestions": ["what is actually measured?"],
        "insufficient_evidence_conditions": ["no source states a figure"],
    }
    body.update(over)
    return body


def _write_response(run_dir: Path, name: str, payload) -> None:
    (run_dir / "responses" / name).write_text(json.dumps(payload, indent=1), encoding="utf-8")


# --------------------------------------------------------------- acceptance


def test_a_plain_json_response_is_validated_stamped_and_promoted(fresh_run):
    ws, rid, run_dir = fresh_run
    _write_response(run_dir, "plan.json", _plan(rid))

    result = promote_stage(ws, rid, Stage.PLANNING)
    assert result["accepted"] is True
    assert result["previous_phase"] == "initialized" and result["phase"] == "planned"

    promoted = json.loads((run_dir / "plan.json").read_text(encoding="utf-8"))
    assert promoted["artifact_hash"].startswith("sha256:"), "the CLI stamps what it validated"
    assert promoted["main_question"] == "does it hold up?"


def test_an_invalid_response_promotes_nothing_and_does_not_advance(fresh_run):
    """All or nothing. A half-accepted stage is a run whose canonical state nobody chose."""
    ws, rid, run_dir = fresh_run
    _write_response(run_dir, "plan.json", _plan(rid, subquestions="not a list"))

    result = promote_stage(ws, rid, Stage.PLANNING)
    assert result["accepted"] is False
    assert result["problems"]
    assert not (run_dir / "plan.json").exists()
    assert load_run(ws, rid)["phase"] == "initialized"


def test_a_response_carrying_a_wrong_hash_is_refused_not_re_stamped(fresh_run):
    """Stamping an absent hash is promotion. Silently correcting a wrong one would erase the
    evidence that something had already tampered with it."""
    ws, rid, run_dir = fresh_run
    plan = stamp_artifact_hash(_plan(rid))
    plan["main_question"] = "a different question, after stamping"
    _write_response(run_dir, "plan.json", plan)

    result = promote_stage(ws, rid, Stage.PLANNING)
    assert result["accepted"] is False
    assert any("does not match its content" in p for p in result["problems"])


def test_a_missing_response_file_is_reported_not_assumed_absent_on_purpose(fresh_run):
    ws, rid, run_dir = fresh_run
    result = promote_stage(ws, rid, Stage.PLANNING)
    assert result["accepted"] is False
    assert any("no such file" in p for p in result["problems"])


# --------------------------------------------------------------- the flag that was ignored


def test_an_unknown_stage_is_refused():
    """`--stage bogus_nonsense` used to produce byte-identical output to no flag at all."""
    with pytest.raises(InvalidArguments) as exc:
        parse_stage("bogus_nonsense")
    assert "bogus_nonsense" in exc.value.message


@pytest.mark.parametrize("stage", [Stage.FINAL_VALIDATION, Stage.REPORT])
def test_the_cli_performed_stages_refuse_promotion(fresh_run, stage):
    ws, rid, _ = fresh_run
    with pytest.raises(InvalidArguments):
        promote_stage(ws, rid, stage)


def test_every_agent_stage_is_promotable_or_explicitly_not(fresh_run):
    """No stage may be silently unhandled — that is how `--stage` became a no-op in the first
    place.

    Each stage now refuses for the reason that is actually load-bearing. On a fresh run only
    `planning` is reachable, so it is the only one that gets as far as looking for a response file;
    every later stage is refused by the lifecycle first. That ordering matters: telling someone at
    `initialized` that `responses/claims.json` is missing invites them to go write it, and writing
    it cannot help. Naming the skip is the true answer.
    """
    ws, rid, _ = fresh_run
    for stage in Stage:
        if stage in (Stage.FINAL_VALIDATION, Stage.REPORT):
            with pytest.raises(InvalidArguments):
                promote_stage(ws, rid, stage)
        elif stage is Stage.PLANNING:
            # reachable, so it reads the stage's outputs: no response written, report don't crash
            result = promote_stage(ws, rid, stage)
            assert result["accepted"] is False and result["problems"]
        else:
            with pytest.raises(LifecycleError) as exc:
                promote_stage(ws, rid, stage)
            assert "skip" in exc.value.message


# --------------------------------------------------------------- the lifecycle becomes real


def test_stages_cannot_be_skipped(fresh_run):
    """`is_valid_transition` had never been called on a real run. Now it decides."""
    ws, rid, run_dir = fresh_run
    _write_response(run_dir, "plan.json", _plan(rid))
    promote_stage(ws, rid, Stage.PLANNING)
    _write_response(run_dir, "claims.json", [])

    with pytest.raises(ResearchError) as exc:
        promote_stage(ws, rid, Stage.SYNTHESIS)
    assert "skip" in exc.value.message


def test_a_refused_backwards_promotion_does_not_touch_the_canonical_artifact(fresh_run):
    """The refusal used to arrive AFTER the damage.

    `promote_stage` wrote every canonical artifact and only then called `transition`, so promoting
    an earlier stage on a run that had moved on printed "cannot move backwards ... corrections are
    recorded as amendments, not by rewinding the lifecycle", exited non-zero, left the phase alone
    and logged nothing — with `plan.json` already replaced by content nobody approved. Three of the
    four things the operator could see said the promotion had not happened. The file said otherwise,
    and the file is what the report is built from.

    This test fails on the old ordering at the last assertion, which is the only one that ever
    looked at the disk.
    """
    ws, rid, run_dir = fresh_run
    _write_response(run_dir, "plan.json", _plan(rid))
    promote_stage(ws, rid, Stage.PLANNING)
    _write_response(run_dir, "retrieval.json", [])
    promote_stage(ws, rid, Stage.RETRIEVAL)

    canonical = run_dir / "plan.json"
    before = canonical.read_text(encoding="utf-8")
    events_before = (run_dir / "events.jsonl").read_text(encoding="utf-8")

    _write_response(run_dir, "plan.json",
                    _plan(rid, main_question="a question nobody approved"))
    with pytest.raises(LifecycleError) as exc:
        promote_stage(ws, rid, Stage.PLANNING)

    assert "cannot move backwards" in exc.value.message
    assert load_run(ws, rid)["phase"] == "retrieved"
    assert (run_dir / "events.jsonl").read_text(encoding="utf-8") == events_before
    assert canonical.read_text(encoding="utf-8") == before, (
        "the canonical plan was rewritten by a promotion the lifecycle refused")


def test_a_refused_promotion_is_refused_before_the_response_is_even_read(fresh_run):
    """No response file at all, and the refusal still names the real reason.

    Reading first would report `responses/claims.json: the stage produced no such file`, which is
    true and useless: writing that file cannot make a run at `initialized` promotable to
    `synthesized`. A signpost pointing down a closed road is worse than none.
    """
    ws, rid, _ = fresh_run
    with pytest.raises(LifecycleError) as exc:
        promote_stage(ws, rid, Stage.SYNTHESIS)
    assert "skip" in exc.value.message
    assert "no such file" not in exc.value.message


def test_the_event_log_records_the_transition(fresh_run):
    ws, rid, run_dir = fresh_run
    _write_response(run_dir, "plan.json", _plan(rid))
    promote_stage(ws, rid, Stage.PLANNING)

    lines = (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    events = [json.loads(line) for line in lines if line.strip()]
    moves = [(e["previous_phase"], e["new_phase"]) for e in events
             if e.get("event") == "lifecycle_transition"]
    assert ("initialized", "planned") in moves


def test_an_illegal_transition_in_the_log_fails_validation(fresh_run):
    ws, rid, run_dir = fresh_run
    log = run_dir / "events.jsonl"
    log.write_text(log.read_text(encoding="utf-8") + json.dumps({
        "event": "lifecycle_transition", "previous_phase": "initialized",
        "new_phase": "independently_reviewed", "previous_disposition": "active",
        "new_disposition": "active", "actor_type": "cli"}) + "\n", encoding="utf-8")

    result = validate_run(ws, rid)
    status = next(c["status"] for c in result["checks"]
                  if c["check"] == "lifecycle_transitions_valid")
    assert status == "failed"


def test_a_hole_in_the_event_log_fails_validation(complete_run):
    """Every edge legal, the chain broken. This used to pass.

    Each event was judged alone, so deleting the single line recording that a stage was ever
    accepted left a log whose every remaining transition was a legal one-step advance and whose
    last event still matched the manifest. The check reported *"event log replays cleanly"* about
    a history with its middle removed — and the event log's entire job is answering "how did this
    run reach published?".

    The deleted event is deliberately not the last one, so the manifest/log cross-check that
    already existed cannot be what catches it.
    """
    ws, rid, meta = complete_run
    log = meta["run_dir"] / "events.jsonl"
    lines = [ln for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()]
    moves = [i for i, ln in enumerate(lines)
             if json.loads(ln).get("event") == "lifecycle_transition"]
    assert len(moves) >= 4, "this run did not walk enough stages to have a middle"

    dropped = json.loads(lines[moves[2]])
    log.write_text("\n".join(ln for i, ln in enumerate(lines) if i != moves[2]) + "\n",
                   encoding="utf-8")

    result = validate_run(ws, rid)
    status = next(c["status"] for c in result["checks"]
                  if c["check"] == "lifecycle_transitions_valid")
    detail = next(c.get("detail", "") for c in result["checks"]
                  if c["check"] == "lifecycle_transitions_valid")
    assert status == "failed", f"a deleted {dropped['previous_phase']} -> " \
                               f"{dropped['new_phase']} was invisible"
    assert dropped["previous_phase"] in detail, "the failure must name where the chain breaks"


def test_a_log_with_its_beginning_removed_fails(complete_run):
    """The other end of the same hole: truncate the front instead of the middle.

    The TAIL is kept deliberately, so the log still ends where the manifest says the run is. The
    pre-existing manifest/log cross-check therefore cannot be what fails — only the rule that a
    replay has to start at `initialized` can. A first draft of this test used a fresh run and a
    single invented event, which failed on the phase mismatch instead; deleting the start check
    left it green, and mutation is what showed that.
    """
    ws, rid, meta = complete_run
    log = meta["run_dir"] / "events.jsonl"
    lines = [ln for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()]
    moves = [i for i, ln in enumerate(lines)
             if json.loads(ln).get("event") == "lifecycle_transition"]
    log.write_text("\n".join(lines[moves[3]:]) + "\n", encoding="utf-8")

    result = validate_run(ws, rid)
    status = next(c["status"] for c in result["checks"]
                  if c["check"] == "lifecycle_transitions_valid")
    detail = next(c.get("detail", "") for c in result["checks"]
                  if c["check"] == "lifecycle_transitions_valid")
    assert status == "failed"
    assert "first transition" in detail, detail


def test_a_manifest_phase_the_log_does_not_support_fails(fresh_run):
    """`phase` is a field. A manifest claiming `published` above a one-line log used to pass."""
    ws, rid, run_dir = fresh_run
    path = run_dir / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["phase"] = "published"
    path.write_text(json.dumps(stamp_artifact_hash(manifest)), encoding="utf-8")

    result = validate_run(ws, rid)
    status = next(c["status"] for c in result["checks"]
                  if c["check"] == "lifecycle_transitions_valid")
    assert status == "failed"


# --------------------------------------------------- a stage may not accept and silently discard


def test_a_stage_with_no_canonical_form_refuses_artifacts_instead_of_dropping_them(fresh_run):
    """`retrieval` has no canonical artifact, so it ignored its file's contents — and returned
    `accepted: True`. That was the only route anyone could find for an `Amendment`, which meant a
    human verification could be "recorded" and simply not exist. Accepted-and-discarded is not an
    outcome this package may have.
    """
    from research.artifacts.io import make_artifact
    from research.identifiers import amendment_id

    ws, rid, run_dir = fresh_run
    (run_dir / "responses" / "plan.json").write_text(json.dumps(_plan(rid)), encoding="utf-8")
    assert promote_stage(ws, rid, Stage.PLANNING)["accepted"]

    aid = amendment_id()
    (run_dir / "responses" / "retrieval.json").write_text(json.dumps(make_artifact(
        schema_name="Amendment", artifact_id=aid, actor_type="human",
        body=dict(amendment_id=aid, run_id=rid, amendment_type="human_ocr_verification",
                  target_artifact_id="EVD-sha256-" + "0" * 64,
                  target_artifact_hash="sha256:" + "0" * 64,
                  changed_fields=["x"], reason="r", human={"identifier": "someone"},
                  requires_revalidation=True))), encoding="utf-8")

    result = promote_stage(ws, rid, Stage.RETRIEVAL)
    assert result["accepted"] is False
    assert any("discard" in p for p in result["problems"]), result["problems"]
    assert any("research amend" in p for p in result["problems"]), \
        "the refusal must say where the artifact should go instead"


def test_a_schemaless_stage_still_accepts_its_ordinary_response(fresh_run):
    """The refusal above must not break the stage. A retrieval record is not an artifact."""
    ws, rid, run_dir = fresh_run
    (run_dir / "responses" / "plan.json").write_text(json.dumps(_plan(rid)), encoding="utf-8")
    promote_stage(ws, rid, Stage.PLANNING)
    (run_dir / "responses" / "retrieval.json").write_text(
        json.dumps({"queries": ["memory"], "chunk_ids": []}), encoding="utf-8")

    assert promote_stage(ws, rid, Stage.RETRIEVAL)["accepted"] is True


# ------------------------------------------------------------------- re-accepting a stage is said


def test_re_accepting_a_stage_is_allowed_and_reported(fresh_run):
    """`transition` skips the state machine when the phase would not change, so a second
    `--stage planning` silently re-ran and overwrote canonical artifacts. Allowed is right — it is
    how you fix a response you just accepted — but silence is not."""
    ws, rid, run_dir = fresh_run
    (run_dir / "responses" / "plan.json").write_text(json.dumps(_plan(rid)), encoding="utf-8")

    first = promote_stage(ws, rid, Stage.PLANNING)
    assert first["accepted"] and first["re_promoted"] is False

    second = promote_stage(ws, rid, Stage.PLANNING)
    assert second["accepted"] and second["re_promoted"] is True
    assert "stale" in second["note"]

    events = [json.loads(line) for line in
              (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    assert any("re-accepted" in str(e.get("reason", "")) for e in events), \
        "the run's history must show the stage was accepted twice"


def test_a_stage_cannot_be_re_accepted_once_the_run_has_moved_on(fresh_run):
    """The window is narrow by construction: promoting an earlier stage would move backwards, and
    the lifecycle refuses that — so re-acceptance can never rewrite work a later stage reviewed."""
    ws, rid, run_dir = fresh_run
    (run_dir / "responses" / "plan.json").write_text(json.dumps(_plan(rid)), encoding="utf-8")
    promote_stage(ws, rid, Stage.PLANNING)
    (run_dir / "responses" / "retrieval.json").write_text(
        json.dumps({"queries": ["m"], "chunk_ids": []}), encoding="utf-8")
    promote_stage(ws, rid, Stage.RETRIEVAL)

    with pytest.raises(ResearchError) as exc:
        promote_stage(ws, rid, Stage.PLANNING)
    assert "backwards" in str(exc.value.message) or "backwards" in str(exc.value.detail)


# ------------------------------------------------------------------------ source relationships


def test_the_synthesis_packet_declares_source_relationships(fresh_run):
    """`check_source_independence` blocks a `strongly_supported` claim until relationships are
    assessed. Bundling one into claims.json always worked; nothing said so, and a route nobody can
    discover is not a route."""
    from research.runs.packets import build_packet

    ws, rid, _run_dir = fresh_run
    packet = build_packet(run_id=rid, stage=Stage.SYNTHESIS, question="q", profile="default",
                          workspace_root=str(ws.root))
    assert "SourceRelationship" in packet["schema_versions"]
    assert any("SourceRelationship" in c for c in packet["completion_criteria"]), \
        "the packet must tell the agent when to produce one"


def test_a_relationship_id_is_content_derived_and_order_independent():
    """"A duplicates B" and "B duplicates A" are one fact. Two ids would let the same assessment be
    recorded twice and counted as two. There was no factory at all, and no pattern in the schema."""
    from research.identifiers import relationship_id

    a, b = "DOC-sha256-" + "1" * 64, "DOC-sha256-" + "2" * 64
    forward = relationship_id(source_document_id=a, related_document_id=b,
                              relationship_type="duplicate")
    backward = relationship_id(source_document_id=b, related_document_id=a,
                               relationship_type="duplicate")
    assert forward == backward
    assert forward.startswith("REL-sha256-")
    assert forward != relationship_id(source_document_id=a, related_document_id=b,
                                      relationship_type="independent")
