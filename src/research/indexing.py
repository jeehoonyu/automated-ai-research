from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unicodedata
from pathlib import Path
from typing import Any

from research.artifacts import artifact_base, load_and_verify_artifact, store_artifact
from research.canonical import canonical_sha256
from research.config import load_config
from research.constants import NORMALIZATION_VERSION
from research.errors import ResearchError
from research.identifiers import derived_identifier
from research.io import append_jsonl, file_sha256, iter_json, utc_now, write_json_atomic
from research.security import redact_secrets

DATABASE_SCHEMA_VERSION = "1.0.0"


def build_index(workspace: Path) -> dict[str, Any]:
    config = load_config(workspace)
    chunks = _current_chunks(workspace)
    chunks.sort(
        key=lambda item: (
            str(item["document_id"]),
            _nullable_number(item.get("page")),
            str(item["chunk_id"]),
        )
    )
    rows = [_index_row(chunk, workspace) for chunk in chunks]
    rows.sort(key=lambda row: (row["document_id"], _nullable_number(row["page"]), row["chunk_id"]))
    tokenizer = str(config["index"]["tokenizer"])
    logical_payload = {
        "database_schema_version": DATABASE_SCHEMA_VERSION,
        "tokenizer": tokenizer,
        "ranking": config["index"]["ranking"],
        "chunking": config["chunking"],
        "rows": rows,
    }
    logical_hash = canonical_sha256(logical_payload)
    index_id = derived_identifier("IDX", logical_payload)
    indexes = workspace / "indexes"
    indexes.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".research-index-", suffix=".sqlite3", dir=indexes
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    database = indexes / "research.sqlite3"
    try:
        connection = sqlite3.connect(temporary)
        try:
            _create_database(connection, tokenizer)
            for row in rows:
                cursor = connection.execute(
                    """
                    INSERT INTO chunks (
                        chunk_id, document_id, document_version_id, page, source_line_start,
                        source_line_end, section_path, start_offset, end_offset, text,
                        text_sha256, media_type, title, source_metadata
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["chunk_id"],
                        row["document_id"],
                        row["document_version_id"],
                        row["page"],
                        row["source_line_start"],
                        row["source_line_end"],
                        json.dumps(row["section_path"], ensure_ascii=False),
                        row["start_offset"],
                        row["end_offset"],
                        row["text"],
                        row["text_sha256"],
                        row["media_type"],
                        row["title"],
                        json.dumps(row["source_metadata"], ensure_ascii=False, sort_keys=True),
                    ),
                )
                connection.execute(
                    "INSERT INTO chunks_fts(rowid, text) VALUES (?, ?)",
                    (cursor.lastrowid, row["text"]),
                )
            connection.commit()
            connection.execute("PRAGMA optimize")
        finally:
            connection.close()
        os.replace(temporary, database)
    finally:
        if temporary.exists():
            temporary.unlink()
    database_hash = f"sha256:{file_sha256(database)}"
    manifest = artifact_base("IndexManifest", index_id)
    manifest.update(
        {
            "index_id": index_id,
            "sqlite_version": sqlite3.sqlite_version,
            "tokenizer": tokenizer,
            "ranking": config["index"]["ranking"],
            "input_artifact_hashes": [chunk["artifact_hash"] for chunk in chunks],
            "input_ordering": "document_id ASC, page ASC NULLS LAST, chunk_id ASC",
            "database_schema_version": DATABASE_SCHEMA_VERSION,
            "chunking_configuration": config["chunking"],
            "extraction_versions": [NORMALIZATION_VERSION],
            "document_version_ids": sorted({str(chunk["document_version_id"]) for chunk in chunks}),
            "logical_index_hash": logical_hash,
            "database_file_hash": database_hash,
            "chunk_count": len(chunks),
        }
    )
    stored, path = store_artifact(workspace, manifest)
    write_json_atomic(indexes / "index-manifest.json", stored)
    return {
        "index_id": index_id,
        "index_path": str(database),
        "manifest_path": str(path),
        "chunk_count": len(chunks),
        "logical_index_hash": logical_hash,
        "database_file_hash": database_hash,
        "sqlite_version": sqlite3.sqlite_version,
    }


def search_index(
    workspace: Path,
    query: str,
    *,
    document_type: str | None = None,
    document_id: str | None = None,
    limit: int = 20,
    run_id: str | None = None,
) -> dict[str, Any]:
    normalized = unicodedata.normalize("NFC", " ".join(query.split()))
    fts_query = _literal_fts_query(normalized)
    database = workspace / "indexes" / "research.sqlite3"
    manifest_path = workspace / "indexes" / "index-manifest.json"
    if not database.is_file() or not manifest_path.is_file():
        raise ResearchError(
            "No index exists; run `research index` first", category="index_not_found"
        )
    manifest = load_and_verify_artifact(manifest_path)
    predicates = ["chunks_fts MATCH ?"]
    parameters: list[Any] = [fts_query]
    filters: dict[str, Any] = {}
    if document_type:
        predicates.append("chunks.media_type = ?")
        parameters.append(document_type)
        filters["document_type"] = document_type
    if document_id:
        predicates.append("chunks.document_id = ?")
        parameters.append(document_id)
        filters["document_id"] = document_id
    parameters.append(limit)
    sql = f"""
        SELECT chunks.*, bm25(chunks_fts) AS native_score
        FROM chunks_fts
        JOIN chunks ON chunks.rowid = chunks_fts.rowid
        WHERE {" AND ".join(predicates)}
        ORDER BY native_score ASC, chunks.document_id ASC,
                 CASE WHEN chunks.page IS NULL THEN 2147483647 ELSE chunks.page END ASC,
                 chunks.chunk_id ASC
        LIMIT ?
    """
    connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        raw_rows = connection.execute(sql, parameters).fetchall()
    except sqlite3.OperationalError as exc:
        raise ResearchError(
            f"Invalid or unsupported search query: {exc}", category="invalid_query"
        ) from exc
    finally:
        connection.close()
    results: list[dict[str, Any]] = []
    for rank, row in enumerate(raw_rows, start=1):
        source_metadata = json.loads(row["source_metadata"])
        results.append(
            {
                "rank": rank,
                "native_bm25_score": row["native_score"],
                "document_id": row["document_id"],
                "document_version_id": row["document_version_id"],
                "chunk_id": row["chunk_id"],
                "page": row["page"],
                "source_line_start": row["source_line_start"],
                "source_line_end": row["source_line_end"],
                "section_path": json.loads(row["section_path"]),
                "text_span": {"start_offset": row["start_offset"], "end_offset": row["end_offset"]},
                "locator": {
                    "type": "text_span",
                    "page": row["page"],
                    "source_line_start": row["source_line_start"],
                    "source_line_end": row["source_line_end"],
                    "chunk_id": row["chunk_id"],
                    "start_offset": 0,
                    "end_offset": len(row["text"]),
                    "span_sha256": row["text_sha256"],
                },
                "text": row["text"],
                "source_metadata": source_metadata,
            }
        )
    event = {
        "timestamp": utc_now(),
        "run_id": run_id,
        "query": redact_secrets(query),
        "query_normalization": redact_secrets(normalized),
        "fts_query": redact_secrets(fts_query),
        "filters": filters,
        "limit": limit,
        "result_chunk_ids": [result["chunk_id"] for result in results],
        "index_id": manifest["index_id"],
    }
    append_jsonl(workspace / "logs" / "search-events.jsonl", event)
    return {
        "query": query,
        "query_normalization": normalized,
        "applied_filters": filters,
        "ranking_configuration": {
            "function": manifest["ranking"],
            "tokenizer": manifest["tokenizer"],
            "tie_breaking": "document_id ASC, page ASC NULLS LAST, chunk_id ASC",
        },
        "index_id": manifest["index_id"],
        "results": results,
    }


def _create_database(connection: sqlite3.Connection, tokenizer: str) -> None:
    connection.executescript(
        """
        PRAGMA journal_mode=DELETE;
        PRAGMA synchronous=FULL;
        CREATE TABLE chunks (
            rowid INTEGER PRIMARY KEY,
            chunk_id TEXT NOT NULL UNIQUE,
            document_id TEXT NOT NULL,
            document_version_id TEXT NOT NULL,
            page INTEGER,
            source_line_start INTEGER,
            source_line_end INTEGER,
            section_path TEXT NOT NULL,
            start_offset INTEGER NOT NULL,
            end_offset INTEGER NOT NULL,
            text TEXT NOT NULL,
            text_sha256 TEXT NOT NULL,
            media_type TEXT NOT NULL,
            title TEXT,
            source_metadata TEXT NOT NULL
        );
        CREATE INDEX chunks_document_id_idx ON chunks(document_id);
        CREATE INDEX chunks_media_type_idx ON chunks(media_type);
        """
    )
    safe_tokenizer = tokenizer.replace("'", "''")
    connection.execute(
        f"CREATE VIRTUAL TABLE chunks_fts USING fts5(text, content='chunks', "
        f"content_rowid='rowid', tokenize='{safe_tokenizer}')"
    )


def _current_chunks(workspace: Path) -> list[dict[str, Any]]:
    expected_chunking_hash = canonical_sha256(load_config(workspace)["chunking"])
    versions: dict[str, dict[str, Any]] = {}
    for candidate in iter_json(workspace / "documents" / "versions"):
        if candidate.get("schema_name") != "DocumentVersion":
            continue
        document_id = str(candidate["document_id"])
        if document_id not in versions or str(candidate["created_at"]) > str(
            versions[document_id]["created_at"]
        ):
            versions[document_id] = candidate
    current_version_ids = {str(value["document_version_id"]) for value in versions.values()}
    chunks: dict[str, dict[str, Any]] = {}
    for candidate in iter_json(workspace / "documents" / "chunks"):
        if candidate.get("schema_name") != "Chunk":
            continue
        if candidate.get("document_version_id") not in current_version_ids:
            continue
        if candidate.get("chunking_configuration_hash") != expected_chunking_hash:
            continue
        load_and_verify_artifact(_find_artifact_file(workspace, candidate))
        chunks[str(candidate["chunk_id"])] = candidate
    return list(chunks.values())


def _find_artifact_file(workspace: Path, artifact: dict[str, Any]) -> Path:
    from research.artifacts import immutable_artifact_path

    return immutable_artifact_path(workspace, artifact)


def _index_row(chunk: dict[str, Any], workspace: Path) -> dict[str, Any]:
    document = _load_latest_by_schema_and_id(
        workspace / "documents" / "manifests", "Document", str(chunk["document_id"])
    )
    version_artifact = _load_latest_by_schema_and_id(
        workspace / "documents" / "versions", "DocumentVersion", str(chunk["document_version_id"])
    )
    metadata = dict(document.get("metadata", {}))
    metadata.update(version_artifact.get("metadata", {}))
    return {
        "chunk_id": chunk["chunk_id"],
        "document_id": chunk["document_id"],
        "document_version_id": chunk["document_version_id"],
        "page": chunk.get("page"),
        "source_line_start": chunk.get("source_line_start"),
        "source_line_end": chunk.get("source_line_end"),
        "section_path": chunk.get("section_path", []),
        "start_offset": chunk["start_offset"],
        "end_offset": chunk["end_offset"],
        "text": chunk["exact_text"],
        "text_sha256": chunk["text_sha256"],
        "media_type": document["media_type"],
        "title": metadata.get("title") or metadata.get("original_filename"),
        "source_metadata": metadata,
    }


def _load_latest_by_schema_and_id(root: Path, schema: str, artifact_id: str) -> dict[str, Any]:
    candidates = [
        value
        for value in iter_json(root)
        if value.get("schema_name") == schema
        and (
            value.get("artifact_id") == artifact_id
            or value.get("document_version_id") == artifact_id
        )
    ]
    if not candidates:
        raise ResearchError(
            f"Missing {schema} artifact {artifact_id}", category="dangling_reference"
        )
    selected = max(candidates, key=lambda value: str(value["created_at"]))
    return load_and_verify_artifact(_find_artifact_file(root.parents[1], selected))


def _literal_fts_query(query: str) -> str:
    tokens = [token for token in query.split() if token]
    if not tokens:
        raise ResearchError("Search query must contain text", category="invalid_query")
    return " AND ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens)


def _nullable_number(value: Any) -> int:
    return int(value) if value is not None else 2_147_483_647
