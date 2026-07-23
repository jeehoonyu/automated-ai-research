from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from research.canonical import canonical_sha256
from research.errors import ResearchError
from research.io import iter_json, read_json, write_json_atomic
from research.reporting import generate_report
from research.runs import run_status
from research.validation import validate_run

HOSTS = ("codex", "claude-code")
SEEDED_CONTRADICTION = "no statistically reliable reduction"


def check_conformance_pair(output_root: Path) -> dict[str, Any]:
    output_root = output_root.expanduser().resolve()
    preparation = read_json(output_root / "conformance-preparation.json")
    preparation_hash = str(preparation.get("preparation_hash", ""))
    unhashed = dict(preparation)
    unhashed.pop("preparation_hash", None)
    if preparation_hash != canonical_sha256(unhashed):
        raise ValueError("Conformance preparation manifest hash does not match")

    host_results: dict[str, dict[str, Any]] = {}
    all_passed = True
    for host in HOSTS:
        host_contract = preparation.get("hosts", {}).get(host)
        if not isinstance(host_contract, dict):
            raise ValueError(f"Preparation manifest is missing host {host}")
        workspace = Path(str(host_contract.get("workspace", ""))).resolve()
        try:
            workspace.relative_to(output_root)
        except ValueError as exc:
            raise ValueError(f"Host workspace is outside conformance root: {workspace}") from exc
        cases: dict[str, dict[str, Any]] = {}
        for case, run_contract in sorted(host_contract.get("runs", {}).items()):
            expected = str(run_contract["expected_outcome"])
            run_id = str(run_contract["run_id"])
            case_result = _check_run(workspace, run_id, expected)
            cases[str(case)] = case_result
            all_passed = all_passed and bool(case_result["passed"])
        expected_cases = set(preparation.get("questions", {}))
        if set(cases) != expected_cases:
            all_passed = False
        host_results[host] = {
            "workspace": str(workspace),
            "cases": cases,
            "passed": bool(cases) and all(item["passed"] for item in cases.values()),
        }

    result = {
        "check_version": "1.0.0",
        "preparation_hash": preparation_hash,
        "passed": all_passed,
        "hosts": host_results,
    }
    result["check_hash"] = canonical_sha256(result)
    write_json_atomic(output_root / "conformance-check.json", result, root=output_root)
    return result


def _check_run(workspace: Path, run_id: str, expected: str) -> dict[str, Any]:
    try:
        validation, exit_code = validate_run(workspace, run_id)
        status = run_status(workspace, run_id)
    except (ResearchError, OSError, ValueError) as exc:
        return {
            "run_id": run_id,
            "expected_outcome": expected,
            "passed": False,
            "failure": f"{type(exc).__name__}: {exc}",
        }

    run_dir = workspace / "runs" / run_id
    claims = _latest_claims(run_dir)
    classifications = sorted(
        {str(item.get("support_classification", "missing")) for item in claims.values()}
    )
    outcome_observed = expected in classifications
    contradiction_linked = True
    if expected == "conflicting_evidence":
        contradiction_linked = _seeded_contradiction_is_linked(run_dir, claims)
    report: dict[str, Any] | None = None
    report_failure: str | None = None
    if exit_code == 0 and validation.get("report_eligible") is True:
        try:
            report = generate_report(workspace, run_id)
        except ResearchError as exc:
            report_failure = f"{exc.category}: {exc}"
    passed = (
        exit_code == 0
        and validation.get("report_eligible") is True
        and outcome_observed
        and contradiction_linked
        and report is not None
    )
    return {
        "run_id": run_id,
        "expected_outcome": expected,
        "observed_classifications": classifications,
        "expected_outcome_observed": outcome_observed,
        "seeded_contradiction_linked": contradiction_linked,
        "validation_exit_code": exit_code,
        "report_eligible": validation.get("report_eligible"),
        "blocking_error_codes": sorted(
            {str(item.get("code")) for item in validation.get("blocking_errors", [])}
        ),
        "human_review_codes": sorted(
            {str(item.get("code")) for item in validation.get("human_review_requirements", [])}
        ),
        "phase": status["phase"],
        "disposition": status["disposition"],
        "report_path": report.get("report_path") if report else None,
        "report_sha256": report.get("report_sha256") if report else None,
        "report_failure": report_failure,
        "passed": passed,
    }


def _latest_claims(run_dir: Path) -> dict[str, dict[str, Any]]:
    claims: dict[str, dict[str, Any]] = {}
    for item in iter_json(run_dir / "claims"):
        if item.get("schema_name") != "Claim":
            continue
        claim_id = str(item["claim_id"])
        if claim_id not in claims or int(item["claim_version"]) > int(
            claims[claim_id]["claim_version"]
        ):
            claims[claim_id] = item
    return claims


def _seeded_contradiction_is_linked(run_dir: Path, claims: dict[str, dict[str, Any]]) -> bool:
    evidence = {
        str(item["evidence_id"]): item
        for item in iter_json(run_dir / "evidence")
        if item.get("schema_name") == "Evidence"
    }
    return any(
        SEEDED_CONTRADICTION in str(evidence[evidence_id].get("exact_text", "")).lower()
        for claim in claims.values()
        if claim.get("support_classification") == "conflicting_evidence"
        for evidence_id in claim.get("contradicting_evidence_ids", [])
        if evidence_id in evidence
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate and report-gate both completed host conformance workspaces."
    )
    parser.add_argument("output", type=Path)
    arguments = parser.parse_args()
    result = check_conformance_pair(arguments.output)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
