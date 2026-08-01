"""Page models. Pure functions from a request to a dict — no sockets, no HTML, no writes.

Keeping the views free of HTTP is what makes them testable without binding a port, and every rule in
this package's docstring is enforced here rather than in the server: the server only transports what
these functions decide.

NOTHING IN THIS MODULE WRITES. That is checked by `tests/unit/test_ui_readonly.py`, which greps this
package for the write entry points, because a rule stated in a docstring is a rule until someone
adds a route.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, get_args

from ..artifacts.io import read_artifact
from ..config import Workspace
from ..errors import ResearchError
from ..hashing import sha256_file
from ..runs.inspector import UNTRUSTED_NOTE, inspect
from ..runs.lifecycle import PHASE_ORDER, STAGE_ORDER, Phase
from ..runs.manager import list_runs
from ..search.engine import search
from ..security.paths import safe_join
from ..validation.validator import (
    CheckResult,
    Status,
    build_context,
    compare_inputs,
    validated_inputs,
)

# Identifiers arrive from a URL, which is attacker-controlled in the threat model. They are checked
# for shape here and passed to `safe_join` downstream regardless — belt and braces, because the
# consequence of getting this wrong is reading a file outside the workspace.
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")

MAX_SEARCH_LIMIT = 50
QUOTE_CHARS = 600


class NotFound(ResearchError):
    """No such page. Distinct from a workspace error so the server can answer 404."""

    category = "not_found"


@dataclass
class Page:
    """What the server needs in order to answer: a template, a title, and a model."""

    template: str
    title: str
    model: dict[str, Any] = field(default_factory=dict)
    status: int = 200


# --------------------------------------------------------------------------- status presentation
#
# `blocks` is not restated here. Asking `CheckResult` itself means that if the semantics of
# `not_evaluated` ever change, this page changes with them instead of quietly disagreeing.


KNOWN_STATUSES: frozenset[str] = frozenset(get_args(Status))


def check_blocks(check_status: str) -> bool:
    """Does this check status block publication?

    `CheckResult.blocks` is the authority for the four statuses it is typed to. It answers **False**
    for anything else — correctly, since a `Status` can only be one of four — but the UI reads these
    out of a JSON file on disk, where any word can appear. So an unrecognised status is decided
    here, and it blocks.

    This was split for a while: `status_class` failed closed on an unknown status while this
    function delegated and failed open, so the page painted the rows red and then counted zero of
    them, printing "0 blocking" above a wall of blocking rows.
    """
    if check_status not in KNOWN_STATUSES:
        return True
    return CheckResult(check="", status=check_status).blocks  # type: ignore[arg-type]


def status_class(check_status: str) -> str:
    """CSS class for a check status. Blocking statuses share one class, deliberately."""
    if check_blocks(check_status):
        return "blocking"
    return "passed" if check_status == "passed" else "neutral"


#: Shown next to each status so the page never relies on colour alone to carry the meaning.
STATUS_MEANING: dict[Status, str] = {
    "passed": "checked, and it holds",
    "failed": "checked, and it does not hold — blocks publication",
    "not_evaluated": "nobody looked — blocks publication exactly as a failure does",
    "not_applicable": "this run has nothing for this check to judge",
}


def status_meaning(check_status: str) -> str:
    """Prose for a status. An unrecognised one is described as blocking, not as blank.

    A status this build has never heard of is a status it cannot say anything reassuring about.
    """
    known = STATUS_MEANING.get(check_status)  # type: ignore[call-overload]
    if isinstance(known, str):
        return known
    return f"unrecognised status {check_status!r} — treated as blocking"


# ------------------------------------------------------------------------ claim field vocabulary
#
# THIS BELONGS IN CODE, NOT IN A TEMPLATE. It lived in two Jinja expressions — one in run.html.j2
# and a copy in artifact-claim.html.j2 — each restating an enum from memory. Both got it wrong the
# same way: they blocked on a value (`unknown`) that is not in the Claim schema at all, and let
# `not_confirmed` and `not_yet_reviewed` fall through to the green chip. So a claim that had never
# been independently reviewed displayed a green chip reading "not yet reviewed", and a claim that
# recorded nothing displayed a blocking one — writing the truth down rendered calmer than writing
# nothing, which is the exact inversion this project exists to refuse.
#
# The sets below name the values that ESTABLISH the property. Everything else blocks, including
# absent, including anything the schema gains later. `tests/unit/test_ui_contract.py` pins them
# against the shipped Claim schema so a new enum member is a test failure, not a green chip.

CLAIM_ESTABLISHING: dict[str, frozenset[str]] = {
    # Mirrors check_support_classifications: None / not_yet_reviewed / not_confirmed /
    # not_independent all mean independence was NOT established.
    "independent_review_status": frozenset({"confirmed_independent", "procedurally_isolated"}),
    # Mirrors check_contradictions_disclosed: `not_checked` is "nobody looked", not "none found".
    "contradiction_status": frozenset({"none_found", "resolved"}),
    "citation_status": frozenset({"passed"}),
}

#: `support_classification` is deliberately absent above. It is a category, not a verdict:
#: `unsupported`, `conflicting_evidence` and `unable_to_determine` are legitimate research
#: outcomes, and painting them red would editorialize about findings the UI has no basis to judge —
#: while painting `verified` green would imply the classification was earned, which is exactly what
#: `support_classifications_earned` decides and this page must not pre-empt.
SUPPORT_IS_A_CATEGORY_NOT_A_VERDICT = True


def claim_field_class(field: str, value: object) -> str:
    """Blocking unless the value establishes the property. Absent and unknown both block."""
    if not isinstance(value, str):
        return "blocking"
    return "passed" if value in CLAIM_ESTABLISHING[field] else "blocking"


def claim_chips(claim: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Pre-computed chips for a claim row. Templates print; they do not decide."""
    out: dict[str, dict[str, str]] = {}
    for field_name in CLAIM_ESTABLISHING:
        value = claim.get(field_name)
        out[field_name] = {
            "label": str(value) if isinstance(value, str) else "not recorded",
            "class": claim_field_class(field_name, value),
        }
    support = claim.get("support_classification")
    out["support_classification"] = {
        "label": str(support) if isinstance(support, str) else "unclassified",
        "class": "neutral",
    }
    return out


# ------------------------------------------------------------------------------------- freshness


def validation_view(ws: Workspace, run_id: str) -> dict[str, Any]:
    """The stored verdict, plus whether it still describes the artifacts on disk.

    `research validate` records the roster of artifacts its verdict was computed over. Re-deriving
    that roster now and comparing digests answers the question a dashboard is otherwise very good at
    obscuring: is this green tick about the files I am looking at, or about older ones?
    """
    path = safe_join(ws.root, "runs", run_id, "validation", "validation-result.json")
    if not path.is_file():
        return {"present": False,
                "note": "this run has never been validated, so nothing here has been checked"}

    try:
        result = read_artifact(path, expect_schema="ValidationResult")
    except ResearchError as exc:
        # An unreadable verdict is reported, never skipped. Skipping it would render a run with a
        # tampered validation result identically to one that was never validated.
        return {"present": True, "unreadable": exc.message, "detail": exc.detail}

    checks = [
        {**c,
         "class": status_class(str(c.get("status"))),
         "blocks": check_blocks(str(c.get("status"))),
         "meaning": status_meaning(str(c.get("status")))}
        for c in result.get("checks", [])
    ]
    try:
        ctx = build_context(ws, run_id)
        diffs = compare_inputs(result.get("validated_inputs"), validated_inputs(ctx))
        load_errors = list(ctx.load_errors)
    except ResearchError as exc:
        diffs = [f"the run could not be re-read to compare: {exc.message}"]
        load_errors = []

    counts = {
        "passed": sum(1 for c in checks if c["status"] == "passed"),
        "blocking": sum(1 for c in checks if c["blocks"]),
        "not_applicable": sum(1 for c in checks if c["status"] == "not_applicable"),
    }
    stored_eligible = bool(result.get("report_eligible"))
    human_review_reasons = result.get("human_review_reasons") or []

    # DOES THE VERDICT AGREE WITH ITS OWN CHECKS?
    #
    # `report_eligible` is a boolean stored beside the check list, and `validate_run` derives it as
    # `not blocking and not human_review_required`. Re-deriving it here from the checks on the page
    # costs nothing and answers a question the banner was previously not asking: the page rendered
    # "Report eligible — every gate cleared" directly above "10 blocking" and ten red rows, because
    # the banner read the boolean and the table read the checks. Neither the hash nor the staleness
    # comparison covers this — the validation result is not in its own artifact roster, so a run
    # whose verdict was flipped and re-stamped reads as perfectly fresh.
    contradicts_own_checks = stored_eligible and bool(counts["blocking"] or human_review_reasons)

    return {
        "present": True,
        "result": result,
        "checks": checks,
        "counts": counts,
        "report_eligible": stored_eligible,
        "contradicts_own_checks": contradicts_own_checks,
        #: The only value a page may treat as good news: the stored verdict, agreeing with the
        #: checks it was stored beside, computed over the artifacts that are on disk now.
        "trustworthy_pass": stored_eligible and not contradicts_own_checks and not diffs,
        "human_review_reasons": human_review_reasons,
        "stale": bool(diffs),
        "diffs": diffs,
        "load_errors": load_errors,
        "validated_at": result.get("created_at"),
        "artifact_hash": result.get("artifact_hash"),
    }


# ----------------------------------------------------------------------------------------- pages


def _documents(ws: Workspace) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    manifests = ws.root / "documents" / "manifests"
    if not manifests.is_dir():
        return out
    for path in sorted(manifests.glob("*.json")):
        try:
            out.append(read_artifact(path, expect_schema="Document"))
        except ResearchError as exc:
            # A document whose hash no longer matches is shown as such rather than dropped: a
            # corpus listing that silently omits a tampered manifest is worse than no listing.
            out.append({"document_id": path.stem, "unreadable": exc.message,
                        "extraction_status": "unreadable"})
    return out


def _index_hash(ws: Workspace) -> str | None:
    path = ws.root / "indexes" / "index-manifest.json"
    if not path.is_file():
        return None
    try:
        return str(read_artifact(path, expect_schema="IndexManifest")["index_hash"])
    except ResearchError:
        return None


def overview(ws: Workspace) -> Page:
    docs = _documents(ws)
    runs: list[dict[str, Any]] = []
    for row in list_runs(ws):
        view = validation_view(ws, row["run_id"])
        runs.append({
            **row,
            "validated": view.get("present", False),
            # `trustworthy_pass`, not the stored boolean: the overview chip had the same defect as
            # the run banner and would show a green "eligible" beside its own blocking count.
            "report_eligible": view.get("trustworthy_pass", False),
            "contradicts_own_checks": view.get("contradicts_own_checks", False),
            "blocking_count": view.get("counts", {}).get("blocking"),
            "stale": view.get("stale", False),
        })
    return Page(
        template="overview.html.j2",
        title="Workspace",
        model={
            "root": str(ws.root),
            "default_profile": ws.get("default_profile", "default"),
            "config_hash": ws.config_hash,
            "documents": docs,
            "document_count": len(docs),
            "ocr_documents": [d for d in docs if d.get("ocr_required_pages")],
            "unreadable_documents": [d for d in docs if d.get("unreadable")],
            "index_hash": _index_hash(ws),
            "runs": runs,
        })


def project_page(project: Any) -> Page:
    """Every study in a project, ordered by what needs attention.

    Deliberately not a scoreboard. `project_overview` sorts unreadable studies first, then those
    awaiting a human, then those with blocked runs — and the template prints those counts before it
    prints anything that went well. A project view is the most tempting place in this codebase to
    average a blocked run together with a published one, and averaging is what the whole platform
    exists to refuse.
    """
    from ..projects import project_overview

    return Page(template="project.html.j2", title=f"Project — {project.name}",
                model=project_overview(project))


def documents(ws: Workspace) -> Page:
    docs = _documents(ws)
    return Page(template="documents.html.j2", title="Documents",
                model={"documents": docs, "count": len(docs)})


def run_page(ws: Workspace, run_id: str) -> Page:
    """One run, in full.

    The id is normalised ONCE, up front, and nothing downstream sees the raw URL segment again.
    That used to happen inline at the `inspect` call only, so `/runs/<uuid>` without the `RUN-`
    prefix resolved the manifest and the validation verdict correctly while `claims/`, `evidence/`
    and `reviews/` were read from a directory named after the un-prefixed id — which does not exist.
    `_run_artifacts` returns `[]` for a missing directory, so the page rendered "Report eligible"
    above "No claims. A run with no claims has produced no findings", describing a run that has one.
    An empty directory and an empty result are not the same thing, and a URL a person might
    plausibly type produced the second while meaning the first.
    """
    if not ID_RE.match(run_id):
        raise NotFound(f"not a well-formed run id: {run_id!r}")
    canonical = run_id if run_id.startswith("RUN-") else f"RUN-{run_id}"
    try:
        detail = inspect(ws, canonical)
    except ResearchError as exc:
        raise NotFound(exc.message, detail=exc.detail) from exc
    run_id = str(detail["run_id"])

    st: dict[str, Any] = detail["status"]
    reached = PHASE_ORDER.index(Phase(st["phase"]))
    timeline = [
        {"phase": str(p), "reached": i <= reached, "current": i == reached}
        for i, p in enumerate(PHASE_ORDER)
    ]
    stages = [
        {"stage": str(s),
         "state": ("done" if str(s) in st["completed_stages"]
                   else "awaiting_validation" if str(s) in st["responses_awaiting_validation"]
                   else "next" if str(s) == st["next_stage"]
                   else "pending")}
        for s in STAGE_ORDER
    ]

    claims = [{**c, "chips": claim_chips(c)} for c in
              _run_artifacts(ws, run_id, "claims", "claim_id")]
    evidence = _run_artifacts(ws, run_id, "evidence", "evidence_id")
    reviews = _run_artifacts(ws, run_id, "reviews", "review_id")

    report_dir = safe_join(ws.root, "runs", run_id, "report")
    reports = sorted(p.name for p in report_dir.glob("*.md")) if report_dir.is_dir() else []

    return Page(
        template="run.html.j2",
        title=f"Run {detail['run_id']}",
        model={
            "run": detail,
            "status": st,
            "timeline": timeline,
            "stages": stages,
            "validation": validation_view(ws, detail["run_id"]),
            "claims": claims,
            "evidence": evidence,
            "reviews": reviews,
            "reports": reports,
            "events": detail["events"],
        })


def _run_artifacts(ws: Workspace, run_id: str, subdir: str, id_field: str) -> list[dict[str, Any]]:
    """Artifacts of one kind in one run, with unreadable files surfaced rather than skipped."""
    directory = safe_join(ws.root, "runs", run_id, subdir)
    out: list[dict[str, Any]] = []
    if not directory.is_dir():
        return out
    for path in sorted(directory.glob("*.json")):
        try:
            artifact = read_artifact(path)
        except ResearchError as exc:
            out.append({id_field: path.name, "unreadable": exc.message})
            continue
        for item in (artifact if isinstance(artifact, list) else [artifact]):
            if isinstance(item, dict) and item.get(id_field):
                out.append(item)
    return out


ARTIFACT_TEMPLATES = {
    "document": "artifact-document.html.j2",
    "chunk": "artifact-chunk.html.j2",
    "evidence": "artifact-evidence.html.j2",
    "claim": "artifact-claim.html.j2",
    "review": "artifact-review.html.j2",
}


def artifact_page(ws: Workspace, artifact_id: str) -> Page:
    """One artifact, resolved through `research inspect` so the UI shows what the CLI shows.

    Reusing the inspector matters beyond saving code. `inspect` re-slices the stored normalized text
    at the recorded offsets instead of printing what the artifact says its text is, and reports any
    divergence. A UI that read `exact_text` straight out of the evidence record would display a
    quote that no longer exists at the place it cites, which is precisely the failure the inspector
    was written to catch.
    """
    if not ID_RE.match(artifact_id):
        raise NotFound(f"not a well-formed artifact id: {artifact_id!r}")
    if artifact_id.startswith("RUN-"):
        return run_page(ws, artifact_id)
    try:
        detail = inspect(ws, artifact_id)
    except ResearchError as exc:
        raise NotFound(exc.message, detail=exc.detail) from exc

    kind = str(detail["kind"])
    template = ARTIFACT_TEMPLATES.get(kind)
    if template is None:  # pragma: no cover - inspect only returns the kinds above
        raise NotFound(f"no view for artifact kind {kind!r}")

    if kind == "document":
        # WHERE THE FILE ACTUALLY IS. `stored_original` and `normalized_text_path` are recorded
        # relative to the workspace, which is right for the artifacts — a workspace has to survive
        # being moved — but useless to a person who wants to open the thing in Explorer.
        detail = {**detail, "on_disk": _on_disk_paths(ws, detail)}

    if kind == "claim":
        detail = {**detail,
                  "chips": claim_chips(detail),
                  "evidence_detail": [_evidence_summary(ws, e["evidence_id"])
                                      for e in detail["supporting_evidence"]]}

    return Page(template=template, title=f"{kind} {artifact_id}",
                model={"a": detail, "kind": kind, "untrusted_note": UNTRUSTED_NOTE})


def _on_disk_paths(ws: Workspace, detail: dict[str, Any]) -> list[dict[str, Any]]:
    """Absolute locations for a document's files, with whether each is actually there."""
    document = next((d for d in _documents(ws)
                     if d.get("document_id") == detail.get("document_id")), None)
    out: list[dict[str, Any]] = []
    for label, relative in (("original bytes", (document or {}).get("stored_original")),
                            ("normalized text", (document or {}).get("normalized_text_path")),
                            ("chunks", (document or {}).get("chunk_set_path"))):
        if not relative:
            continue
        path = ws.root / str(relative)
        out.append({"label": label, "path": str(path), "present": path.is_file()})
    return out


def page_render(ws: Workspace, document_id: str, page: int) -> tuple[bytes, str]:
    """The PNG a page render points at — but only after re-hashing it.

    The whole reason to show a page image is that a text quote cannot settle a figure or a table:
    someone has to look. That makes the image evidence, and evidence gets the same treatment as
    everything else here — the bytes on disk are hashed and compared against the digest the Document
    manifest recorded. `locators.py` already draws the distinction this enforces: a missing render
    is an accident, a *changed* one is a different image under someone's existing citation.

    Serving it unverified would be worse than not serving it at all, because a picture is the most
    convincing thing on the page.
    """
    if not ID_RE.match(document_id):
        raise NotFound(f"not a well-formed document id: {document_id!r}")
    for doc in _documents(ws):
        if doc.get("document_id") != document_id:
            continue
        for entry in doc.get("pages", []):
            render = entry.get("render")
            if not render or int(entry.get("page_number", -1)) != page:
                continue
            path = safe_join(ws.root, *str(render["path"]).split("/"))
            if not path.is_file():
                raise NotFound(f"the render recorded for page {page} is not on disk: "
                               f"{render['path']}")
            recorded = str(render.get("sha256", ""))
            actual = sha256_file(path)
            if actual != recorded:
                raise NotFound(
                    f"the render for page {page} does not hash to the value cited for it "
                    f"(recorded {recorded}, found {actual}) — a changed image under an existing "
                    f"citation is not something this interface will display")
            return path.read_bytes(), "image/png"
        raise NotFound(f"document {document_id} has no render for page {page}")
    raise NotFound(f"no document {document_id!r} in this workspace")


def _evidence_summary(ws: Workspace, evidence_id: str) -> dict[str, Any]:
    """Enough of a piece of evidence to judge it in place, including whether it still resolves."""
    try:
        ev = inspect(ws, evidence_id)
    except ResearchError as exc:
        return {"evidence_id": evidence_id, "unreadable": exc.message, "resolves": False}
    quote = ev.get("resolved_text") or ""
    return {
        "evidence_id": evidence_id,
        "document_id": ev.get("document_id"),
        "resolves": ev.get("resolves"),
        "resolution_status": ev.get("resolution_status"),
        "text_matches_source": ev.get("text_matches_source"),
        "quote": quote[:QUOTE_CHARS] + ("…" if len(quote) > QUOTE_CHARS else ""),
        "locator": ev.get("locator") or {},
    }


def search_page(ws: Workspace, query: str, limit: int = 20) -> Page:
    """Search the index. Read-only — this deliberately does not record retrieval provenance.

    `research search --run <id>` writes a RetrievalLog, because evidence a run relies on has to name
    the search that produced it. Clicking around a dashboard is not that, and writing an artifact
    from a page load would put un-asked-for provenance into a run.
    """
    query = query.strip()
    limit = max(1, min(limit, MAX_SEARCH_LIMIT))
    model: dict[str, Any] = {"query": query, "limit": limit, "results": [], "error": None,
                             "untrusted_note": UNTRUSTED_NOTE}
    if query:
        try:
            found = search(ws, query, limit=limit)
            model["results"] = found["results"]
            model["normalization"] = found.get("query_normalization")
            model["result_count"] = len(found["results"])
        except ResearchError as exc:
            model["error"] = exc.message
    return Page(template="search.html.j2", title="Search", model=model)


def events_page(ws: Workspace, run_id: str) -> Page:
    """The append-only lifecycle log. The manifest says where a run is; this says how it got there.

    Rendered from the raw JSONL rather than from the manifest, because the two disagreeing is
    exactly the kind of thing an auditor is looking for.
    """
    if not ID_RE.match(run_id):
        raise NotFound(f"not a well-formed run id: {run_id!r}")
    path = safe_join(ws.root, "runs", run_id, "events.jsonl")
    if not path.is_file():
        raise NotFound(f"no event log for run {run_id!r}")
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            events.append({"unparseable": line[:200]})
    return Page(template="events.html.j2", title=f"Events — {run_id}",
                model={"run_id": run_id, "events": events, "count": len(events)})


def report_page(ws: Workspace, run_id: str, name: str) -> Page:
    """A rendered report, shown as text.

    Shown as text, never as rendered Markdown. A report is a *view* of validated JSON; re-rendering
    it here would add a second renderer with its own vocabulary, and the whole point of the report
    template is that no other component gets to describe how well-supported something is.
    """
    if not ID_RE.match(run_id) or not re.fullmatch(r"[A-Za-z0-9._-]{1,120}\.md", name):
        raise NotFound("not a well-formed report path")
    path = safe_join(ws.root, "runs", run_id, "report", name)
    if not path.is_file():
        raise NotFound(f"no report {name!r} for run {run_id!r}")
    return Page(template="report.html.j2", title=f"Report — {run_id}",
                model={"run_id": run_id, "name": name,
                       "text": path.read_text(encoding="utf-8"),
                       "draft": "DRAFT" in path.read_text(encoding="utf-8")[:400]})


# ---------------------------------------------------------------------------------------- router

_ROUTES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^/$"), "overview"),
    (re.compile(r"^/documents$"), "documents"),
    (re.compile(r"^/search$"), "search"),
    (re.compile(r"^/runs/(?P<run_id>[^/]+)$"), "run"),
    (re.compile(r"^/runs/(?P<run_id>[^/]+)/events$"), "events"),
    (re.compile(r"^/runs/(?P<run_id>[^/]+)/report/(?P<name>[^/]+)$"), "report"),
    (re.compile(r"^/artifacts/(?P<artifact_id>[^/]+)$"), "artifact"),
)


def resolve(ws: Workspace, path: str, params: dict[str, list[str]] | None = None) -> Page:
    """Route a decoded request path to a page. Raises NotFound for anything unrouted."""
    params = params or {}
    for pattern, name in _ROUTES:
        match = pattern.match(path)
        if not match:
            continue
        kwargs = match.groupdict()
        if name == "overview":
            return overview(ws)
        if name == "documents":
            return documents(ws)
        if name == "search":
            limit_raw = (params.get("limit") or ["20"])[0]
            limit = int(limit_raw) if limit_raw.isdigit() else 20
            return search_page(ws, (params.get("q") or [""])[0], limit=limit)
        if name == "run":
            return run_page(ws, kwargs["run_id"])
        if name == "events":
            return events_page(ws, kwargs["run_id"])
        if name == "report":
            return report_page(ws, kwargs["run_id"], kwargs["name"])
        if name == "artifact":
            return artifact_page(ws, kwargs["artifact_id"])
    raise NotFound(f"no page at {path!r}")


def error_page(message: str, *, code: int, detail: dict[str, Any] | None = None) -> Page:
    return Page(template="error.html.j2", title=f"{code}", status=code,
                model={"message": message, "code": code, "detail": detail or {}})


def workspace_error_page(exc: Exception, root: Path | None) -> Page:
    return Page(template="error.html.j2", title="Workspace unavailable", status=500,
                model={"message": str(exc), "code": 500,
                       "detail": {"workspace": str(root) if root else "(not resolved)"}})
