"""The UI's promises, checked without binding a socket.

Three of these are structural rather than behavioural, and that is deliberate. "The UI never writes"
and "`not_evaluated` is styled exactly as `failed`" are properties of the code, not of any one page;
asserting them per-page would leave the next page unguarded.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from research.ui import server, views
from research.ui.render import TEMPLATE_DIR, environment
from research.validation.validator import CheckResult

UI_ROOT = Path(views.__file__).resolve().parent
ALL_STATUSES = ("passed", "failed", "not_evaluated", "not_applicable")


# --------------------------------------------------------------- the status vocabulary is honest


@pytest.mark.parametrize("status", ALL_STATUSES)
def test_status_class_agrees_with_check_result(status: str):
    """The one that matters. A status blocks iff the UI paints it as blocking.

    This is asserted against `CheckResult.blocks` rather than against a list written here, so the
    two cannot drift: if `not_evaluated` ever stopped blocking, this test would follow it, and if
    the UI grew a gentler class for it, this test would fail.
    """
    blocks = CheckResult(check="x", status=status).blocks  # type: ignore[arg-type]
    assert (views.status_class(status) == "blocking") is blocks


def test_not_evaluated_and_failed_are_indistinguishable_to_the_stylesheet():
    assert views.status_class("not_evaluated") == views.status_class("failed") == "blocking"


@pytest.mark.parametrize("status", ALL_STATUSES)
def test_every_status_carries_its_meaning_in_words(status: str):
    """Colour is never the only carrier: each status has prose the page can show."""
    assert views.STATUS_MEANING[status].strip()  # type: ignore[index]


def test_blocking_statuses_say_so_in_their_meaning():
    for status in ALL_STATUSES:
        text = views.STATUS_MEANING[status]  # type: ignore[index]
        assert ("blocks" in text) is views.check_blocks(status), status


@pytest.mark.parametrize("status", ["fine", "", "PASSED", "ok"])
def test_an_unrecognised_status_fails_closed(status: str):
    """These are read out of a JSON file. A word this build has never heard of is not reassuring.

    `CheckResult.blocks` answers False for an unknown status — correctly, since it is typed to the
    four literals — so the UI cannot delegate this one and decides it explicitly.
    """
    assert views.status_class(status) == "blocking"
    assert views.check_blocks(status) is True
    assert "blocking" in views.status_meaning(status)


def test_the_class_and_the_count_cannot_disagree():
    """These were split: `status_class` failed closed on an unknown status while `check_blocks`
    delegated and failed open, so a page painted rows red and then counted zero of them."""
    for status in [*ALL_STATUSES, "escalated", "", "deferred"]:
        assert (views.status_class(status) == "blocking") is views.check_blocks(status), status


# -------------------------------------------------- the claim vocabulary matches the shipped schema

CLAIM_SCHEMA = json.loads(
    (Path(views.__file__).resolve().parents[1] / "schemas" / "v1" / "claim.schema.json")
    .read_text(encoding="utf-8"))


@pytest.mark.parametrize("field", sorted(views.CLAIM_ESTABLISHING))
def test_every_schema_value_is_classified(field: str):
    """The defect that got through review, pinned.

    Two Jinja expressions restated these enums from memory. Both blocked on `unknown` — which is not
    in the schema at all — and let `not_confirmed` and `not_yet_reviewed` fall through to the green
    chip, so a claim that had never been independently reviewed showed a green "not yet reviewed".
    Reading the schema here means a value added there cannot silently land in the reassuring branch.
    """
    enum = set(CLAIM_SCHEMA["properties"][field]["enum"])
    establishing = views.CLAIM_ESTABLISHING[field]
    assert establishing <= enum, (
        f"{field}: {sorted(establishing - enum)} is not in the schema — a value the UI treats as "
        f"establishing that no artifact can ever carry")
    for value in sorted(enum):
        assert views.claim_field_class(field, value) in ("passed", "blocking")


@pytest.mark.parametrize(("field", "value"), [
    # Exactly the values check_support_classifications treats as independence NOT established.
    ("independent_review_status", "not_yet_reviewed"),
    ("independent_review_status", "not_confirmed"),
    ("independent_review_status", "not_independent"),
    ("independent_review_status", None),
    # `not_checked` is "nobody looked", per check_contradictions_disclosed.
    ("contradiction_status", "not_checked"),
    ("contradiction_status", "unresolved"),
    ("contradiction_status", None),
    ("citation_status", "not_checked"),
    ("citation_status", "related_not_supporting"),
])
def test_unestablished_claim_properties_block(field: str, value: str | None):
    assert views.claim_field_class(field, value) == "blocking"


@pytest.mark.parametrize(("field", "value"), [
    ("independent_review_status", "confirmed_independent"),
    ("independent_review_status", "procedurally_isolated"),
    ("contradiction_status", "none_found"),
    ("contradiction_status", "resolved"),
    ("citation_status", "passed"),
])
def test_established_claim_properties_pass(field: str, value: str):
    assert views.claim_field_class(field, value) == "passed"


def test_recording_the_truth_is_never_styled_worse_than_recording_nothing():
    """The inversion that made the original defect worse than a wrong colour.

    An omitted field rendered the blocking chip while an honestly recorded `not_yet_reviewed`
    rendered green — so writing down that independence was not established looked *better* than
    writing nothing at all.
    """
    for field, values in views.CLAIM_ESTABLISHING.items():
        absent = views.claim_field_class(field, None)
        for value in CLAIM_SCHEMA["properties"][field]["enum"]:
            if value in values:
                continue
            assert views.claim_field_class(field, value) == absent, (field, value)


def test_support_classification_is_never_painted_as_a_verdict():
    """`unsupported` and `unable_to_determine` are legitimate research outcomes, not failures, and
    `verified` being *claimed* is not `verified` being *earned* — that is a validator check."""
    for value in CLAIM_SCHEMA["properties"]["support_classification"]["enum"]:
        chips = views.claim_chips({"support_classification": value})
        assert chips["support_classification"]["class"] == "neutral", value
    assert "support_classification" not in views.CLAIM_ESTABLISHING


def test_no_template_decides_a_chip_class():
    """Policy belongs in views.py. Two templates held copies of it and both were wrong."""
    for path in sorted(TEMPLATE_DIR.glob("*.j2")):
        text = path.read_text(encoding="utf-8")
        for field in views.CLAIM_ESTABLISHING:
            assert f"get('{field}')" not in text, (
                f"{path.name} inspects {field} directly; use views.claim_chips")


# ------------------------------------------------------------------------------ it cannot write

#: Every way this package could mutate a workspace. A route that used one of these would be a hole
#: in the read-only guarantee, and the guarantee is what makes it safe to point at a real corpus.
WRITE_ENTRY_POINTS = (
    "write_artifact", "atomic_write_bytes", "atomic_write_text", "append_event",
    "record_retrieval", "promote_stage", "transition", "validate_run", "render_report",
    "create_run", "import_paths", "build_index", "init_workspace",
    "os.remove", "shutil.", ".unlink(", ".mkdir(", ".rmdir(", ".rename(", ".touch(",
    ".write_text(", ".write_bytes(",
)


@pytest.mark.parametrize("name", WRITE_ENTRY_POINTS)
def test_the_ui_package_contains_no_write_entry_point(name: str):
    for path in sorted(UI_ROOT.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        # Strip comments and docstrings' worth of prose is overkill; the names above are specific
        # enough that a prose mention is itself worth reviewing.
        offenders = [line for line in source.splitlines()
                     if name in line and not line.lstrip().startswith("#")]
        assert not offenders, f"{path.name} references {name!r}: {offenders}"


def test_open_is_never_called_for_writing():
    pattern = re.compile(r"open\([^)]*['\"][wax]")
    for path in sorted(UI_ROOT.rglob("*.py")):
        assert not pattern.search(path.read_text(encoding="utf-8")), path


# ------------------------------------------------------------------------------- rendering rules


def test_autoescape_is_enabled():
    """Off by one boolean and every document in the corpus becomes executable markup."""
    assert environment().autoescape is True


def test_templates_escape_document_text():
    tmpl = environment().from_string("{{ text }}")
    assert tmpl.render(text="<script>x</script>") == "&lt;script&gt;x&lt;/script&gt;"


def test_no_template_ships_a_script_tag():
    """The content-security policy forbids script from every origin; nothing here needs one."""
    for path in sorted(TEMPLATE_DIR.glob("*.j2")):
        text = path.read_text(encoding="utf-8").lower()
        assert "<script" not in text, path
        assert "onclick" not in text and "onerror" not in text, path


def test_every_template_is_reachable():
    """A template no route renders is either dead or a route someone forgot to wire up."""
    referenced = set(views.ARTIFACT_TEMPLATES.values())
    for path in sorted(UI_ROOT.rglob("*.py")):
        referenced |= set(re.findall(r"[\w-]+\.html\.j2", path.read_text(encoding="utf-8")))
    on_disk = {p.name for p in TEMPLATE_DIR.glob("*.j2")}
    # base and the macro library are included by others rather than named by a route.
    unreachable = on_disk - referenced - {"base.html.j2", "_macros.html.j2"}
    assert not unreachable, f"templates nothing renders: {sorted(unreachable)}"


# -------------------------------------------------------------------------------------- binding


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "127.0.0.1:8787", "[::1]:8787",
                                  "LOCALHOST:8787"])
def test_loopback_host_headers_are_accepted(host: str):
    assert server.is_loopback(host)


@pytest.mark.parametrize("host", ["evil.example", "example.com:8787", "10.0.0.4",
                                  "127.0.0.1.evil.example",
                                  "0.0.0.0"])  # noqa: S104 - the value under test, not a bind
def test_other_host_headers_are_rejected(host: str):
    """A page on the internet can point a name it controls at 127.0.0.1. The header is the check."""
    assert not server.is_loopback(host)


@pytest.mark.parametrize("host", ["0.0.0.0",  # noqa: S104 - asserting this bind is REFUSED
                                  "::", "example.invalid"])
def test_binding_off_loopback_is_refused(host: str, tmp_path: Path):
    from research.config import Workspace
    from research.errors import ResearchError

    with pytest.raises(ResearchError) as exc:
        server.build_server(Workspace(root=tmp_path), host=host, port=0)
    assert "allow-remote" in str(exc.value.detail)


def test_the_documented_default_port_is_the_real_one():
    """The `--port` help text names a literal, because importing the UI to read a constant would
    load Jinja on every CLI invocation. This keeps the two from drifting."""
    cli_source = (Path(views.__file__).resolve().parents[1] / "cli.py").read_text(encoding="utf-8")
    assert f"[default: {server.DEFAULT_PORT}]" in cli_source


def test_the_security_policy_forbids_script_from_everywhere():
    csp = server.SECURITY_HEADERS["Content-Security-Policy"]
    assert "default-src 'none'" in csp
    assert "script-src" not in csp, "adding a script source would need a reason recorded here"
    assert "frame-ancestors 'none'" in csp
