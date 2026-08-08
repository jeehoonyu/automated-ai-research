"""`research export` — a validated run in formats other tools read.

WHY THIS EXISTS. A finished run produced exactly one thing: Markdown. Research that cannot be
cited, filtered or checked anywhere else stays in the tool, which quietly makes the tool the point
rather than the research. `GOAL.md` has carried this as *"nothing leaves the tool"* since Goal 7.

WHAT IS DELIBERATELY NOT HERE, and this is the load-bearing decision:

**There is no BibTeX or CSL bibliography export, because this package does not hold a
bibliography.** What it holds about a source is the filename you imported, the PDF's `/Title` and
`/Author` strings when the file carries them, `/CreationDate`, and a sha256. That is not the same
thing, and the gap is not cosmetic:

  - `/Author` is attacker-controlled metadata inside an untrusted file (see
    `extraction/pdf.py:_clean_metadata`, which keeps it as inert strings for exactly this reason).
    It is *who made the PDF*, which is frequently a typesetting service, a scanner, or nobody.
  - `/CreationDate` is when the FILE was made. Emitting it as a publication `year` would be
    actively wrong for every paper scanned or re-exported after publication — that is, most of
    them.
  - Journal, volume, pages and DOI are not extracted at all, and a `@article` entry asserts a
    journal publication that nothing here has checked.

So a generated `.bib` would look like a citation and be a guess. This package's entire premise is
refusing to produce that. `citations.csv` instead carries the identifying facts it *does* know —
title as recorded, where it came from, and the hash that pins which bytes were read — and leaves
the bibliographic fields to a tool that actually resolves them. A user who wants BibTeX has the DOI
lookup; what they could not get anywhere else is "which exact bytes did this claim rest on".

THE SAME GATE AS PUBLICATION. An export is a published view. `claims.csv` circulates as easily as
`report.md` and is easier to paste into something else, so it passes `open_for_output` unchanged —
including the check that the artifacts on disk are the ones the verdict was computed over. A draft
is written to `*-draft.csv` and every row carries `report_eligible=false`, because a filename is
lost the moment someone opens the file in a spreadsheet.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from typing import Any

from ..config import Workspace
from ..errors import InvalidArguments
from ..security.paths import safe_join
from .gate import open_for_output

FORMATS = ("claims", "evidence", "citations")

# Column orders are fixed and explicit rather than derived from a dict, so that adding a field
# cannot silently reorder someone's saved spreadsheet or downstream parser.
CLAIM_COLUMNS = (
    "run_id", "claim_id", "claim", "claim_type", "claim_status", "support_classification",
    "citation_status", "contradiction_status", "independent_review_status",
    "supporting_evidence_ids", "contradicting_evidence_ids", "scope", "assumptions",
    "limitations", "confidence_factors", "human_review_required", "artifact_hash",
    "report_eligible",
)
EVIDENCE_COLUMNS = (
    "run_id", "evidence_id", "claim_ids", "document_id", "document_version_id", "evidence_type",
    "extraction_status", "locator_type", "page", "section_path", "start_offset", "end_offset",
    "exact_text", "interpretation_status", "human_review_required", "artifact_hash",
    "report_eligible",
)
CITATION_COLUMNS = (
    "document_id", "document_version_id", "title_as_recorded", "title_source", "filename_aliases",
    "media_type", "page_count", "extraction_status", "source_sha256", "normalized_text_sha256",
    "cited_by_evidence_count", "report_eligible",
)


@dataclass
class ExportResult:
    run_id: str
    fmt: str
    draft: bool
    path: str
    row_count: int


def _flatten(value: Any) -> str:
    """One cell, losslessly enough to be re-read by a person.

    Lists join with `; ` and dicts render as `key=value` pairs, sorted — sorted because an export
    that reorders between runs is useless for diffing, and diffing two runs of the same question is
    a large part of why anyone wants a CSV.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, dict):
        return "; ".join(f"{k}={_flatten(v)}" for k, v in sorted(value.items()))
    if isinstance(value, (list, tuple)):
        return "; ".join(_flatten(v) for v in value)
    return str(value)


def _claim_rows(ctx: Any, eligible: bool) -> list[dict[str, Any]]:
    return [
        {
            "run_id": claim.get("run_id", ""),
            "claim_id": claim.get("claim_id", ""),
            "claim": claim.get("claim", ""),
            "claim_type": claim.get("claim_type", ""),
            "claim_status": claim.get("claim_status", ""),
            "support_classification": claim.get("support_classification", ""),
            "citation_status": claim.get("citation_status", ""),
            "contradiction_status": claim.get("contradiction_status", ""),
            "independent_review_status": claim.get("independent_review_status", ""),
            "supporting_evidence_ids": _flatten(claim.get("supporting_evidence_ids")),
            "contradicting_evidence_ids": _flatten(claim.get("contradicting_evidence_ids")),
            "scope": claim.get("scope", ""),
            "assumptions": _flatten(claim.get("assumptions")),
            "limitations": _flatten(claim.get("limitations")),
            "confidence_factors": _flatten(claim.get("confidence_factors")),
            "human_review_required": _flatten(claim.get("human_review_required")),
            "artifact_hash": claim.get("artifact_hash", ""),
            "report_eligible": _flatten(eligible),
        }
        for claim in sorted(ctx.claims, key=lambda c: str(c.get("claim_id")))
    ]


def _evidence_rows(ctx: Any, eligible: bool) -> list[dict[str, Any]]:
    cited_by: dict[str, list[str]] = {}
    for claim in ctx.claims:
        for eid in (claim.get("supporting_evidence_ids") or []) + (
                claim.get("contradicting_evidence_ids") or []):
            cited_by.setdefault(eid, []).append(str(claim.get("claim_id")))

    rows = []
    for ev in sorted(ctx.evidence, key=lambda e: str(e.get("evidence_id"))):
        loc = ev.get("locator") or {}
        rows.append({
            "run_id": ctx.run_id,
            "evidence_id": ev.get("evidence_id", ""),
            "claim_ids": _flatten(sorted(cited_by.get(str(ev.get("evidence_id")), []))),
            "document_id": ev.get("document_id", ""),
            "document_version_id": ev.get("document_version_id", ""),
            "evidence_type": ev.get("evidence_type", ""),
            "extraction_status": ev.get("extraction_status", ""),
            "locator_type": loc.get("type", ""),
            "page": _flatten(loc.get("page")),
            "section_path": _flatten(loc.get("section_path")),
            "start_offset": _flatten(loc.get("start_offset")),
            "end_offset": _flatten(loc.get("end_offset")),
            # The STORED quote, not a re-resolution. `text_locators_resolve` has already compared
            # the two and the run does not publish when they differ, so re-slicing here would only
            # add a second opinion about a question already decided.
            "exact_text": ev.get("exact_text", ""),
            "interpretation_status": ev.get("interpretation_status", ""),
            "human_review_required": _flatten(ev.get("human_review_required")),
            "artifact_hash": ev.get("artifact_hash", ""),
            "report_eligible": _flatten(eligible),
        })
    return rows


def _citation_rows(ctx: Any, eligible: bool) -> list[dict[str, Any]]:
    """One row per document this run's evidence actually cites — not per imported document.

    A corpus holds what you gave it; a run rests on what it used. Exporting the corpus would
    overstate what the conclusions stand on, which is the same error as counting a related source
    as support.
    """
    used: dict[str, int] = {}
    for ev in ctx.evidence:
        doc_id = str(ev.get("document_id"))
        used[doc_id] = used.get(doc_id, 0) + 1

    rows = []
    for doc_id in sorted(used):
        doc = ctx.documents.get(doc_id) or {}
        meta = doc.get("metadata") or {}
        aliases = doc.get("original_filename_aliases") or []
        # WHERE THE TITLE CAME FROM, always. A PDF `/Title` is a string inside an untrusted file
        # and a filename is what someone happened to save it as. Both are usable; neither is a
        # verified bibliographic title, and a column that did not say which was which would invite
        # exactly the assumption this module refuses to make.
        if meta.get("title"):
            title, source = str(meta["title"]), "pdf_metadata_title_unverified"
        elif aliases:
            title, source = str(aliases[0]), "imported_filename"
        else:
            title, source = "", "unknown"
        rows.append({
            "document_id": doc_id,
            "document_version_id": doc.get("document_version_id", ""),
            "title_as_recorded": title,
            "title_source": source,
            "filename_aliases": _flatten(aliases),
            "media_type": doc.get("media_type", ""),
            "page_count": _flatten(doc.get("page_count")),
            "extraction_status": doc.get("extraction_status", ""),
            "source_sha256": doc.get("source_sha256", ""),
            "normalized_text_sha256": doc.get("normalized_text_sha256", ""),
            "cited_by_evidence_count": used[doc_id],
            "report_eligible": _flatten(eligible),
        })
    return rows


_BUILDERS = {
    "claims": (CLAIM_COLUMNS, _claim_rows),
    "evidence": (EVIDENCE_COLUMNS, _evidence_rows),
    "citations": (CITATION_COLUMNS, _citation_rows),
}


def render_csv(columns: tuple[str, ...], rows: list[dict[str, Any]]) -> str:
    """RFC 4180 with `\\r\\n`, via the stdlib writer.

    `lineterminator` is set explicitly because `csv.writer`'s default is already `\\r\\n` but
    `newline=""` handling differs by platform, and this output is hashed by tests: a CSV that
    differs between Windows and Linux would make determinism untestable.
    """
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=list(columns), lineterminator="\r\n",
                            extrasaction="raise")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buf.getvalue()


def export_run(ws: Workspace, run_id: str, *, fmt: str, draft: bool = False) -> ExportResult:
    """Write one CSV of a run, refusing unless the run may be published."""
    if fmt not in _BUILDERS:
        raise InvalidArguments(f"unknown export format {fmt!r}",
                               detail={"known": list(FORMATS)})

    ctx, _validation, _blocking, eligible = open_for_output(ws, run_id, draft=draft,
                                                            command="export")
    columns, build = _BUILDERS[fmt]
    rows = build(ctx, eligible)
    text = render_csv(columns, rows)

    name = f"{fmt}-draft.csv" if draft else f"{fmt}.csv"
    path = safe_join(ws.root, "runs", run_id, "export", name)
    path.parent.mkdir(parents=True, exist_ok=True)
    # newline="" so the writer's own terminators survive; Python would otherwise translate them.
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)

    return ExportResult(run_id=run_id, fmt=fmt, draft=draft,
                        path=str(path.relative_to(ws.root)).replace("\\", "/"),
                        row_count=len(rows))
