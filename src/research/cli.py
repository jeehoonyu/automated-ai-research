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
from pathlib import Path
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
    from .importers.importer import import_paths

    env = Envelope(command="import")
    try:
        ws = load_workspace(workspace_path)
        env.data = import_paths(ws, list(paths))
    except ResearchError as exc:
        env.status = "failed"
        env.errors.append(exc.to_dict())
        _emit(env, as_json, human=f"research import: {exc.message}")

    d = env.data
    # Partial processing must not read as complete success (spec section 34). A failed source or a
    # document needing human review sets a non-ok status, and the exit code follows from it.
    for doc in d["documents"]:
        if doc["error"]:
            env.warn("source_processing_failure", doc["error"], path=doc["path"])
    if d["failed_count"]:
        env.status = "partial"
    if d["needs_human_review_count"]:
        env.warn("human_review_required",
                 f"{d['needs_human_review_count']} document(s) extracted with a status that cannot "
                 f"back a citation without human review",
                 documents=[x["document_id"] for x in d["documents"]
                            if x["extraction_status"] in
                            {"ocr_required", "partially_extracted", "ambiguous",
                             "human_review_required"}])
        if env.status == "ok":
            env.status = "partial"

    lines = [
        f"imported   {d['imported_count']}",
        f"duplicate  {d['duplicate_count']}",
        f"failed     {d['failed_count']}",
        f"warnings   {d['warning_count']}",
    ]
    if d["needs_human_review_count"]:
        lines.append(f"needs human review  {d['needs_human_review_count']}")
    for doc in d["documents"]:
        mark = "dup " if doc["duplicate"] else ("ERR " if doc["error"] else "    ")
        lines.append(f"  {mark}{Path(doc['path']).name}  {doc['extraction_status'] or doc['error']}")
    _emit(env, as_json, human="\n".join(lines))


@main.command("index")
@_WS_OPT
@_JSON_OPT
def cmd_index(workspace_path: str | None, as_json: bool) -> None:
    """Build or rebuild the SQLite FTS5 index from canonical artifacts."""
    from .indexing.builder import build_index

    env = Envelope(command="index")
    try:
        ws = load_workspace(workspace_path)
        result = build_index(ws)
    except ResearchError as exc:
        env.status = "failed"
        env.errors.append(exc.to_dict())
        _emit(env, as_json, human=f"research index: {exc.message}")

    env.data = {
        "document_count": result.document_count,
        "chunk_count": result.chunk_count,
        "skipped_ineligible_chunks": result.skipped_ineligible,
        "index_hash": result.index_hash,
        "sqlite_file_hash": result.sqlite_file_hash,
        "manifest_path": result.manifest_path,
    }
    for warning in result.warnings:
        env.warn("index_warning", warning)
    _emit(env, as_json, human="\n".join([
        f"indexed {result.chunk_count} chunk(s) from {result.document_count} document(s)",
        f"  skipped (not index-eligible)  {result.skipped_ineligible}",
        f"  index_hash                    {result.index_hash}",
        f"  manifest                      {result.manifest_path}",
    ]))


@main.command("search")
@click.argument("query")
@click.option("--document-type", help="Filter by document type (pdf, markdown).")
@click.option("--document-id", help="Restrict to one document.")
@click.option("--limit", type=int, default=20, show_default=True)
@_WS_OPT
@_JSON_OPT
def cmd_search(query: str, document_type: str | None, document_id: str | None, limit: int,
               workspace_path: str | None, as_json: bool) -> None:
    """Return ranked passages with exact citation locators."""
    from .search.engine import search

    env = Envelope(command="search")
    try:
        ws = load_workspace(workspace_path)
        env.data = search(ws, query, document_type=document_type, document_id=document_id,
                          limit=limit)
    except ResearchError as exc:
        env.status = "failed"
        env.errors.append(exc.to_dict())
        _emit(env, as_json, human=f"research search: {exc.message}")

    d = env.data
    lines = [f"{d['result_count']} result(s) for {d['query']!r}",
             "  (BM25 lexical overlap — not a measure of support)"]
    for r in d["results"]:
        where = f"p{r['page']}" if r["page"] is not None else f"L{r['line_start']}"
        section = " › ".join(r["section_path"]) if r["section_path"] else "-"
        lines.append(f"  {r['rank']:2d}. {(r['source']['title'] or '?')[:34]:34s} {where:>6s}  {section}")
        lines.append(f"      {r['snippet'][:96]}")
        lines.append(f"      {r['chunk_id']}")
    _emit(env, as_json, human="\n".join(lines))


@main.command("run")
@click.option("--question", required=True, help="The research question.")
@click.option("--profile", default=None, help="Research profile. Defaults to the workspace default.")
@_WS_OPT
@_JSON_OPT
def cmd_run(question: str, profile: str | None, workspace_path: str | None, as_json: bool) -> None:
    """Initialize a research run and generate stage work packets."""
    from .runs.manager import create_run

    env = Envelope(command="run")
    try:
        ws = load_workspace(workspace_path)
        env.data = create_run(ws, question=question, profile=profile)
    except ResearchError as exc:
        env.status = "failed"
        env.errors.append(exc.to_dict())
        _emit(env, as_json, human=f"research run: {exc.message}")

    d = env.data
    if d["source_document_count"] == 0:
        env.warn("empty_corpus", "this workspace has no documents; import some before planning")
    if not d["index_hash"]:
        env.warn("no_index", "no index has been built; `research search` will not work")
    _emit(env, as_json, human="\n".join([
        f"run {d['run_id']}",
        f"  profile        {d['profile']}",
        f"  phase          {d['phase']} / {d['disposition']}",
        f"  sources        {d['source_document_count']} document(s)",
        f"  packets        {d['packet_count']} written to runs/{d['run_id']}/packets/",
        "",
        f"Next: give your agent runs/{d['run_id']}/packets/00-planning.json",
        f"      then `research validate {d['run_id']} --stage planning`",
    ]))


@main.command("status")
@click.argument("run_id")
@_WS_OPT
@_JSON_OPT
def cmd_status(run_id: str, workspace_path: str | None, as_json: bool) -> None:
    """Show lifecycle state, pending stages, and what is blocking publication."""
    from .runs.manager import status

    env = Envelope(command="status")
    try:
        ws = load_workspace(workspace_path)
        env.data = status(ws, run_id)
    except ResearchError as exc:
        env.status = "failed"
        env.errors.append(exc.to_dict())
        _emit(env, as_json, human=f"research status: {exc.message}")

    d = env.data
    if d["blocking"]:
        env.status = "blocked"
        for b in d["blocking"]:
            env.warn(b["category"], b["message"])
    lines = [
        f"run {d['run_id']}",
        f"  question       {d['research_question'][:70]}",
        f"  phase          {d['phase']} / {d['disposition']}",
        f"  completed      {len(d['completed_stages'])}/10 stages",
        f"  next stage     {d['next_stage'] or '(none)'}",
        f"  report         {'eligible' if d['report_eligible'] else 'not eligible'} "
        f"- {d['report_eligible_reason']}",
    ]
    if d["responses_awaiting_validation"]:
        lines.append(f"  unvalidated    {', '.join(d['responses_awaiting_validation'])}")
    if d["next_packet"]:
        lines.append(f"  next packet    {d['next_packet']}")
    _emit(env, as_json, human="\n".join(lines))


@main.command("inspect")
@click.argument("artifact_id")
@_WS_OPT
@_JSON_OPT
def cmd_inspect(artifact_id: str, workspace_path: str | None, as_json: bool) -> None:
    """Resolve and display an artifact, including citation context."""
    from .runs.inspector import inspect

    env = Envelope(command="inspect")
    try:
        ws = load_workspace(workspace_path)
        env.data = inspect(ws, artifact_id)
    except ResearchError as exc:
        env.status = "failed"
        env.errors.append(exc.to_dict())
        _emit(env, as_json, human=f"research inspect: {exc.message}")

    d = env.data
    lines = [f"{d['kind']}  {artifact_id}"]
    if d["kind"] == "chunk":
        if not d["resolves"]:
            env.fail("locator_resolution_failure",
                     f"this chunk's locator does not resolve: {d['resolution_status']}")
        lines += [
            f"  document     {d['document_id']}",
            f"  position     " + (f"page {d['page']}" if d["page"] is not None
                                  else f"lines {d['line_start']}-{d['line_end']}"),
            f"  section      {' > '.join(d['section_path']) or '-'}",
            f"  resolves     {d['resolution_status']}",
            f"  indexable    {d['index_eligible']}",
            "",
            "--- resolved text (re-sliced from the stored normalized text) ---",
            (d["resolved_text"] or "")[:1200],
        ]
    elif d["kind"] == "document":
        lines += [
            f"  status       {d['extraction_status']}",
            f"  aliases      {', '.join(d['aliases'])}",
            f"  pages        {d['page_count']}   renders {len(d['renders'])}",
            f"  chunks       {d['chunk_count']} ({d['index_eligible_chunk_count']} indexable)",
            f"  ocr pages    {d['ocr_required_pages'] or 'none'}",
        ]
    else:
        lines += [
            f"  question     {d['research_question'][:70]}",
            f"  phase        {d['phase']} / {d['disposition']}",
            f"  events       {d['event_count']}",
        ]
    _emit(env, as_json, human="\n".join(lines))


@main.command("validate")
@click.argument("run_id")
@click.option("--stage", default=None, help="Validate a single stage.")
@_WS_OPT
@_JSON_OPT
def cmd_validate(run_id: str, stage: str | None, workspace_path: str | None, as_json: bool) -> None:
    """Validate a run and decide report eligibility."""
    from .validation.validator import validate_run

    env = Envelope(command="validate")
    try:
        ws = load_workspace(workspace_path)
        env.data = validate_run(ws, run_id)
    except ResearchError as exc:
        env.status = "failed"
        env.errors.append(exc.to_dict())
        _emit(env, as_json, human=f"research validate: {exc.message}")

    d = env.data
    if not d["report_eligible"]:
        env.status = "blocked"
    for err in d["blocking_errors"]:
        env.warn(f"gate_{err['status']}", f"{err['check']}: {err['detail']}")
    if d["human_review_required"]:
        env.warn("human_review_required", "; ".join(d["human_review_reasons"])[:300])

    icon = {"passed": "PASS", "failed": "FAIL", "not_evaluated": "N/EVAL",
            "not_applicable": "n/a"}
    lines = [
        f"validation of {run_id}",
        f"  passed {d['passed']}   failed {d['failed']}   "
        f"not evaluated {d['not_evaluated']}   n/a {d['not_applicable']}",
        "",
    ]
    for check in d["checks"]:
        lines.append(f"  {icon[check['status']]:>6s}  {check['check']}")
        if check["status"] in ("failed", "not_evaluated") and check.get("detail"):
            lines.append(f"          {check['detail'][:110]}")
    lines += [
        "",
        f"  REPORT ELIGIBLE: {d['report_eligible']}",
    ]
    if not d["report_eligible"]:
        lines.append("  A check that could not be evaluated blocks publication exactly as a "
                     "failure does.")
    _emit(env, as_json, human="\n".join(lines))


@main.command("report")
@click.argument("run_id")
@click.option("--draft", is_flag=True, help="Render a visibly-marked draft before full validation.")
@_WS_OPT
@_JSON_OPT
def cmd_report(run_id: str, draft: bool, workspace_path: str | None, as_json: bool) -> None:
    """Generate a cited Markdown report from validated artifacts."""
    from .reporting.renderer import render_report

    env = Envelope(command="report")
    try:
        ws = load_workspace(workspace_path)
        result = render_report(ws, run_id, draft=draft)
    except ResearchError as exc:
        env.status = "blocked" if exc.category == "report_gating_failure" else "failed"
        env.errors.append(exc.to_dict())
        _emit(env, as_json, human=f"research report: {exc.message}")

    env.data = {
        "run_id": result.run_id,
        "draft": result.draft,
        "report_path": result.report_path,
        "report_sha256": result.report_sha256,
        "manifest_path": result.manifest_path,
        "claim_count": result.claim_count,
        "citation_count": result.citation_count,
        "overstatements": result.overstatements,
    }
    if result.draft:
        env.status = "partial"
        env.warn("draft_report",
                 "this is a DRAFT rendered before validation passed; it is not a published output")
    for over in result.overstatements:
        env.warn("claim_language_exceeds_classification", over["detail"], claim_id=over["claim_id"])

    _emit(env, as_json, human="\n".join([
        f"{'DRAFT ' if result.draft else ''}report written",
        f"  path        {result.report_path}",
        f"  sha256      {result.report_sha256}",
        f"  manifest    {result.manifest_path}",
        f"  claims      {result.claim_count}   citations {result.citation_count}",
    ] + ([f"  flagged     {len(result.overstatements)} claim(s) whose wording may exceed their "
          f"validated classification"] if result.overstatements else [])))


@main.command("doctor", hidden=True)
@_WS_OPT
@_JSON_OPT
def cmd_doctor(workspace_path: str | None, as_json: bool) -> None:
    """Report what this build can actually do. Used by the honesty test."""
    env = Envelope(command="doctor")
    implemented = ["init", "import", "index", "search", "run", "status", "inspect",
                   "validate", "report"]
    pending = []
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
