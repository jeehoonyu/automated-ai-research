"""Schema registry and artifact validation.

THIS CLOSES THE GAP NAMED IN docs/lessons-carried-forward.md §4. Checking that a *schema* is
well-formed says nothing about any document. The predecessor project shipped a test that called
`check_schema` and never `validate`, and for months the docs claimed artifacts were validated while
nothing had ever validated one. `validate_artifact` is the function that makes the claim true, and
`write_artifact` calls it on every write, so an invalid artifact cannot reach disk in the first
place.

Validation happens at WRITE time, not only at read time, on purpose. An artifact that is already on
disk has already been counted: the import summary reported it, the index may have consumed it, and a
later reader rejecting it produces a workspace that is internally inconsistent rather than one that
never accepted the bad data.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

from ..errors import SchemaValidationError, UnsupportedVersionError

# INSIDE the package, not beside it. This was `parents[3] / "schemas"` — the repository root — which
# resolves to a directory that does not exist once the wheel is installed, so every schema load
# raised and the package could do nothing but `--version` and `init`. Package data must live under
# `src/research/` to be shipped at all; see `[tool.setuptools.package-data]` in pyproject.toml.
SCHEMA_ROOT = Path(__file__).resolve().parents[1] / "schemas"
SUPPORTED_MAJOR = 1

# schema_name (as written into artifacts) -> schema file stem
SCHEMA_FILES: dict[str, str] = {
    "Document": "document",
    "ChunkSet": "chunk-set",
    "ResearchPlan": "research-plan",
    "Evidence": "evidence",
    "Claim": "claim",
    "Review": "review",
    "ReviewContext": "review-context",
    "RetrievalLog": "retrieval-log",
    "ValidationResult": "validation-result",
    "Amendment": "amendment",
    "SourceRelationship": "source-relationship",
    "RunManifest": "run-manifest",
    "WorkPacket": "work-packet",
    "IndexManifest": "index-manifest",
    "ReportManifest": "report-manifest",
}


@cache
def _load(schema_name: str, major: int = SUPPORTED_MAJOR) -> dict[str, Any]:
    stem = SCHEMA_FILES.get(schema_name)
    if stem is None:
        raise SchemaValidationError(
            f"no schema is registered for artifact type {schema_name!r}",
            detail={"known": sorted(SCHEMA_FILES)})
    path = SCHEMA_ROOT / f"v{major}" / f"{stem}.schema.json"
    if not path.is_file():
        raise SchemaValidationError(f"schema file is missing: {path}",
                                    detail={"schema_name": schema_name, "path": str(path)})
    with open(path, encoding="utf-8") as fh:
        loaded: dict[str, Any] = json.load(fh)
    return loaded


@cache
def _validator(schema_name: str, major: int = SUPPORTED_MAJOR) -> Any:
    import jsonschema

    return jsonschema.Draft202012Validator(_load(schema_name, major))


def known_schemas() -> list[str]:
    return sorted(SCHEMA_FILES)


@cache
def schema_enum(schema_name: str, *path: str) -> frozenset[str]:
    """The permitted values of a field, read from the shipped schema.

    ASK, DO NOT RESTATE. The schemas hold 53 enums, and Python around this package used to copy
    slices of them into sets, tuples and inline membership tests. Every copy is a bet that nobody
    will ever add a member — and the bets were being lost silently, in the direction that matters:
    a value nobody listed lands in whichever branch the author did not think about, which is
    reliably the reassuring one. The UI shipped a green chip for a claim that had never been
    independently reviewed for exactly this reason.

    A restatement is still right where the code needs a *judgement* about a subset — which
    relationships establish independence, which statuses block. Those are decisions, and decisions
    belong in code with the reason beside them. This is for the other case, where the code simply
    needs to know what the field may contain.

    Raises rather than returning empty: a vocabulary that quietly resolves to nothing would permit
    everything or forbid everything, and both are worse than a startup failure.
    """
    node: Any = _load(schema_name)
    for part in path:
        properties = node.get("properties") if isinstance(node, dict) else None
        node = properties[part] if isinstance(properties, dict) and part in properties \
            else node[part]
    values = node.get("enum") if isinstance(node, dict) else None
    if not isinstance(values, list) or not values:
        raise SchemaValidationError(
            f"{schema_name}.{'.'.join(path)} has no enum to read",
            detail={"schema_name": schema_name, "path": list(path)})
    return frozenset(str(v) for v in values)


def _nearest_rule(schema_doc: dict[str, Any], error: Any) -> str | None:
    """Find the `$comment` on the closest enclosing subschema.

    The constraint that actually fails is usually a leaf (`enum`, `minItems`), while the spec rule
    it encodes is written on the `if/then` wrapper above it. Reporting only the leaf gives an agent
    "'causal_claim' is not one of ['direct_fact', ...]" with no hint that the rule is "`verified` is
    reserved for directly checkable facts" — so walk outward until a rule is found.
    """
    path = list(getattr(error, "absolute_schema_path", []))
    for depth in range(len(path), -1, -1):
        node: Any = schema_doc
        try:
            for key in path[:depth]:
                node = node[key]
        except (KeyError, IndexError, TypeError):
            continue
        if isinstance(node, dict):
            rule = node.get("$comment") or node.get("description")
            if rule:
                return str(rule)
    return None


def validate_artifact(artifact: dict[str, Any], *, schema_name: str | None = None,
                      path: str | Path | None = None) -> None:
    """Validate an artifact instance. Raises on the first problem, listing all of them.

    Errors are sorted and reported together rather than one at a time: an agent fixing an artifact
    needs the whole list, and a partial fix followed by a second rejection wastes a round trip.
    """
    name = schema_name or artifact.get("schema_name")
    if not name:
        raise SchemaValidationError("artifact does not declare schema_name",
                                    detail={"path": str(path) if path else None})

    version = str(artifact.get("schema_version", ""))
    major = version.split(".")[0]
    if not major.isdigit():
        raise SchemaValidationError(
            f"artifact declares an unparseable schema_version {version!r}",
            detail={"schema_name": name, "path": str(path) if path else None})
    if int(major) != SUPPORTED_MAJOR:
        raise UnsupportedVersionError(
            f"{name} schema_version {version} is not supported by this build "
            f"(supported major: {SUPPORTED_MAJOR})",
            detail={"schema_name": name, "found": version,
                    "path": str(path) if path else None})

    schema_doc = _load(name)
    errors = sorted(_validator(name).iter_errors(artifact), key=lambda e: list(e.path))
    if errors:
        raise SchemaValidationError(
            f"{name} artifact failed schema validation ({len(errors)} problem(s))",
            detail={
                "schema_name": name,
                "path": str(path) if path else None,
                "problems": [
                    {
                        "at": "/".join(str(p) for p in err.absolute_path) or "(root)",
                        "message": err.message,
                        "rule": _nearest_rule(schema_doc, err),
                    }
                    for err in errors[:25]
                ],
            })


def is_valid(artifact: dict[str, Any], *, schema_name: str | None = None) -> bool:
    try:
        validate_artifact(artifact, schema_name=schema_name)
    except (SchemaValidationError, UnsupportedVersionError):
        return False
    return True
