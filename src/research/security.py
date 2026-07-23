from __future__ import annotations

import os
import re
from pathlib import Path

from research.constants import EXIT_SECURITY
from research.errors import ResearchError

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def is_within(root: Path, candidate: Path) -> bool:
    resolved_root = root.resolve()
    resolved_candidate = candidate.resolve(strict=False)
    try:
        resolved_candidate.relative_to(resolved_root)
        return True
    except ValueError:
        return False


def ensure_workspace_write(root: Path, candidate: Path) -> Path:
    resolved = candidate.resolve(strict=False)
    if not is_within(root, resolved):
        raise ResearchError(
            f"Refusing to write outside workspace: {candidate}",
            category="unsafe_path",
            exit_code=EXIT_SECURITY,
        )
    return resolved


def validate_import_source(path: Path, max_bytes: int) -> Path:
    if path.is_symlink():
        raise ResearchError(
            f"Symbolic links are not accepted as import sources: {path}",
            category="unsafe_path",
            exit_code=EXIT_SECURITY,
        )
    resolved = path.resolve(strict=True)
    if not resolved.is_file():
        raise ResearchError(f"Not a regular file: {path}", category="invalid_source")
    if resolved.stat().st_size > max_bytes:
        raise ResearchError(
            f"Source exceeds configured limit of {max_bytes} bytes: {path}",
            category="resource_limit",
            exit_code=EXIT_SECURITY,
        )
    return resolved


def sanitize_filename(name: str) -> str:
    cleaned = _SAFE_NAME.sub("_", Path(name).name).strip("._")
    return cleaned[:180] or "unnamed"


def redact_secrets(value: str) -> str:
    patterns = (
        r"(?i)(api[_-]?key\s*[=:]\s*)\S+",
        r"(?i)(authorization:\s*bearer\s+)\S+",
        r"(?i)(secret\s*[=:]\s*)\S+",
        r"(?i)(token\s*[=:]\s*)\S+",
    )
    result = value
    for pattern in patterns:
        result = re.sub(pattern, r"\1[REDACTED]", result)
    return result


def ensure_no_symlink_components(root: Path, path: Path) -> None:
    resolved_root = root.resolve()
    current = resolved_root
    relative = path.resolve(strict=False).relative_to(resolved_root)
    for part in relative.parts:
        current = current / part
        if os.path.lexists(current) and current.is_symlink():
            raise ResearchError(
                f"Symbolic link encountered in workspace path: {current}",
                category="unsafe_path",
                exit_code=EXIT_SECURITY,
            )
