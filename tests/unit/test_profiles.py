"""Profiles must decide something.

`research_profiles/*.yaml` shipped, were documented, were a ticked release task — and no code read
them. `medicine.yaml` promised `prohibited_confidence: [verified]`, three methodology requirements
and seven human-review triggers, and delivered one hard-coded independence bar it happened to agree
with. That is the docs-outrun-code failure in docs/lessons-carried-forward.md §4, inside the project
built to refuse it.

The load-time discipline is what keeps it fixed: every key is either honoured or declared
unimplemented with a reason, and anything else is a loud error. These tests pin that, and they pin
the specific rules the shipped profiles now actually apply.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from research.errors import InvalidArguments
from research.profiles import (
    HONOURED_KEYS,
    KNOWN_TRIGGERS,
    NOT_IMPLEMENTED,
    PACKAGED_PROFILE_DIR,
    Profile,
    known_profiles,
    load_profile,
)

SHIPPED = sorted(PACKAGED_PROFILE_DIR.glob("*.yaml"))


def _write(tmp_path: Path, name: str, body: dict) -> Path:
    root = tmp_path / "ws"
    (root / "profiles").mkdir(parents=True, exist_ok=True)
    path = root / "profiles" / f"{name}.yaml"
    path.write_text(yaml.safe_dump(body), encoding="utf-8")
    return root


# --------------------------------------------------------------- the discipline


@pytest.mark.parametrize("path", SHIPPED, ids=lambda p: p.stem)
def test_every_key_in_a_shipped_profile_is_honoured_or_declared_unimplemented(path: Path):
    """The rule that prevents the original bug from recurring one key at a time."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    stray = sorted(set(data) - HONOURED_KEYS - set(NOT_IMPLEMENTED))
    assert not stray, (
        f"{path.name} sets {stray}, which nothing reads and nothing admits to not reading. "
        f"Implement it, or add it to NOT_IMPLEMENTED with the reason.")


def test_a_key_nothing_reads_is_rejected_at_load_time(tmp_path: Path):
    root = _write(tmp_path, "invented", {"name": "invented", "maximum_claims": 3})
    with pytest.raises(InvalidArguments) as exc:
        load_profile("invented", root)
    assert "maximum_claims" in str(exc.value.detail) or "maximum_claims" in exc.value.message


def test_a_trigger_no_check_can_fire_is_rejected(tmp_path: Path):
    """A profile may not promise review for a condition nothing detects."""
    root = _write(tmp_path, "wishful", {
        "name": "wishful", "human_review_triggers": ["author_seems_biased"]})
    with pytest.raises(InvalidArguments) as exc:
        load_profile("wishful", root)
    assert "author_seems_biased" in exc.value.message


def test_an_unknown_independence_level_is_rejected(tmp_path: Path):
    root = _write(tmp_path, "typo", {
        "name": "typo", "reviewer_independence": {"minimum": "very_independent"}})
    with pytest.raises(InvalidArguments):
        load_profile("typo", root)


def test_an_unknown_profile_is_an_error_not_a_silent_default():
    """Falling back would validate a `medicine` run under the standard bar while its manifest said
    `medicine` — stated rules and applied rules differing is worse than refusing."""
    with pytest.raises(InvalidArguments) as exc:
        load_profile("nonexistent")
    assert "nonexistent" in exc.value.message


def test_declared_unimplemented_keys_are_reported_not_hidden():
    medicine = load_profile("medicine")
    assert "methodology_review" in medicine.unimplemented
    assert NOT_IMPLEMENTED["methodology_review"], "an unimplemented key must carry its reason"


# --------------------------------------------------------------- the rules they now apply


def test_medicine_actually_forbids_verified():
    """This line was in medicine.yaml from the start and did nothing."""
    assert load_profile("medicine").prohibited_confidence == ("verified",)


def test_medicine_is_high_risk_and_default_is_not():
    assert load_profile("medicine").high_risk is True
    assert load_profile("default").high_risk is False


def test_the_independence_bar_comes_from_the_file():
    assert load_profile("medicine").minimum_independence == "confirmed_independent"
    assert load_profile("default").minimum_independence == "procedurally_isolated"


@pytest.mark.parametrize("status,accepted", [
    ("confirmed_independent", True),
    ("procedurally_isolated", False),
    ("not_confirmed", False),
    (None, False),
])
def test_independence_is_compared_by_rank_not_set_membership(status, accepted):
    assert load_profile("medicine").accepts_independence(status) is accepted


def test_both_shipped_profiles_fire_every_detectable_trigger():
    """Routing triggers through the profile made loosening POSSIBLE. It must not have loosened
    anything today — this pins that the shipped behaviour is unchanged."""
    for name in ("default", "medicine"):
        profile = load_profile(name)
        assert set(profile.human_review_triggers) == KNOWN_TRIGGERS, name


def test_a_workspace_profile_overrides_the_packaged_one(tmp_path: Path):
    root = _write(tmp_path, "medicine", {
        "name": "medicine", "risk": "high",
        "reviewer_independence": {"minimum": "procedurally_isolated"}})
    assert load_profile("medicine", root).minimum_independence == "procedurally_isolated"
    assert load_profile("medicine").minimum_independence == "confirmed_independent"


def test_known_profiles_lists_the_shipped_ones():
    assert {"default", "medicine"} <= set(known_profiles())


def test_disclosure_is_required_below_the_profiles_ideal():
    default = load_profile("default")
    assert default.accepts_independence("procedurally_isolated") is True
    assert default.must_disclose_independence("procedurally_isolated") is True
    assert default.must_disclose_independence("confirmed_independent") is False


def test_a_bare_profile_object_is_the_conservative_default():
    """`RunContext.rules` falls back to this when nothing loaded; it must not be permissive."""
    fallback = Profile(name="whatever")
    assert fallback.high_risk is False
    assert fallback.prohibited_confidence == ()
    assert fallback.human_review_triggers == ()
    assert fallback.accepts_independence("procedurally_isolated") is True
