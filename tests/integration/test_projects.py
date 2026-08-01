"""One folder, many studies — and the properties that keep them from contaminating each other.

A project is a thin layer: discovery, and a view across studies. The tests that matter are therefore
not about the layer working, but about the two things it could quietly break — isolation between
studies, and the honesty of a summary that spans them.
"""

from __future__ import annotations

import json
import threading
import urllib.request
from pathlib import Path

import pytest
import yaml

from research.config import WORKSPACE_FILE, Workspace, load_workspace
from research.errors import InvalidArguments, WorkspaceError
from research.profiles import known_profiles, load_profile, profile_search_path
from research.projects import (
    PROJECT_FILE,
    find_project_root,
    init_project,
    load_project,
    new_study,
    project_overview,
    studies,
    study_dir_name,
)
from research.runs.manager import create_run
from research.ui.server import build_server


@pytest.fixture
def project(tmp_path: Path):
    init_project(tmp_path / "ai-research", name="Test project")
    return load_project(tmp_path / "ai-research")


# ------------------------------------------------------------------------------------ the shape


def test_a_project_holds_studies_in_different_fields(project):
    new_study(project, "Statins and outcomes", field_name="medicine", profile="medicine")
    new_study(project, "PIM architecture", field_name="computer-architecture")

    found = {s.name: s for s in studies(project)}
    assert set(found) == {"Statins and outcomes", "PIM architecture"}
    assert found["Statins and outcomes"].field == "medicine"
    assert found["Statins and outcomes"].profile == "medicine"
    assert found["PIM architecture"].field == "computer-architecture"


def test_a_study_is_an_ordinary_workspace(project):
    """No second model. Moving a study out of its project leaves a working workspace behind."""
    result = new_study(project, "Solo", field_name="physics")
    root = Path(result["workspace"])
    assert (root / WORKSPACE_FILE).is_file()
    ws = load_workspace(root)
    assert ws.get("field") == "physics"
    # And the ordinary commands work on it with no project involved.
    assert create_run(ws, question="does it stand alone?")["run_id"].startswith("RUN-")


def test_studies_are_discovered_not_registered(project):
    """A registry can say a study exists when it does not, and vice versa. The filesystem cannot."""
    new_study(project, "One", field_name="a")
    assert len(studies(project)) == 1

    # A directory added by hand is found; the project file is never rewritten.
    before = (project.root / PROJECT_FILE).read_text(encoding="utf-8")
    from research.workspace import init_workspace
    init_workspace(project.root / "added-by-hand")
    assert {s.name for s in studies(project)} == {"One", "added-by-hand"}
    assert (project.root / PROJECT_FILE).read_text(encoding="utf-8") == before


def test_the_projects_own_directories_are_not_studies(project):
    """`profiles/` belongs to the project. Listing it as a study would be absurd and confusing."""
    assert (project.root / "profiles").is_dir()
    assert studies(project) == []
    with pytest.raises(InvalidArguments):
        new_study(project, "profiles", field_name="x")


@pytest.mark.parametrize(("typed", "expected"), [
    # Spaces become hyphens so the path is pleasant to type; `:` is not legal in a Windows path
    # component and is sanitized, not silently dropped.
    ("COVID-19: outcomes (2024)", "COVID-19_-outcomes-(2024)"),
    ("a b  c", "a-b--c"),
    ("  padded  ", "padded"),
])
def test_a_study_name_reaches_the_filesystem_safely(typed: str, expected: str):
    assert study_dir_name(typed) == expected


@pytest.mark.parametrize("hostile", ["..", "../escape", "CON", "", "   ", "."])
def test_a_study_name_cannot_escape_or_name_a_device(hostile: str, project):
    """A study name is user input that becomes a directory. `..` and the Windows device names are
    the two ways that goes wrong."""
    try:
        directory = study_dir_name(hostile)
    except InvalidArguments:
        return                                    # refused outright is a fine answer
    assert ".." not in directory
    assert directory.upper() not in {"CON", "PRN", "AUX", "NUL"}
    result = new_study(project, hostile, field_name="x")
    assert Path(result["workspace"]).resolve().parent == project.root.resolve()


def test_a_workspace_cannot_also_be_a_project(tmp_path: Path):
    from research.workspace import init_workspace

    init_workspace(tmp_path / "ws")
    with pytest.raises(WorkspaceError) as exc:
        init_project(tmp_path / "ws")
    assert "cannot also be a project" in exc.value.message


def test_discovery_walks_up_from_inside_a_study(project):
    result = new_study(project, "Deep", field_name="a")
    inside = Path(result["workspace"]) / "runs"
    assert find_project_root(inside) == project.root


# ------------------------------------------------------------------------------------- isolation
#
# The property the whole design rests on: a run pins its source collection, so one study importing a
# document must never change what another study's runs resolve against.


def test_studies_do_not_share_a_corpus(project, tmp_path: Path):
    from research.importers.importer import import_paths

    a = load_workspace(new_study(project, "A", field_name="x")["workspace"])
    b = load_workspace(new_study(project, "B", field_name="y")["workspace"])

    source = tmp_path / "paper.md"
    source.write_text("# Paper\n\nA finding worth citing.\n", encoding="utf-8")
    import_paths(a, [source])

    assert len(list((a.root / "documents" / "manifests").glob("*.json"))) == 1
    assert list((b.root / "documents" / "manifests").glob("*.json")) == [], \
        "importing into one study must not populate another"
    assert list((b.root / "originals").rglob("*")) == [] or not any(
        p.is_file() for p in (b.root / "originals").rglob("*"))


def test_the_same_document_imported_into_two_studies_keeps_one_identity(project, tmp_path: Path):
    """Isolation costs disk, not agreement. Content-addressing means both studies name it the same,
    so a finding in one is recognisable in the other even though nothing is shared."""
    from research.importers.importer import import_paths

    a = load_workspace(new_study(project, "A", field_name="x")["workspace"])
    b = load_workspace(new_study(project, "B", field_name="y")["workspace"])
    source = tmp_path / "paper.md"
    source.write_text("# Paper\n\nA finding worth citing.\n", encoding="utf-8")

    ids = []
    for ws in (a, b):
        import_paths(ws, [source])
        manifest = next((ws.root / "documents" / "manifests").glob("*.json"))
        ids.append(json.loads(manifest.read_text(encoding="utf-8"))["document_id"])
    assert ids[0] == ids[1]


# -------------------------------------------------------------------------------------- profiles


def test_a_project_profile_reaches_every_study_but_not_beyond(project, tmp_path: Path):
    (project.root / "profiles" / "lab.yaml").write_text(yaml.safe_dump({
        "name": "lab", "risk": "high",
        "reviewer_independence": {"minimum": "confirmed_independent"},
    }), encoding="utf-8")

    study_root = Path(new_study(project, "Inside", field_name="x")["workspace"])
    assert "lab" in known_profiles(study_root)
    assert load_profile("lab", study_root).risk == "high"

    from research.workspace import init_workspace
    init_workspace(tmp_path / "outside")
    assert "lab" not in known_profiles(tmp_path / "outside")


def test_a_study_profile_wins_over_the_projects(project):
    """One-way: a study may make itself stricter than its project. The search stops at the first
    file with the name, so a project cannot loosen a study that has already spoken."""
    (project.root / "profiles" / "house.yaml").write_text(
        yaml.safe_dump({"name": "house", "risk": "standard"}), encoding="utf-8")
    study_root = Path(new_study(project, "Strict", field_name="x")["workspace"])
    (study_root / "profiles" / "house.yaml").write_text(
        yaml.safe_dump({"name": "house", "risk": "high"}), encoding="utf-8")

    order = profile_search_path(study_root)
    assert order[0] == study_root / "profiles"
    assert order[1] == project.root / "profiles"
    assert load_profile("house", study_root).risk == "high"


# --------------------------------------------------------------------- the summary does not lie


def test_the_overview_puts_what_needs_attention_first(project):
    """A project page is the most tempting place in this codebase to average a blocked run together
    with a published one."""
    quiet = load_workspace(new_study(project, "Quiet", field_name="x")["workspace"])
    busy = load_workspace(new_study(project, "Busy", field_name="y")["workspace"])
    create_run(busy, question="a question nobody has answered yet")

    overview = project_overview(project)
    assert overview["studies"][0]["study"] == "Busy", "the study with a blocked run must sort first"
    assert overview["totals"]["blocked"] == 1
    assert overview["totals"]["published"] == 0
    assert quiet.root.name  # quiet study still listed
    assert {s["study"] for s in overview["studies"]} == {"Quiet", "Busy"}


def test_a_run_counts_as_published_only_when_its_own_lifecycle_says_so(project):
    busy = load_workspace(new_study(project, "Busy", field_name="y")["workspace"])
    create_run(busy, question="unfinished")

    record = next(s for s in project_overview(project)["studies"] if s["study"] == "Busy")
    assert record["published_count"] == 0
    assert record["blocked_count"] == 1
    assert record["runs"][0]["published"] is False
    assert record["runs"][0]["report_eligible"] is False


def test_one_unreadable_study_does_not_hide_the_others(project):
    """A project view that dies on a corrupt study shows you nothing about the healthy ones."""
    load_workspace(new_study(project, "Fine", field_name="x")["workspace"])
    broken = Path(new_study(project, "Broken", field_name="y")["workspace"])
    (broken / WORKSPACE_FILE).write_text("{{{ not yaml", encoding="utf-8")

    overview = project_overview(project)
    names = {s["study"] for s in overview["studies"]}
    assert "Fine" in names and "Broken" in names
    broken_record = next(s for s in overview["studies"] if s["study"] == "Broken")
    assert broken_record["unreadable"]
    assert overview["totals"]["unreadable_studies"] == 1
    # And it sorts to the very top: a study that cannot be read is not a study with no findings.
    assert overview["studies"][0]["study"] == "Broken"


# --------------------------------------------------------------------------------------- the UI


def _serve(project):
    """A running project server plus a fetcher. Returns (get, shutdown)."""
    server = build_server(Workspace(root=project.root), host="127.0.0.1", port=0,
                          quiet=True, project=project)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]

    def get(path: str) -> tuple[int, str]:
        import urllib.error
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=10) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", "replace")

    def shutdown() -> None:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    return get, shutdown


def test_a_study_is_browsable_in_place_from_the_project_page(project):
    """Clicking a study opens it under `/studies/<dir>/`, and every link inside stays there."""
    import re

    busy = load_workspace(new_study(project, "Busy", field_name="medicine")["workspace"])
    create_run(busy, question="a question nobody has answered yet")

    get, shutdown = _serve(project)
    try:
        code, home = get("/")
        assert code == 200
        links = sorted(set(re.findall(r'href="(/studies/[^"]+)"', home)))
        assert links, "the project page offers no way into a study"

        prefix = "/studies/Busy"
        code, study_home = get(prefix + "/")
        assert code == 200
        # The way back out, and the study's own name in the nav rather than a generic label.
        assert 'href="/" class="crumb"' in study_home
        assert "Busy" in study_home

        for path in (prefix + "/documents", prefix + "/search?q=anything"):
            assert get(path)[0] == 200, path

        # Every internal link on the study's pages carries the prefix. One that did not would
        # silently jump to the project root and 404, or worse, to another study's page.
        run_links = re.findall(r'href="(/studies/Busy/runs/[^"]+)"', study_home)
        assert run_links, "the study overview does not link to its run"
        code, run_page = get(run_links[0])
        assert code == 200
        assert 'href="/runs/' not in run_page, "a link escaped the study prefix"
        assert 'href="/artifacts/' not in run_page, "a link escaped the study prefix"
    finally:
        shutdown()


@pytest.mark.parametrize("hostile", [
    "/studies/../../etc/passwd",
    "/studies/nope/",
    "/studies/profiles/",
    "/studies/..%2f..%2fresearch-project.yaml",
    "/studies//",
])
def test_the_study_prefix_is_not_a_way_out_of_the_project(project, hostile: str):
    """The workspace is resolved by MATCHING the segment against the studies the project actually
    contains — never by joining it onto a path. `profiles/` is the project's own and is not a
    study, so it is refused like anything else that is not one."""
    new_study(project, "Real", field_name="x")
    get, shutdown = _serve(project)
    try:
        code, body = get(hostile)
        assert code == 404, hostile
        assert "research-project.yaml" not in body or "no study" in body
    finally:
        shutdown()


def test_a_plain_workspace_still_has_unprefixed_links(complete_run):
    """`base` is empty outside a project. If it leaked a prefix, every ordinary install would break.
    """
    ws, run_id, _meta = complete_run
    server = build_server(ws, host="127.0.0.1", port=0, quiet=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/"
        with urllib.request.urlopen(url, timeout=10) as response:
            body = response.read().decode("utf-8")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert f'href="/runs/{run_id}"' in body
    assert "/studies/" not in body
    assert 'class="crumb"' not in body, "a standalone workspace has no project to go back to"


def test_the_project_page_lists_every_study_and_leads_with_the_blocked_one(project):
    new_study(project, "Quiet", field_name="physics")
    busy = load_workspace(new_study(project, "Busy", field_name="medicine")["workspace"])
    create_run(busy, question="a question nobody has answered yet")

    server = build_server(Workspace(root=project.root), host="127.0.0.1", port=0,
                          quiet=True, project=project)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/"
        with urllib.request.urlopen(url, timeout=10) as response:
            body = response.read().decode("utf-8")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert "Quiet" in body and "Busy" in body
    assert "physics" in body and "medicine" in body
    assert "blocked from publication" in body
    assert "Nothing is blocked" not in body
    # The blocked study is rendered before the quiet one.
    assert body.index("Busy") < body.index("Quiet")
