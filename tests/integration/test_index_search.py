"""Phase 4: indexing and search.

Covers release gate 38.3 (index determinism) and the search contract in spec §8.4.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fixtures.make_fixtures import build  # noqa: E402

from research.artifacts.io import read_artifact  # noqa: E402
from research.artifacts.locators import resolve_text_locator  # noqa: E402
from research.config import load_workspace  # noqa: E402
from research.errors import InvalidArguments, SourceProcessingError  # noqa: E402
from research.indexing.builder import DB_RELPATH, build_index  # noqa: E402
from research.importers.importer import import_paths  # noqa: E402
from research.search.engine import normalize_query, search  # noqa: E402
from research.workspace import init_workspace  # noqa: E402


@pytest.fixture
def sources(tmp_path: Path) -> dict[str, Path]:
    return build(tmp_path / "sources")


@pytest.fixture
def indexed(tmp_path: Path, sources):
    init_workspace(tmp_path / "ws")
    ws = load_workspace(tmp_path / "ws")
    import_paths(ws, [sources["text_pdf"], sources["markdown"], sources["low_text_pdf"]])
    result = build_index(ws)
    return ws, result


# --------------------------------------------------------------- 38.3 index determinism


def test_rebuilding_from_identical_artifacts_gives_the_same_index_hash(indexed):
    ws, first = indexed
    second = build_index(ws)
    assert second.index_hash == first.index_hash


def test_index_hash_matches_across_independent_workspaces(tmp_path: Path, sources):
    """Reproducibility is a property of the canonical inputs, not of one machine's database file."""
    hashes = []
    for name in ("a", "b"):
        init_workspace(tmp_path / name)
        ws = load_workspace(tmp_path / name)
        import_paths(ws, [sources["text_pdf"], sources["markdown"]])
        hashes.append(build_index(ws).index_hash)
    assert hashes[0] == hashes[1]


def test_index_hash_changes_when_the_corpus_changes(tmp_path: Path, sources):
    init_workspace(tmp_path / "ws")
    ws = load_workspace(tmp_path / "ws")
    import_paths(ws, [sources["text_pdf"]])
    before = build_index(ws).index_hash
    import_paths(ws, [sources["markdown"]])
    assert build_index(ws).index_hash != before


def test_sqlite_file_hash_is_recorded_separately_from_the_index_hash(indexed):
    """Database bytes vary across SQLite builds, so they must not carry the reproducibility claim."""
    ws, result = indexed
    manifest = read_artifact(ws.root / "indexes" / "index-manifest.json",
                             expect_schema="IndexManifest")
    assert manifest["index_hash"] == result.index_hash
    assert manifest["sqlite_file_hash"] != manifest["index_hash"]
    assert "vary across SQLite builds" in manifest["sqlite_file_hash_note"]


def test_manifest_records_everything_needed_to_reproduce(indexed):
    ws, _ = indexed
    manifest = read_artifact(ws.root / "indexes" / "index-manifest.json",
                             expect_schema="IndexManifest")
    cfg = manifest["config"]
    for key in ("index_schema_version", "tokenizer", "tokenizer_args", "ranking", "chunking",
                "extraction_toolchain_version", "normalization_version"):
        assert key in cfg, f"index manifest must record {key}"
    assert manifest["sqlite_version"]
    assert manifest["input_artifact_hashes"]


def test_index_is_a_complete_rebuild_not_an_append(indexed):
    ws, first = indexed
    build_index(ws)
    conn = sqlite3.connect(str(ws.root / DB_RELPATH))
    try:
        count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    finally:
        conn.close()
    assert count == first.chunk_count, "rebuilding must not duplicate rows"


def test_ocr_required_chunks_never_enter_the_index(indexed):
    """A searchable passage is one step from becoming a citation."""
    ws, result = indexed
    assert result.skipped_ineligible >= 1
    conn = sqlite3.connect(str(ws.root / DB_RELPATH))
    try:
        statuses = {r[0] for r in conn.execute("SELECT DISTINCT extraction_status FROM chunks")}
    finally:
        conn.close()
    assert "ocr_required" not in statuses


def test_index_requires_documents(tmp_path: Path):
    init_workspace(tmp_path / "empty")
    with pytest.raises(SourceProcessingError):
        build_index(load_workspace(tmp_path / "empty"))


# --------------------------------------------------------------- query safety


@pytest.mark.parametrize("raw,expected_terms", [
    ("process-in-memory", ["process-in-memory"]),
    ("data movement", ["data", "movement"]),
    ("v1.2 config", ["v1.2", "config"]),
])
def test_tokenization_keeps_intra_word_marks(raw, expected_terms):
    _, norm = normalize_query(raw)
    assert norm["terms"] == expected_terms


def test_fts_operators_are_not_interpreted():
    """`NOT`, `OR`, `*` and column filters must be literals, not operators."""
    fts, norm = normalize_query("memory NOT movement")
    assert norm["operators_interpreted"] is False
    assert fts == '"memory" "NOT" "movement"'


def test_quoted_phrases_are_preserved():
    fts, norm = normalize_query('"data movement" reduction')
    assert norm["phrases"] == ["data movement"]
    assert '"data movement"' in fts


@pytest.mark.parametrize("hostile", [
    'foo" OR "bar',
    "chunks_fts MATCH 'x'",
    'text:"injected"',
    "a AND (b OR c)",
    "'; DROP TABLE chunks; --",
    "NEAR(a b, 2)",
    "*",
])
def test_hostile_queries_do_not_break_or_escape(indexed, hostile):
    """Untrusted text can reach a query through an agent; it must never reach the FTS grammar."""
    ws, _ = indexed
    try:
        out = search(ws, hostile)
    except InvalidArguments:
        return          # rejecting a query with no searchable terms is a valid outcome
    assert isinstance(out["result_count"], int)
    assert out["query_normalization"]["operators_interpreted"] is False


def test_query_with_no_searchable_terms_is_rejected(indexed):
    ws, _ = indexed
    with pytest.raises(InvalidArguments):
        search(ws, "!!! ??? ***")


# --------------------------------------------------------------- search contract


def test_results_are_ranked_and_deterministic(indexed):
    ws, _ = indexed
    a = search(ws, "process-in-memory data movement")
    b = search(ws, "process-in-memory data movement")
    assert [r["chunk_id"] for r in a["results"]] == [r["chunk_id"] for r in b["results"]]
    assert [r["rank"] for r in a["results"]] == list(range(1, a["result_count"] + 1))


def test_ranking_is_reported_but_carries_no_evidence_quality(indexed):
    ws, _ = indexed
    out = search(ws, "data movement")
    assert "bm25" in out["ranking"]["function"]
    for r in out["results"]:
        assert "NOT a measure of evidence quality" in r["score_note"]
        # there must be no field that could be mistaken for support
        assert "confidence" not in r and "relevance" not in r and "verified" not in r


def test_every_result_carries_a_locator_that_actually_resolves(indexed):
    """The end-to-end property: search → locator → exact source text."""
    ws, _ = indexed
    out = search(ws, "process-in-memory data movement")
    assert out["result_count"] > 0
    for result in out["results"]:
        manifest_path = next(
            p for p in (ws.root / "documents" / "manifests").glob("*.json")
            if read_artifact(p, expect_schema="Document")["document_id"] == result["document_id"])
        manifest = read_artifact(manifest_path, expect_schema="Document")
        text = (ws.root / manifest["normalized_text_path"]).read_text(encoding="utf-8")
        resolution = resolve_text_locator(result["locator"], text)
        assert resolution.ok, f"{result['chunk_id']}: {resolution.status} {resolution.detail}"
        assert resolution.text


def test_results_carry_document_version_and_position(indexed):
    ws, _ = indexed
    for r in search(ws, "data movement")["results"]:
        assert r["document_version_id"].startswith("DVER-sha256-")
        assert r["page"] is not None or r["line_start"] is not None


def test_document_type_filter_applies(indexed):
    ws, _ = indexed
    out = search(ws, "retrieval accuracy", document_type="markdown")
    assert out["filters"]["document_type"] == "markdown"
    for r in out["results"]:
        assert r["source"]["document_type"] == "markdown"


def test_unknown_filter_values_are_rejected(indexed):
    ws, _ = indexed
    with pytest.raises(InvalidArguments):
        search(ws, "anything", document_type="powerpoint")
    with pytest.raises(InvalidArguments):
        search(ws, "anything", document_id="not-a-document-id")


def test_limit_is_enforced_and_validated(indexed):
    ws, _ = indexed
    assert search(ws, "the", limit=1)["result_count"] <= 1
    with pytest.raises(InvalidArguments):
        search(ws, "the", limit=0)


def test_retrieval_log_hash_is_stable_for_the_same_query(indexed):
    """Retrieval must be replayable: same query, same filters, same result set (spec §29)."""
    ws, _ = indexed
    a = search(ws, "data movement")
    b = search(ws, "data movement")
    assert a["retrieval_log_hash"] == b["retrieval_log_hash"]
    c = search(ws, "data movement", limit=1)
    assert c["retrieval_log_hash"] != a["retrieval_log_hash"]


def test_searching_without_an_index_is_an_actionable_error(tmp_path: Path):
    init_workspace(tmp_path / "ws")
    with pytest.raises(SourceProcessingError) as exc:
        search(load_workspace(tmp_path / "ws"), "anything")
    assert "research index" in str(exc.value.detail)
