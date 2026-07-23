from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from research.canonical import canonical_sha256
from research.constants import SCHEMA_VERSION, WORKFLOW_VERSION
from research.errors import ResearchError
from research.security import ensure_no_symlink_components

DEFAULT_CONFIG: dict[str, Any] = {
    "workspace_version": "1.0.0",
    "schema_version": "1.0.0",
    "workflow_version": "1.0.0",
    "network_access": False,
    "imports": {
        "max_file_bytes": 250 * 1024 * 1024,
        "follow_symlinks": False,
    },
    "pdf": {
        "render_dpi": 150,
        "render_format": "png",
        "minimum_usable_characters": 40,
        "maximum_pages": 2000,
        "maximum_render_pixels_per_page": 50_000_000,
    },
    "chunking": {
        "max_characters": 1200,
        "overlap_characters": 150,
        "version": "1.0.0",
    },
    "index": {
        "tokenizer": "unicode61 remove_diacritics 2",
        "ranking": "fts5_bm25_ascending",
    },
    "default_profile": "default",
}


def config_hash(config: dict[str, Any]) -> str:
    return canonical_sha256(config)


def write_default_config(path: Path, *, workspace_root: Path | None = None) -> None:
    from research.io import write_text_atomic

    write_text_atomic(
        path,
        yaml.safe_dump(DEFAULT_CONFIG, sort_keys=True, allow_unicode=True),
        root=workspace_root,
    )


def load_config(workspace: Path) -> dict[str, Any]:
    path = workspace / "research.yaml"
    ensure_no_symlink_components(workspace, path)
    try:
        with path.open("r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle)
    except OSError as exc:
        raise ResearchError(f"Cannot read workspace configuration: {path}") from exc
    if not isinstance(loaded, dict):
        raise ResearchError("research.yaml must contain a mapping", category="invalid_config")
    result = deepcopy(DEFAULT_CONFIG)
    _merge(result, loaded)
    if result.get("network_access") is not False:
        raise ResearchError(
            "MVP core processing requires network_access: false",
            category="invalid_config",
        )
    _validate_config(result)
    return result


def _merge(target: dict[str, Any], update: dict[str, Any]) -> None:
    for key, value in update.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge(target[key], value)
        else:
            target[key] = value


def _validate_config(config: dict[str, Any]) -> None:
    imports = config.get("imports")
    pdf = config.get("pdf")
    chunking = config.get("chunking")
    index = config.get("index")
    if not all(isinstance(item, dict) for item in (imports, pdf, chunking, index)):
        raise ResearchError(
            "imports, pdf, chunking, and index configuration must be mappings",
            category="invalid_config",
        )
    assert isinstance(imports, dict)
    assert isinstance(pdf, dict)
    assert isinstance(chunking, dict)
    assert isinstance(index, dict)
    positive_integers = {
        "imports.max_file_bytes": imports.get("max_file_bytes"),
        "pdf.render_dpi": pdf.get("render_dpi"),
        "pdf.minimum_usable_characters": pdf.get("minimum_usable_characters"),
        "pdf.maximum_pages": pdf.get("maximum_pages"),
        "pdf.maximum_render_pixels_per_page": pdf.get("maximum_render_pixels_per_page"),
        "chunking.max_characters": chunking.get("max_characters"),
    }
    invalid = [
        name
        for name, value in positive_integers.items()
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0
    ]
    for field, expected in {
        "workspace_version": "1.0.0",
        "schema_version": SCHEMA_VERSION,
        "workflow_version": WORKFLOW_VERSION,
    }.items():
        if config.get(field) != expected:
            invalid.append(field)
    overlap = chunking.get("overlap_characters")
    maximum = chunking.get("max_characters")
    if (
        not isinstance(overlap, int)
        or isinstance(overlap, bool)
        or overlap < 0
        or isinstance(maximum, bool)
        or not isinstance(maximum, int)
        or overlap >= maximum
    ):
        invalid.append("chunking.overlap_characters")
    if imports.get("follow_symlinks") is not False:
        invalid.append("imports.follow_symlinks")
    if pdf.get("render_format") != "png":
        invalid.append("pdf.render_format")
    if index.get("tokenizer") != "unicode61 remove_diacritics 2":
        invalid.append("index.tokenizer")
    if index.get("ranking") != "fts5_bm25_ascending":
        invalid.append("index.ranking")
    if not isinstance(config.get("default_profile"), str) or not config["default_profile"]:
        invalid.append("default_profile")
    if invalid:
        raise ResearchError(
            f"Invalid workspace configuration fields: {', '.join(sorted(set(invalid)))}",
            category="invalid_config",
        )
