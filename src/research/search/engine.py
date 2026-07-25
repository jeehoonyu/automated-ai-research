"""Search over the FTS5 index.

A SEARCH RESULT IS A CANDIDATE, NOT EVIDENCE (spec §8.4). Every result carries a resolvable locator
so a human or agent *can* turn it into evidence, and carries no quality judgement so nothing is
tempted to skip that step. There is deliberately no "relevance" or "confidence" field: BM25 measures
lexical overlap, and letting a retrieval score leak into an evidence-quality field is precisely how
"the search ranked it first" becomes "the source supports the claim".

QUERY SAFETY. FTS5 has its own expression language — `AND`, `OR`, `NOT`, `NEAR`, `*`, `^`, `:`,
column filters, and quoted phrases. Passing user text straight to `MATCH` means a query containing an
apostrophe or a stray quote is a syntax error, and one containing `NOT` silently means something the
user did not ask for. Worse, imported document text can reach a query through an agent, and document
content is untrusted (spec §3.9). Every query is therefore reduced to quoted literal terms; the exact
transformation is returned in `query_normalization` so a retrieval log is reproducible and auditable.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from ..config import Workspace
from ..errors import InvalidArguments
from ..hashing import canonical_json, sha256_text
from ..indexing.builder import open_index

# Anything not a word character or an intra-word mark is a separator. Keeping hyphens and periods
# inside tokens preserves "process-in-memory" and "v1.2" as single terms.
_TOKEN = re.compile(r"[^\W_]+(?:[.\-][^\W_]+)*", re.UNICODE)
_PHRASE = re.compile(r'"([^"]+)"')

DOCUMENT_TYPES = {"pdf", "markdown"}


@dataclass
class SearchResult:
    rank: int
    bm25: float
    chunk_id: str
    document_id: str
    document_version_id: str
    page: int | None
    line_start: int | None
    line_end: int | None
    section_path: list[str]
    snippet: str
    locator: dict[str, Any]
    source: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "bm25_score": self.bm25,
            "score_note": "BM25 lexical overlap. NOT a measure of evidence quality or support.",
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "document_version_id": self.document_version_id,
            "page": self.page,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "section_path": self.section_path,
            "snippet": self.snippet,
            "snippet_note": "display excerpt; cite via the locator, not this string",
            "locator": self.locator,
            "source": self.source,
        }


def normalize_query(raw: str) -> tuple[str, dict[str, Any]]:
    """Reduce arbitrary text to a safe FTS5 expression of quoted literals.

    Quoted spans in the input are preserved as phrases; everything else becomes individual terms.
    FTS5 ANDs adjacent terms, which matches what a user expects from a plain search box.
    """
    phrases = [p.strip() for p in _PHRASE.findall(raw) if p.strip()]
    remainder = _PHRASE.sub(" ", raw)
    terms = _TOKEN.findall(remainder)

    parts = [f'"{p}"' for p in (phrases + terms)]
    if not parts:
        raise InvalidArguments(
            "the query contains no searchable terms",
            detail={"query": raw,
                    "hint": "queries are reduced to literal words and quoted phrases; punctuation "
                            "and FTS operators are not interpreted"})

    fts = " ".join(parts)
    return fts, {
        "original": raw,
        "phrases": phrases,
        "terms": terms,
        "fts_expression": fts,
        "operators_interpreted": False,
        "note": "FTS5 operators (AND/OR/NOT/NEAR/*/^/:) are NOT interpreted; every part is a "
                "literal. Terms are combined with implicit AND.",
    }


def _validate_filters(document_type: str | None, document_id: str | None) -> dict[str, Any]:
    filters: dict[str, Any] = {}
    if document_type is not None:
        if document_type not in DOCUMENT_TYPES:
            raise InvalidArguments(
                f"unknown document type {document_type!r}",
                detail={"allowed": sorted(DOCUMENT_TYPES)})
        filters["document_type"] = document_type
    if document_id is not None:
        if not document_id.startswith("DOC-sha256-"):
            raise InvalidArguments(
                f"not a document id: {document_id!r}",
                detail={"expected_prefix": "DOC-sha256-"})
        filters["document_id"] = document_id
    return filters


def search(
    ws: Workspace,
    query: str,
    *,
    document_type: str | None = None,
    document_id: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Run a search and return results with resolvable locators."""
    if limit < 1:
        raise InvalidArguments("limit must be at least 1", detail={"limit": limit})

    fts_expr, normalization = normalize_query(query)
    filters = _validate_filters(document_type, document_id)

    where = ["chunks_fts MATCH ?"]
    params: list[Any] = [fts_expr]
    if "document_type" in filters:
        where.append("c.document_type = ?")
        params.append(filters["document_type"])
    if "document_id" in filters:
        where.append("c.document_id = ?")
        params.append(filters["document_id"])

    # DETERMINISTIC ORDERING. SQLite's bm25() returns NEGATIVE scores where a lower (more negative)
    # value is a better match, so best-first is ASC. Ties are broken by document_id, then page, then
    # chunk_id — all total orders — so two runs over the same index cannot disagree.
    sql = f"""
        SELECT c.*, bm25(chunks_fts) AS bm25_score,
               snippet(chunks_fts, 0, '', '', '…', 24) AS snip
        FROM chunks_fts
        JOIN chunks c ON c.rowid = chunks_fts.rowid
        WHERE {' AND '.join(where)}
        ORDER BY bm25_score ASC,
                 c.document_id ASC,
                 CASE WHEN c.page IS NULL THEN -1 ELSE c.page END ASC,
                 c.chunk_id ASC
        LIMIT ?
    """
    params.append(limit)

    conn = open_index(ws)
    try:
        try:
            rows = conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError as exc:  # pragma: no cover - normalization should prevent
            raise InvalidArguments(
                f"the index rejected this query: {exc}",
                detail={"fts_expression": fts_expr}) from exc
    finally:
        conn.close()

    results: list[SearchResult] = []
    for position, row in enumerate(rows, start=1):
        import json as _json
        section_path = _json.loads(row["section_path"]) if row["section_path"] else []
        # The locator spans the whole chunk. span_sha256 equals the chunk's text hash, so the
        # citation is verifiable without reading the document first.
        locator = {
            "type": "text_span",
            "page": row["page"],
            "section_path": section_path,
            "chunk_id": row["chunk_id"],
            "start_offset": row["start_offset"],
            "end_offset": row["end_offset"],
            "source_line_start": row["line_start"],
            "source_line_end": row["line_end"],
            "span_sha256": row["text_sha256"],
        }
        results.append(SearchResult(
            rank=position, bm25=float(row["bm25_score"]), chunk_id=row["chunk_id"],
            document_id=row["document_id"], document_version_id=row["document_version_id"],
            page=row["page"], line_start=row["line_start"], line_end=row["line_end"],
            section_path=section_path, snippet=row["snip"], locator=locator,
            source={"title": row["title"], "document_type": row["document_type"],
                    "media_type": row["media_type"],
                    "extraction_status": row["extraction_status"]}))

    return {
        "query": query,
        "query_normalization": normalization,
        "filters": filters,
        "ranking": {
            "function": "bm25",
            "order": ["bm25 ASC (SQLite bm25 is negative; lower is a better match)",
                      "document_id ASC", "page ASC", "chunk_id ASC"],
            "note": "ranking reflects lexical overlap only and assigns no evidence quality",
        },
        "result_count": len(results),
        "limit": limit,
        "results": [r.to_dict() for r in results],
        "retrieval_log_hash": sha256_text(canonical_json({
            "query_normalization": normalization, "filters": filters, "limit": limit,
            "chunk_ids": [r.chunk_id for r in results]})),
    }
