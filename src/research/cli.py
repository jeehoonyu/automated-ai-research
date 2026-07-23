from __future__ import annotations

import functools
from collections.abc import Callable
from pathlib import Path
from typing import Any, ParamSpec, TypeVar

import click

from research import __version__
from research.constants import EXIT_SOURCE
from research.errors import ResearchError
from research.indexing import build_index, search_index
from research.ingestion import import_sources
from research.inspection import inspect_artifact
from research.reporting import generate_report
from research.result import CommandResult, emit
from research.runs import create_run, promote_stage, run_status
from research.validation import validate_run
from research.workspace import find_workspace, init_workspace

P = ParamSpec("P")
R = TypeVar("R")

STAGES_WITH_RESPONSES = (
    "planning",
    "retrieval",
    "evidence_extraction",
    "synthesis",
    "contradiction_review",
    "citation_review",
    "methodology_review",
    "independent_review",
    "human_review",
    "amendment",
)


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.option(
    "workspace_option",
    "--workspace",
    type=click.Path(path_type=Path, file_okay=False),
    help="Explicit workspace path; otherwise locate the nearest parent research.yaml.",
)
@click.version_option(__version__, prog_name="research")
@click.pass_context
def cli(ctx: click.Context, workspace_option: Path | None) -> None:
    """Local-first evidence processing and research validation for host coding agents."""
    ctx.ensure_object(dict)
    ctx.obj["workspace_option"] = workspace_option


def json_option(function: Callable[P, R]) -> Callable[P, R]:
    return click.option(
        "json_output", "--json", is_flag=True, help="Emit a stable JSON result envelope."
    )(function)


def handled(
    command: str,
) -> Callable[[Callable[P, dict[str, Any] | tuple[dict[str, Any], int]]], Callable[P, None]]:
    def decorator(
        function: Callable[P, dict[str, Any] | tuple[dict[str, Any], int]],
    ) -> Callable[P, None]:
        @functools.wraps(function)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> None:
            json_output = bool(kwargs.get("json_output", False))
            try:
                outcome = function(*args, **kwargs)
                if isinstance(outcome, tuple):
                    data, exit_code = outcome
                else:
                    data, exit_code = outcome, 0
                warnings = list(data.pop("_warnings", []))
                errors = list(data.pop("_errors", []))
                status = str(data.pop("_status", "success" if exit_code == 0 else "failed"))
                emit(CommandResult(command, status, data, warnings, errors), json_output)
                if exit_code:
                    raise click.exceptions.Exit(exit_code)
            except ResearchError as exc:
                error = {"category": exc.category, "message": str(exc), "details": exc.details}
                emit(CommandResult(command, "failed", {}, [], [error]), json_output)
                raise click.exceptions.Exit(exc.exit_code) from exc
            except click.exceptions.Exit:
                raise
            except Exception as exc:
                error = {
                    "category": "general_failure",
                    "message": f"{type(exc).__name__}: {exc}",
                    "details": {},
                }
                emit(CommandResult(command, "failed", {}, [], [error]), json_output)
                raise click.exceptions.Exit(1) from exc

        return wrapper

    return decorator


def _workspace(ctx: click.Context) -> Path:
    return find_workspace(ctx.obj.get("workspace_option"))


@cli.command("init")
@click.argument("target", type=click.Path(path_type=Path), default=".")
@click.option(
    "--allow-non-empty",
    is_flag=True,
    help="Allow initialization in a non-empty directory without overwriting collisions.",
)
@json_option
@handled("init")
def init_command(target: Path, allow_non_empty: bool, json_output: bool) -> dict[str, Any]:
    """Create a new research workspace."""
    return init_workspace(target, allow_non_empty)


@cli.command("import")
@click.argument("sources", nargs=-1, required=True, type=click.Path(path_type=Path, exists=True))
@json_option
@click.pass_context
@handled("import")
def import_command(
    ctx: click.Context, sources: tuple[Path, ...], json_output: bool
) -> tuple[dict[str, Any], int]:
    """Import local PDF and Markdown documents."""
    result = import_sources(_workspace(ctx), sources)
    exit_code = EXIT_SOURCE if result["failed_count"] else 0
    result["_status"] = result.pop("status")
    result["_warnings"] = result.pop("warnings")
    result["_errors"] = list(result["failures"])
    return result, exit_code


@cli.command("index")
@json_option
@click.pass_context
@handled("index")
def index_command(ctx: click.Context, json_output: bool) -> dict[str, Any]:
    """Build or rebuild the deterministic SQLite FTS5 index."""
    return build_index(_workspace(ctx))


@cli.command("search")
@click.argument("query")
@click.option("--document-type", type=click.Choice(["application/pdf", "text/markdown"]))
@click.option("--document-id")
@click.option("--limit", type=click.IntRange(1, 1000), default=20, show_default=True)
@click.option("--run-id", help="Associate the query with a research run in the search log.")
@json_option
@click.pass_context
@handled("search")
def search_command(
    ctx: click.Context,
    query: str,
    document_type: str | None,
    document_id: str | None,
    limit: int,
    run_id: str | None,
    json_output: bool,
) -> dict[str, Any]:
    """Search indexed chunks; ranking is not evidence quality."""
    return search_index(
        _workspace(ctx),
        query,
        document_type=document_type,
        document_id=document_id,
        limit=limit,
        run_id=run_id,
    )


@cli.command("run")
@click.option("--question", required=True, help="Research question.")
@click.option("--profile", "profile_name", default="default", show_default=True)
@click.option("--host", type=click.Choice(["codex", "claude-code", "other"]))
@click.option("--model-identifier")
@json_option
@click.pass_context
@handled("run")
def run_command(
    ctx: click.Context,
    question: str,
    profile_name: str,
    host: str | None,
    model_identifier: str | None,
    json_output: bool,
) -> dict[str, Any]:
    """Initialize a research run and generate host-agent work packets."""
    return create_run(
        _workspace(ctx), question, profile_name, host=host, model_identifier=model_identifier
    )


@cli.command("status")
@click.argument("run_id")
@json_option
@click.pass_context
@handled("status")
def status_command(ctx: click.Context, run_id: str, json_output: bool) -> dict[str, Any]:
    """Show lifecycle, review, and report-eligibility state."""
    return run_status(_workspace(ctx), run_id)


@cli.command("inspect")
@click.argument("artifact_id")
@json_option
@click.pass_context
@handled("inspect")
def inspect_command(ctx: click.Context, artifact_id: str, json_output: bool) -> dict[str, Any]:
    """Resolve an artifact, citation locator, or page render."""
    return inspect_artifact(_workspace(ctx), artifact_id)


@cli.command("validate")
@click.argument("run_id")
@click.option("--stage", type=click.Choice(list(STAGES_WITH_RESPONSES)))
@json_option
@click.pass_context
@handled("validate")
def validate_command(
    ctx: click.Context, run_id: str, stage: str | None, json_output: bool
) -> dict[str, Any] | tuple[dict[str, Any], int]:
    """Promote one stage or validate a complete run for publication."""
    workspace = _workspace(ctx)
    if stage:
        return promote_stage(workspace, run_id, stage)
    return validate_run(workspace, run_id)


@cli.command("report")
@click.argument("run_id")
@click.option("--draft", is_flag=True, help="Render an explicitly unvalidated draft.")
@json_option
@click.pass_context
@handled("report")
def report_command(
    ctx: click.Context, run_id: str, draft: bool, json_output: bool
) -> dict[str, Any]:
    """Render a Markdown report from canonical JSON artifacts."""
    return generate_report(_workspace(ctx), run_id, draft=draft)


def main() -> None:
    cli(obj={})
