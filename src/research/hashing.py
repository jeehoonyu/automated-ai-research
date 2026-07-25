"""SHA-256 hashing and RFC 8785 JSON Canonicalization.

Everything downstream depends on this file: document identity, artifact identity, index
reproducibility, and the tamper-evidence of the whole audit trail. It is deliberately small and
heavily tested.

WHY CANONICALIZATION. `artifact_hash` must be a property of an artifact's *content*, not of how it
happened to be serialized. If pretty-printing, key order, or an inserted space changed the hash, then
two byte-identical-in-meaning artifacts would get different identities and the immutability guarantee
(spec section 3.4) would be unenforceable. RFC 8785 fixes key ordering, string escaping, and number
formatting so the mapping from content to bytes is unique.

THE SELF-REFERENCE RULE. `artifact_hash` is computed over the artifact with the `artifact_hash` field
OMITTED. Hashing an object that contains its own hash is impossible; omitting the field (rather than
blanking it) keeps the operation well-defined and lets verification recompute it exactly.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

HASH_PREFIX = "sha256:"
_CHUNK = 1024 * 1024


def _canonical_number(value: int | float) -> str:
    """RFC 8785 number serialization.

    JSON has no NaN or Infinity, and admitting them would produce a hash for something that cannot
    round-trip. Reject rather than silently coerce.
    """
    if isinstance(value, bool):  # bool is a subclass of int; must be checked first
        raise TypeError("bool handled separately")
    if isinstance(value, int):
        return str(value)
    if math.isnan(value) or math.isinf(value):
        raise ValueError(f"non-finite numbers cannot be canonicalized: {value!r}")
    if value == 0:
        return "0"
    # ECMAScript Number::toString semantics, which RFC 8785 adopts. repr() gives Python's shortest
    # round-tripping form; normalize the exponent spelling to match.
    out = repr(float(value))
    if out.endswith(".0"):
        out = out[:-2]
    if "e" in out:
        mantissa, exponent = out.split("e")
        if mantissa.endswith(".0"):
            mantissa = mantissa[:-2]
        exp_int = int(exponent)
        out = f"{mantissa}e{'+' if exp_int >= 0 else '-'}{abs(exp_int)}"
    return out


def canonical_json(value: Any) -> str:
    """Serialize to the RFC 8785 canonical form.

    Object keys sort by UTF-16 code unit, which is what the RFC specifies and what
    `sorted()` on Python `str` gives for the Basic Multilingual Plane. Characters outside the BMP
    would differ; we sort on the UTF-16 encoding explicitly so astral-plane keys are also correct.
    """

    def enc(v: Any) -> str:
        if v is None:
            return "null"
        if v is True:
            return "true"
        if v is False:
            return "false"
        if isinstance(v, (int, float)):
            return _canonical_number(v)
        if isinstance(v, str):
            return json.dumps(v, ensure_ascii=False, separators=(",", ":"))
        if isinstance(v, (list, tuple)):
            return "[" + ",".join(enc(x) for x in v) + "]"
        if isinstance(v, dict):
            for k in v:
                if not isinstance(k, str):
                    raise TypeError(f"canonical JSON requires string keys, got {type(k).__name__}")
            items = sorted(v.items(), key=lambda kv: kv[0].encode("utf-16-be"))
            return "{" + ",".join(f"{enc(k)}:{enc(val)}" for k, val in items) + "}"
        raise TypeError(f"cannot canonicalize {type(v).__name__}")

    return enc(value)


def sha256_bytes(data: bytes) -> str:
    return HASH_PREFIX + hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: str | Path) -> str:
    """Stream a file so a large PDF does not have to fit in memory."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(_CHUNK):
            h.update(chunk)
    return HASH_PREFIX + h.hexdigest()


ARTIFACT_HASH_FIELD = "artifact_hash"


def artifact_hash(artifact: dict[str, Any]) -> str:
    """Hash an artifact's canonical content, omitting the artifact_hash field itself."""
    payload = {k: v for k, v in artifact.items() if k != ARTIFACT_HASH_FIELD}
    return sha256_text(canonical_json(payload))


def stamp_artifact_hash(artifact: dict[str, Any]) -> dict[str, Any]:
    """Return a copy with a correct `artifact_hash`."""
    out = dict(artifact)
    out[ARTIFACT_HASH_FIELD] = artifact_hash(out)
    return out


def verify_artifact_hash(artifact: dict[str, Any]) -> bool:
    """True when the recorded hash matches the content.

    A recorded verdict that no longer reproduces from its own content is not a verdict - the same
    principle the validation layer applies to claims.
    """
    recorded = artifact.get(ARTIFACT_HASH_FIELD)
    return bool(recorded) and recorded == artifact_hash(artifact)


_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def is_hash(value: str) -> bool:
    return bool(_HASH_RE.match(value))


def short_hash(value: str, length: int = 12) -> str:
    """Display-only abbreviation. The full hash is always what gets stored and compared."""
    digest = value[len(HASH_PREFIX):] if value.startswith(HASH_PREFIX) else value
    return digest[:length]
