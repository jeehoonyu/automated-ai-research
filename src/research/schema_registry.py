from __future__ import annotations

import json
import sysconfig
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from research.constants import EXIT_SCHEMA, EXIT_UNSUPPORTED, SCHEMA_VERSION
from research.errors import ResearchError


class SchemaRegistry:
    def __init__(self, schema_root: Path | None = None) -> None:
        self.schema_root = schema_root or self._default_root()
        self._schemas: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _default_root() -> Path:
        checkout_root = Path(__file__).resolve().parents[2] / "schemas" / "v1"
        if checkout_root.is_dir():
            return checkout_root
        packaged = Path(__file__).resolve().parent / "schema_catalog" / "v1"
        if packaged.is_dir():
            return packaged
        installed = (
            Path(sysconfig.get_path("data")) / "share" / "automated-ai-research" / "schemas" / "v1"
        )
        if installed.is_dir():
            return installed
        raise ResearchError("No JSON Schema catalog was found", category="missing_schemas")

    def get(self, schema_name: str, schema_version: str = SCHEMA_VERSION) -> dict[str, Any]:
        if schema_version != SCHEMA_VERSION:
            raise ResearchError(
                f"Unsupported schema version {schema_version!r}; supported: {SCHEMA_VERSION}",
                category="unsupported_schema_version",
                exit_code=EXIT_UNSUPPORTED,
            )
        normalized = _schema_filename(schema_name)
        if normalized not in self._schemas:
            path = self.schema_root / f"{normalized}.schema.json"
            if not path.is_file():
                raise ResearchError(
                    f"Unsupported schema name: {schema_name}",
                    category="unsupported_schema",
                    exit_code=EXIT_UNSUPPORTED,
                )
            try:
                with path.open("r", encoding="utf-8") as handle:
                    schema = json.load(handle)
                Draft202012Validator.check_schema(schema)
            except (OSError, json.JSONDecodeError, SchemaError) as exc:
                raise ResearchError(f"Invalid schema catalog entry: {path}") from exc
            self._schemas[normalized] = schema
        return self._schemas[normalized]

    def validate(self, artifact: dict[str, Any]) -> None:
        schema_name = artifact.get("schema_name")
        schema_version = artifact.get("schema_version")
        if not isinstance(schema_name, str) or not isinstance(schema_version, str):
            raise ResearchError(
                "Artifact must declare schema_name and schema_version",
                category="schema_validation_failure",
                exit_code=EXIT_SCHEMA,
            )
        validator = Draft202012Validator(self.get(schema_name, schema_version))
        errors = sorted(validator.iter_errors(artifact), key=lambda error: list(error.path))
        if errors:
            details = [
                {"path": "/".join(str(item) for item in error.path), "message": error.message}
                for error in errors
            ]
            raise ResearchError(
                f"Artifact {artifact.get('artifact_id', '<unknown>')} failed schema validation",
                category="schema_validation_failure",
                exit_code=EXIT_SCHEMA,
                details={"validation_errors": details},
            )


def _schema_filename(schema_name: str) -> str:
    result: list[str] = []
    for index, character in enumerate(schema_name):
        if character.isupper() and index:
            result.append("-")
        result.append(character.lower())
    return "".join(result).replace("_", "-")
