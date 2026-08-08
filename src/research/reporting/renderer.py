"""`research report` — deterministic Markdown rendered from validated JSON.

THE REPORT IS A VIEW (spec §3.3). Every sentence about a claim comes from one of two places: the
claim's own text, copied verbatim, or a qualifier looked up in a fixed table keyed by the validated
classification. The renderer has no vocabulary of its own for describing how well-supported
something is, which is how spec §32 — *"must not strengthen the language of a claim beyond its
validated classification"* — is satisfied structurally rather than by care.

GATING. Publication requires a validation result with `report_eligible: true`. `--draft` renders
anyway, and the draft is marked in the first line of the file, in the manifest, and in the status
line — because a draft that circulates without its marking is indistinguishable from a published
report, and drafts do circulate.

NOTHING IS REPAIRED. If an artifact is missing or unreadable the report is refused, never patched.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..artifacts.io import make_artifact, write_artifact
from ..artifacts.locators import resolve_text_locator
from ..config import SCHEMA_VERSION, WORKFLOW_VERSION, Workspace
from ..errors import ResearchError
from ..extraction.status import ExtractionStatus
from ..hashing import sha256_text
from ..security.paths import safe_join
from .gate import open_for_output
from .language import QUALIFIER, scan_claims

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
QUOTE_CHARS = 400


@dataclass
class ReportResult:
    run_id: str
    draft: bool
    report_path: str
    report_sha256: str
    manifest_path: str
    claim_count: int
    citation_count: int
    overstatements: list[dict[str, Any]]
    blocking: list[dict[str, Any]]


def _extraction_needs_disclosure(status: str) -> bool:
    """Anything but a clean, complete extraction has to be disclosed in the report.

    Asked of the package's own vocabulary rather than restated, and phrased as "not `extracted`" so
    a status added to the enum later is disclosed by default instead of quietly omitted. A value
    outside the enum is disclosed too: a word this build does not recognise is not a clean bill of
    health for a source.
    """
    try:
        return ExtractionStatus(status) is not ExtractionStatus.EXTRACTED
    except ValueError:
        return True


def _position(evidence: dict[str, Any]) -> str:
    loc = evidence.get("locator", {})
    if loc.get("type") == "visual_region":
        return f"page {loc.get('page')}, figure region"
    parts = []
    if loc.get("page") is not None:
        parts.append(f"page {loc['page']}")
    elif loc.get("source_line_start"):
        parts.append(f"lines {loc['source_line_start']}–{loc.get('source_line_end')}")
    if loc.get("section_path"):
        parts.append(" › ".join(loc["section_path"]))
    return ", ".join(parts) or "position unrecorded"


def _quote(ctx: Any, evidence: dict[str, Any]) -> str:
    """Quote the text the locator RESOLVES TO, not the artifact's stored copy of it.

    These should be identical — validation fails the run if they are not. Reading through the
    locator anyway means the report cannot display a quote that no longer exists at the place it
    cites, even if some path let a mismatched artifact through.
    """
    loc = evidence.get("locator", {})
    if loc.get("type") == "text_span":
        text = ctx.normalized_text(evidence["document_id"])
        if text is not None:
            resolved = resolve_text_locator(loc, text)
            if resolved.ok and resolved.text:
                snippet = " ".join(resolved.text.split())
                return snippet[:QUOTE_CHARS] + ("…" if len(snippet) > QUOTE_CHARS else "")
    caption = evidence.get("caption")
    if caption:
        return f"[visual region] {caption}"
    return "[quote unavailable — the locator did not resolve]"


def _source_label(ctx: Any, document_id: str) -> str:
    doc = ctx.documents.get(document_id)
    if not doc:
        return document_id
    meta = doc.get("metadata") or {}
    return str(meta.get("title") or (doc.get("original_filename_aliases") or [document_id])[0])


def render_report(ws: Workspace, run_id: str, *, draft: bool = False) -> ReportResult:
    """Render the report, refusing publication when the gates are not clear.

    The gate itself lives in `gate.py` because `research export` must apply exactly the same one —
    a CSV that a report would have refused to publish is still a published claim.
    """
    ctx, validation, blocking, eligible = open_for_output(ws, run_id, draft=draft,
                                                          command="report")
    run_dir = safe_join(ws.root, "runs", run_id)

    # ---- assemble the view -------------------------------------------------------
    evidence_by_id = ctx.evidence_by_id()
    citation_index: list[dict[str, Any]] = []
    ref_of: dict[str, int] = {}

    def cite(evidence_id: str) -> dict[str, Any] | None:
        ev = evidence_by_id.get(evidence_id)
        if ev is None:
            return None
        if evidence_id not in ref_of:
            ref_of[evidence_id] = len(citation_index) + 1
            citation_index.append({
                "ref": ref_of[evidence_id],
                "evidence_id": evidence_id,
                "document_id": ev["document_id"],
                "document_version_id": ev["document_version_id"],
                "source": _source_label(ctx, ev["document_id"]),
                "position": _position(ev),
                "quote": _quote(ctx, ev),
                # WHAT KIND OF THING THIS QUOTE IS. The report rendered every citation as
                # `source — position` and the quote, so an `expert_opinion` and a
                # `statistical_result` were byte-identical in the deliverable. Evidence records
                # the distinction; hiding it in the only artifact a reader actually reads makes
                # the distinction decorative.
                "evidence_type": ev.get("evidence_type", "unrecorded"),
            })
        entry = citation_index[ref_of[evidence_id] - 1]
        return entry

    overstatements = scan_claims(ctx.claims)
    by_claim: dict[str, list[Any]] = {}
    for over in overstatements:
        by_claim.setdefault(over.claim_id, []).append(over)

    claims_view: list[dict[str, Any]] = []
    insufficient: list[dict[str, Any]] = []
    for claim in sorted(ctx.claims, key=lambda c: c["claim_id"]):
        view = dict(claim)
        view["qualifier"] = QUALIFIER.get(claim.get("support_classification", ""),
                                          "Classification not recorded.")
        view["supporting"] = [c for c in (cite(e) for e in
                                          claim.get("supporting_evidence_ids", [])) if c]
        view["contradicting"] = [c for c in (cite(e) for e in
                                             claim.get("contradicting_evidence_ids", [])) if c]
        view["overstatements"] = [{"detail": o.detail} for o in by_claim.get(claim["claim_id"], [])]
        # The template runs under StrictUndefined so a typo is an error rather than a blank. That
        # means every optional field must be given an explicit default HERE, where the absence can
        # be reasoned about, rather than silently rendering empty inside the template.
        view.setdefault("independent_review_status", "not_yet_reviewed")
        view.setdefault("scope", "")
        view.setdefault("assumptions", [])
        view.setdefault("limitations", [])
        view.setdefault("claim_status", "draft")
        view.setdefault("citation_status", "not_checked")
        view.setdefault("contradiction_status", "not_checked")
        # Sorted so the rendered report is byte-identical across runs — dict order out of JSON is
        # insertion order, and `test_rendering_twice_produces_an_identical_report` is only
        # meaningful if the inputs cannot vary. Empty is a real state and renders as a disclosure:
        # `check_confidence_factors` blocks a support-asserting claim that recorded nothing, but a
        # DRAFT renders anyway, and the reader is owed the gap rather than a silent omission.
        view["confidence_factor_rows"] = sorted(
            (claim.get("confidence_factors") or {}).items())
        if claim.get("claim_type") == "insufficient_evidence_finding":
            insufficient.append(view)
        else:
            claims_view.append(view)

    documents = [
        {
            "document_id": doc["document_id"],
            "alias": (doc.get("original_filename_aliases") or ["?"])[0],
            "media_type": doc.get("media_type", ""),
            "extraction_status": doc.get("extraction_status", ""),
            "page_count": doc.get("page_count"),
        }
        for doc in sorted(ctx.documents.values(), key=lambda d: d["document_id"])
    ]
    independence = next(
        ((r.get("review_independence") or {}).get("status", "not_confirmed")
         for r in ctx.reviews if r["review_type"] == "independent_review"),
        "not_confirmed")

    context = {
        "title": f"Research report — {ctx.manifest['research_question'][:80]}",
        "question": ctx.manifest["research_question"],
        "run_id": run_id,
        "profile": ctx.profile,
        "draft": draft,
        "scope": (ctx.plan or {}).get("scope"),
        "insufficient_evidence_conditions": (ctx.plan or {}).get(
            "insufficient_evidence_conditions", []),
        "documents": documents,
        # Every document whose extraction the package itself considers unreliable — asked of
        # `ExtractionStatus`, not restated. This was the inline tuple
        # `("ocr_required", "partially_extracted")`: two of seven members, so a source that failed
        # to parse at all, or was an unsupported format, or was flagged ambiguous, appeared in the
        # report's Sources table with no disclosure whatsoever. The narrowest slice of the enum
        # produced the most reassuring report.
        "ocr_documents": [d for d in documents
                          if _extraction_needs_disclosure(d["extraction_status"])],
        "claims": claims_view,
        "insufficient_findings": insufficient,
        "unresolved": [c for c in claims_view if c.get("contradiction_status") == "unresolved"],
        "limitations": (ctx.plan or {}).get("expected_limitations", []),
        "reviews": sorted(({"review_type": r["review_type"], "decision": r["decision"]}
                           for r in ctx.reviews), key=lambda r: r["review_type"]),
        "independence_status": independence,
        "human_review_required": bool(validation and validation.get("human_review_required")),
        "human_review_reasons": (validation or {}).get("human_review_reasons", []),
        "checks": (validation or {}).get("checks", []),
        "report_eligible": eligible,
        "blocking": blocking,
        "citation_index": citation_index,
        "workflow_version": WORKFLOW_VERSION,
        "config_hash": ctx.manifest.get("config_hash"),
        "index_hash": (ctx.manifest.get("source_collection") or {}).get("index_hash"),
        "validation_result_hash": (validation or {}).get("artifact_hash"),
        "schema_versions": {"Claim": SCHEMA_VERSION, "Evidence": SCHEMA_VERSION,
                            "Review": SCHEMA_VERSION, "ValidationResult": SCHEMA_VERSION},
    }

    markdown = _render(context)
    report_path = safe_join(run_dir, "report", "report-draft.md" if draft else "report.md")
    from ..security.paths import atomic_write_text
    atomic_write_text(report_path, markdown, root=ws.root)
    report_hash = sha256_text(markdown)

    manifest = make_artifact(
        schema_name="ReportManifest", artifact_id=run_id, actor_type="cli",
        body={
            "run_id": run_id,
            "report_path": str(report_path.relative_to(ws.root)).replace("\\", "/"),
            "report_sha256": report_hash,
            "draft": draft,
            "validation_result_hash": (validation or {}).get("artifact_hash"),
            "claim_ids": [c["claim_id"] for c in ctx.claims],
            "retrieval_log_hashes": sorted(
                r["retrieval_log_hash"] for r in ctx.retrieval
                if r.get("schema_name") == "RetrievalLog"),
            "evidence_ids": sorted(evidence_by_id),
            "citation_index": [{k: v for k, v in entry.items() if k != "quote"}
                               for entry in citation_index],
            "schema_versions_used": context["schema_versions"],
            "disclosures": _disclosures(context, overstatements),
        })
    manifest_path = safe_join(run_dir, "report", "report-manifest.json")
    write_artifact(manifest_path, manifest, root=ws.root)

    # A published report is a lifecycle event. `Phase.PUBLISHED` existed and nothing set it.
    if not draft:
        from ..runs.lifecycle import Phase
        from ..runs.manager import load_run, transition
        if Phase(load_run(ws, run_id)["phase"]) is Phase.REPORT_ELIGIBLE:
            transition(ws, run_id, to_phase=Phase.PUBLISHED,
                       triggered_by="research report", reason="report published",
                       validation_result=(validation or {}).get("artifact_hash"))

    return ReportResult(
        run_id=run_id, draft=draft,
        report_path=str(report_path), report_sha256=report_hash,
        manifest_path=str(manifest_path), claim_count=len(ctx.claims),
        citation_count=len(citation_index),
        overstatements=[{"claim_id": o.claim_id, "kind": o.kind, "detail": o.detail}
                        for o in overstatements],
        blocking=blocking)


def _disclosures(context: dict[str, Any], overstatements: list[Any]) -> list[str]:
    """Everything the report is obliged to surface (spec §32), recorded in the manifest too."""
    out: list[str] = []
    if context["draft"]:
        out.append("DRAFT: rendered before validation passed; not a published research output")
    if context["independence_status"] != "confirmed_independent":
        out.append(f"reviewer independence is {context['independence_status']}")
    if context["human_review_required"]:
        out.append("human review is outstanding")
    if context["unresolved"]:
        out.append(f"{len(context['unresolved'])} claim(s) carry an unresolved contradiction")
    if context["ocr_documents"]:
        out.append(f"{len(context['ocr_documents'])} document(s) contain unreadable pages")
    if overstatements:
        out.append(f"{len(overstatements)} claim(s) have wording flagged as possibly exceeding "
                   f"their validated classification")
    if context["insufficient_findings"]:
        out.append(f"{len(context['insufficient_findings'])} question(s) returned "
                   f"unable_to_determine")
    return out


def _render(context: dict[str, Any]) -> str:
    """Jinja2 with autoescape OFF (Markdown, not HTML), trim/lstrip on for determinism."""
    from jinja2 import Environment, FileSystemLoader, StrictUndefined

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        undefined=StrictUndefined,     # a missing variable is a bug, not an empty string
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        # noqa: S701 — the output is Markdown, not HTML. HTML-escaping would corrupt every
        # quoted passage (`&` -> `&amp;`) and silently alter evidence text, which matters far
        # more here than XSS in a file that is never served. Claim text is emitted verbatim by
        # design; see reporting/language.py.
        autoescape=False,  # noqa: S701
    )
    try:
        return env.get_template("report.md.j2").render(**context)
    except Exception as exc:  # noqa: BLE001
        raise ResearchError(f"report rendering failed: {type(exc).__name__}: {exc}") from exc
