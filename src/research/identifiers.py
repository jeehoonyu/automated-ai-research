from __future__ import annotations

import secrets
import time
import uuid
from typing import Any

from research.canonical import canonical_sha256


def content_identifier(prefix: str, sha256_hex: str) -> str:
    return f"{prefix}-sha256-{sha256_hex.lower()}"


def derived_identifier(prefix: str, value: Any) -> str:
    digest = canonical_sha256(value).removeprefix("sha256:")
    return content_identifier(prefix, digest)


def uuid7() -> uuid.UUID:
    """Create an RFC 9562 UUIDv7 without relying on Python 3.14's uuid.uuid7."""
    timestamp_ms = int(time.time() * 1000) & ((1 << 48) - 1)
    random_a = secrets.randbits(12)
    random_b = secrets.randbits(62)
    integer = (timestamp_ms << 80) | (0x7 << 76) | (random_a << 64)
    integer |= (0b10 << 62) | random_b
    return uuid.UUID(int=integer)


def generated_identifier(prefix: str) -> str:
    return f"{prefix}-{uuid7()}"


def run_identifier() -> str:
    return f"RUN-{uuid.uuid4()}"
