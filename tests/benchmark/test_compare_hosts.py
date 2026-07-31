"""The harness that decides gate 38.10 must be able to disagree.

`compare_hosts.py` reduced each host's claims to three INDEPENDENTLY sorted lists — one of claim
types, one of support classifications, one of contradiction statuses. Sorting each field on its own
throws away which value belonged to which claim, so two hosts that swapped verdicts between two
claims compared as identical. And `claim_types` was collected and never compared at all.

A comparison harness that cannot produce a difference reports agreement about everything, which is
the fail-open shape this project keeps finding in itself — here on the check that decides whether
cross-host conformance is met.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "benchmark"))
from compare_hosts import compare  # noqa: E402

SOURCE = REPO / "benchmark" / "expected" / "claude-code"


@pytest.fixture
def two_hosts(tmp_path: Path):
    """Two copies of the same committed run. Identical until deliberately mutated."""
    a, b = tmp_path / "host-a", tmp_path / "host-b"
    shutil.copytree(SOURCE, a)
    shutil.copytree(SOURCE, b)
    return a, b


def _claim_paths(host: Path) -> list[Path]:
    return sorted(host.glob("*/claims/*.json"))


def _mutate(path: Path, **fields) -> None:
    """Edit a claim in place. These copies are comparison INPUT, not artifacts under validation, so
    no hash re-stamping is involved — compare_hosts reads them as plain JSON."""
    data = json.loads(path.read_text(encoding="utf-8"))
    data.update(fields)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_identical_hosts_agree(two_hosts):
    """The control. Without it, a harness that always disagreed would pass every test below."""
    a, b = two_hosts
    diffs, notes = compare(a, b)
    assert not diffs and not notes


def test_a_changed_claim_type_is_detected(two_hosts):
    """`claim_types` was collected into the comparison dict and then never compared."""
    a, b = two_hosts
    _mutate(_claim_paths(b)[0], claim_type="hypothesis")
    diffs, _ = compare(a, b)
    assert diffs, "a claim reclassified as a hypothesis is not the same research outcome"


def test_a_changed_support_classification_is_detected(two_hosts):
    a, b = two_hosts
    _mutate(_claim_paths(b)[0], support_classification="verified")
    diffs, _ = compare(a, b)
    assert diffs


def test_swapped_verdicts_between_two_claims_are_detected(two_hosts):
    """The mutation independently sorted lists could never see.

    After the swap the multiset of verdicts is IDENTICAL — the two hosts differ only in which
    passage carries which conclusion. That is detectable exactly because each verdict is anchored to
    its content-derived evidence ids, which are the one thing stable across hosts (claim ids are
    UUIDs, and spec §37 permits the prose to differ).
    """
    a, b = two_hosts
    for host in (a, b):
        first = _claim_paths(host)[0]
        original = json.loads(first.read_text(encoding="utf-8"))
        evidence_ids = sorted(p.stem for p in first.parent.parent.glob("evidence/*.json"))
        if len(evidence_ids) < 2:
            pytest.skip("this fixture needs two distinct evidence records")

        # Two claims resting on DIFFERENT passages, so the pairing is meaningful.
        _mutate(first, supporting_evidence_ids=[f"EVD-sha256-{'a' * 64}"],
                claim_type="descriptive_result", support_classification="moderately_supported")
        partner = dict(original)
        partner["claim_id"] = "CLM-00000000-0000-7000-8000-00000000000b"
        partner["supporting_evidence_ids"] = [f"EVD-sha256-{'b' * 64}"]
        partner["claim_type"] = "interpretation"
        partner["support_classification"] = "weakly_supported"
        (first.parent / "c2.json").write_text(json.dumps(partner), encoding="utf-8")

    assert not compare(a, b)[0], "sanity: the two hosts match before the swap"

    # Swap the two verdicts in host B only. The multiset of verdicts does not change.
    first_b, second_b = _claim_paths(b)[0], _claim_paths(b)[1]
    _mutate(first_b, claim_type="interpretation", support_classification="weakly_supported")
    _mutate(second_b, claim_type="descriptive_result",
            support_classification="moderately_supported")

    diffs, _ = compare(a, b)
    assert diffs, "swapping verdicts between claims must not read as agreement"


def test_a_differing_claim_count_is_detected(two_hosts):
    a, b = two_hosts
    path = _claim_paths(b)[0]
    extra = json.loads(path.read_text(encoding="utf-8"))
    extra["claim_id"] = "CLM-00000000-0000-7000-8000-00000000000c"
    (path.parent / "c-extra.json").write_text(json.dumps(extra), encoding="utf-8")

    diffs, _ = compare(a, b)
    assert diffs, "one host reaching more conclusions than the other is a difference"


def test_a_missing_host_still_cannot_compare(tmp_path: Path):
    """Unchanged behaviour, re-pinned here: an empty comparison must not read as agreement."""
    a = tmp_path / "a"
    shutil.copytree(SOURCE, a)
    diffs, notes = compare(a, tmp_path / "absent")
    assert notes and not diffs
