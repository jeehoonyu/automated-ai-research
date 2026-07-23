from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from research.canonical import canonical_sha256
from research.errors import ResearchError

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


def write_default_config(path: Path) -> None:
    from research.io import write_text_atomic

    write_text_atomic(path, yaml.safe_dump(DEFAULT_CONFIG, sort_keys=True, allow_unicode=True))


def load_config(workspace: Path) -> dict[str, Any]:
    path = workspace / "research.yaml"
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
    return result


def _merge(target: dict[str, Any], update: dict[str, Any]) -> None:
    for key, value in update.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge(target[key], value)
        else:
            target[key] = value
