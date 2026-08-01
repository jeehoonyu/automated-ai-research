"""The HTTP layer. Transport only — every decision about what may be shown lives in `views`.

WHY THE STANDARD LIBRARY. Adding a web framework would put a server, its middleware, and its
transitive dependencies inside a package whose `pyproject.toml` says in a comment that core
processing performs no network requests and that this is an architectural boundary. `http.server` is
enough for a loopback read-only view of local files, and it is already installed everywhere Python
is.

WHAT THIS REFUSES, AND WHY EACH ONE MATTERS

- **Any method but GET and HEAD** → 405. The UI has no write path; answering POST at all would
  create the possibility of one.
- **A non-loopback `Host` header** → 421. A page on the public internet cannot read a response from
  127.0.0.1 directly, but it *can* point a hostname it controls at 127.0.0.1 and then ask the
  browser to fetch it — same-origin from the browser's point of view. Checking the header is what
  closes that, and it costs one comparison.
- **Binding to a non-loopback address** unless `allow_remote=True`. There is no authentication here
  and the pages contain the full text of every imported document.

Every response carries a content-security policy that forbids script from every origin, including
inline. The UI ships no JavaScript at all, so the policy costs nothing and means an injected
`<script>` — from a document title, say — could not run even if the escaping were wrong.
"""

from __future__ import annotations

import http.server
import os
import re
import socket
import socketserver
import sys
import urllib.parse
import webbrowser
from pathlib import Path
from typing import Any

from ..config import Workspace
from ..errors import ResearchError, UnsafeExposureError
from . import views
from .render import render, stylesheet

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787

LOOPBACK_NAMES = {"localhost", "127.0.0.1", "::1", "[::1]", "0000:0000:0000:0000:0000:0000:0000:1"}

#: `/renders/<document-id>/<page>.png` — the one route that answers with something other than HTML.
RENDER_PATH = re.compile(r"^/renders/(?P<document_id>[^/]+)/(?P<page>\d{1,6})\.png$")

#: Cap on a request body this handler will read and throw away. Past it the connection is closed
#: instead, because the only reason to read a body here is to keep the connection's framing honest.
MAX_DRAIN_BYTES = 1 << 20

SECURITY_HEADERS = {
    # No script from anywhere, inline included; styles only from this origin; no framing; no
    # outbound connections of any kind. The UI is entirely static HTML and one stylesheet.
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'self'; img-src 'self' data:; "
        "form-action 'self'; base-uri 'none'; frame-ancestors 'none'"),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


def is_loopback(host: str) -> bool:
    """True when a `Host` header names this machine's loopback interface."""
    name = host.strip().lower()
    if name.startswith("["):  # [::1]:8787
        name, _, _ = name.partition("]")
        name += "]"
    else:
        name = name.split(":")[0]
    return name in LOOPBACK_NAMES


class ReadOnlyHandler(http.server.BaseHTTPRequestHandler):
    """Answers GET and HEAD. Everything else is refused before a workspace is even opened."""

    server_version = "research-ui"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    workspace: Workspace
    #: Set when serving a project. `/` then lists its studies instead of one workspace's runs.
    project: Any = None
    allow_remote: bool = False
    quiet: bool = False

    # ------------------------------------------------------------------ methods

    def do_GET(self) -> None:  # noqa: N802 - name fixed by BaseHTTPRequestHandler
        self._respond(body=True)

    def do_HEAD(self) -> None:  # noqa: N802
        self._respond(body=False)

    def _refuse_method(self) -> None:
        self._drain_request_body()
        self._send(405, b"405 - this interface is read-only and answers GET and HEAD only\n",
                   "text/plain; charset=utf-8", extra={"Allow": "GET, HEAD"})

    # Spelled out rather than handled by `__getattr__`, so the refusal is greppable and a new
    # method cannot be added by accident.
    do_POST = do_PUT = do_DELETE = do_PATCH = _refuse_method  # noqa: N815
    do_OPTIONS = do_CONNECT = do_TRACE = _refuse_method  # noqa: N815

    # ------------------------------------------------------------------ dispatch

    def _drain_request_body(self) -> None:
        """Read and discard the request body, or close the connection if it cannot be read.

        `protocol_version = "HTTP/1.1"` makes every connection keep-alive, and nothing here ever
        wanted a request body — so none was read. The bytes stayed in the socket, and the parser
        treated them as the NEXT request on the connection. A body that happens to be a well-formed
        request was therefore executed:

            POST / HTTP/1.1
            Host: attacker.example        <- refused, 405
            Content-Length: 37

            GET / HTTP/1.1
            Host: localhost               <- served in full, 200

        Two responses came back on one connection, the second one having bypassed the Host check
        that the first was refused by. Refusing a method is not refusing a request if its body is
        still sitting there waiting to be parsed as one.
        """
        if self.headers.get("Transfer-Encoding"):
            # Chunked framing needs a decoder this handler has no reason to own.
            self.close_connection = True
            return
        raw = self.headers.get("Content-Length")
        if raw is None:
            return
        try:
            length = int(raw)
        except ValueError:
            self.close_connection = True
            return
        if length < 0 or length > MAX_DRAIN_BYTES:
            self.close_connection = True
            return
        while length > 0:
            chunk = self.rfile.read(min(length, 65536))
            if not chunk:
                self.close_connection = True
                return
            length -= len(chunk)

    def _respond(self, *, body: bool) -> None:
        self._drain_request_body()
        # An ABSENT or EMPTY Host is refused, not waved through. This read `... and host and not
        # is_loopback(host)`, so a request with no Host header short-circuited the check and was
        # served in full — a fail-open answer to a security question, in the same file that argues
        # against exactly that for the bind check below.
        host = self.headers.get("Host", "")
        if not self.allow_remote and not is_loopback(host):
            # 421 Misdirected Request: the honest code. The request reached a server that does not
            # serve that name.
            self._send(421,
                       b"421 - this interface only answers requests addressed to localhost\n",
                       "text/plain; charset=utf-8", body=body)
            return

        parsed = urllib.parse.urlsplit(self.path)
        path = urllib.parse.unquote(parsed.path)
        params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)

        if path == "/static/app.css":
            self._send(200, stylesheet(), "text/css; charset=utf-8", body=body)
            return
        if path == "/favicon.ico":
            self._send(404, b"", "text/plain; charset=utf-8", body=body)
            return

        # The only binary route. Handled here rather than through `resolve` because a page render
        # is bytes, not a template — and because it is the one response whose payload does not pass
        # through autoescaping, which is worth having in one obvious place.
        render = RENDER_PATH.match(path)
        if render:
            try:
                payload, content_type = views.page_render(
                    self.workspace, render["document_id"], int(render["page"]))
            except views.NotFound as exc:
                self._send_page(views.error_page(exc.message, code=404, detail=exc.detail),
                                body=body)
            else:
                self._send(200, payload, content_type, body=body)
            return

        try:
            if self.project is not None and path == "/":
                page = views.project_page(self.project)
            else:
                page = views.resolve(self.workspace, path, params)
        except views.NotFound as exc:
            page = views.error_page(exc.message, code=404, detail=exc.detail)
        except ResearchError as exc:
            # A workspace error is shown, not swallowed. `detail` regularly contains the path that
            # failed, which is the first thing anyone debugging this wants.
            page = views.error_page(exc.message, code=500, detail=exc.detail)
        except Exception as exc:  # noqa: BLE001 - a view bug must not take the server down
            page = views.error_page(f"{type(exc).__name__}: {exc}", code=500)

        self._send_page(page, body=body)

    def _send_page(self, page: views.Page, *, body: bool) -> None:
        html = render(page.template, {**page.model, "page_title": page.title,
                                      "workspace_root": str(self.workspace.root)})
        self._send(page.status, html.encode("utf-8"), "text/html; charset=utf-8", body=body)

    # ------------------------------------------------------------------ plumbing

    def _send(self, code: int, payload: bytes, content_type: str, *,
              body: bool = True, extra: dict[str, str] | None = None) -> None:
        if code in (405, 421):
            # A refused request does not get to keep the connection open for another attempt on it.
            self.close_connection = True
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        for key, value in {**SECURITY_HEADERS, **(extra or {})}.items():
            self.send_header(key, value)
        self.end_headers()
        if body:
            self.wfile.write(payload)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - signature is fixed
        if not self.quiet:
            sys.stderr.write(f"  {self.address_string()} {format % args}\n")


class _Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """Threaded, and deliberately NOT `allow_reuse_address` on Windows.

    `http.server.HTTPServer` sets `allow_reuse_address = 1`, which on POSIX only permits rebinding a
    socket in TIME_WAIT. On Windows the same option means something else entirely: a second process
    may bind a port another process is actively listening on, and incoming connections are then
    split between them unpredictably. `research ui --port 8787` against an already-served port
    therefore appeared to start normally and served pages from a *different workspace* — a window
    that lies about which corpus you are looking at, which is the one thing this interface must
    never do. Windows gets `SO_EXCLUSIVEADDRUSE` instead, so the second bind fails and the CLI says
    the port is taken.
    """

    daemon_threads = True
    allow_reuse_address = os.name != "nt"

    def server_bind(self) -> None:
        if os.name == "nt":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def handle_error(self, request: Any, client_address: Any) -> None:
        """A client that hung up is not a server fault.

        The default prints a full traceback, which for a browser navigating away mid-response reads
        exactly like a crash. Genuine errors still get the default treatment — narrowing this to the
        disconnect family rather than swallowing everything.
        """
        exc = sys.exc_info()[1]
        if isinstance(exc, ConnectionError | TimeoutError):
            return
        super().handle_error(request, client_address)


def build_server(ws: Workspace, *, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                 allow_remote: bool = False, quiet: bool = False,
                 project: Any = None) -> _Server:
    """Construct a bound server. Separate from `serve` so tests can drive it without blocking."""
    if not allow_remote and not _is_loopback_address(host):
        raise UnsafeExposureError(
            f"refusing to bind the UI to {host!r}: it exposes every document and artifact in the "
            f"workspace and has no authentication",
            detail={"host": host, "how_to_override": "--allow-remote, on a network you control"})

    handler = type("BoundHandler", (ReadOnlyHandler,),
                   {"workspace": ws, "project": project,
                    "allow_remote": allow_remote, "quiet": quiet})
    return _Server((host, port), handler)


def _is_loopback_address(host: str) -> bool:
    """Every address this name resolves to must be loopback.

    `all()` over an empty sequence is True, so a name that resolves to nothing would otherwise be
    treated as safe to bind — a fail-open answer to a security question.
    """
    try:
        info = socket.getaddrinfo(host, None)
    except OSError:
        return False
    if not info:
        return False
    for family, _, _, _, sockaddr in info:
        address = sockaddr[0]
        if not isinstance(address, str):
            return False
        if family == socket.AF_INET:
            if not socket.inet_pton(family, address).startswith(b"\x7f"):
                return False
        elif address != "::1":
            return False
    return True


def serve(ws: Workspace, *, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
          allow_remote: bool = False, open_browser: bool = False,
          quiet: bool = False, project: Any = None) -> None:
    """Bind and serve until interrupted."""
    server = build_server(ws, host=host, port=port, allow_remote=allow_remote, quiet=quiet,
                          project=project)
    bound_host, bound_port = str(server.server_address[0]), server.server_address[1]
    url = f"http://{bound_host}:{bound_port}/"
    sys.stderr.write(
        f"research ui  {url}\n"
        f"  workspace  {ws.root}\n"
        f"  read-only  this interface never writes to the workspace\n"
        f"  stop       Ctrl-C\n")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        sys.stderr.write("\nresearch ui: stopped\n")
    finally:
        server.server_close()


def workspace_or_error(root: Path) -> Workspace:  # pragma: no cover - convenience for embedding
    from ..config import load_workspace

    return load_workspace(root)
