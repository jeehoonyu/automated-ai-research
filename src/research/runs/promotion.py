"""Stage acceptance — turning a host agent's response into a canonical artifact.

WHAT WAS MISSING. `docs/architecture.md`, `workflow/canonical-workflow.md` and
`validation/validator.py`'s own docstring all state that agents write to `responses/`, that nothing
there is canonical, and that validation promotes a response into `evidence/`, `claims/` or
`reviews/` only after it validates. **Nothing read `runs/<id>/responses/` at all.** Eight of ten
work packets named a `responses/*.json` path as their required output, so a host following the
shipped workflow literally produced files that validation never saw, and `research validate --stage`
— the command every packet names as the one that will judge it — was accepted and ignored.

WHY IMPLEMENT IT RATHER THAN DELETE THE CLAIM. The specification does not require a `responses/`
step, so retracting the docs was an option. Two things argue against it. Candidate-versus-canonical
is a real safety property: a file should not become authoritative because an agent created it. And
since validation began verifying `artifact_hash`, an agent writing straight into `claims/` has to
produce an RFC 8785 canonical digest by hand or its work is rejected as tampering — promotion is
what makes plain JSON usable, because the CLI stamps the hash it validated.

ALL OR NOTHING. If any artifact a stage produced is invalid, nothing from that stage is promoted and
the phase does not advance. A half-promoted stage is a run whose canonical state nobody chose.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..artifacts.io import write_artifact
from ..artifacts.registry import validate_artifact
from ..config import Workspace
from ..errors import InvalidArguments, ResearchError
from ..hashing import stamp_artifact_hash, verify_artifact_hash
from ..security.paths import safe_join
from .lifecycle import Disposition, Phase, Stage, assert_transition
from .manager import load_run, transition

# Where a promoted artifact becomes canonical. `ResearchPlan` is a single file at the run root
# because there is exactly one plan; everything else is a directory of many.
DESTINATION: dict[str, str] = {
    "ResearchPlan": "plan.json",
    "Evidence": "evidence",
    "Claim": "claims",
    "Review": "reviews",
    "ReviewContext": "review-contexts",
    "SourceRelationship": "relationships",
    "Amendment": "amendments",
}

# One stage advances the run by exactly one phase (spec §10).
STAGE_PHASE: dict[Stage, Phase] = {
    Stage.PLANNING: Phase.PLANNED,
    Stage.RETRIEVAL: Phase.RETRIEVED,
    Stage.EVIDENCE_EXTRACTION: Phase.EVIDENCE_EXTRACTED,
    Stage.SYNTHESIS: Phase.SYNTHESIZED,
    Stage.CONTRADICTION_REVIEW: Phase.CONTRADICTION_REVIEWED,
    Stage.CITATION_REVIEW: Phase.CITATION_REVIEWED,
    Stage.METHODOLOGY_REVIEW: Phase.METHODOLOGY_REVIEWED,
    Stage.INDEPENDENT_REVIEW: Phase.INDEPENDENTLY_REVIEWED,
}

_HEX = re.compile(r"^[0-9a-f]+$")


def parse_stage(name: str) -> Stage:
    """An unknown stage name is an error, not a full-run validation wearing a flag.

    `--stage bogus_nonsense` used to produce byte-identical output to no flag at all, which is the
    worst of both: the caller believes it scoped the work and it did not.
    """
    try:
        return Stage(name)
    except ValueError:
        raise InvalidArguments(
            f"unknown stage {name!r}",
            detail={"known": [str(s) for s in Stage]}) from None


def _filename(artifact_id: str) -> str:
    """Short, stable, legible. Two artifacts with the same id promote to the same file, which is
    what re-running a stage should do."""
    parts = artifact_id.split("-")
    prefix = parts[0].lower()
    tail = parts[-1]
    if len(parts) >= 3 and _HEX.match(tail):
        return f"{prefix}-{tail[:16]}.json"
    return f"{prefix}-{'-'.join(parts[1:])[:24]}.json"


def _candidates(ws: Workspace, run_id: str,
                stage: Stage) -> tuple[list[dict[str, Any]], list[str], bool]:
    """Read the stage's declared outputs. Returns (artifacts, problems, declares_schemas)."""
    from .packets import build_packet

    packet = build_packet(run_id=run_id, stage=stage, question="", profile="",
                          workspace_root=str(ws.root))
    declares_schemas = bool(packet["schema_versions"])
    artifacts: list[dict[str, Any]] = []
    problems: list[str] = []
    for relative in packet["required_outputs"]:
        path = ws.root / relative
        if not path.is_file():
            problems.append(f"{relative}: the stage produced no such file")
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{relative}: unreadable ({type(exc).__name__}: {exc})")
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                problems.append(f"{relative}: contains a {type(item).__name__}, not an artifact")
                continue
            item["_source_path"] = relative
            artifacts.append(item)
    return artifacts, problems, declares_schemas


def _assert_promotable(ws: Workspace, run_id: str, stage: Stage) -> bool:
    """Refuse an illegal stage BEFORE anything is written. Returns whether this is a re-promotion.

    THE DEFECT THIS CLOSES. `promote_stage` used to write every canonical artifact and only then
    call `transition`, which is where the state machine lives. Promoting an earlier stage on a run
    that had moved on therefore did all its damage first and refused afterwards: the CLI printed
    "cannot move backwards from retrieved to planned; corrections are recorded as amendments, not
    by rewinding the lifecycle", exited non-zero, left the phase untouched and logged no event —
    while `plan.json` on disk had already been replaced with content nobody approved. Reproduced
    end to end before the fix; a refusal that has already happened is not a refusal.

    The comment above the old `transition` call asserted the opposite — "this cannot rewrite work a
    later stage reviewed" — which is the shape this repository keeps finding: a guarantee stated in
    prose that no code kept. It is now kept here, by asking the same state machine the same
    question, one step earlier.

    Deciding legality BEFORE the write is also the only ordering that can be right. Writing first
    and transitioning second leaves artifacts nobody accepted; transitioning first and writing
    second leaves a phase nothing produced. Only a question with no side effects can be asked first.
    """
    manifest = load_run(ws, run_id)
    from_phase = Phase(manifest["phase"])
    to_phase = STAGE_PHASE[stage]

    # A stage the run is ALREADY at is re-accepted, not transitioned — `transition` skips the state
    # machine when the phase would not change, and re-promoting is how you fix a response you have
    # just accepted and immediately noticed was wrong. Documented at the call site below.
    if to_phase == from_phase:
        return True

    assert_transition(from_phase, to_phase, Disposition(manifest["disposition"]))
    return False


def promote_stage(ws: Workspace, run_id: str, stage: Stage) -> dict[str, Any]:
    """Validate a stage's responses and, if every one is sound, make them canonical.

    The hash is STAMPED when absent and VERIFIED when present. Stamping is the point of promotion —
    the CLI is asserting "I validated this content" — but an artifact that carries a hash which does
    not match its own body was tampered with somewhere, and silently re-stamping it would erase the
    evidence.

    NOTHING IS WRITTEN UNTIL THE LIFECYCLE HAS AGREED. See `_assert_promotable`.
    """
    load_run(ws, run_id)                       # 404s clearly if the run does not exist
    if stage in (Stage.FINAL_VALIDATION, Stage.REPORT):
        raise InvalidArguments(
            f"stage {stage} is performed by the CLI, not by a host agent",
            detail={"hint": f"run `research validate {run_id}` or `research report {run_id}`"})

    # ASKED FIRST, BEFORE ANY FILE IS READ OR WRITTEN. A stage the lifecycle will refuse is refused
    # now, so the refusal cannot arrive after the damage. It also outranks "your response file is
    # missing": fixing a file you were never allowed to promote is a wasted round trip.
    re_promoted = _assert_promotable(ws, run_id, stage)

    run_dir = safe_join(ws.root, "runs", run_id)
    artifacts, problems, declares_schemas = _candidates(ws, run_id, stage)

    # RETRIEVAL declares no schema: its output is the retrieval record, which has no canonical form
    # yet (Theme 5 in GOAL.md). Such a stage is accepted when its file is present and readable, and
    # promotes nothing — stated here rather than silently succeeding as though it had.
    if not declares_schemas:
        # ACCEPTED AND SILENTLY DISCARDED is not an outcome this package may have. A stage with no
        # canonical form ignores its file's contents, so an artifact placed there vanished while
        # the command reported success — and that was the only route anyone could find for an
        # Amendment, which meant a human verification could be "recorded" and never exist.
        # Anything that looks like an artifact is now refused, by name.
        stray = sorted({str(a.get("schema_name")) for a in artifacts if a.get("schema_name")})
        for artifact in artifacts:
            artifact.pop("_source_path", None)
        if stray:
            problems.append(
                f"this stage has no canonical artifact, so it would discard the "
                f"{', '.join(stray)} artifact(s) in its response file. Nothing here is saved — "
                f"use `research amend` for an Amendment, or the stage that owns that artifact.")
        if problems:
            return {"run_id": run_id, "stage": str(stage), "accepted": False,
                    "promoted": [], "problems": problems,
                    "phase": load_run(ws, run_id)["phase"]}
        moved = transition(ws, run_id, to_phase=STAGE_PHASE[stage],
                           triggered_by=f"research validate --stage {stage}",
                           reason="stage response present; this stage has no canonical artifact")
        return {"run_id": run_id, "stage": str(stage), "accepted": True, "promoted": [],
                "problems": [], "phase": moved["phase"],
                "previous_phase": moved["previous_phase"],
                "note": "this stage declares no artifact schema, so nothing was promoted"}

    accepted: list[tuple[dict[str, Any], str]] = []
    for artifact in artifacts:
        source = artifact.pop("_source_path")
        name = artifact.get("schema_name")
        if name not in DESTINATION:
            problems.append(f"{source}: {name!r} is not an artifact this stage can promote "
                            f"(known: {sorted(DESTINATION)})")
            continue
        if artifact.get("artifact_hash") and not verify_artifact_hash(artifact):
            problems.append(f"{source}: {artifact.get('artifact_id')} carries an artifact_hash "
                            f"that does not match its content")
            continue
        stamped = stamp_artifact_hash(artifact)
        try:
            validate_artifact(stamped)
        except ResearchError as exc:
            problems.append(f"{source}: {stamped.get('artifact_id')} — {exc.message}")
            continue
        accepted.append((stamped, source))

    if problems:
        # Nothing is promoted and the phase does not move. A half-accepted stage is a run whose
        # canonical state nobody chose.
        return {"run_id": run_id, "stage": str(stage), "accepted": False,
                "promoted": [], "problems": problems,
                "phase": load_run(ws, run_id)["phase"]}

    promoted: list[str] = []
    for artifact, _ in accepted:
        destination = DESTINATION[artifact["schema_name"]]
        path = (run_dir / destination if destination.endswith(".json")
                else safe_join(run_dir, destination, _filename(artifact["artifact_id"])))
        write_artifact(path, artifact, root=ws.root)
        promoted.append(str(path.relative_to(ws.root)).replace("\\", "/"))

    # RE-ACCEPTING A STAGE THE RUN IS ALREADY AT is allowed, and is now said out loud.
    #
    # `transition` skips the state machine when the phase would not change, so a second
    # `--stage synthesis` on a run already at `synthesized` silently re-ran and re-wrote canonical
    # artifacts. Allowed is the right answer — it is how you fix a response you have just accepted
    # and immediately noticed was wrong — but silence is not: the run's history should show that a
    # stage was accepted twice, and the caller should be told which of the two happened.
    #
    # The window is narrow by construction: `_assert_promotable` has already refused any stage the
    # run has moved past, so this branch can only overwrite artifacts from the phase the run is
    # standing on. A review recorded against those artifacts is caught separately — a Review binds
    # to the hashes it read (`check_reviews_bind_to_bytes`), so an overwrite invalidates it rather
    # than inheriting its approval.
    moved = transition(
        ws, run_id, to_phase=STAGE_PHASE[stage],
        triggered_by=f"research validate --stage {stage}",
        reason=(f"stage re-accepted; {len(promoted)} artifact(s) re-validated and overwritten"
                if re_promoted else f"{len(promoted)} artifact(s) validated and promoted"))

    return {"run_id": run_id, "stage": str(stage), "accepted": True,
            "promoted": promoted, "problems": [], "re_promoted": re_promoted,
            "phase": moved["phase"], "previous_phase": moved["previous_phase"],
            **({"note": "this stage had already been accepted; its artifacts were overwritten. "
                        "Any validation result from before this point is stale."}
               if re_promoted else {})}
