"""Jinja environment for the UI.

AUTOESCAPE IS ON AND IS NOT OPTIONAL. The report renderer disables it with a documented `S701`
annotation, which is correct there: it produces Markdown, where HTML escaping would corrupt the
output. This produces HTML, and the values interpolated into it include text extracted from imported
documents — the same bytes the trust model calls attacker-controlled. `select_autoescape` is not
used, because it decides by filename and would leave a `.txt` template unescaped by accident;
autoescape is set unconditionally instead.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent / "static"


@lru_cache(maxsize=1)
def environment() -> Environment:
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=True,
        undefined=StrictUndefined,  # a typo in a template is an error, not a silent empty string
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["shorthash"] = _shorthash
    env.filters["shortid"] = _shortid
    return env


def _shorthash(value: Any, length: int = 12) -> str:
    text = str(value or "")
    digest = text.split(":")[-1]
    return digest[:length] + "…" if len(digest) > length else digest


def _shortid(value: Any, length: int = 10) -> str:
    """Shorten a content-derived id for display, keeping its prefix.

    `EVD-sha256-3f2a…`. The prefix is the part a reader needs — it says what kind of thing this is —
    and the full id stays in the link target and the `title` attribute.
    """
    text = str(value or "")
    prefix, sep, rest = text.partition("sha256-")
    if sep:
        return f"{prefix}{sep}{rest[:length]}…" if len(rest) > length else text
    head, dash, tail = text.partition("-")
    if dash and len(tail) > length:
        return f"{head}-{tail[:length]}…"
    return text


def render(template: str, model: dict[str, Any]) -> str:
    return environment().get_template(template).render(**model)


def stylesheet() -> bytes:
    return (STATIC_DIR / "app.css").read_bytes()
