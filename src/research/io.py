from __future__ import annotations

import contextlib
import hashlib
import json
import os
import tempfile
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from research.canonical import sha256_bytes


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return value


def write_json_atomic(path: Path, value: Any, *, root: Path | None = None) -> None:
    text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    write_text_atomic(path, text, root=root)


def write_text_atomic(path: Path, text: str, *, root: Path | None = None) -> None:
    _validate_write_target(root, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)
        raise


def write_bytes_atomic(path: Path, data: bytes, *, root: Path | None = None) -> None:
    _validate_write_target(root, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)
        raise


def append_jsonl(path: Path, value: dict[str, Any], *, root: Path | None = None) -> None:
    _validate_write_target(root, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(serialized + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def iter_json(path: Path) -> Iterator[dict[str, Any]]:
    if path.is_file():
        try:
            yield read_json(path)
        except (ValueError, json.JSONDecodeError):
            return
        return
    if not path.exists():
        return
    for candidate in sorted(path.rglob("*.json"), key=lambda item: item.as_posix()):
        try:
            yield read_json(candidate)
        except (ValueError, json.JSONDecodeError):
            continue


def file_sha256(path: Path, block_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(block_size):
            digest.update(block)
    return digest.hexdigest()


def bytes_sha256(data: bytes) -> str:
    return sha256_bytes(data)


def _validate_write_target(root: Path | None, path: Path) -> None:
    if root is None:
        return
    from research.security import ensure_no_symlink_components, ensure_workspace_write

    ensure_workspace_write(root, path)
    ensure_no_symlink_components(root, path)
