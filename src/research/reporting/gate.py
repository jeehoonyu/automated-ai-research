"""The gate every published view of a run must pass.

WHY THIS IS ITS OWN MODULE. It was forty-five lines inline in `render_report`, and `research export`
needs exactly the same decision: may this run leave the tool as a finished thing, or only as a
clearly-marked draft? Copying it would have created a second answer to one question — the same
mistake as two hosts with two sets of rules, which is why this repository has no host-specific
logic. A CSV that a report would have refused to publish is still a published claim; it just does
not look like one.

The gate asks four things in order, and the order matters:

    1. has this run been validated at all?
    2. did the validation clear every gate?
    3. are the artifacts on disk the artifacts that verdict was computed over?
    4. can they all still be loaded?

Three and four are the ones that are easy to leave out. `report_eligible` is a boolean read from a
file, while everything downstream re-reads `claims/` and `evidence/` from disk — so a claim written
after `research validate` was once published having never been validated, and one deleted afterwards
vanished from a report that still asserted it rested on that evidence.

A DRAFT IS EXEMPT, deliberately and only because it is marked. It is a picture of the run as it
stands, its filename says so, and its first line says so. Exempting it from the byte-comparison is
what makes `--draft` useful while the run is still being worked on.
"""

from __future__ import annotations

from typing import Any, NamedTuple

from ..artifacts.io import read_artifact
from ..config import Workspace
from ..errors import ReportGatingError
from ..security.paths import safe_join
from ..validation.validator import (
    RunContext,
    build_context,
    compare_inputs,
    validated_inputs,
)


class GateResult(NamedTuple):
    ctx: RunContext
    validation: dict[str, Any] | None
    blocking: list[dict[str, Any]]
    eligible: bool


def open_for_output(ws: Workspace, run_id: str, *, draft: bool, command: str) -> GateResult:
    """Load a run for rendering, refusing unless it may be published — or unless `draft`.

    `command` only shapes the hint. It is passed rather than hard-coded so that
    `research export` does not tell someone to run `research report --draft`, which would be a
    command that does not produce what they asked for.
    """
    ctx = build_context(ws, run_id)
    run_dir = safe_join(ws.root, "runs", run_id)

    validation_path = run_dir / "validation" / "validation-result.json"
    validation: dict[str, Any] | None = None
    if validation_path.is_file():
        validation = read_artifact(validation_path, expect_schema="ValidationResult")

    if validation is None:
        if not draft:
            raise ReportGatingError(
                "this run has not been validated; publication requires a validation result",
                detail={"hint": f"run `research validate {run_id}` first, "
                                f"or `research {command} {run_id} --draft`"})
        return GateResult(ctx, None,
                          [{"check": "validation", "status": "not_evaluated",
                            "detail": "the run has never been validated"}], False)

    blocking = list(validation.get("blocking_errors", []))
    eligible = bool(validation.get("report_eligible"))

    if not eligible and not draft:
        raise ReportGatingError(
            f"publication is blocked by {len(blocking)} gate(s); refusing to generate a report",
            detail={
                "run_id": run_id,
                "blocking": [{"check": b["check"], "status": b["status"],
                              "detail": b.get("detail", "")} for b in blocking],
                "hint": f"fix the blocking artifacts, or use `research {command} {run_id} --draft` "
                        f"for a clearly-marked draft",
            })

    if not draft:
        differences = compare_inputs(validation.get("validated_inputs"), validated_inputs(ctx))
        if differences:
            raise ReportGatingError(
                "the artifacts on disk are not the artifacts that were validated; refusing to "
                "publish a verdict that was computed over something else",
                detail={
                    "run_id": run_id,
                    "differences": differences[:20],
                    "hint": f"re-run `research validate {run_id}`, or use --draft",
                })
        if ctx.load_errors:
            raise ReportGatingError(
                f"{len(ctx.load_errors)} artifact(s) could not be loaded now, so the output would "
                f"silently omit them",
                detail={"run_id": run_id, "load_errors": ctx.load_errors[:10],
                        "hint": f"re-run `research validate {run_id}`, or use --draft"})

    return GateResult(ctx, validation, blocking, eligible)
