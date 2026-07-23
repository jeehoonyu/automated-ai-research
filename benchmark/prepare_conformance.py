from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from research.canonical import canonical_sha256
from research.indexing import build_index
from research.ingestion import import_sources
from research.io import file_sha256, iter_json, write_json_atomic
from research.runs import create_run
from research.workspace import init_workspace

REPOSITORY = Path(__file__).resolve().parents[1]
HOSTS = ("codex", "claude-code")


def prepare_conformance_pair(output_root: Path) -> dict[str, Any]:
    output_root = output_root.expanduser().resolve()
    if output_root.exists() and (not output_root.is_dir() or any(output_root.iterdir())):
        raise ValueError(f"Conformance output must be absent or empty: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)

    base = output_root / "base-workspace"
    init_workspace(base)
    imported = import_sources(
        base,
        [REPOSITORY / "benchmark" / "sources", REPOSITORY / "benchmark" / "fixtures"],
    )
    if imported["failed_count"]:
        raise RuntimeError(f"Benchmark import failed: {imported['failures']}")
    index = build_index(base)
    question_contracts = {
        path.stem: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((REPOSITORY / "benchmark" / "questions").glob("*.json"))
    }
    if not question_contracts:
        raise RuntimeError("No benchmark question contracts were found")

    host_results: dict[str, dict[str, Any]] = {}
    semantic_contracts: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for host in HOSTS:
        workspace = output_root / host / "workspace"
        workspace.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(base, workspace)
        host_contracts: dict[str, list[dict[str, Any]]] = {}
        runs: dict[str, dict[str, Any]] = {}
        for case, question_contract in question_contracts.items():
            run = create_run(workspace, str(question_contract["question"]), "default", host=host)
            run_dir = Path(run["run_path"])
            contracts = _semantic_packet_contracts(run_dir)
            host_contracts[case] = contracts
            runs[case] = {
                "run_id": run["run_id"],
                "question": question_contract["question"],
                "expected_outcome": question_contract["expected_outcome"],
                "packet_contract_hash": canonical_sha256(contracts),
                "packet_count": len(contracts),
            }
        semantic_contracts[host] = host_contracts
        host_results[host] = {
            "workspace": str(workspace),
            "runs": runs,
            "packet_contract_hash": canonical_sha256(host_contracts),
            "packet_count": sum(len(items) for items in host_contracts.values()),
        }

    if semantic_contracts[HOSTS[0]] != semantic_contracts[HOSTS[1]]:
        raise RuntimeError("Host work packets are not semantically equivalent")

    source_documents = sorted(
        (
            {
                "document_id": str(item["document_id"]),
                "source_sha256": str(item["source_sha256"]),
                "media_type": str(item["media_type"]),
            }
            for item in iter_json(base / "documents" / "manifests")
        ),
        key=lambda item: item["document_id"],
    )
    schema_hashes = {
        path.name: f"sha256:{file_sha256(path)}"
        for path in sorted((base / "schemas" / "v1").glob("*.schema.json"))
    }
    result = {
        "preparation_version": "1.0.0",
        "questions": {
            case: {
                "question": contract["question"],
                "expected_outcome": contract["expected_outcome"],
            }
            for case, contract in question_contracts.items()
        },
        "profile": "default",
        "source_documents": source_documents,
        "source_set_hash": canonical_sha256(source_documents),
        "schema_hashes": schema_hashes,
        "schema_set_hash": canonical_sha256(schema_hashes),
        "logical_index_hash": index["logical_index_hash"],
        "index_id": index["index_id"],
        "import_counts": {
            "imported": imported["imported_count"],
            "duplicates": imported["duplicate_count"],
            "partial": imported["partial_count"],
            "failed": imported["failed_count"],
        },
        "packet_contract_hash": host_results[HOSTS[0]]["packet_contract_hash"],
        "hosts": host_results,
    }
    result["preparation_hash"] = canonical_sha256(result)
    write_json_atomic(output_root / "conformance-preparation.json", result, root=output_root)
    return result


def _semantic_packet_contracts(run_dir: Path) -> list[dict[str, Any]]:
    contracts: list[dict[str, Any]] = []
    for packet in iter_json(run_dir / "packets"):
        contracts.append(
            {
                "stage": packet["stage"],
                "workflow_version": packet["workflow_version"],
                "schema_versions": packet["schema_versions"],
                "relevant_schemas": packet["relevant_schemas"],
                "research_question": packet["research_question"],
                "allowed_inputs": packet["allowed_inputs"],
                "excluded_inputs": packet["excluded_inputs"],
                "required_outputs": packet["required_outputs"],
                "completion_criteria": packet["completion_criteria"],
                "validation_command": str(packet["validation_command"]).replace(
                    str(packet["run_id"]), "<run-id>"
                ),
                "failure_conditions": packet["failure_conditions"],
                "human_review_triggers": packet["human_review_triggers"],
                "trusted_instructions": packet["trusted_instructions"],
                "untrusted_content_notice": packet["untrusted_content_notice"],
            }
        )
    return sorted(contracts, key=lambda item: str(item["stage"]))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepare equivalent current-benchmark workspaces for Codex and Claude Code."
    )
    parser.add_argument("output", type=Path)
    arguments = parser.parse_args()
    result = prepare_conformance_pair(arguments.output)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
