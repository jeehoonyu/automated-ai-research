"""Run creation, state transitions, status, and artifact inspection.

A run's state lives in `runs/<run-id>/manifest.json`, and every change to it also appends an event
to `runs/<run-id>/events.jsonl`. The manifest answers "where is this run now"; the event log answers
"how did it get here", and the second question is the one an auditor asks.

`research run` does NOT perform reasoning (spec §8.5). It records the question, pins the source
collection, writes the packets, and stops. A stage is complete only when its artifact exists AND
validates — never because a file appeared.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..artifacts.io import append_event, make_artifact, now_rfc3339, read_artifact, write_artifact
from ..config import SCHEMA_VERSION, WORKFLOW_VERSION, Workspace
from ..errors import InvalidArguments, ResearchError
from ..identifiers import run_id as make_run_id
from ..security.paths import safe_join
from .lifecycle import (
    Disposition,
    Phase,
    Stage,
    assert_transition,
    completed_stages,
    current_stage,
    pending_stages,
    transition_event,
)
from .packets import all_packets

RUN_DIRS = ("packets", "responses", "evidence", "claims", "reviews", "review-contexts",
            "validation", "amendments", "relationships", "report")


class RunNotFound(ResearchError):
    category = "run_not_found"


def _run_dir(ws: Workspace, run_id: str) -> Path:
    return safe_join(ws.root, "runs", run_id)


def create_run(ws: Workspace, *, question: str, profile: str | None = None,
               host: str | None = None) -> dict[str, Any]:
    """Initialize a run and write its stage packets."""
    question = question.strip()
    if not question:
        raise InvalidArguments("a research question is required", detail={"question": question})

    profile = profile or str(ws.get("default_profile", "default"))
    rid = make_run_id()
    run_dir = _run_dir(ws, rid)
    for sub in RUN_DIRS:
        safe_join(run_dir, sub).mkdir(parents=True, exist_ok=True)

    # Pin the source collection. A run is answerable against the corpus as it stood when the run
    # started; documents imported later are outside its scope unless the run is re-created.
    documents = []
    for path in sorted(safe_join(ws.root, "documents", "manifests").glob("*.json")):
        doc = read_artifact(path, expect_schema="Document")
        documents.append({
            "document_id": doc["document_id"],
            "document_version_id": doc["document_version_id"],
            "artifact_hash": doc["artifact_hash"],
            "extraction_status": doc["extraction_status"],
        })

    index_hash = None
    manifest_path = ws.root / "indexes" / "index-manifest.json"
    if manifest_path.is_file():
        index_hash = read_artifact(manifest_path, expect_schema="IndexManifest")["index_hash"]

    packets = all_packets(run_id=rid, question=question, profile=profile,
                          workspace_root=str(ws.root))
    packet_paths = []
    for stage, packet in packets.items():
        artifact = make_artifact(schema_name="WorkPacket", artifact_id=packet["packet_id"],
                                 body=packet, actor_type="cli")
        path = safe_join(run_dir, "packets", f"{list(Stage).index(stage):02d}-{stage}.json")
        write_artifact(path, artifact, root=ws.root)
        packet_paths.append(str(path.relative_to(ws.root)).replace("\\", "/"))

    manifest = make_artifact(
        schema_name="RunManifest", artifact_id=rid, actor_type="cli",
        body={
            "run_id": rid,
            "research_question": question,
            "profile": profile,
            "phase": str(Phase.INITIALIZED),
            "disposition": str(Disposition.ACTIVE),
            "workflow_version": WORKFLOW_VERSION,
            "schema_version": SCHEMA_VERSION,
            "config_hash": ws.config_hash,
            "host": host,
            "source_collection": {
                "document_count": len(documents),
                "documents": documents,
                "index_hash": index_hash,
            },
            "packet_paths": packet_paths,
            "started_at": now_rfc3339(),
        })
    write_artifact(safe_join(run_dir, "manifest.json"), manifest, root=ws.root)

    append_event(run_dir / "events.jsonl", transition_event(
        from_phase=Phase.INITIALIZED, to_phase=Phase.INITIALIZED,
        from_disposition=Disposition.ACTIVE, to_disposition=Disposition.ACTIVE,
        triggered_by="research run", reason="run created",
        artifact_hashes=[manifest["artifact_hash"]]), root=ws.root)

    return {
        "run_id": rid,
        "profile": profile,
        "phase": str(Phase.INITIALIZED),
        "disposition": str(Disposition.ACTIVE),
        "source_document_count": len(documents),
        "index_hash": index_hash,
        "packet_count": len(packet_paths),
        "packet_paths": packet_paths,
        "next_stage": str(Stage.PLANNING),
        "run_dir": str(run_dir),
    }


def load_run(ws: Workspace, run_id: str) -> dict[str, Any]:
    path = _run_dir(ws, run_id) / "manifest.json"
    if not path.is_file():
        raise RunNotFound(f"no run {run_id!r} in this workspace",
                          detail={"expected": str(path),
                                  "hint": "run `research run --question ...`"})
    return read_artifact(path, expect_schema="RunManifest")


def transition(ws: Workspace, run_id: str, *, to_phase: Phase | None = None,
               to_disposition: Disposition | None = None, triggered_by: str,
               reason: str, has_human_amendment: bool = False,
               validation_result: str | None = None) -> dict[str, Any]:
    """Change phase and/or disposition, enforcing the state machine and appending an event."""
    manifest = load_run(ws, run_id)
    from_phase = Phase(manifest["phase"])
    from_disposition = Disposition(manifest["disposition"])

    new_phase = to_phase or from_phase
    new_disposition = to_disposition or from_disposition

    if to_phase is not None and to_phase != from_phase:
        assert_transition(from_phase, to_phase, from_disposition,
                          has_human_amendment=has_human_amendment)

    manifest["phase"] = str(new_phase)
    manifest["disposition"] = str(new_disposition)
    manifest["updated_at"] = now_rfc3339()
    from ..hashing import stamp_artifact_hash
    manifest = stamp_artifact_hash(manifest)
    write_artifact(_run_dir(ws, run_id) / "manifest.json", manifest, root=ws.root)

    append_event(_run_dir(ws, run_id) / "events.jsonl", transition_event(
        from_phase=from_phase, to_phase=new_phase,
        from_disposition=from_disposition, to_disposition=new_disposition,
        triggered_by=triggered_by, reason=reason,
        validation_result=validation_result,
        artifact_hashes=[manifest["artifact_hash"]]), root=ws.root)

    return {"run_id": run_id, "phase": str(new_phase), "disposition": str(new_disposition),
            "previous_phase": str(from_phase), "previous_disposition": str(from_disposition)}


def _stage_artifact_present(ws: Workspace, run_id: str, stage: Stage) -> bool:
    """A response file exists for this stage. Presence is NOT completion (spec §28)."""
    run_dir = _run_dir(ws, run_id)
    packet_path = safe_join(run_dir, "packets",
                            f"{list(Stage).index(stage):02d}-{stage}.json")
    if not packet_path.is_file():
        return False
    packet = read_artifact(packet_path, expect_schema="WorkPacket")
    return all((ws.root / rel).exists() for rel in packet["required_outputs"])


def status(ws: Workspace, run_id: str) -> dict[str, Any]:
    """Everything spec §8.6 requires, including what is blocking publication."""
    manifest = load_run(ws, run_id)
    phase = Phase(manifest["phase"])
    disposition = Disposition(manifest["disposition"])

    done = completed_stages(phase)
    pending = pending_stages(phase)
    nxt = current_stage(phase)

    # A response file that exists but has not advanced the phase has not been validated.
    unvalidated = [str(s) for s in pending if _stage_artifact_present(ws, run_id, s)]

    blocking: list[dict[str, str]] = []
    if not disposition.can_advance:
        blocking.append({"category": str(disposition),
                         "message": f"run disposition is {disposition}"})
    for stage in pending:
        if str(stage) in unvalidated:
            blocking.append({
                "category": "awaiting_validation",
                "message": f"{stage}: a response exists but has not passed "
                           f"`research validate {run_id} --stage {stage}`"})
            break

    validation_path = _run_dir(ws, run_id) / "validation" / "validation-result.json"
    report_eligible = phase in {Phase.REPORT_ELIGIBLE, Phase.PUBLISHED}

    return {
        "run_id": run_id,
        "research_question": manifest["research_question"],
        "profile": manifest["profile"],
        "phase": str(phase),
        "disposition": str(disposition),
        "can_advance": disposition.can_advance,
        "completed_stages": [str(s) for s in done],
        "pending_stages": [str(s) for s in pending],
        "next_stage": str(nxt) if nxt else None,
        "next_packet": (f"runs/{run_id}/packets/{list(Stage).index(nxt):02d}-{nxt}.json"
                        if nxt else None),
        "responses_awaiting_validation": unvalidated,
        "human_review_required": disposition is Disposition.HUMAN_REVIEW_REQUIRED,
        "independent_review_status": (
            "completed" if Stage.INDEPENDENT_REVIEW in done else "not_yet_performed"),
        "validation_result_present": validation_path.is_file(),
        "report_eligible": report_eligible,
        "report_eligible_reason": (
            "validation passed and gates cleared" if report_eligible
            else f"run is at {phase}; report eligibility requires reaching "
                 f"{Phase.REPORT_ELIGIBLE}"),
        "blocking": blocking,
        "source_document_count": manifest["source_collection"]["document_count"],
        "index_hash": manifest["source_collection"]["index_hash"],
        "unresolved_contradictions": [],   # populated by validation in Phase 7
        "superseded_artifacts": [],        # populated by amendments in Phase 6
    }


def list_runs(ws: Workspace) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    runs_dir = ws.root / "runs"
    if not runs_dir.is_dir():
        return out
    for path in sorted(runs_dir.glob("*/manifest.json")):
        manifest = read_artifact(path, expect_schema="RunManifest")
        out.append({"run_id": manifest["run_id"], "phase": manifest["phase"],
                    "disposition": manifest["disposition"],
                    "research_question": manifest["research_question"]})
    return out
