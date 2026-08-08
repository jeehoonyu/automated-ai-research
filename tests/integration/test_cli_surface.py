"""Every CLI command, driven as a command.

WHY THIS FILE EXISTS. `research inspect <evidence-id>` died with `KeyError: 'research_question'` for
three of the six artifact kinds it can return, and 668 tests did not notice. The coverage was real
but shaped like a keyhole: `tests/integration/test_exit_codes.py` drives five commands by subprocess
(`init`, `import`, `index`, `run`, `validate`), always with `--json`, asserting only the process
exit code — and everything else tested the library functions underneath. Nothing asserted a
command's rendered human output, the code path the defect was in and the one every user reads.

So this file is deliberately shallow and wide. It does not re-test what the layer below already
pins. It asks the two questions that layer cannot:

    does the command run at all, in BOTH renderings
    does a command that should refuse actually refuse

A sweep like this is worth keeping even when it finds nothing — running it the first time found no
crash beyond `inspect` and no refusal that wrongly succeeded, which is how "isolated" was
established rather than assumed.

WHAT THIS FILE DOES NOT COVER, stated because the first draft implied otherwise. Its workspace has
a fresh run with no artifacts, so there are no evidence, claim or review ids here to inspect —
per-kind rendering of `research inspect` is pinned in `test_read_surface.py`, over a completed run.
Mutating away `inspect`'s claim branch leaves this file green. Breadth here, depth there; claiming
depth it does not have would make this exactly the kind of reassuring-but-empty check the
repository exists to refuse.

EXIT CODES ARE NOT ALL ZERO ON SUCCESS. `status` and `next` on a run with outstanding work exit 5:
the run is blocked, that is a true statement about it, and automation is told to branch on it
(spec §34). A first draft of this sweep called those failures. `_ok` names the acceptable set per
command rather than assuming 0, because "the command worked" and "the run is fine" are different
questions and this file only asks the first.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner, Result

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fixtures.make_fixtures import build  # noqa: E402

from research.cli import main  # noqa: E402


def _invoke(*args: object) -> Result:
    result = CliRunner().invoke(main, [str(a) for a in args])
    if result.exception is not None and not isinstance(result.exception, SystemExit):
        raise AssertionError(
            f"`research {' '.join(str(a) for a in args)}` raised "
            f"{type(result.exception).__name__}: {result.exception}") from result.exception
    return result


def _ok(*args: object, allowed: tuple[int, ...] = (0,)) -> Result:
    result = _invoke(*args)
    assert result.exit_code in allowed, (
        f"`research {' '.join(str(a) for a in args)}` exited {result.exit_code}, "
        f"expected one of {allowed}\n{result.output}")
    return result


def _refuses(*args: object, because: str) -> Result:
    result = _invoke(*args)
    assert result.exit_code != 0, (
        f"`research {' '.join(str(a) for a in args)}` succeeded; it must refuse — {because}\n"
        f"{result.output}")
    return result


@pytest.fixture
def workspace(tmp_path: Path):
    """A real workspace built THROUGH THE CLI, not by calling the library.

    Building it any other way would let the setup succeed while the commands a user actually types
    are broken — which is the exact failure this file exists to catch.
    """
    sources = build(tmp_path / "sources")
    ws = tmp_path / "ws"
    _ok("init", ws)
    _ok("import", sources["markdown"], "--workspace", ws)
    _ok("import", sources["text_pdf"], "--workspace", ws)
    _ok("index", "--workspace", ws)
    created = json.loads(_ok("run", "--question", "Does process-in-memory reduce data movement?",
                             "--workspace", ws, "--json").output)
    return ws, created["data"]["run_id"], sources


# --------------------------------------------------------------- every command runs


def test_the_read_commands_run_in_both_renderings(workspace):
    """Human and `--json` are separate code paths in every command. Only one was ever exercised."""
    ws, rid, _ = workspace
    for args, allowed in (
        (("search", "process-in-memory", "--workspace", ws), (0,)),
        (("index", "--workspace", ws), (0,)),
        (("doctor", "--workspace", ws), (0,)),
        # 5 = blocked. The run exists and has no agent work yet, which is a true answer.
        (("status", rid, "--workspace", ws), (0, 5)),
        (("next", rid, "--workspace", ws), (0, 5)),
    ):
        human = _ok(*args, allowed=allowed)
        machine = _ok(*args, "--json", allowed=allowed)
        assert human.output.strip(), f"`research {args[0]}` printed nothing"
        json.loads(machine.output)          # --json must be parseable, not prose with a flag


def test_the_project_commands_run(tmp_path: Path):
    project = tmp_path / "proj"
    _ok("project", "init", project, "--name", "Sweep")
    _ok("project", "new", "PIM architecture", "--field", "computer-architecture",
        "--project", project)
    _ok("project", "list", "--project", project)
    json.loads(_ok("project", "list", "--project", project, "--json").output)


def test_a_fresh_run_refuses_to_validate_or_publish(workspace):
    """Not a formatting check — the two commands that must say no on an unworked run."""
    ws, rid, _ = workspace
    _refuses("validate", rid, "--workspace", ws,
             because="the run has produced no artifacts to validate")
    _refuses("report", rid, "--workspace", ws,
             because="an unvalidated run has nothing to publish")


# --------------------------------------------------------------- every refusal refuses


@pytest.mark.parametrize("args,because", [
    (("status", "RUN-does-not-exist"), "there is no such run"),
    (("next", "RUN-does-not-exist"), "there is no such run"),
    (("inspect", "NOPE-123"), "that id has no recognised prefix"),
    (("inspect", "CLM-00000000-0000-0000-0000-000000000000"),
     "the id is well formed but names no claim in this workspace"),
    (("import", "definitely-not-a-file.pdf"), "the source does not exist"),
])
def test_a_command_given_something_that_does_not_exist_refuses(workspace, args, because):
    ws, _, _ = workspace
    _refuses(*args, "--workspace", ws, because=because)


def test_an_unknown_stage_is_refused_rather_than_treated_as_a_full_validation(workspace):
    """`--stage bogus_nonsense` once produced byte-identical output to no flag at all — the worst
    of both, because the caller believes it scoped the work and it did not.

    A non-zero exit is NOT enough to assert here, and mutation is what showed it: on a fresh run
    every stage refuses anyway, for want of a response file, so a `parse_stage` that quietly
    returned `planning` for an unknown name still produced a failure and the test still passed. The
    two outcomes are distinguishable only by what they say — `invalid_arguments` naming the bad
    stage (exit 2) versus `stage_not_accepted` naming a missing file (exit 5).
    """
    ws, rid, _ = workspace
    result = _refuses("validate", rid, "--stage", "bogus_nonsense", "--workspace", ws,
                      because="an unknown stage name is an error, not an unscoped full validation")
    assert result.exit_code == 2, "an unknown stage is an argument error, not a gate failure"
    assert "bogus_nonsense" in result.output, "the refusal must name what it did not recognise"


def test_an_amendment_against_a_target_that_does_not_exist_is_refused(workspace):
    """`research amend` is the only command that writes `actor_type: human`. It must not be
    possible to record a human verification of nothing."""
    ws, rid, _ = workspace
    _refuses("amend", rid, "--type", "human_ocr_verification",
             "--target", "EVD-sha256-" + "0" * 64, "--rationale", "I read the scan",
             "--human", "someone", "--workspace", ws,
             because="the target artifact is not in this run")


@pytest.mark.parametrize("args", [
    ("search", "anything"),
    ("index",),
])
def test_commands_refuse_a_path_that_is_not_a_workspace(tmp_path: Path, args):
    _refuses(*args, "--workspace", tmp_path / "not-a-workspace",
             because="there is no workspace at that path")


def test_doctor_reports_a_missing_workspace_rather_than_refusing(tmp_path: Path):
    """`doctor` is the exception, correctly. Every other command needs a workspace to do its job;
    `doctor`'s job IS to say what the state is, and "there is no workspace here" is an answer, not
    a failure. Pinned because a sweep that assumed uniformity got this one wrong first."""
    result = _ok("doctor", "--workspace", tmp_path / "not-a-workspace")
    assert "no_workspace" in result.output


@pytest.mark.parametrize("args", [
    ("project", "list"),
    ("project", "new", "Some study"),
])
def test_project_commands_refuse_a_path_that_is_not_a_project(tmp_path: Path, args):
    _refuses(*args, "--project", tmp_path / "not-a-project",
             because="there is no project at that path")
