"""Stable identifiers for every artifact class.

THE RULE (spec section 15): an identifier derived from content must depend ONLY on content. Not on
filename, import path, import time, user, or workspace location. Re-importing the same bytes on a
different machine six months later must produce the same document id, or deduplication and the
audit trail both collapse.

Identifiers that name a *thing in the world* are content-derived. Identifiers that name an *event*
(a run) or a mutable-text object (a claim, whose wording changes through superseding versions) are
random, because there is no content to derive them from that stays fixed.

    DOC-sha256-<64hex>    original source bytes
    DVER-sha256-<64hex>   a specific normalized extraction of a document
    CHK-sha256-<64hex>    a retrieval unit within a document version
    EVD-sha256-<64hex>    an exact passage cited as evidence
    CLM-<uuid7>           a claim (wording is mutable; identity is not derivable)
    REV-<uuid7>, AMD-<uuid7>
    RUN-<uuid4>           a run is an event, not a content hash

Abbreviated forms are display-only. The full identifier is what is stored and compared.
"""

from __future__ import annotations

import os
import re
import time
import uuid
from typing import Any

from .hashing import HASH_PREFIX, canonical_json, sha256_text

DOC_PREFIX = "DOC-sha256-"
DVER_PREFIX = "DVER-sha256-"
CHUNK_PREFIX = "CHK-sha256-"
EVIDENCE_PREFIX = "EVD-sha256-"
CLAIM_PREFIX = "CLM-"
REVIEW_PREFIX = "REV-"
AMENDMENT_PREFIX = "AMD-"
RUN_PREFIX = "RUN-"
PACKET_PREFIX = "PKT-"

_ID_RE = re.compile(
    r"^(DOC|DVER|CHK|EVD)-sha256-[0-9a-f]{64}$"
    r"|^(CLM|REV|AMD|RUN|PKT)-[0-9a-fA-F-]{36}$"
)


def _digest(value: str) -> str:
    return sha256_text(value)[len(HASH_PREFIX):]


def _composite(parts: dict[str, Any]) -> str:
    """Hash a canonicalized composite so field order can never change an identifier."""
    return _digest(canonical_json(parts))


def document_id(source_sha256: str) -> str:
    """Identity of immutable original bytes. Nothing else may contribute."""
    digest = source_sha256[len(HASH_PREFIX):] if source_sha256.startswith(HASH_PREFIX) else source_sha256
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError(f"expected a sha256 hex digest, got {source_sha256!r}")
    return DOC_PREFIX + digest


def document_version_id(
    *, document_id_: str, extraction_config_hash: str, toolchain_version: str,
    normalization_version: str,
) -> str:
    """A document re-extracted with a different toolchain is a NEW version, not the same one.

    This is what keeps a citation honest across upgrades: evidence points at the extraction it was
    actually read from, so improving the PDF parser cannot silently move someone's quote.
    """
    return DVER_PREFIX + _composite({
        "document_id": document_id_,
        "extraction_config_hash": extraction_config_hash,
        "toolchain_version": toolchain_version,
        "normalization_version": normalization_version,
    })


def chunk_id(
    *, document_version_id_: str, page: int | None, section_path: list[str],
    start_offset: int, end_offset: int, chunking_config_hash: str,
) -> str:
    return CHUNK_PREFIX + _composite({
        "document_version_id": document_version_id_,
        "page": page,
        "section_path": section_path,
        "start_offset": start_offset,
        "end_offset": end_offset,
        "chunking_config_hash": chunking_config_hash,
    })


def evidence_id(
    *, document_version_id_: str, locator: dict[str, Any], exact_text: str, evidence_type: str,
) -> str:
    """Two agents extracting the identical passage from the identical version get the identical id.

    That is deliberate: it makes duplicate evidence collapse instead of inflating an apparent
    evidence count. Counting the same thing twice as two supports is a real and easy mistake.
    """
    return EVIDENCE_PREFIX + _composite({
        "document_version_id": document_version_id_,
        "locator": locator,
        "exact_text": exact_text,
        "evidence_type": evidence_type,
    })


_last_ms = 0
_counter = 0


def _uuid7() -> str:
    """UUIDv7 with an intra-millisecond monotonic counter (RFC 9562 "method 2").

    Layout: 48-bit unix_ts_ms | version(7) | 12-bit counter | variant | 62-bit random.

    The plain timestamp-plus-random form is NOT sortable within a single millisecond, and artifacts
    here are created in tight loops - a batch of evidence records routinely lands in the same
    millisecond. Without the counter, "time-ordered" would be true only across milliseconds and
    would quietly fail exactly when it is most used. The counter is seeded randomly each new
    millisecond so ids stay unguessable, and it saturates rather than wrapping (wrapping would go
    backwards, breaking the ordering guarantee outright).
    """
    global _last_ms, _counter
    ms = int(time.time() * 1000) & ((1 << 48) - 1)
    if ms > _last_ms:
        _last_ms = ms
        _counter = int.from_bytes(os.urandom(2), "big") & 0x0FF  # leave headroom below 0xFFF
    else:
        ms = _last_ms                      # clock went backwards or same ms: keep ordering
        _counter = min(_counter + 1, 0xFFF)

    rand_b = int.from_bytes(os.urandom(8), "big")
    b = bytearray(16)
    b[0:6] = ms.to_bytes(6, "big")
    b[6] = 0x70 | ((_counter >> 8) & 0x0F)          # version 7 + counter high nibble
    b[7] = _counter & 0xFF                          # counter low byte
    b[8:16] = rand_b.to_bytes(8, "big")
    b[8] = (b[8] & 0x3F) | 0x80                     # RFC 4122 variant
    return str(uuid.UUID(bytes=bytes(b)))


def claim_id() -> str:
    return CLAIM_PREFIX + _uuid7()


def review_id() -> str:
    return REVIEW_PREFIX + _uuid7()


def amendment_id() -> str:
    return AMENDMENT_PREFIX + _uuid7()


def packet_id() -> str:
    return PACKET_PREFIX + _uuid7()


def run_id() -> str:
    """UUIDv4. A run id must not encode the wall clock (spec section 15.6); the timestamp is stored
    as metadata instead, so it can be corrected without changing identity."""
    return RUN_PREFIX + str(uuid.uuid4())


def is_valid_id(value: str) -> bool:
    return bool(_ID_RE.match(value))


def short_id(value: str, length: int = 12) -> str:
    """Display-only. Never persist or compare an abbreviated identifier."""
    for prefix in (DOC_PREFIX, DVER_PREFIX, CHUNK_PREFIX, EVIDENCE_PREFIX):
        if value.startswith(prefix):
            return prefix[:-7] + "…" + value[len(prefix):][:length]
    return value
