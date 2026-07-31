"""Compare two hosts' conformance runs.

Spec §37: *"The expected prose may differ. The required artifacts, references, validation behavior,
and benchmark outcomes must remain equivalent."*

So this compares OUTCOMES, never wording. Two hosts asked the same question of the same corpus
should reach the same verdict, block on the same gates, and cite the same source documents — while
writing entirely different sentences.

    python benchmark/compare_hosts.py benchmark/expected/claude-code benchmark/expected/codex
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def load_runs(host_dir: Path) -> dict[str, dict[str, Any]]:
    """Map run-name -> {verdict fields}. Missing hosts return {} rather than raising."""
    out: dict[str, dict[str, Any]] = {}
    if not host_dir.is_dir():
        return out
    for run in sorted(p for p in host_dir.iterdir() if p.is_dir()):
        vpath = run / "validation" / "validation-result.json"
        if not vpath.is_file():
            continue
        v = json.loads(vpath.read_text(encoding="utf-8"))
        claims = [json.loads(p.read_text(encoding="utf-8"))
                  for p in sorted((run / "claims").glob("*.json"))] \
            if (run / "claims").is_dir() else []
        evidence = [json.loads(p.read_text(encoding="utf-8"))
                    for p in sorted((run / "evidence").glob("*.json"))] \
            if (run / "evidence").is_dir() else []
        out[run.name] = {
            "report_eligible": v["report_eligible"],
            "human_review_required": v["human_review_required"],
            # Which gates failed matters; the wording of their detail does not.
            "failed_checks": sorted(c["check"] for c in v["checks"] if c["status"] == "failed"),
            "not_evaluated_checks": sorted(c["check"] for c in v["checks"]
                                           if c["status"] == "not_evaluated"),
            # PER CLAIM, not three independently sorted lists.
            #
            # Sorting each field on its own threw away which value belonged to which claim, so two
            # hosts that swapped verdicts between two claims compared as identical — and
            # `claim_types` was collected and then never compared at all, so a changed claim type
            # was invisible. This is the harness that decides gate 38.10; it has to be able to
            # disagree.
            #
            # Each verdict is anchored to the EVIDENCE it rests on. Claim ids are UUIDs and differ
            # between hosts, and spec §37 says the prose may differ too — so neither can key the
            # comparison. Evidence ids are content-derived, so two hosts citing the same passage
            # produce the same id, and "did they reach the same verdict about the same passage?" is
            # answerable. Without this anchor, two hosts that swapped verdicts between two claims
            # have an identical multiset of verdicts and compare as agreeing.
            "claim_verdicts": sorted(
                [sorted(c.get("supporting_evidence_ids") or []),
                 c.get("claim_type", ""), c.get("support_classification", ""),
                 c.get("contradiction_status", ""), c.get("citation_status", ""),
                 c.get("independent_review_status", "")]
                for c in claims),
            "claim_count": len(claims),
            # Which SOURCES were cited — not which passages, since chunking may differ if the
            # hosts ran against different configurations.
            "cited_documents": sorted({e["document_id"] for e in evidence}),
        }
    return out


def compare(a_dir: Path, b_dir: Path) -> tuple[list[str], list[str]]:
    """Returns (differences, notes)."""
    a, b = load_runs(a_dir), load_runs(b_dir)
    diffs: list[str] = []
    notes: list[str] = []

    if not a:
        notes.append(f"{a_dir.name}: no conformance runs present")
    if not b:
        notes.append(f"{b_dir.name}: no conformance runs present")
    if not a or not b:
        return diffs, notes

    only_a, only_b = sorted(set(a) - set(b)), sorted(set(b) - set(a))
    if only_a:
        diffs.append(f"{a_dir.name} has runs the other lacks: {only_a}")
    if only_b:
        diffs.append(f"{b_dir.name} has runs the other lacks: {only_b}")

    for run in sorted(set(a) & set(b)):
        for field in ("report_eligible", "human_review_required", "failed_checks",
                      "not_evaluated_checks", "claim_verdicts", "claim_count",
                      "cited_documents"):
            if a[run][field] != b[run][field]:
                diffs.append(f"{run}.{field}: {a_dir.name}={a[run][field]!r} "
                             f"{b_dir.name}={b[run][field]!r}")
    return diffs, notes


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    a, b = Path(sys.argv[1]), Path(sys.argv[2])
    diffs, notes = compare(a, b)

    for note in notes:
        print(f"note: {note}")
    if notes and not diffs:
        print("\nCannot compare: at least one host has not run. Gate 38.10 stays open.")
        return 3
    if diffs:
        print(f"\n{len(diffs)} outcome difference(s):")
        for d in diffs:
            print(f"  - {d}")
        print("\nHosts disagree on outcomes. Prose may differ; verdicts may not.")
        return 1
    print("Hosts agree on every compared outcome. Gate 38.10 satisfied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
