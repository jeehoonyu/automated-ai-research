"""Run lifecycle: an enforced state machine, not a string field.

TWO FIELDS, NOT ONE (spec §11). The spec lists twelve *primary* states and six *additional* ones.
Collapsing both into a single field loses information at exactly the wrong moment: a run that has
completed synthesis and is then blocked on human review would have to overwrite `synthesized` with
`human_review_required`, discarding how far it got. When the review resolves, nothing knows where to
resume.

    phase        where the run got to, strictly ordered, only ever advances by one step
    disposition  whether it may currently advance at all

So a blocked run is `phase=synthesized, disposition=human_review_required`. Progress is preserved,
the block is explicit, and resuming is unambiguous.

WHY ADVANCEMENT IS ONE STEP AT A TIME. The spec's invalid-transition examples (`initialized` →
`published`, `retrieved` → `independently_reviewed`) are all skips. Permitting a jump would let a run
reach `published` without the stages in between ever producing an artifact — which is the difference
between a report that passed review and one that merely says it did.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from ..errors import ResearchError


class Phase(StrEnum):
    """Primary lifecycle, in order. Position in this tuple IS the ordering."""

    INITIALIZED = "initialized"
    PLANNED = "planned"
    RETRIEVED = "retrieved"
    EVIDENCE_EXTRACTED = "evidence_extracted"
    SYNTHESIZED = "synthesized"
    CONTRADICTION_REVIEWED = "contradiction_reviewed"
    CITATION_REVIEWED = "citation_reviewed"
    METHODOLOGY_REVIEWED = "methodology_reviewed"
    INDEPENDENTLY_REVIEWED = "independently_reviewed"
    VALIDATION_PASSED = "validation_passed"
    REPORT_ELIGIBLE = "report_eligible"
    PUBLISHED = "published"


class Disposition(StrEnum):
    """Whether the run may advance. Orthogonal to how far it has got."""

    ACTIVE = "active"
    BLOCKED = "blocked"
    REVIEW_PENDING = "review_pending"
    HUMAN_REVIEW_REQUIRED = "human_review_required"
    VALIDATION_FAILED = "validation_failed"
    SUPERSEDED = "superseded"
    CANCELLED = "cancelled"

    @property
    def can_advance(self) -> bool:
        return self is Disposition.ACTIVE

    @property
    def is_terminal(self) -> bool:
        """Superseded and cancelled runs never advance again, by any route."""
        return self in {Disposition.SUPERSEDED, Disposition.CANCELLED}


PHASE_ORDER: tuple[Phase, ...] = tuple(Phase)
_PHASE_INDEX = {phase: i for i, phase in enumerate(PHASE_ORDER)}


class Stage(StrEnum):
    """The canonical workflow (spec §10). One stage advances the run by exactly one phase."""

    PLANNING = "planning"
    RETRIEVAL = "retrieval"
    EVIDENCE_EXTRACTION = "evidence_extraction"
    SYNTHESIS = "synthesis"
    CONTRADICTION_REVIEW = "contradiction_review"
    CITATION_REVIEW = "citation_review"
    METHODOLOGY_REVIEW = "methodology_review"
    INDEPENDENT_REVIEW = "independent_review"
    FINAL_VALIDATION = "final_validation"
    REPORT = "report"


STAGE_ORDER: tuple[Stage, ...] = tuple(Stage)

# Completing a stage moves the run to this phase.
STAGE_COMPLETES_INTO: dict[Stage, Phase] = {
    Stage.PLANNING: Phase.PLANNED,
    Stage.RETRIEVAL: Phase.RETRIEVED,
    Stage.EVIDENCE_EXTRACTION: Phase.EVIDENCE_EXTRACTED,
    Stage.SYNTHESIS: Phase.SYNTHESIZED,
    Stage.CONTRADICTION_REVIEW: Phase.CONTRADICTION_REVIEWED,
    Stage.CITATION_REVIEW: Phase.CITATION_REVIEWED,
    Stage.METHODOLOGY_REVIEW: Phase.METHODOLOGY_REVIEWED,
    Stage.INDEPENDENT_REVIEW: Phase.INDEPENDENTLY_REVIEWED,
    Stage.FINAL_VALIDATION: Phase.VALIDATION_PASSED,
    Stage.REPORT: Phase.PUBLISHED,
}

# A run must be at this phase before the stage may run.
STAGE_REQUIRES_PHASE: dict[Stage, Phase] = {
    stage: PHASE_ORDER[_PHASE_INDEX[STAGE_COMPLETES_INTO[stage]] - 1] for stage in Stage
}
# report is the exception: it runs from report_eligible, not from validation_passed.
STAGE_REQUIRES_PHASE[Stage.REPORT] = Phase.REPORT_ELIGIBLE


class LifecycleError(ResearchError):
    category = "invalid_lifecycle_transition"


def next_phase(phase: Phase) -> Phase | None:
    index = _PHASE_INDEX[phase] + 1
    return PHASE_ORDER[index] if index < len(PHASE_ORDER) else None


def is_valid_transition(
    from_phase: Phase, to_phase: Phase, disposition: Disposition,
    *, has_human_amendment: bool = False,
) -> tuple[bool, str]:
    """Decide whether a phase change is allowed. Returns (allowed, reason)."""
    if disposition.is_terminal:
        return False, f"run disposition is {disposition}; it cannot advance again"

    if to_phase == from_phase:
        return False, "a transition must change the phase"

    if _PHASE_INDEX[to_phase] < _PHASE_INDEX[from_phase]:
        return False, (f"cannot move backwards from {from_phase} to {to_phase}; corrections are "
                       f"recorded as amendments, not by rewinding the lifecycle")

    if _PHASE_INDEX[to_phase] != _PHASE_INDEX[from_phase] + 1:
        skipped = [p for p in PHASE_ORDER
                   if _PHASE_INDEX[from_phase] < _PHASE_INDEX[p] < _PHASE_INDEX[to_phase]]
        return False, (f"cannot skip from {from_phase} to {to_phase}; "
                       f"{len(skipped)} stage(s) in between produced no artifact: "
                       f"{', '.join(skipped)}")

    # `human_review_required` is the one non-active disposition with a documented way forward
    # (spec §11): a recorded human amendment or review artifact. The branches must be exclusive —
    # an earlier version checked the amendment and then fell through to the generic `can_advance`
    # test, which is False for this disposition, making the sanctioned path unreachable.
    if disposition is Disposition.HUMAN_REVIEW_REQUIRED:
        if not has_human_amendment:
            return False, ("human review is required; advancing needs a recorded human amendment "
                           "or review artifact, not a state change")
    elif not disposition.can_advance:
        return False, f"run disposition is {disposition}; resolve it before advancing"

    return True, "ok"


def assert_transition(from_phase: Phase, to_phase: Phase, disposition: Disposition,
                      *, has_human_amendment: bool = False) -> None:
    allowed, reason = is_valid_transition(from_phase, to_phase, disposition,
                                          has_human_amendment=has_human_amendment)
    if not allowed:
        raise LifecycleError(
            f"invalid lifecycle transition {from_phase} -> {to_phase}: {reason}",
            detail={"from_phase": str(from_phase), "to_phase": str(to_phase),
                    "disposition": str(disposition), "reason": reason})


def completed_stages(phase: Phase) -> list[Stage]:
    return [s for s in STAGE_ORDER
            if _PHASE_INDEX[STAGE_COMPLETES_INTO[s]] <= _PHASE_INDEX[phase]]


def pending_stages(phase: Phase) -> list[Stage]:
    return [s for s in STAGE_ORDER
            if _PHASE_INDEX[STAGE_COMPLETES_INTO[s]] > _PHASE_INDEX[phase]]


def current_stage(phase: Phase) -> Stage | None:
    """The stage that should run next."""
    remaining = pending_stages(phase)
    return remaining[0] if remaining else None


def transition_event(
    *, from_phase: Phase, to_phase: Phase, from_disposition: Disposition,
    to_disposition: Disposition, triggered_by: str, reason: str,
    actor_type: str = "cli", artifact_hashes: list[str] | None = None,
    validation_result: str | None = None,
) -> dict[str, Any]:
    """Build the append-only lifecycle event (spec §11).

    Every field the spec requires is present. The event is the audit trail: without the triggering
    command and the artifact hashes, "how did this run reach published?" has no answer.
    """
    return {
        "event": "lifecycle_transition",
        "previous_phase": str(from_phase),
        "new_phase": str(to_phase),
        "previous_disposition": str(from_disposition),
        "new_disposition": str(to_disposition),
        "triggered_by": triggered_by,
        "actor_type": actor_type,
        "validation_result": validation_result,
        "artifact_hashes": artifact_hashes or [],
        "reason": reason,
    }
