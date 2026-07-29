"""Research profiles — the rules a domain tightens, loaded from YAML rather than hard-coded.

WHAT THIS REPLACES. `research_profiles/*.yaml` shipped in the repository, were documented, were
listed as a completed release task, and **no code read them**. The only profile logic that existed
was one hard-coded set:

    return bool((self.plan or {}).get("high_risk")) or self.profile in {"medicine", "finance"}

So `medicine.yaml` promised `prohibited_confidence`, three methodology requirements and seven human
review triggers, and delivered exactly one thing — a stricter independence bar — that it happened to
agree with by coincidence. That is the docs-outrun-code failure in
`docs/lessons-carried-forward.md` §4, inside the project built to refuse it.

THE RULE THAT KEEPS IT FIXED. Every key in a profile file must be either **honoured** — named in
`HONOURED_KEYS` and actually read below — or **declared unimplemented** in `NOT_IMPLEMENTED`, with
the reason. Loading rejects anything else. A future key that nothing reads therefore fails loudly at
load time instead of quietly meaning nothing, and `tests/unit/test_profiles.py` asserts the shipped
files contain no key outside those two sets.

An unimplemented key is not a lie as long as it says so. A key that silently does nothing is.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .errors import InvalidArguments

PACKAGED_PROFILE_DIR = Path(__file__).resolve().parent / "profiles"

# Independence statuses, weakest to strongest. A profile names its minimum; anything at or above it
# is acceptable.
INDEPENDENCE_ORDER = ("not_independent", "not_confirmed", "procedurally_isolated",
                      "confirmed_independent")

# Human-review triggers the validator can actually detect. A profile may only name these — anything
# else would be a promise no code can keep.
KNOWN_TRIGGERS = {
    "unresolved_contradiction_on_material_claim",
    "citation_failed_or_partial",
    "uncertain_visual_interpretation",
    "evidence_depends_on_ocr_required_page",
    "causal_claim_from_correlational_evidence",
    "source_independence_unestablished",
}

HONOURED_KEYS = {
    "name", "description", "risk", "reviewer_independence", "prohibited_confidence",
    "human_review_triggers",
}

# Keys a shipped profile may carry that nothing reads yet. The value is the reason, which is
# surfaced by `research doctor` and reproduced in docs/validation-rules.md. Adding a key here is a
# deliberate act of saying "we do not do this"; adding one nowhere is a load error.
NOT_IMPLEMENTED: dict[str, str] = {
    "contradiction_review":
        "contradiction review is already required for every profile and already instructed to "
        "search for disagreement, so these keys cannot tighten anything. Kept so a profile that "
        "wanted to LOOSEN them would be visibly rejected rather than silently honoured.",
    "methodology_review":
        "requires judging study design from the source text, which is the host agent's job, not "
        "the CLI's. Making it a real gate needs the methodology review to record a per-item "
        "assessment the validator can check for presence — not yet built.",
    "report_sections":
        "the report template is fixed (reporting/templates/report.md.j2). Profile-driven sections "
        "would let a profile omit `contradictions` or `limitations`, so this stays unread until "
        "there is a rule about which sections may never be dropped.",
    "advisory_human_review_triggers":
        "conditions no code can detect — 'any claim bearing on patient care' requires reading the "
        "claim. Recorded so the intent survives, but nothing fires them. A human applying this "
        "profile should read them; the CLI cannot.",
}


@dataclass(frozen=True)
class Profile:
    """A loaded profile. Every field here is read by something; see the module docstring."""

    name: str
    description: str = ""
    risk: str = "standard"
    minimum_independence: str = "procedurally_isolated"
    disclose_independence_below: str = "confirmed_independent"
    prohibited_confidence: tuple[str, ...] = ()
    human_review_triggers: tuple[str, ...] = ()
    unimplemented: tuple[str, ...] = ()
    source_path: str | None = None
    _raw: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @property
    def high_risk(self) -> bool:
        return self.risk == "high"

    def accepts_independence(self, status: str | None) -> bool:
        if status not in INDEPENDENCE_ORDER:
            return False
        return (INDEPENDENCE_ORDER.index(status)
                >= INDEPENDENCE_ORDER.index(self.minimum_independence))

    def must_disclose_independence(self, status: str | None) -> bool:
        """Acceptable but weaker than ideal — the report has to say so."""
        if status not in INDEPENDENCE_ORDER:
            return True
        return (INDEPENDENCE_ORDER.index(status)
                < INDEPENDENCE_ORDER.index(self.disclose_independence_below))

    def forces_human_review(self, trigger: str) -> bool:
        return trigger in self.human_review_triggers


def _parse(data: dict[str, Any], *, name: str, source: str | None) -> Profile:
    unknown = sorted(set(data) - HONOURED_KEYS - set(NOT_IMPLEMENTED))
    if unknown:
        raise InvalidArguments(
            f"profile {name!r} sets keys that nothing reads: {unknown}",
            detail={"source": source,
                    "honoured": sorted(HONOURED_KEYS),
                    "declared_unimplemented": sorted(NOT_IMPLEMENTED),
                    "hint": "implement the key, or add it to NOT_IMPLEMENTED in "
                            "src/research/profiles.py with the reason it is not honoured. A "
                            "profile key that silently does nothing is the failure this module "
                            "exists to prevent."})

    independence = data.get("reviewer_independence") or {}
    minimum = str(independence.get("minimum", "procedurally_isolated"))
    disclose = str(independence.get("disclose_when_below", "confirmed_independent"))
    for label, value in (("minimum", minimum), ("disclose_when_below", disclose)):
        if value not in INDEPENDENCE_ORDER:
            raise InvalidArguments(
                f"profile {name!r} sets reviewer_independence.{label} to {value!r}",
                detail={"source": source, "allowed": list(INDEPENDENCE_ORDER)})

    triggers = tuple(str(t) for t in (data.get("human_review_triggers") or []))
    undetectable = sorted(set(triggers) - KNOWN_TRIGGERS)
    if undetectable:
        raise InvalidArguments(
            f"profile {name!r} names human-review triggers the validator cannot detect: "
            f"{undetectable}",
            detail={"source": source, "detectable": sorted(KNOWN_TRIGGERS),
                    "hint": "a trigger nothing can fire is a promise, not a rule"})

    return Profile(
        name=str(data.get("name", name)),
        description=str(data.get("description", "")),
        risk=str(data.get("risk", "standard")),
        minimum_independence=minimum,
        disclose_independence_below=disclose,
        prohibited_confidence=tuple(str(c) for c in (data.get("prohibited_confidence") or [])),
        human_review_triggers=triggers,
        unimplemented=tuple(sorted(set(data) & set(NOT_IMPLEMENTED))),
        source_path=source,
        _raw=data,
    )


def profile_search_path(workspace_root: Path | None = None) -> list[Path]:
    """Workspace profiles win over packaged ones, so a workspace can tighten its own rules."""
    paths = []
    if workspace_root is not None:
        paths.append(Path(workspace_root) / "profiles")
    paths.append(PACKAGED_PROFILE_DIR)
    return paths


def known_profiles(workspace_root: Path | None = None) -> list[str]:
    names: list[str] = []
    for directory in profile_search_path(workspace_root):
        if directory.is_dir():
            names.extend(p.stem for p in sorted(directory.glob("*.yaml")))
    return sorted(set(names))


def load_profile(name: str, workspace_root: Path | None = None) -> Profile:
    """Load a profile by name. An unknown name is an error, never a silent fall back to `default`.

    Falling back would mean a run requested under `medicine` quietly validating under the standard
    bar — the run manifest would record `medicine` and the gates applied would be someone else's.
    """
    for directory in profile_search_path(workspace_root):
        path = directory / f"{name}.yaml"
        if not path.is_file():
            continue
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        if not isinstance(data, dict):
            raise InvalidArguments(f"profile {name!r} is not a mapping",
                                   detail={"source": str(path)})
        return _parse(data, name=name, source=str(path))

    raise InvalidArguments(
        f"unknown research profile {name!r}",
        detail={"known": known_profiles(workspace_root),
                "searched": [str(d) for d in profile_search_path(workspace_root)]})
