"""`research amend` — the way forward when a gate says a human has to look.

WHY THIS EXISTS. `docs/release-checklist.md` has said since it was written that `ocr_required`
content *"becomes usable only through a recorded human amendment"*. It was not possible to record
one. No stage's packet declared `Amendment`, so no stage would promote it; putting one in a
schema-less stage's response file returned `accepted: True` and silently discarded it; and once a
run advanced past a stage, that stage could not be re-promoted. A corpus containing a single scanned
page was a dead end — the gate fired correctly and the only sanctioned remedy did not exist.

A platform whose entire value is refusing to publish has to be exact about what to do next. "No"
with no route forward is not rigour, it is an unfinished product.

WHAT THIS CANNOT DO, AND SAYS SO. `human_ocr_verification` and `human_visual_verification` require
`created_by.actor_type == "human"`, and this command writes that. **It cannot verify that a human
ran it.** A script can invoke a CLI. What the record buys is not proof but accountability: the
amendment names an identifier, is hashed, and is bound to the exact version of the artifact that was
checked — so a verification cannot silently outlive the thing it verified. That is the same
distinction the rest of this codebase draws about hashes: an integrity check, never a signature.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..artifacts.io import append_event, make_artifact, now_rfc3339, write_artifact
from ..config import Workspace
from ..errors import InvalidArguments
from ..identifiers import amendment_id
from ..security.paths import safe_join
from .manager import load_run

#: Directories inside a run that hold amendable canonical artifacts, and the id field in each.
AMENDABLE = (
    ("evidence", "evidence_id"),
    ("claims", "claim_id"),
    ("reviews", "review_id"),
    ("relationships", "relationship_id"),
)

#: Amendment types that must be recorded by a human, per the Claim/Amendment schema's own rule.
HUMAN_ONLY_TYPES = frozenset({"human_ocr_verification", "human_visual_verification"})

#: Types that verify an artifact as it stands rather than replacing it. The schema requires every
#: non-withdrawal amendment to name a replacement, so a verification names the target itself —
#: which is also what keeps `research status` from reporting it as superseded.
VERIFICATION_TYPES = frozenset({"human_ocr_verification", "human_visual_verification"})


def find_target(ws: Workspace, run_id: str, artifact_id: str) -> tuple[dict[str, Any], str]:
    """The artifact being amended, and the directory it lives in.

    Read fresh, so `target_artifact_hash` records the version that was actually looked at. An
    amendment pointing at a superseded hash is exactly what `_unverified` treats as stale — a human
    verification must not outlive the artifact it verified.
    """
    run_dir = safe_join(ws.root, "runs", run_id)
    for subdir, id_field in AMENDABLE:
        directory = run_dir / subdir
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.json")):
            try:
                with open(path, encoding="utf-8") as fh:
                    data = json.load(fh)
            except (OSError, json.JSONDecodeError):
                continue
            for item in (data if isinstance(data, list) else [data]):
                if isinstance(item, dict) and item.get(id_field) == artifact_id:
                    return item, subdir
    raise InvalidArguments(
        f"no artifact {artifact_id!r} in run {run_id}",
        detail={"searched": [d for d, _ in AMENDABLE],
                "hint": "amend an artifact this run produced; `research status` lists them"})


def record_amendment(
    ws: Workspace,
    run_id: str,
    *,
    amendment_type: str,
    target_artifact_id: str,
    reason: str,
    human_identifier: str,
    human_role: str | None = None,
    changed_fields: list[str] | None = None,
    replacement_artifact_id: str | None = None,
) -> dict[str, Any]:
    """Write an Amendment against the CURRENT version of its target."""
    load_run(ws, run_id)                        # 404s clearly if the run does not exist
    reason = reason.strip()
    if not reason:
        raise InvalidArguments(
            "an amendment must say why",
            detail={"hint": "the reason is the whole record; a blank one documents nothing"})
    if not human_identifier.strip():
        raise InvalidArguments(
            "an amendment must name who made it",
            detail={"hint": "--by 'name or role'. The schema requires it because a verification "
                            "nobody is named for is not accountability"})

    target, subdir = find_target(ws, run_id, target_artifact_id)
    target_hash = str(target.get("artifact_hash") or "")
    if not target_hash:
        raise InvalidArguments(
            f"{target_artifact_id} carries no artifact_hash, so an amendment cannot be bound to a "
            f"version of it", detail={"artifact": target_artifact_id, "directory": subdir})

    # A verification does not replace its target; the schema still requires a replacement to be
    # named for anything but a withdrawal, so it names the target itself. `research status` treats
    # replacement == target as "not superseded", which is the truth.
    if amendment_type != "withdrawal" and not replacement_artifact_id:
        if amendment_type not in VERIFICATION_TYPES:
            raise InvalidArguments(
                f"{amendment_type} replaces content, so it must name what replaces it",
                detail={"hint": "--replacement <artifact-id>, or use a verification type"})
        replacement_artifact_id = target_artifact_id

    replacement_hash = None
    if replacement_artifact_id:
        if replacement_artifact_id == target_artifact_id:
            replacement_hash = target_hash
        else:
            replacement, _ = find_target(ws, run_id, replacement_artifact_id)
            replacement_hash = str(replacement.get("artifact_hash") or "")

    aid = amendment_id()
    body: dict[str, Any] = {
        "amendment_id": aid,
        "run_id": run_id,
        "target_artifact_id": target_artifact_id,
        "target_artifact_hash": target_hash,
        "amendment_type": amendment_type,
        "changed_fields": changed_fields or (
            ["(verified as recorded; no field changed)"] if amendment_type in VERIFICATION_TYPES
            else ["unspecified"]),
        "reason": reason,
        "human": {"identifier": human_identifier.strip(),
                  **({"role": human_role} if human_role else {})},
        "requires_revalidation": True,
    }
    if replacement_artifact_id:
        body["replacement_artifact_id"] = replacement_artifact_id
        body["replacement_artifact_hash"] = replacement_hash

    # `actor_type: human` because the schema demands it for the verification types and because a
    # person typed this command. The CLI cannot check that, and says so in its output.
    artifact = make_artifact(schema_name="Amendment", artifact_id=aid, body=body,
                             actor_type="human")
    path = safe_join(ws.root, "runs", run_id, "amendments", f"{aid.lower()}.json")
    write_artifact(path, artifact, root=ws.root)

    append_event(safe_join(ws.root, "runs", run_id) / "events.jsonl", {
        "event_type": "amendment_recorded",
        "amendment_id": aid,
        "amendment_type": amendment_type,
        "target_artifact_id": target_artifact_id,
        "target_artifact_hash": target_hash,
        "human": human_identifier.strip(),
        "triggered_by": "research amend",
        "recorded_at": now_rfc3339(),
    }, root=ws.root)

    return {
        "run_id": run_id,
        "amendment_id": aid,
        "amendment_type": amendment_type,
        "target_artifact_id": target_artifact_id,
        "target_artifact_hash": target_hash,
        "target_directory": subdir,
        "replacement_artifact_id": replacement_artifact_id,
        "human": human_identifier.strip(),
        "path": str(Path(path).relative_to(ws.root)).replace("\\", "/"),
        "requires_revalidation": True,
        "attestation_note":
            "Recorded as made by a human. This package cannot verify that one ran the command — "
            "it records the claim, binds it to the exact version of the artifact checked, and "
            "hashes it. That is accountability, not proof.",
    }
