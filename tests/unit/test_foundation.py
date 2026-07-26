"""Phase 1 foundation tests.

These cover the properties everything else rests on. If canonicalization, hashing, identifier
derivation, or path containment is wrong, every downstream guarantee is decorative.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from research.config import WORKSPACE_FILE, load_workspace
from research.errors import Envelope, ExitCode, UnsafePathError, WorkspaceError
from research.hashing import (
    artifact_hash,
    canonical_json,
    sha256_bytes,
    sha256_file,
    stamp_artifact_hash,
    verify_artifact_hash,
)
from research.identifiers import (
    chunk_id,
    claim_id,
    document_id,
    document_version_id,
    evidence_id,
    is_valid_id,
    run_id,
)
from research.security.paths import (
    atomic_write_bytes,
    content_address_path,
    safe_join,
    sanitize_filename,
)
from research.workspace import init_workspace

# --------------------------------------------------------------------- canonical JSON


def test_canonical_json_is_key_order_independent():
    a = {"b": 1, "a": 2, "c": {"z": 1, "y": 2}}
    b = {"c": {"y": 2, "z": 1}, "a": 2, "b": 1}
    assert canonical_json(a) == canonical_json(b)


def test_canonical_json_has_no_insignificant_whitespace():
    assert canonical_json({"a": 1, "b": [1, 2]}) == '{"a":1,"b":[1,2]}'


def test_canonical_json_rejects_non_finite_numbers():
    # JSON cannot represent these; hashing one would produce an identity that cannot round-trip.
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError):
            canonical_json({"x": bad})


def test_canonical_json_rejects_non_string_keys():
    with pytest.raises(TypeError):
        canonical_json({1: "a"})


def test_canonical_json_distinguishes_bool_from_int():
    assert canonical_json({"x": True}) == '{"x":true}'
    assert canonical_json({"x": 1}) == '{"x":1}'


def test_canonical_json_sorts_by_utf16_code_unit_not_code_point():
    """RFC 8785 orders keys by UTF-16 code unit, which differs from code-point order above the BMP.

    U+1F600 encodes as the surrogate pair D83D DE00; U+FFFD is FFFD. Under UTF-16, D83D < FFFD, so
    the emoji sorts FIRST \u2014 the opposite of what comparing code points (0x1F600 > 0xFFFD) gives.
    Getting this backwards would silently produce a different artifact_hash than any other
    conforming implementation.
    """
    out = canonical_json({"\U0001F600": 1, "\uFFFD": 2})
    assert out.index("\U0001F600") < out.index("\uFFFD")


# --------------------------------------------------------------------- hashing


def test_artifact_hash_omits_the_hash_field_itself():
    art = {"schema_name": "Evidence", "value": 1}
    stamped = stamp_artifact_hash(art)
    assert verify_artifact_hash(stamped)
    # recomputing over the stamped artifact must give the same digest
    assert artifact_hash(stamped) == stamped["artifact_hash"]


def test_artifact_hash_is_pretty_printing_independent():
    art = {"b": 2, "a": 1}
    reparsed = json.loads(json.dumps(art, indent=4, sort_keys=False))
    assert artifact_hash(art) == artifact_hash(reparsed)


def test_verify_artifact_hash_detects_tampering():
    stamped = stamp_artifact_hash({"claim": "original"})
    stamped["claim"] = "edited after the fact"
    assert verify_artifact_hash(stamped) is False


def test_sha256_file_matches_bytes(tmp_path: Path):
    p = tmp_path / "x.bin"
    data = os.urandom(3000)
    p.write_bytes(data)
    assert sha256_file(p) == sha256_bytes(data)


# --------------------------------------------------------------------- identifiers

_DIGEST = "a" * 64


def test_document_id_depends_only_on_bytes():
    assert document_id(_DIGEST) == document_id("sha256:" + _DIGEST)
    assert is_valid_id(document_id(_DIGEST))


def test_document_id_rejects_a_non_digest():
    with pytest.raises(ValueError):
        document_id("not-a-hash")


def test_document_version_changes_when_the_toolchain_changes():
    """A citation must point at the extraction it was actually read from."""
    base = dict(document_id_=document_id(_DIGEST), extraction_config_hash="sha256:c",
                normalization_version="1.0.0")
    v1 = document_version_id(**base, toolchain_version="0.1.0")
    v2 = document_version_id(**base, toolchain_version="0.2.0")
    assert v1 != v2


def test_evidence_id_is_identical_for_the_identical_passage():
    """Duplicate evidence must collapse, not inflate an apparent count of independent support."""
    kw = dict(document_version_id_="DVER-sha256-" + _DIGEST,
              locator={"type": "text_span", "page": 3, "start_offset": 1, "end_offset": 9},
              exact_text="the same passage", evidence_type="direct_statement")
    assert evidence_id(**kw) == evidence_id(**kw)


def test_evidence_id_ignores_locator_key_order():
    a = evidence_id(document_version_id_="DVER-sha256-" + _DIGEST,
                    locator={"page": 3, "type": "text_span"},
                    exact_text="t", evidence_type="direct_statement")
    b = evidence_id(document_version_id_="DVER-sha256-" + _DIGEST,
                    locator={"type": "text_span", "page": 3},
                    exact_text="t", evidence_type="direct_statement")
    assert a == b


def test_chunk_id_is_deterministic():
    kw = dict(document_version_id_="DVER-sha256-" + _DIGEST, page=1, section_path=["1", "1.1"],
              start_offset=0, end_offset=100, chunking_config_hash="sha256:k")
    assert chunk_id(**kw) == chunk_id(**kw)


def test_claim_and_run_ids_are_unique_and_well_formed():
    assert claim_id() != claim_id()
    assert run_id() != run_id()
    assert is_valid_id(claim_id()) and is_valid_id(run_id())


def test_claim_ids_are_time_ordered_even_within_one_millisecond():
    """Artifacts are created in tight loops, so ordering must hold inside a single millisecond.

    Plain timestamp+random UUIDv7 fails here: a batch of evidence records lands in the same
    millisecond and the random tails sort arbitrarily. The intra-millisecond counter is what makes
    'time-ordered' true when it is actually used.
    """
    ids = [claim_id() for _ in range(500)]
    assert ids == sorted(ids)
    assert len(set(ids)) == len(ids)


# --------------------------------------------------------------------- path safety


def test_safe_join_blocks_traversal(tmp_path: Path):
    with pytest.raises(UnsafePathError):
        safe_join(tmp_path, "..", "escaped.txt")


def test_safe_join_blocks_absolute_components(tmp_path: Path):
    with pytest.raises(UnsafePathError):
        safe_join(tmp_path, "/etc/passwd" if os.name != "nt" else "C:\\Windows\\system32")


def test_safe_join_allows_normal_nesting(tmp_path: Path):
    p = safe_join(tmp_path, "documents", "manifests", "a.json")
    assert str(p).startswith(str(tmp_path.resolve()))


def test_safe_join_works_when_the_root_does_not_exist_yet(tmp_path: Path):
    """Regression: joining under a not-yet-created root must not be treated as an escape.

    Creating `runs/<run-id>/packets/` happens before the run directory exists. An earlier
    implementation resolved the deepest EXISTING ancestor, which climbed above the root and rejected
    a legitimate path with a security error."""
    fresh_root = tmp_path / "runs" / "RUN-not-created-yet"
    joined = safe_join(fresh_root, "packets", "00-planning.json")
    assert str(joined).startswith(str(fresh_root.resolve()))
    # and traversal is still refused from a non-existent root
    with pytest.raises(UnsafePathError):
        safe_join(fresh_root, "..", "..", "escaped.json")


@pytest.mark.skipif(os.name == "nt", reason="symlink creation needs privileges on Windows")
def test_safe_join_blocks_symlink_escape(tmp_path: Path):
    outside = tmp_path.parent / "outside"
    outside.mkdir(exist_ok=True)
    root = tmp_path / "ws"
    root.mkdir()
    (root / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(UnsafePathError):
        safe_join(root, "link", "loot.txt")


def test_sanitize_filename_handles_hostile_names():
    assert "/" not in sanitize_filename("../../etc/passwd")
    assert sanitize_filename("...") == "unnamed"
    assert sanitize_filename("") == "unnamed"
    assert sanitize_filename("CON.txt").upper().startswith("_CON")
    assert "\x00" not in sanitize_filename("bad\x00name.pdf")
    assert len(sanitize_filename("x" * 500 + ".pdf")) <= 200


def test_content_address_path_fans_out(tmp_path: Path):
    p = content_address_path(tmp_path, _DIGEST)
    assert p.parent.name == _DIGEST[2:4]
    assert p.parent.parent.name == _DIGEST[:2]
    assert p.name == _DIGEST


def test_atomic_write_leaves_no_temp_file(tmp_path: Path):
    target = tmp_path / "nested" / "a.json"
    atomic_write_bytes(target, b"{}", root=tmp_path)
    assert target.read_bytes() == b"{}"
    assert not list(tmp_path.rglob(".*tmp*"))


# --------------------------------------------------------------------- envelope


def test_envelope_exit_code_is_derived_from_its_contents():
    env = Envelope(command="x")
    assert env.exit_code() == ExitCode.SUCCESS
    env.fail("unsafe_path_or_security", "nope")
    # a command cannot report an error and still exit 0
    assert env.exit_code() == ExitCode.UNSAFE_PATH_OR_SECURITY


def test_envelope_partial_is_not_success():
    """Presenting partial processing as complete success is explicitly forbidden."""
    env = Envelope(command="import", status="partial")
    assert env.exit_code() != ExitCode.SUCCESS


def test_envelope_blocked_maps_to_report_gating():
    assert Envelope(command="report", status="blocked").exit_code() == ExitCode.REPORT_GATING_FAILURE


# --------------------------------------------------------------------- workspace


def test_init_creates_a_usable_workspace(tmp_path: Path):
    out = init_workspace(tmp_path / "ws")
    ws = load_workspace(tmp_path / "ws")
    assert (ws.root / WORKSPACE_FILE).is_file()
    assert (ws.root / "originals" / "sha256").is_dir()
    assert (ws.root / "AGENTS.md").is_file() and (ws.root / "CLAUDE.md").is_file()
    assert out["initialized"] is True


def test_init_refuses_a_non_empty_directory(tmp_path: Path):
    d = tmp_path / "ws"
    d.mkdir()
    (d / "existing.txt").write_text("mine")
    with pytest.raises(WorkspaceError):
        init_workspace(d)


def test_init_with_allow_non_empty_does_not_overwrite(tmp_path: Path):
    d = tmp_path / "ws"
    d.mkdir()
    (d / "AGENTS.md").write_text("MY OWN CONTENT")
    init_workspace(d, allow_non_empty=True)
    assert (d / "AGENTS.md").read_text() == "MY OWN CONTENT"


def test_workspace_discovery_walks_upward(tmp_path: Path):
    init_workspace(tmp_path / "ws")
    deep = tmp_path / "ws" / "documents" / "manifests"
    assert load_workspace(None, start=deep).root == (tmp_path / "ws").resolve()


def test_load_workspace_outside_any_workspace_is_actionable(tmp_path: Path):
    with pytest.raises(WorkspaceError) as exc:
        load_workspace(None, start=tmp_path)
    assert "research init" in str(exc.value.detail)


def test_config_hash_is_stable_across_loads(tmp_path: Path):
    init_workspace(tmp_path / "ws")
    a = load_workspace(tmp_path / "ws").config_hash
    b = load_workspace(tmp_path / "ws").config_hash
    assert a == b


# --------------------------------------------------------------------- honesty


def _run_cli(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "research.cli", *args],
        capture_output=True, text=True, cwd=cwd,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )


IMPLEMENTED = ["init", "import", "index", "search", "run", "status", "inspect"]
NOT_IMPLEMENTED = ["validate", "report"]


@pytest.mark.parametrize("command", NOT_IMPLEMENTED)
def test_unimplemented_commands_do_not_claim_success(command: str, tmp_path: Path):
    """A CLI that exits 0 for work it did not do is the same defect class as a report claiming
    support it does not have. Unimplemented commands must fail loudly and name the phase."""
    args = {"search": ["q"], "status": ["RUN-x"], "inspect": ["DOC-x"],
            "validate": ["RUN-x"], "report": ["RUN-x"],
            "run": ["--question", "q"]}.get(command, [])
    proc = _run_cli(command, *args, "--json", cwd=tmp_path)
    assert proc.returncode != 0, f"`research {command}` exited 0 without being implemented"
    payload = json.loads(proc.stdout)
    assert payload["status"] == "failed"
    assert payload["errors"][0]["category"] == "not_implemented"
    assert "Phase" in payload["errors"][0]["detail"]["phase"]


def test_every_public_command_exists():
    """The nine commands in the spec must all be routable, even before they do work."""
    proc = _run_cli("--help")
    for command in [*IMPLEMENTED, *NOT_IMPLEMENTED]:
        assert command in proc.stdout


def test_doctor_capability_list_matches_reality():
    """`doctor` must not advertise a capability the CLI does not have, and must not hide one it
    does. This is the list that goes stale first, so it is asserted rather than trusted."""
    proc = _run_cli("doctor", "--json")
    data = json.loads(proc.stdout)["data"]
    assert data["implemented"] == IMPLEMENTED
    assert data["not_implemented"] == NOT_IMPLEMENTED


def test_json_envelope_is_versioned_and_complete(tmp_path: Path):
    proc = _run_cli("init", str(tmp_path / "ws"), "--json")
    payload = json.loads(proc.stdout)
    assert payload["envelope_version"] == "1.0.0"
    assert set(payload) == {"envelope_version", "command", "status", "data", "warnings", "errors"}
