"""Path containment and filename sanitization.

TRUST MODEL. Imported files and agent-produced output are UNTRUSTED (spec sections 3.9, 33). A
document's filename, its internal links, and an agent's requested output path are all attacker-
controlled in the threat model. Every write this platform performs must be proven to land inside the
workspace root before it happens.

The dangerous cases are not just `../`:
  - an absolute path supplied where a relative one was expected
  - a symlink inside the workspace pointing outside it
  - a Windows drive-relative path (`C:foo`) or UNC path (`\\\\server\\share`)
  - a name that is a reserved device on Windows (`CON`, `NUL`, `LPT1`)
  - a name differing only by case or Unicode normalization on a case-insensitive filesystem
  - a component that is empty, `.`, or `..` after normalization

`resolve()` is used deliberately: it follows symlinks, which is exactly what makes an escape
detectable. Comparing unresolved paths would let a symlink slip through.
"""

from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path, PurePath

from ..errors import UnsafePathError

# Reserved device names on Windows. Creating these can hang or misbehave even on other platforms
# when the workspace is later copied to Windows, so they are rejected everywhere for portability.
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

_UNSAFE_CHARS = re.compile(r'[\x00-\x1f\x7f<>:"|?*\\/]')
_DOT_RUN = re.compile(r"^\.+$")
MAX_COMPONENT = 200


def contains(root: str | Path, candidate: str | Path) -> bool:
    """True when `candidate` resolves to a location inside `root`.

    Both sides are fully resolved first so symlinks cannot hide an escape.
    """
    root_r = Path(root).resolve()
    cand_r = Path(candidate).resolve()
    return cand_r == root_r or root_r in cand_r.parents


def safe_join(root: str | Path, *parts: str) -> Path:
    """Join under `root`, refusing anything that escapes it.

    Raises UnsafePathError rather than returning a fallback: silently redirecting a suspicious write
    to a "safe" location would hide an attack instead of surfacing it.
    """
    root_r = Path(root).resolve()
    for part in parts:
        p = PurePath(part)
        if p.is_absolute() or (len(p.parts) and re.match(r"^[A-Za-z]:", p.parts[0])):
            raise UnsafePathError(
                f"absolute path component is not allowed: {part!r}",
                detail={"root": str(root_r), "component": part})
        if ".." in p.parts:
            raise UnsafePathError(
                f"path traversal component is not allowed: {part!r}",
                detail={"root": str(root_r), "component": part})

    candidate = root_r.joinpath(*parts)
    # `Path.resolve()` is non-strict: it follows symlinks through the components that DO exist and
    # normalises the rest. That is exactly the check we want, and it works whether or not the target
    # (or the root) has been created yet.
    #
    # An earlier version walked up to the deepest *existing* ancestor and checked that instead. That
    # was wrong in a way worth recording: when the root itself did not exist yet — creating
    # `runs/<run-id>/packets/` under a fresh run directory — the walk climbed ABOVE the root, and
    # the containment test then failed on a perfectly legitimate path. A security check that rejects
    # correct behaviour gets relaxed or removed, so a false positive here is not a safe failure.
    if not contains(root_r, candidate):
        raise UnsafePathError(
            f"resolved path escapes the workspace root: {candidate}",
            detail={"root": str(root_r), "resolved": str(candidate.resolve())})
    return candidate


def assert_within(root: str | Path, candidate: str | Path) -> Path:
    """Gate for every write. Returns the path when it is contained, raises otherwise."""
    if not contains(root, candidate):
        raise UnsafePathError(
            f"refusing to write outside the workspace: {candidate}",
            detail={"root": str(Path(root).resolve()), "path": str(candidate)})
    return Path(candidate)


def is_symlink(path: str | Path) -> bool:
    return Path(path).is_symlink()


def reject_symlink(path: str | Path) -> Path:
    """Symlinks are rejected by default on import (spec section 33).

    A symlinked source would make the "original bytes" ambiguous: the link can be repointed after
    import, breaking the immutability the whole evidence chain rests on.
    """
    p = Path(path)
    if p.is_symlink():
        raise UnsafePathError(
            f"symlinked sources are rejected by default: {p}",
            detail={"path": str(p), "target": str(p.resolve())})
    return p


def sanitize_filename(name: str, *, fallback: str = "unnamed") -> str:
    """Make an untrusted filename safe to place on disk.

    The original name is never discarded - it is preserved as provenance metadata (spec section 16).
    This only produces something safe to *write*.
    """
    name = unicodedata.normalize("NFC", name)
    name = name.replace("\\", "_").replace("/", "_")
    name = _UNSAFE_CHARS.sub("_", name).strip().strip(".")
    if not name or _DOT_RUN.match(name):
        return fallback
    stem, dot, ext = name.partition(".")
    if stem.upper() in _WINDOWS_RESERVED:
        stem = f"_{stem}"
    name = stem + dot + ext
    if len(name) > MAX_COMPONENT:
        stem, dot, ext = name.rpartition(".")
        keep = MAX_COMPONENT - (len(ext) + 1 if dot else 0)
        name = (stem[:keep] + dot + ext) if dot else name[:MAX_COMPONENT]
    return name or fallback


def content_address_path(root: str | Path, sha256_hex: str, *, subdir: str = "originals") -> Path:
    """Two-level fan-out so a large corpus does not put 100k entries in one directory.

        originals/sha256/ab/cd/<full-digest>
    """
    digest = sha256_hex.split(":")[-1]
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise UnsafePathError(f"not a sha256 hex digest: {sha256_hex!r}")
    return safe_join(root, subdir, "sha256", digest[:2], digest[2:4], digest)


def atomic_write_bytes(path: str | Path, data: bytes, *, root: str | Path | None = None) -> Path:
    """Write via a temp file in the SAME directory, then rename.

    Same-directory matters: rename is only atomic within a filesystem, and a temp dir may be on a
    different one. A half-written canonical artifact is worse than no artifact, because it looks
    like a record.
    """
    p = Path(path)
    if root is not None:
        assert_within(root, p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.tmp{os.getpid()}")
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, p)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
    return p


def atomic_write_text(path: str | Path, text: str, *, root: str | Path | None = None) -> Path:
    return atomic_write_bytes(path, text.encode("utf-8"), root=root)
