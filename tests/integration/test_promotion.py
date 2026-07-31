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
from research.runs.lifecycle import Stage  # noqa: E402
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
    place."""
    ws, rid, _ = fresh_run
    for stage in Stage:
        if stage in (Stage.FINAL_VALIDATION, Stage.REPORT):
            with pytest.raises(InvalidArguments):
                promote_stage(ws, rid, stage)
        else:
            # no responses written: it must report, not crash
            result = promote_stage(ws, rid, stage)
            assert result["accepted"] is False and result["problems"]


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
