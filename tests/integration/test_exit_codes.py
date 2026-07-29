"""Process exit codes (spec §34).

WHY THIS FILE EXISTS. Exit code 6, `HUMAN_REVIEW_REQUIRED`, was unreachable. `human_review_required`
is only ever emitted as a *warning*, and `Envelope.exit_code()` derived 6 only from `errors`; the
`HumanReviewRequired` exception carrying it was never raised anywhere. So the code the spec tells
automation to branch on could not occur, and an import whose own summary read `failed 0` exited 4 —
`SOURCE_PROCESSING_FAILURE`.

Nothing caught it because nothing asserted an exit code end to end. These tests do, for the three
outcomes that mean different things to a caller: a source genuinely broke (4), a gate genuinely
failed (5), and a human has to look at something (6).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fixtures.make_fixtures import build  # noqa: E402

from research.errors import Envelope, ExitCode  # noqa: E402


def _cli(*args: str) -> subprocess.CompletedProcess[str]:
    # S603: argv is built from literals and test-controlled paths.
    return subprocess.run(  # noqa: S603
        [sys.executable, "-m", "research.cli", *args],
        capture_output=True, text=True,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"})


# --------------------------------------------------------------- the mapping itself


@pytest.mark.parametrize("status,expected", [
    ("ok", ExitCode.SUCCESS),
    ("partial", ExitCode.SOURCE_PROCESSING_FAILURE),
    ("human_review", ExitCode.HUMAN_REVIEW_REQUIRED),
    ("blocked", ExitCode.REPORT_GATING_FAILURE),
])
def test_each_status_maps_to_its_own_exit_code(status, expected):
    assert Envelope(command="x", status=status).exit_code() == expected


def test_every_declared_exit_code_is_reachable():
    """A stable interface nothing can produce is documentation, not an interface.

    Codes 1, 2, 3, 7 and 8 come from raised errors; 0, 4, 5 and 6 come from the envelope status.
    """
    from_status = {Envelope(command="x", status=s).exit_code()
                   for s in ("ok", "partial", "human_review", "blocked")}
    from_errors = set()
    for category, code in (
        ("general_failure", ExitCode.GENERAL_FAILURE),
        ("invalid_arguments", ExitCode.INVALID_ARGUMENTS),
        ("schema_validation_failure", ExitCode.SCHEMA_VALIDATION_FAILURE),
        ("unsafe_path_or_security", ExitCode.UNSAFE_PATH_OR_SECURITY),
        ("unsupported_artifact_or_schema_version",
         ExitCode.UNSUPPORTED_ARTIFACT_OR_SCHEMA_VERSION),
    ):
        env = Envelope(command="x")
        env.fail(category, "x")
        assert env.exit_code() == code, category
        from_errors.add(code)

    unreachable = set(ExitCode) - from_status - from_errors
    assert not unreachable, f"exit code(s) no command can produce: {sorted(unreachable)}"


# --------------------------------------------------------------- end to end


@pytest.fixture(scope="module")
def sources(tmp_path_factory):
    return build(tmp_path_factory.mktemp("sources"))


def test_import_needing_human_review_exits_6_not_4(tmp_path: Path, sources):
    """The regression. `low_text_pdf` is image-only, so it imports as `ocr_required`: nothing
    failed to process, but the content cannot back a citation until a human verifies it."""
    ws = tmp_path / "ws"
    assert _cli("init", str(ws)).returncode == 0

    result = _cli("import", str(sources["low_text_pdf"]), "--workspace", str(ws), "--json")
    envelope = json.loads(result.stdout)
    assert envelope["data"]["failed_count"] == 0, "nothing failed, so 4 would be a lie"
    assert envelope["data"]["needs_human_review_count"] >= 1
    assert result.returncode == ExitCode.HUMAN_REVIEW_REQUIRED, envelope["status"]


def test_import_of_a_broken_source_still_exits_4(tmp_path: Path, sources):
    """The other half: `partial` must keep meaning "a source broke", or the new code is just a
    rename of the old one."""
    ws = tmp_path / "ws"
    _cli("init", str(ws))
    result = _cli("import", str(sources["malformed_pdf"]), "--workspace", str(ws), "--json")
    envelope = json.loads(result.stdout)
    assert envelope["data"]["failed_count"] >= 1
    assert result.returncode == ExitCode.SOURCE_PROCESSING_FAILURE


def test_a_run_with_no_agent_work_is_blocked_with_5(tmp_path: Path, sources):
    """Gates that could not be evaluated are a gating failure, not a request for a human."""
    ws = tmp_path / "ws"
    _cli("init", str(ws))
    _cli("import", str(sources["text_pdf"]), "--workspace", str(ws))
    assert _cli("index", "--workspace", str(ws)).returncode == 0

    created = json.loads(_cli("run", "--workspace", str(ws), "--json",
                              "--question", "does anything hold up?").stdout)
    run_id = created["data"]["run_id"]

    result = _cli("validate", run_id, "--workspace", str(ws), "--json")
    envelope = json.loads(result.stdout)
    assert envelope["data"]["blocking_errors"], "this run has real unmet gates"
    assert result.returncode == ExitCode.REPORT_GATING_FAILURE
