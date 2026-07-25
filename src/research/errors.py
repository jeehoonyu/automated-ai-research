"""Error model, stable exit codes, and the versioned result envelope.

Every command returns the same envelope shape so automation can consume any command without
special-casing. The exit codes are part of the public contract (spec section 34) and must stay
stable across releases.

DESIGN NOTE - fail closed. `human_review_required` and `unable_to_determine` are *successful*
research outcomes, not failures (spec sections 23.3, 44), but they still get distinct machine-readable
statuses so automation can branch on them. The inverse mistake - a gate that cannot return the bad
verdict - is the failure mode this whole platform exists to prevent, so "not measurable" is never
allowed to read as "passed".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Literal

ENVELOPE_VERSION = "1.0.0"

Status = Literal["ok", "partial", "blocked", "failed"]


class ExitCode(IntEnum):
    """Stable process exit codes. Spec section 34."""

    SUCCESS = 0
    GENERAL_FAILURE = 1
    INVALID_ARGUMENTS = 2
    SCHEMA_VALIDATION_FAILURE = 3
    SOURCE_PROCESSING_FAILURE = 4
    REPORT_GATING_FAILURE = 5
    HUMAN_REVIEW_REQUIRED = 6
    UNSAFE_PATH_OR_SECURITY = 7
    UNSUPPORTED_ARTIFACT_OR_SCHEMA_VERSION = 8


class ResearchError(Exception):
    """Base class. Every raised error carries an exit code and a stable category string."""

    exit_code: ExitCode = ExitCode.GENERAL_FAILURE
    category: str = "general_failure"

    def __init__(self, message: str, *, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail or {}

    def to_dict(self) -> dict[str, Any]:
        return {"category": self.category, "message": self.message, "detail": self.detail}


class InvalidArguments(ResearchError):
    exit_code = ExitCode.INVALID_ARGUMENTS
    category = "invalid_arguments"


class SchemaValidationError(ResearchError):
    exit_code = ExitCode.SCHEMA_VALIDATION_FAILURE
    category = "schema_validation_failure"


class SourceProcessingError(ResearchError):
    exit_code = ExitCode.SOURCE_PROCESSING_FAILURE
    category = "source_processing_failure"


class ReportGatingError(ResearchError):
    exit_code = ExitCode.REPORT_GATING_FAILURE
    category = "report_gating_failure"


class HumanReviewRequired(ResearchError):
    """Not a bug. An expected workflow state that automation still needs to detect."""

    exit_code = ExitCode.HUMAN_REVIEW_REQUIRED
    category = "human_review_required"


class UnsafePathError(ResearchError):
    """Path traversal, symlink escape, or a write outside the workspace root."""

    exit_code = ExitCode.UNSAFE_PATH_OR_SECURITY
    category = "unsafe_path_or_security"


class UnsupportedVersionError(ResearchError):
    exit_code = ExitCode.UNSUPPORTED_ARTIFACT_OR_SCHEMA_VERSION
    category = "unsupported_artifact_or_schema_version"


class WorkspaceError(ResearchError):
    category = "workspace_error"


@dataclass
class Envelope:
    """The versioned machine-readable result every command emits under --json.

    `status` is deliberately separate from the exit code: a command can succeed at what it was asked
    to do while reporting that publication is blocked. Presenting partial processing as complete
    success is explicitly forbidden (spec section 34), so `partial` exists as a first-class status.
    """

    command: str
    status: Status = "ok"
    data: dict[str, Any] = field(default_factory=dict)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    envelope_version: str = ENVELOPE_VERSION

    def warn(self, category: str, message: str, **detail: Any) -> None:
        self.warnings.append({"category": category, "message": message, "detail": detail})

    def fail(self, category: str, message: str, **detail: Any) -> None:
        self.errors.append({"category": category, "message": message, "detail": detail})
        if self.status == "ok":
            self.status = "failed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "envelope_version": self.envelope_version,
            "command": self.command,
            "status": self.status,
            "data": self.data,
            "warnings": self.warnings,
            "errors": self.errors,
        }

    def exit_code(self) -> ExitCode:
        """Derive the process exit code from the envelope's own contents.

        Kept as a pure function of the envelope so a command cannot report failures in `errors`
        while exiting 0 - a class of contradiction (a pass label beside disqualifying evidence)
        that is worth making structurally impossible rather than relying on discipline.
        """
        if self.errors:
            categories = {e.get("category") for e in self.errors}
            for cat, code in (
                ("unsafe_path_or_security", ExitCode.UNSAFE_PATH_OR_SECURITY),
                ("unsupported_artifact_or_schema_version",
                 ExitCode.UNSUPPORTED_ARTIFACT_OR_SCHEMA_VERSION),
                ("schema_validation_failure", ExitCode.SCHEMA_VALIDATION_FAILURE),
                ("report_gating_failure", ExitCode.REPORT_GATING_FAILURE),
                ("source_processing_failure", ExitCode.SOURCE_PROCESSING_FAILURE),
                ("invalid_arguments", ExitCode.INVALID_ARGUMENTS),
                ("human_review_required", ExitCode.HUMAN_REVIEW_REQUIRED),
            ):
                if cat in categories:
                    return code
            return ExitCode.GENERAL_FAILURE
        if self.status == "blocked":
            return ExitCode.REPORT_GATING_FAILURE
        if self.status == "partial":
            return ExitCode.SOURCE_PROCESSING_FAILURE
        return ExitCode.SUCCESS
