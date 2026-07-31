"""The UI over a real socket, against a real workspace.

The unit tests assert the shape of the code. These assert what actually comes back over HTTP, which
is the only place a claim about escaping or about refusing a method can really be settled.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import re
import socket
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from research.artifacts.io import read_artifact, write_artifact
from research.config import Workspace
from research.hashing import stamp_artifact_hash
from research.importers.importer import import_paths
from research.indexing.builder import build_index
from research.ui.server import build_server
from research.validation.validator import validate_run

# Markup that must reach the browser as text and nothing else.
HOSTILE_MARKDOWN = (
    "# Probe\n\n"
    "<script>window.pwned = true;</script>\n\n"
    'An image: <img src=x onerror="window.pwned = true">\n\n'
    'An attribute break: " onmouseover="window.pwned=true" x="\n\n'
    "A closing tag: </blockquote><h1>injected</h1>\n"
)


class Client:
    """A minimal HTTP client. `urllib` normalises away the traversal cases worth testing."""

    def __init__(self, host: str, port: int) -> None:
        self.host, self.port = host, port

    def request(self, method: str, path: str, *,
                host_header: str | None = None) -> tuple[int, dict[str, str], str]:
        conn = http.client.HTTPConnection(self.host, self.port, timeout=10)
        try:
            headers = {"Host": host_header} if host_header else {}
            conn.putrequest(method, path, skip_host=bool(host_header), skip_accept_encoding=True)
            for key, value in headers.items():
                conn.putheader(key, value)
            conn.endheaders()
            response = conn.getresponse()
            body = response.read().decode("utf-8", "replace")
            return response.status, dict(response.getheaders()), body
        finally:
            conn.close()

    def get(self, path: str, **kwargs: Any) -> tuple[int, dict[str, str], str]:
        return self.request("GET", path, **kwargs)


@pytest.fixture
def ui(complete_run: tuple[Workspace, str, dict[str, Any]]) -> Iterator[tuple[Client, Workspace,
                                                                             str, dict[str, Any]]]:
    ws, run_id, meta = complete_run
    validate_run(ws, run_id)
    server = build_server(ws, host="127.0.0.1", port=0, quiet=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield Client("127.0.0.1", server.server_address[1]), ws, run_id, meta
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


# ------------------------------------------------------------------------------ it answers reads


def test_the_overview_lists_the_run(ui):
    client, _ws, run_id, _meta = ui
    code, headers, body = client.get("/")
    assert code == 200
    assert run_id in body
    assert headers["Content-Type"].startswith("text/html")


def test_the_run_page_shows_the_verdict(ui):
    client, _ws, run_id, _meta = ui
    code, _headers, body = client.get(f"/runs/{run_id}")
    assert code == 200
    assert "Report eligible" in body


def test_the_evidence_chain_is_walkable(ui):
    """Claim to evidence to the source text, by following links the pages actually contain."""
    client, _ws, run_id, meta = ui
    _code, _headers, run_html = client.get(f"/runs/{run_id}")
    assert f"/artifacts/{meta['claim_id']}" in run_html

    code, _headers, claim_html = client.get(f"/artifacts/{meta['claim_id']}")
    assert code == 200
    assert f"/artifacts/{meta['evidence_id']}" in claim_html

    code, _headers, evidence_html = client.get(f"/artifacts/{meta['evidence_id']}")
    assert code == 200
    # The quote is re-sliced from the stored normalized text, not copied out of the artifact.
    assert "Resolved" in evidence_html


def test_the_stylesheet_is_served(ui):
    client, _ws, _run_id, _meta = ui
    code, headers, body = client.get("/static/app.css")
    assert code == 200
    assert headers["Content-Type"].startswith("text/css")
    assert ".chip-blocking" in body


# --------------------------------------------------------------------------------- it refuses


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH", "OPTIONS", "TRACE"])
def test_every_write_method_is_refused(ui, method: str):
    client, _ws, _run_id, _meta = ui
    code, headers, _body = client.request(method, "/")
    assert code == 405
    assert headers["Allow"] == "GET, HEAD"


def test_a_foreign_host_header_is_refused(ui):
    """DNS rebinding: the attacker's name resolves to 127.0.0.1, so only the header betrays it."""
    client, _ws, _run_id, _meta = ui
    code, _headers, body = client.get("/", host_header="attacker.example")
    assert code == 421
    assert "localhost" in body


def test_a_loopback_host_header_is_accepted(ui):
    client, _ws, _run_id, _meta = ui
    code, _headers, _body = client.get("/", host_header="localhost:1")
    assert code == 200


@pytest.mark.parametrize("path", [
    "/nope",
    "/runs/../../../etc/passwd",
    "/artifacts/..%2f..%2fresearch.yaml",
    "/artifacts/../../../../../../Windows/System32/drivers/etc/hosts",
    "/runs/RUN-nope/report/../../../research.yaml",
    "/artifacts/",
])
def test_traversal_and_unknown_paths_are_refused(ui, path: str):
    client, _ws, _run_id, _meta = ui
    code, _headers, body = client.get(path)
    assert code == 404, path
    assert "research.yaml" not in body or "no page at" in body or "well-formed" in body


def test_security_headers_are_on_every_response(ui):
    client, _ws, run_id, _meta = ui
    for path in ("/", f"/runs/{run_id}", "/static/app.css", "/nope"):
        _code, headers, _body = client.get(path)
        assert "default-src 'none'" in headers["Content-Security-Policy"], path
        assert headers["X-Content-Type-Options"] == "nosniff", path
        assert headers["Referrer-Policy"] == "no-referrer", path


# ------------------------------------------------------------------------------ it does not lie


def test_document_text_reaches_the_browser_as_text(ui, tmp_path: Path):
    """The corpus is untrusted input. A UI that renders it into HTML has to prove it escapes."""
    client, ws, _run_id, _meta = ui
    source = tmp_path / "hostile.md"
    source.write_text(HOSTILE_MARKDOWN, encoding="utf-8")
    import_paths(ws, [source])
    build_index(ws)

    code, _headers, body = client.get("/search?q=probe+injected")
    assert code == 200
    assert "<script>window.pwned" not in body
    assert "&lt;script&gt;" in body
    assert "<h1>injected</h1>" not in body
    assert 'onerror="window.pwned' not in body


def test_a_not_evaluated_check_is_shown_as_blocking(ui):
    """`not_evaluated` blocks exactly as `failed`. A dashboard is where that gets softened."""
    client, ws, _run_id, _meta = ui
    from research.runs.manager import create_run

    empty = create_run(ws, question="a run that has done nothing at all")["run_id"]
    validate_run(ws, empty)

    code, _headers, body = client.get(f"/runs/{empty}")
    assert code == 200
    assert "not evaluated" in body
    assert "chip-blocking" in body
    assert "blocks publication exactly as a failure does" in body
    # And it must never be presented as a pass.
    assert "Report eligible" not in body


def test_an_edited_claim_makes_the_verdict_visibly_stale(ui):
    """The failure this project keeps finding: a green tick about artifacts no longer there.

    `research validate` records the roster it judged. Editing a claim afterwards must not leave the
    page showing the old verdict without saying so.
    """
    client, _ws, run_id, meta = ui
    _code, _headers, before = client.get(f"/runs/{run_id}")
    assert "Report eligible" in before

    claim = read_artifact(meta["claim_path"])
    claim["claim"] = "A sentence nobody validated."
    write_artifact(meta["claim_path"], stamp_artifact_hash(claim), validate=False)

    code, _headers, after = client.get(f"/runs/{run_id}")
    assert code == 200
    assert "does not describe the artifacts now on disk" in after
    assert "re-stamped since validation" in after


def test_a_run_reached_without_its_prefix_does_not_lose_its_artifacts(ui):
    """`/runs/<uuid>` without `RUN-` resolved the manifest and the verdict from the canonical id but
    read `claims/` from a directory named after the un-prefixed one — which does not exist. The page
    said "Report eligible" above "No claims. A run with no claims has produced no findings"."""
    client, _ws, run_id, meta = ui
    stripped = run_id.removeprefix("RUN-")

    code, _headers, body = client.get(f"/runs/{stripped}")
    assert code == 200
    assert f"/artifacts/{meta['claim_id']}" in body, "the claim vanished from the un-prefixed page"
    assert "No claims" not in body


def test_a_verdict_that_disagrees_with_its_own_checks_is_called_out(ui):
    """`report_eligible` is a boolean stored beside the checks. Nothing made the page compare them,
    so flipping it and re-stamping produced a green banner above ten blocking rows. The artifact
    hash cannot catch that — a re-stamped result is internally consistent — and neither can the
    staleness comparison, because a validation result is not part of its own artifact roster."""
    client, ws, run_id, _meta = ui
    from research.runs.manager import create_run

    empty = create_run(ws, question="a run that has done nothing at all")["run_id"]
    validate_run(ws, empty)
    path = ws.root / "runs" / empty / "validation" / "validation-result.json"

    result = read_artifact(path, expect_schema="ValidationResult")
    assert result["report_eligible"] is False
    result["report_eligible"] = True
    write_artifact(path, stamp_artifact_hash(result), validate=False)

    code, _headers, body = client.get(f"/runs/{empty}")
    assert code == 200
    assert "disagrees with its own checks" in body
    assert "Every gate cleared" not in body

    _code, _headers, overview = client.get("/")
    assert "verdict disagrees with its checks" in overview


def test_an_unrecognised_check_status_is_counted_as_blocking(ui):
    """The rows failed closed and the count failed open, so the page printed "0 blocking" above a
    wall of blocking rows."""
    client, ws, run_id, _meta = ui
    path = ws.root / "runs" / run_id / "validation" / "validation-result.json"
    result = read_artifact(path, expect_schema="ValidationResult")
    result["checks"][0]["status"] = "escalated"
    write_artifact(path, stamp_artifact_hash(result), validate=False)

    code, _headers, body = client.get(f"/runs/{run_id}")
    assert code == 200
    assert "0 blocking" not in body
    assert "1 blocking" in body
    assert "Every gate cleared" not in body


def test_a_claim_that_was_never_independently_reviewed_is_not_green(ui):
    """The worst of the audit's findings: three lenses found it independently.

    The chip class was decided by a Jinja expression restating the schema enum from memory. It
    blocked on `unknown` — not a member — and let `not_yet_reviewed` and `not_confirmed` fall
    through to the green chip used for `confirmed_independent`.
    """
    client, _ws, run_id, meta = ui
    claim = read_artifact(meta["claim_path"])
    claim["independent_review_status"] = "not_yet_reviewed"
    write_artifact(meta["claim_path"], stamp_artifact_hash(claim), validate=False)

    for path in (f"/runs/{run_id}", f"/artifacts/{meta['claim_id']}"):
        _code, _headers, body = client.get(path)
        # The chip macro renders underscores as spaces.
        chip = re.search(r'<span class="chip chip-(\w+)"[^>]*>not yet reviewed</span>', body)
        assert chip, f"{path}: the status is not rendered as a chip at all"
        assert chip.group(1) == "blocking", f"{path}: painted {chip.group(1)}"


def test_a_tampered_claim_is_reported_not_hidden(ui):
    """An artifact whose hash no longer matches is named on the page, not quietly skipped."""
    client, _ws, run_id, meta = ui
    raw = json.loads(meta["claim_path"].read_text(encoding="utf-8"))
    raw["claim"] = "edited without re-stamping the hash"
    meta["claim_path"].write_text(json.dumps(raw, indent=2), encoding="utf-8")

    code, _headers, body = client.get(f"/runs/{run_id}")
    assert code == 200
    assert "modified outside the amendment process" in body


def test_the_evidence_page_shows_the_source_not_the_stored_copy(ui):
    """If the two disagree, the page says so rather than printing the artifact's version."""
    client, _ws, _run_id, meta = ui
    evidence = read_artifact(meta["evidence_path"])
    evidence["exact_text"] = "a quote that is not in the document"
    write_artifact(meta["evidence_path"], stamp_artifact_hash(evidence), validate=False)

    code, _headers, body = client.get(f"/artifacts/{meta['evidence_id']}")
    assert code == 200
    assert "not what the locator resolves to" in body
    assert "a quote that is not in the document" in body  # shown, and labelled as the stored copy


# --------------------------------------------------------------------------- it never writes


def _snapshot(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = str(path.relative_to(root)).replace("\\", "/")
        out[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def test_browsing_the_whole_workspace_changes_nothing(ui):
    """The read-only guarantee, measured rather than asserted.

    Every page is fetched, then every file in the workspace is re-hashed. SQLite may leave its own
    journal sidecars beside the index; nothing else may appear, change, or disappear.
    """
    client, ws, run_id, meta = ui
    before = _snapshot(ws.root)

    paths = ["/", "/documents", "/search", "/search?q=data+movement",
             f"/runs/{run_id}", f"/runs/{run_id}/events",
             f"/artifacts/{meta['claim_id']}", f"/artifacts/{meta['evidence_id']}",
             f"/artifacts/{meta['doc']['document_id']}", "/nope"]
    for path in paths:
        code, _headers, _body = client.get(path)
        assert code in (200, 404), path

    after = _snapshot(ws.root)
    sidecars = {"-wal", "-shm", "-journal"}
    appeared = {k for k in after.keys() - before.keys()
                if not any(k.endswith(s) for s in sidecars)}
    assert not appeared, f"the UI created {sorted(appeared)}"
    assert not before.keys() - after.keys(), "the UI removed files"
    changed = {k for k in before.keys() & after.keys() if before[k] != after[k]}
    assert not changed, f"the UI modified {sorted(changed)}"


def test_a_request_body_cannot_smuggle_a_second_request(ui):
    """Keep-alive plus an undrained body meant a refused POST's payload was parsed as the next
    request — so a `Host: attacker.example` POST could carry a GET that the Host check never saw."""
    client, _ws, _run_id, _meta = ui
    smuggled = b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n"
    raw = (b"POST / HTTP/1.1\r\nHost: attacker.example\r\n"
           b"Content-Length: " + str(len(smuggled)).encode() + b"\r\n\r\n" + smuggled)

    with socket.create_connection((client.host, client.port), timeout=10) as sock:
        sock.sendall(raw)
        sock.settimeout(3)
        received = b""
        try:
            while len(received) < 65536:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                received += chunk
        except TimeoutError:
            pass

    # The POST is refused for its method, before any workspace is opened.
    assert received.startswith(b"HTTP/1.1 405"), received[:80]
    # And exactly one response comes back. The smuggled GET was consumed as a body, not executed —
    # previously a second `HTTP/1.1 200` followed with the full workspace page.
    assert received.count(b"HTTP/1.1 ") == 1, received[:400]
    assert b"Workspace" not in received


def test_a_body_on_an_ACCEPTED_request_cannot_smuggle_either(ui):
    """The case the drain uniquely covers, found by mutating the fix.

    A refused method also closes the connection, so the smuggling test above passes even with the
    drain removed — it was pinning the close, not the drain. `GET` is *served*, and its connection
    stays open, so an undrained GET body is what the next parse consumes. Nothing forbids a body on
    a GET; it is merely unusual, which is what makes it a good hiding place.
    """
    client, _ws, _run_id, _meta = ui
    smuggled = b"GET /nope HTTP/1.1\r\nHost: attacker.example\r\n\r\n"
    raw = (b"GET / HTTP/1.1\r\nHost: localhost\r\n"
           b"Content-Length: " + str(len(smuggled)).encode() + b"\r\n\r\n" + smuggled)

    with socket.create_connection((client.host, client.port), timeout=10) as sock:
        sock.sendall(raw)
        sock.settimeout(3)
        received = b""
        try:
            while len(received) < 1 << 18:
                chunk = sock.recv(8192)
                if not chunk:
                    break
                received += chunk
        except TimeoutError:
            pass

    assert received.startswith(b"HTTP/1.1 200"), received[:80]
    assert received.count(b"HTTP/1.1 ") == 1, (
        f"the body was parsed as a second request: {received[-300:]!r}")


@pytest.mark.parametrize("request_line", [
    b"GET / HTTP/1.1\r\n\r\n",                 # no Host header at all
    b"GET / HTTP/1.1\r\nHost: \r\n\r\n",       # present but empty
])
def test_a_missing_host_header_is_refused(ui, request_line: bytes):
    """`... and host and not is_loopback(host)` short-circuited, so no Host meant no check."""
    client, _ws, _run_id, _meta = ui
    with socket.create_connection((client.host, client.port), timeout=10) as sock:
        sock.sendall(request_line)
        sock.settimeout(3)
        received = sock.recv(4096)
    assert received.startswith(b"HTTP/1.1 421"), received[:120]


def test_a_second_server_cannot_steal_the_port(ui):
    """`http.server` sets `allow_reuse_address`, which means something else on Windows.

    There it lets a second process bind a port another is actively listening on, and connections are
    split between them unpredictably — so `research ui --port 8787` against a port already serving
    another workspace started successfully and showed pages from the wrong corpus. A window that
    lies about which corpus you are looking at is the one thing this interface must not do.
    """
    client, ws, _run_id, _meta = ui
    with pytest.raises(OSError):
        build_server(ws, host="127.0.0.1", port=client.port, quiet=True)


def test_binding_off_loopback_exits_as_a_security_refusal(complete_run):
    """Exit 7, not 1. §34 gives security refusals their own code so automation can branch on it."""
    from research.errors import ExitCode, UnsafeExposureError

    ws, _run_id, _meta = complete_run
    with pytest.raises(UnsafeExposureError) as exc:
        build_server(ws, host="0.0.0.0", port=0)  # noqa: S104 - asserting this is REFUSED
    assert exc.value.exit_code is ExitCode.UNSAFE_PATH_OR_SECURITY


def test_search_records_no_retrieval_log(ui):
    """`research search --run` writes provenance on purpose. A page load must not."""
    client, ws, run_id, _meta = ui
    retrieval = ws.root / "runs" / run_id / "retrieval"
    before = sorted(p.name for p in retrieval.glob("*.json"))
    client.get("/search?q=process-in-memory")
    assert sorted(p.name for p in retrieval.glob("*.json")) == before
