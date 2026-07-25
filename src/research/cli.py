"""The `research` CLI.

Every command emits the same versioned envelope under --json and returns a stable exit code derived
from that envelope, so automation never has to parse prose.

Commands for phases not yet implemented return exit 1 with a `not_implemented` error naming the
phase. They do NOT pretend to succeed. A CLI that exits 0 for work it did not do is the same defect
class as a research report that claims support it does not have — and this codebase is not entitled
to make that mistake in its own tooling.
"""

from __future__ import annotations

import json
import sys
from typing import Any

import click

from . import __version__
from .config import load_workspace
from .errors import Envelope, ExitCode, ResearchError
from .workspace import init_workspace

_JSON_OPT = click.option("--json", "as_json", is_flag=True, help="Emit the machine-readable envelope.")
_WS_OPT = click.option("--workspace", "workspace_path", type=click.Path(),
                       help="Workspace root. Defaults to the nearest parent research.yaml.")


def _emit(env: Envelope, as_json: bool, human: str | None = None) -> None:
    if as_json:
        click.echo(json.dumps(env.to_dict(), indent=2, ensure_ascii=False))
    else:
        if human:
            click.echo(human)
        for w in env.warnings:
            click.echo(f"warning [{w['category']}] {w['message']}", err=True)
        for e in env.errors:
            click.echo(f"error [{e['category']}] {e['message']}", err=True)
    sys.exit(int(env.exit_code()))


def _not_implemented(command: str, phase: str, as_json: bool) -> None:
    env = Envelope(command=command, status="failed")
    env.fail("not_implemented",
             f"`research {command}` is not implemented yet (spec implementation {phase}).",
             phase=phase)
    _emit(env, as_json,
          human=f"research {command}: not implemented yet — {phase}.\n"
                f"This command exits non-zero rather than reporting success it has not earned.")


def _handle(fn: Any, command: str, as_json: bool, **kwargs: Any) -> None:
    env = Envelope(command=command)
    try:
        env.data = fn(**kwargs)
    except ResearchError as exc:
        env.status = "failed"
        env.errors.append(exc.to_dict())
        _emit(env, as_json, human=f"research {command}: {exc.message}")
    except Exception as exc:  # noqa: BLE001
        env.status = "failed"
        env.fail("general_failure", str(exc))
        _emit(env, as_json, human=f"research {command}: {exc}")
    _emit(env, as_json, human=None)


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, prog_name="research")
def main() -> None:
    """Local-first, evidence-first research platform.

    This package does deterministic work: import, extraction, indexing, search, state, validation,
    gating, and reporting. It does not embed a model provider or an agent framework — your host
    environment (Codex, Claude Code, or another) performs the reasoning through work packets.
    """


@main.command("init")
@click.argument("path", type=click.Path(), default=".")
@click.option("--allow-non-empty", is_flag=True,
              help="Initialize inside a non-empty directory without overwriting existing files.")
@click.option("--profile", default="default", show_default=True, help="Default research profile.")
@_JSON_OPT
def cmd_init(path: str, allow_non_empty: bool, profile: str, as_json: bool) -> None:
    """Create a new research workspace."""
    env = Envelope(command="init")
    try:
        env.data = init_workspace(path, allow_non_empty=allow_non_empty, profile=profile)
    except ResearchError as exc:
        env.status = "failed"
        env.errors.append(exc.to_dict())
        _emit(env, as_json, human=f"research init: {exc.message}")
    human = (f"Initialized workspace at {env.data['workspace']}\n"
             f"  config          {env.data['config_path']}\n"
             f"  workflow        {env.data['workflow_version']}\n"
             f"  schemas         {env.data['schema_version']}\n"
             f"  profile         {env.data['default_profile']}\n"
             f"  directories     {len(env.data['directories_created'])}\n\n"
             f"Next: research import <path>")
    _emit(env, as_json, human=human)


@main.command("import")
@click.argument("paths", nargs=-1, type=click.Path(exists=True), required=True)
@_WS_OPT
@_JSON_OPT
def cmd_import(paths: tuple[str, ...], workspace_path: str | None, as_json: bool) -> None:
    """Import local PDF or Markdown documents, preserving originals."""
    _not_implemented("import", "Phase 2 (document import)", as_json)


@main.command("index")
@_WS_OPT
@_JSON_OPT
def cmd_index(workspace_path: str | None, as_json: bool) -> None:
    """Build or rebuild the SQLite FTS5 index from canonical artifacts."""
    _not_implemented("index", "Phase 4 (indexing and search)", as_json)


@main.command("search")
@click.argument("query")
@click.option("--document-type", help="Filter by document type.")
@click.option("--limit", type=int, default=20, show_default=True)
@_WS_OPT
@_JSON_OPT
def cmd_search(query: str, document_type: str | None, limit: int,
               workspace_path: str | None, as_json: bool) -> None:
    """Return ranked passages with exact citation locators."""
    _not_implemented("search", "Phase 4 (indexing and search)", as_json)


@main.command("run")
@click.option("--question", required=True, help="The research question.")
@click.option("--profile", default=None, help="Research profile. Defaults to the workspace default.")
@_WS_OPT
@_JSON_OPT
def cmd_run(question: str, profile: str | None, workspace_path: str | None, as_json: bool) -> None:
    """Initialize a research run and generate stage work packets."""
    _not_implemented("run", "Phase 5 (run management)", as_json)


@main.command("status")
@click.argument("run_id")
@_WS_OPT
@_JSON_OPT
def cmd_status(run_id: str, workspace_path: str | None, as_json: bool) -> None:
    """Show lifecycle state, pending stages, and what is blocking publication."""
    _not_implemented("status", "Phase 5 (run management)", as_json)


@main.command("inspect")
@click.argument("artifact_id")
@_WS_OPT
@_JSON_OPT
def cmd_inspect(artifact_id: str, workspace_path: str | None, as_json: bool) -> None:
    """Resolve and display an artifact, including citation context."""
    _not_implemented("inspect", "Phase 5 (run management)", as_json)


@main.command("validate")
@click.argument("run_id")
@click.option("--stage", default=None, help="Validate a single stage.")
@_WS_OPT
@_JSON_OPT
def cmd_validate(run_id: str, stage: str | None, workspace_path: str | None, as_json: bool) -> None:
    """Validate a run and decide report eligibility."""
    _not_implemented("validate", "Phase 7 (validation)", as_json)


@main.command("report")
@click.argument("run_id")
@click.option("--draft", is_flag=True, help="Render a visibly-marked draft before full validation.")
@_WS_OPT
@_JSON_OPT
def cmd_report(run_id: str, draft: bool, workspace_path: str | None, as_json: bool) -> None:
    """Generate a cited Markdown report from validated artifacts."""
    _not_implemented("report", "Phase 8 (reporting)", as_json)


@main.command("doctor", hidden=True)
@_WS_OPT
@_JSON_OPT
def cmd_doctor(workspace_path: str | None, as_json: bool) -> None:
    """Report what this build can actually do. Used by the honesty test."""
    env = Envelope(command="doctor")
    implemented = ["init"]
    pending = ["import", "index", "search", "run", "status", "inspect", "validate", "report"]
    ws: dict[str, Any] | None = None
    try:
        w = load_workspace(workspace_path)
        ws = {"root": str(w.root), "config_hash": w.config_hash,
              "workflow_version": w.get("workflow_version")}
    except ResearchError:
        env.warn("no_workspace", "not inside a workspace; run `research init`")
    env.data = {"version": __version__, "implemented": implemented, "not_implemented": pending,
                "workspace": ws}
    _emit(env, as_json,
          human=f"research {__version__}\n  implemented      {', '.join(implemented)}\n"
                f"  not implemented  {', '.join(pending)}\n"
                + (f"  workspace        {ws['root']}" if ws else "  workspace        (none)"))


if __name__ == "__main__":
    main()
