"""Workspace discovery and configuration loading.

Discovery walks upward from the current directory to the nearest `research.yaml`, the same way git
finds `.git`. `--workspace PATH` overrides it explicitly. Anything that writes must know its root
before it writes, because the root is what path containment is checked against.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .errors import WorkspaceError
from .hashing import canonical_json, sha256_text

WORKSPACE_FILE = "research.yaml"
CONFIG_VERSION = "1.0.0"
WORKFLOW_VERSION = "1.0.0"
SCHEMA_VERSION = "1.0.0"

# Bumping either of these changes every derived document_version_id, which is the intended
# behaviour: a different extraction is a different version, and citations must not silently move.
EXTRACTION_TOOLCHAIN_VERSION = "0.1.0"
NORMALIZATION_VERSION = "1.0.0"
CHUNKING_VERSION = "1.0.0"

DEFAULT_CONFIG: dict[str, Any] = {
    "config_version": CONFIG_VERSION,
    "workflow_version": WORKFLOW_VERSION,
    "schema_version": SCHEMA_VERSION,
    "default_profile": "default",
    "extraction": {
        "toolchain_version": EXTRACTION_TOOLCHAIN_VERSION,
        "normalization_version": NORMALIZATION_VERSION,
        # A page with fewer usable characters than this is assumed to be image-only and is marked
        # ocr_required rather than treated as legitimately near-empty text.
        "min_usable_chars_per_page": 120,
        "max_file_bytes": 250 * 1024 * 1024,
    },
    "render": {
        "renderer": "pypdfium2",
        "dpi": 150,
        "format": "png",
        "color": "rgb",
    },
    "chunking": {
        "version": CHUNKING_VERSION,
        "target_chars": 1800,
        "overlap_chars": 200,
    },
    "index": {
        "tokenizer": "unicode61",
        "tokenizer_args": "remove_diacritics 2",
        "ranking": "bm25",
    },
    "security": {
        "allow_symlinks": False,
        "network_enabled": False,   # core processing performs no network requests, ever
        "follow_markdown_links": False,
    },
}

STANDARD_DIRS = (
    "originals/sha256",
    "documents/manifests", "documents/normalized", "documents/pages",
    "documents/renders", "documents/tables", "documents/figures",
    "indexes", "imports", "runs", "profiles", "logs", "cache",
)


@dataclass
class Workspace:
    """A resolved workspace root plus its configuration."""

    root: Path
    config: dict[str, Any] = field(default_factory=dict)

    @property
    def config_path(self) -> Path:
        return self.root / WORKSPACE_FILE

    def path(self, *parts: str) -> Path:
        from .security.paths import safe_join
        return safe_join(self.root, *parts)

    @property
    def config_hash(self) -> str:
        """Recorded in provenance so a run can be tied to the settings that produced it."""
        return sha256_text(canonical_json(self.config))

    def get(self, dotted: str, default: Any = None) -> Any:
        cur: Any = self.config
        for part in dotted.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    def extraction_config_hash(self) -> str:
        """Only the settings that actually change extraction output feed the version id."""
        return sha256_text(canonical_json({
            "extraction": self.get("extraction", {}),
            "render": self.get("render", {}),
        }))


def find_workspace_root(start: str | Path | None = None) -> Path | None:
    """Walk upward to the nearest directory containing research.yaml."""
    cur = Path(start or os.getcwd()).resolve()
    for candidate in (cur, *cur.parents):
        if (candidate / WORKSPACE_FILE).is_file():
            return candidate
    return None


def load_workspace(explicit: str | Path | None = None, *, start: str | Path | None = None) -> Workspace:
    """Resolve and load a workspace, or raise with an actionable message."""
    if explicit is not None:
        root = Path(explicit).resolve()
        if not (root / WORKSPACE_FILE).is_file():
            raise WorkspaceError(
                f"no {WORKSPACE_FILE} in {root}",
                detail={"path": str(root), "hint": "run `research init <dir>` first"})
    else:
        found = find_workspace_root(start)
        if found is None:
            raise WorkspaceError(
                f"not inside a research workspace (no {WORKSPACE_FILE} found in this directory "
                f"or any parent)",
                detail={"searched_from": str(Path(start or os.getcwd()).resolve()),
                        "hint": "run `research init <dir>`, or pass --workspace PATH"})
        root = found

    with open(root / WORKSPACE_FILE, encoding="utf-8") as fh:
        config = yaml.safe_load(fh) or {}

    declared = config.get("config_version")
    if declared and declared.split(".")[0] != CONFIG_VERSION.split(".")[0]:
        from .errors import UnsupportedVersionError
        raise UnsupportedVersionError(
            f"workspace config_version {declared} is not supported by this build "
            f"(expected {CONFIG_VERSION})",
            detail={"found": declared, "supported": CONFIG_VERSION})

    merged = _deep_merge(DEFAULT_CONFIG, config)
    return Workspace(root=root, config=merged)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in override.items():
        out[k] = _deep_merge(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out
