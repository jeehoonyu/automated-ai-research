"""Projects — one folder on your machine holding many separate studies.

A **workspace** answers questions about one corpus. That is the right unit for a piece of research
and the wrong unit for a person: you do not have one research topic, you have several, and putting
them in unrelated directories scattered across a disk means nothing can show you where any of them
stand.

A **project** is a directory of studies. A study *is* a workspace — no new artifact model, no second
lifecycle, nothing to keep in step. The project layer only adds discovery and a view across them.

    ~/ai-research/                  the project
      research-project.yaml         names it; studies are DISCOVERED, never listed
      profiles/                     rules every study here may use
      cardiology-statins/           a study: field=medicine, profile=medicine
      pim-architecture/             a study: field=computer-architecture

WHY STUDIES DO NOT SHARE A CORPUS. It is tempting: the same paper cited by two studies would be
imported once, and content-addressing means both would agree on its identity. The reason not to is
that a run **pins its source collection** at creation, and pinning is what makes a run answerable
later. If two studies shared one document store, importing a source into study A would move ground
underneath study B's citations — silently, since B's runs would still resolve but against a corpus
that no longer matches what they pinned. Isolation costs disk. Sharing costs the property the whole
platform exists to provide.

Re-importing the same PDF into a second study is therefore normal and correct. It is
content-addressed, so both studies derive the same `document_id`, and the two runs remain
independently answerable.

WHAT THIS MODULE MUST NOT DO. A project view is a dashboard, and dashboards are where this codebase
keeps finding things rounded up — the web UI shipped a green "Report eligible" banner above ten
blocking checks. So `study_record` reports what is blocked before what succeeded, and counts a run
as published only when the run itself says so. It never derives an opinion of its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from .config import CONFIG_VERSION, WORKSPACE_FILE, Workspace, load_workspace
from .errors import InvalidArguments, WorkspaceError
from .runs.lifecycle import Phase
from .security.paths import atomic_write_text, safe_join, sanitize_filename

PROJECT_FILE = "research-project.yaml"
PROJECT_VERSION = "1.0.0"

#: Directories at a project root that are the project's own, never a study.
RESERVED_NAMES = frozenset({"profiles", "logs", ".git", ".venv", "__pycache__"})


@dataclass
class Study:
    """One workspace inside a project, plus the label that says what field it is in."""

    name: str
    root: Path
    field: str
    profile: str

    @property
    def workspace(self) -> Workspace:
        return load_workspace(self.root)


@dataclass
class Project:
    root: Path
    name: str
    config: dict[str, Any] = field(default_factory=dict)

    @property
    def profiles_dir(self) -> Path:
        return self.root / "profiles"


def find_project_root(start: str | Path | None = None) -> Path | None:
    """Walk upward to the nearest directory containing `research-project.yaml`.

    Deliberately the same shape as `find_workspace_root`, and they compose: standing inside a study
    finds that study, and walking on up finds the project it belongs to.
    """
    import os

    cur = Path(start or os.getcwd()).resolve()
    for candidate in (cur, *cur.parents):
        if (candidate / PROJECT_FILE).is_file():
            return candidate
    return None


def load_project(explicit: str | Path | None = None, *,
                 start: str | Path | None = None) -> Project:
    if explicit is not None:
        root = Path(explicit).resolve()
        if not (root / PROJECT_FILE).is_file():
            raise WorkspaceError(
                f"no {PROJECT_FILE} in {root}",
                detail={"path": str(root), "hint": "run `research project init <dir>` first"})
    else:
        found = find_project_root(start)
        if found is None:
            raise WorkspaceError(
                "not inside a research project (no research-project.yaml here or in any parent)",
                detail={"hint": "run `research project init <dir>`, or pass --project <dir>"})
        root = found

    with open(root / PROJECT_FILE, encoding="utf-8") as fh:
        config = yaml.safe_load(fh) or {}
    return Project(root=root, name=str(config.get("name") or root.name), config=config)


def init_project(target: str | Path, *, name: str | None = None) -> dict[str, Any]:
    """Create a project root. It holds no research of its own — only studies."""
    root = Path(target).resolve()
    if (root / PROJECT_FILE).is_file():
        raise WorkspaceError(f"a project already exists at {root}",
                             detail={"path": str(root / PROJECT_FILE)})
    if (root / WORKSPACE_FILE).is_file():
        raise WorkspaceError(
            f"{root} is already a workspace, and a workspace cannot also be a project",
            detail={"path": str(root),
                    "hint": "make the project one directory up, and move this workspace into it"})

    root.mkdir(parents=True, exist_ok=True)
    (root / "profiles").mkdir(exist_ok=True)
    config = {
        "project_version": PROJECT_VERSION,
        "config_version": CONFIG_VERSION,
        "name": name or root.name,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    atomic_write_text(
        root / PROJECT_FILE,
        "# A research project: a folder of independent studies.\n"
        "#\n"
        "# Studies are DISCOVERED, not listed here — any immediate subdirectory containing a\n"
        "# research.yaml is a study. Nothing to keep in step, and moving a study out of the\n"
        "# project leaves it a perfectly good standalone workspace.\n"
        "#\n"
        "# Profiles in ./profiles/ are offered to every study in this project.\n\n"
        + yaml.safe_dump(config, sort_keys=False, allow_unicode=True),
        root=root)
    return {"project_root": str(root), "name": config["name"],
            "profiles_dir": str(root / "profiles"), "study_count": 0}


def study_dir_name(name: str) -> str:
    """A directory name for a study, from whatever the user typed.

    Runs through `sanitize_filename` because a study name reaches the filesystem and users type
    things like `COVID-19: outcomes (2024)`.
    """
    cleaned = sanitize_filename(name.strip().replace(" ", "-"), fallback="")
    if not cleaned:
        raise InvalidArguments(f"cannot make a directory name from {name!r}",
                               detail={"name": name})
    return cleaned


def new_study(project: Project, name: str, *, field_name: str,
              profile: str = "default") -> dict[str, Any]:
    """Create a study inside a project. A study is an ordinary workspace, plus its field."""
    from .workspace import init_workspace

    directory = study_dir_name(name)
    root = safe_join(project.root, directory)
    if (root / WORKSPACE_FILE).is_file():
        raise WorkspaceError(f"a study already exists at {root}", detail={"path": str(root)})
    if directory in RESERVED_NAMES:
        raise InvalidArguments(
            f"{directory!r} is reserved by the project itself and cannot name a study",
            detail={"reserved": sorted(RESERVED_NAMES)})

    result = init_workspace(root, profile=profile)

    # The field is recorded in the study's own config, not in a project-level registry. A registry
    # is a second copy of a fact, and the two would drift the first time someone moved a directory.
    config_path = root / WORKSPACE_FILE
    with open(config_path, encoding="utf-8") as fh:
        config = yaml.safe_load(fh) or {}
    config["field"] = field_name
    config["study_name"] = name
    atomic_write_text(config_path,
                      "# Automated AI Research workspace configuration.\n"
                      "# This workspace is a study inside the project one directory up.\n\n"
                      + yaml.safe_dump(config, sort_keys=False, allow_unicode=True),
                      root=root)
    return {**result, "study": name, "field": field_name, "directory": directory,
            "profile": profile}


def studies(project: Project) -> list[Study]:
    """Every study in the project, discovered from the filesystem.

    Discovery rather than a manifest, on purpose. A listed study that no longer exists, or an
    existing one nobody listed, are both states a registry can reach and the filesystem cannot.
    """
    out: list[Study] = []
    if not project.root.is_dir():
        return out
    for entry in sorted(project.root.iterdir()):
        if not entry.is_dir() or entry.name in RESERVED_NAMES or entry.name.startswith("."):
            continue
        if not (entry / WORKSPACE_FILE).is_file():
            continue
        try:
            with open(entry / WORKSPACE_FILE, encoding="utf-8") as fh:
                config = yaml.safe_load(fh) or {}
        except (OSError, yaml.YAMLError):
            config = {}
        out.append(Study(
            name=str(config.get("study_name") or entry.name),
            root=entry,
            field=str(config.get("field") or "unspecified"),
            profile=str(config.get("default_profile") or "default"),
        ))
    return out


def study_record(study: Study) -> dict[str, Any]:
    """What this study has actually established — blocked first, published last.

    "Reputation" for a research topic is not a score. It is the record: how many questions were
    asked, how many produced a publishable answer, how many were stopped and by what. A single
    number would average a blocked run together with a published one, which is the thing this
    platform exists to refuse.

    A run counts as published only if its own lifecycle says so. This function derives nothing.
    """
    from .runs.manager import list_runs
    from .runs.manager import status as run_status

    record: dict[str, Any] = {
        "study": study.name, "field": study.field, "profile": study.profile,
        "root": str(study.root),
        # The directory name, not the display name: this is what a URL and a path are built from,
        # and the two differ the moment someone types a study name with a space in it.
        "directory": study.root.name,
        "runs": [], "unreadable": None,
    }
    try:
        ws = study.workspace
        rows = list_runs(ws)
    except Exception as exc:  # noqa: BLE001 - one broken study must not hide the others
        record["unreadable"] = f"{type(exc).__name__}: {exc}"
        return record

    documents = list((ws.root / "documents" / "manifests").glob("*.json"))
    record["document_count"] = len(documents)
    record["indexed"] = (ws.root / "indexes" / "index-manifest.json").is_file()

    for row in rows:
        try:
            st = run_status(ws, row["run_id"])
        except Exception as exc:  # noqa: BLE001
            record["runs"].append({"run_id": row["run_id"], "unreadable": str(exc)})
            continue
        record["runs"].append({
            "run_id": row["run_id"],
            "question": st["research_question"],
            "phase": st["phase"],
            "disposition": st["disposition"],
            "published": st["phase"] == str(Phase.PUBLISHED),
            "report_eligible": bool(st["report_eligible"]),
            "blocking": [b["message"] for b in st["blocking"]],
            "human_review_required": bool(st["human_review_required"]),
        })

    runs = [r for r in record["runs"] if "unreadable" not in r]
    record["run_count"] = len(record["runs"])
    record["published_count"] = sum(1 for r in runs if r["published"])
    record["eligible_count"] = sum(1 for r in runs if r["report_eligible"] and not r["published"])
    record["blocked_count"] = sum(
        1 for r in runs if not r["report_eligible"] and not r["published"])
    record["needs_human_count"] = sum(1 for r in runs if r["human_review_required"])
    return record


def project_overview(project: Project) -> dict[str, Any]:
    """Every study and its record. Ordering puts what needs attention first."""
    records = [study_record(s) for s in studies(project)]

    def needs_attention(record: dict[str, Any]) -> tuple[int, str]:
        if record.get("unreadable"):
            return (0, record["study"])
        if record.get("needs_human_count"):
            return (1, record["study"])
        if record.get("blocked_count"):
            return (2, record["study"])
        return (3, record["study"])

    records.sort(key=needs_attention)
    fields = sorted({r["field"] for r in records})
    return {
        "project": project.name,
        "root": str(project.root),
        "study_count": len(records),
        "fields": fields,
        "studies": records,
        "totals": {
            "runs": sum(r.get("run_count", 0) for r in records),
            "published": sum(r.get("published_count", 0) for r in records),
            "blocked": sum(r.get("blocked_count", 0) for r in records),
            "needs_human": sum(r.get("needs_human_count", 0) for r in records),
            "unreadable_studies": sum(1 for r in records if r.get("unreadable")),
        },
    }
