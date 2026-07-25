"""SQLite FTS5 index construction.

THE INDEX IS A CACHE, NEVER EVIDENCE (spec §8.3). It is built entirely from canonical chunk
artifacts and can be deleted and rebuilt at any time without losing anything. Nothing downstream may
treat "the index said so" as support for a claim — search returns *candidates*, and evidence is a
passage someone pinned with a locator that resolves against the original bytes.

TWO HASHES, ON PURPOSE.

  index_hash       computed from the sorted LOGICAL rows plus schema, configuration, and input
                   artifact hashes. This is the reproducibility claim: the same canonical inputs and
                   the same configuration produce the same index_hash on any machine.
  sqlite_file_hash recorded separately and NOT used for reproducibility, because SQLite database
                   bytes legitimately differ across library versions, page sizes, and vacuum state.

Conflating the two would produce a reproducibility check that fails for reasons having nothing to do
with the content — and a check that cries wolf gets switched off.

ONLY INDEX-ELIGIBLE CHUNKS ARE INDEXED. A chunk from an `ocr_required` page exists in the canonical
artifact and is visible to `research inspect`, but it never enters the index, because a searchable
passage is one step away from becoming a citation.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..artifacts.io import make_artifact, read_artifact, write_artifact
from ..config import Workspace
from ..errors import SourceProcessingError
from ..hashing import canonical_json, sha256_file, sha256_text
from ..security.paths import safe_join

INDEX_SCHEMA_VERSION = "1.0.0"
DB_RELPATH = "indexes/research.sqlite3"
MANIFEST_RELPATH = "indexes/index-manifest.json"

_SCHEMA = """
CREATE TABLE chunks (
    rowid                INTEGER PRIMARY KEY,
    chunk_id             TEXT NOT NULL UNIQUE,
    document_id          TEXT NOT NULL,
    document_version_id  TEXT NOT NULL,
    page                 INTEGER,
    line_start           INTEGER,
    line_end             INTEGER,
    section_path         TEXT NOT NULL,
    start_offset         INTEGER NOT NULL,
    end_offset           INTEGER NOT NULL,
    text_sha256          TEXT NOT NULL,
    extraction_status    TEXT NOT NULL,
    media_type           TEXT NOT NULL,
    title                TEXT,
    document_type        TEXT,
    text                 TEXT NOT NULL
);
CREATE INDEX idx_chunks_document ON chunks(document_id);
CREATE INDEX idx_chunks_type ON chunks(document_type);
"""


@dataclass
class IndexResult:
    document_count: int
    chunk_count: int
    skipped_ineligible: int
    index_hash: str
    sqlite_file_hash: str
    manifest_path: str
    warnings: list[str]


def _fts_ddl(tokenizer: str, tokenizer_args: str) -> str:
    """FTS5 over an external content table so the row data is not duplicated.

    The tokenizer spelling is recorded in the manifest because it changes what matches: switching
    `remove_diacritics` silently alters which documents a query returns, which would make an old
    retrieval log irreproducible without anything looking broken.
    """
    tok = f"{tokenizer} {tokenizer_args}".strip()
    return (
        f"CREATE VIRTUAL TABLE chunks_fts USING fts5("
        f"text, content='chunks', content_rowid='rowid', tokenize='{tok}');"
    )


def _load_documents(ws: Workspace) -> list[dict[str, Any]]:
    manifests = sorted(safe_join(ws.root, "documents", "manifests").glob("*.json"))
    docs: list[dict[str, Any]] = []
    for path in manifests:
        # Validation before indexing (spec §8.3): a manifest whose hash does not verify has been
        # edited outside the amendment process and must not silently enter the index.
        docs.append(read_artifact(path, expect_schema="Document"))
    return docs


def build_index(ws: Workspace) -> IndexResult:
    """Build (or completely rebuild) the index from canonical artifacts."""
    documents = _load_documents(ws)
    if not documents:
        raise SourceProcessingError(
            "no documents to index",
            detail={"hint": "run `research import <path>` first"})

    tokenizer = str(ws.get("index.tokenizer", "unicode61"))
    tokenizer_args = str(ws.get("index.tokenizer_args", ""))
    warnings: list[str] = []

    rows: list[dict[str, Any]] = []
    skipped = 0
    input_hashes: list[dict[str, str]] = []

    for doc in sorted(documents, key=lambda d: d["document_id"]):
        input_hashes.append({"document_id": doc["document_id"],
                             "artifact_hash": doc["artifact_hash"]})
        rel = doc.get("chunk_set_path")
        if not rel:
            warnings.append(f"{doc['document_id']}: no chunk set (extraction status "
                            f"{doc.get('extraction_status')}); nothing to index")
            continue
        chunk_set = read_artifact(ws.root / rel, expect_schema="ChunkSet")
        input_hashes.append({"chunk_set_of": doc["document_id"],
                             "artifact_hash": chunk_set["artifact_hash"]})

        for chunk in chunk_set["chunks"]:
            if not chunk["index_eligible"]:
                skipped += 1
                continue
            rows.append({
                "chunk_id": chunk["chunk_id"],
                "document_id": chunk["document_id"],
                "document_version_id": chunk["document_version_id"],
                "page": chunk["page"],
                "line_start": chunk["line_start"],
                "line_end": chunk["line_end"],
                "section_path": canonical_json(chunk["section_path"]),
                "start_offset": chunk["start_offset"],
                "end_offset": chunk["end_offset"],
                "text_sha256": chunk["text_sha256"],
                "extraction_status": chunk["extraction_status"],
                "media_type": doc.get("media_type", ""),
                "title": (doc.get("metadata") or {}).get("title")
                         or (doc.get("original_filename_aliases") or [None])[0],
                "document_type": _document_type(doc),
                "text": chunk["text"],
            })

    # Deterministic input ordering: the row order is part of what index_hash attests, so it must not
    # depend on filesystem iteration order.
    rows.sort(key=lambda r: (r["document_id"], r["page"] if r["page"] is not None else -1,
                             r["chunk_id"]))

    db_path = safe_join(ws.root, *DB_RELPATH.split("/"))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()          # complete rebuild; the index is never incrementally patched

    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(_SCHEMA)
        conn.executescript(_fts_ddl(tokenizer, tokenizer_args))
        conn.executemany(
            "INSERT INTO chunks (rowid, chunk_id, document_id, document_version_id, page, "
            "line_start, line_end, section_path, start_offset, end_offset, text_sha256, "
            "extraction_status, media_type, title, document_type, text) "
            "VALUES (:rowid, :chunk_id, :document_id, :document_version_id, :page, :line_start, "
            ":line_end, :section_path, :start_offset, :end_offset, :text_sha256, "
            ":extraction_status, :media_type, :title, :document_type, :text)",
            [{**row, "rowid": i + 1} for i, row in enumerate(rows)])
        conn.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild')")
        conn.commit()
        sqlite_version = conn.execute("SELECT sqlite_version()").fetchone()[0]
    finally:
        conn.close()

    config = {
        "index_schema_version": INDEX_SCHEMA_VERSION,
        "tokenizer": tokenizer,
        "tokenizer_args": tokenizer_args,
        "ranking": str(ws.get("index.ranking", "bm25")),
        "chunking": ws.get("chunking", {}),
        "extraction_toolchain_version": ws.get("extraction.toolchain_version"),
        "normalization_version": ws.get("extraction.normalization_version"),
    }
    index_hash = _compute_index_hash(rows, config, input_hashes)
    file_hash = sha256_file(db_path)

    manifest = make_artifact(
        schema_name="IndexManifest", artifact_id=index_hash, actor_type="cli",
        body={
            "index_hash": index_hash,
            "sqlite_file_hash": file_hash,
            "sqlite_file_hash_note":
                "recorded for tamper-evidence only. Database bytes vary across SQLite builds, so "
                "reproducibility is asserted by index_hash over the logical rows, not by this.",
            "sqlite_version": sqlite_version,
            "config": config,
            "document_count": len(documents),
            "chunk_count": len(rows),
            "skipped_ineligible_chunks": skipped,
            "input_artifact_hashes": input_hashes,
            "result_ordering": ["bm25 ASC (SQLite returns negative scores; lower is a better match)",
                                "document_id ASC", "page ASC", "chunk_id ASC"],
            "warnings": warnings,
        })
    manifest_path = safe_join(ws.root, *MANIFEST_RELPATH.split("/"))
    write_artifact(manifest_path, manifest, root=ws.root)

    if skipped:
        warnings.append(
            f"{skipped} chunk(s) were excluded from the index because their page requires OCR or "
            f"human verification; they remain visible to `research inspect`")

    return IndexResult(
        document_count=len(documents), chunk_count=len(rows), skipped_ineligible=skipped,
        index_hash=index_hash, sqlite_file_hash=file_hash,
        manifest_path=str(manifest_path), warnings=warnings)


def _document_type(doc: dict[str, Any]) -> str:
    media = doc.get("media_type", "")
    return {"application/pdf": "pdf", "text/markdown": "markdown"}.get(media, "unknown")


def _compute_index_hash(rows: list[dict[str, Any]], config: dict[str, Any],
                        input_hashes: list[dict[str, str]]) -> str:
    """Hash the logical content, not the database file.

    Only fields that affect retrieval are included. `text` is represented by its hash so a very
    large corpus does not have to be re-serialized in full to verify the index.
    """
    logical = [
        {
            "chunk_id": r["chunk_id"],
            "document_id": r["document_id"],
            "document_version_id": r["document_version_id"],
            "page": r["page"],
            "section_path": r["section_path"],
            "start_offset": r["start_offset"],
            "end_offset": r["end_offset"],
            "text_sha256": r["text_sha256"],
        }
        for r in rows
    ]
    return sha256_text(canonical_json({
        "index_schema_version": INDEX_SCHEMA_VERSION,
        "config": config,
        "inputs": sorted(input_hashes, key=lambda h: canonical_json(h)),
        "rows": logical,
    }))


def open_index(ws: Workspace) -> sqlite3.Connection:
    db_path = Path(ws.root) / DB_RELPATH
    if not db_path.is_file():
        raise SourceProcessingError(
            "no index in this workspace",
            detail={"expected": str(db_path), "hint": "run `research index`"})
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn
