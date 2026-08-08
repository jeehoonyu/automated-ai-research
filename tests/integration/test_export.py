"""`research export` — a validated run in a format other tools read.

GOAL.md carried this as *"nothing leaves the tool"*: a finished run produced Markdown and nothing
else, so research that could not be cited, filtered or diffed elsewhere stayed in the tool.

The interesting tests here are not the happy paths. They are:

  - that an export passes the SAME gate as publication, because a CSV circulates more easily than
    a report and is easier to paste into something else;
  - that a draft says so in every row, because a filename is lost the moment someone opens the
    file in a spreadsheet;
  - that the citation table never presents unverified PDF metadata as a bibliographic fact.
"""

from __future__ import annotations

import csv
import io
import json

import pytest
from integration.conftest import re_review

from research.errors import InvalidArguments, ReportGatingError
from research.hashing import stamp_artifact_hash
from research.reporting.export import (
    FORMATS,
    _citation_rows,
    _claim_rows,
    _evidence_rows,
    export_run,
    render_csv,
)
from research.validation.validator import validate_run


def _rows(ws, result):
    text = (ws.root / result.path).read_text(encoding="utf-8")
    return list(csv.DictReader(io.StringIO(text)))


# --------------------------------------------------------------- it produces the data


@pytest.mark.parametrize("fmt", FORMATS)
def test_every_format_exports_a_validated_run(complete_run, fmt):
    ws, rid, _ = complete_run
    validate_run(ws, rid)
    result = export_run(ws, rid, fmt=fmt)
    rows = _rows(ws, result)

    assert result.row_count == len(rows) >= 1, f"{fmt} exported nothing"
    assert result.path.endswith(f"{fmt}.csv")
    assert all(row["report_eligible"] == "true" for row in rows)


def test_claims_carry_what_a_reader_needs_to_check_them(complete_run):
    """Not a column-count assertion — the specific fields that make a row auditable rather than
    merely informative."""
    ws, rid, meta = complete_run
    validate_run(ws, rid)
    row = _rows(ws, export_run(ws, rid, fmt="claims"))[0]

    assert row["claim_id"] == meta["claim_id"]
    assert row["support_classification"] == "moderately_supported"
    assert meta["evidence_id"] in row["supporting_evidence_ids"]
    assert row["artifact_hash"].startswith("sha256:")
    # Spec §23's factor ratings travel with the classification. A support level exported without
    # them is the number without its working.
    assert "evidence_directness=high" in row["confidence_factors"]


def test_evidence_rows_name_the_claims_that_rest_on_them(complete_run):
    """The join a spreadsheet cannot reconstruct: evidence records do not point at claims, claims
    point at evidence, so the reverse index has to be built here or not at all."""
    ws, rid, meta = complete_run
    validate_run(ws, rid)
    row = _rows(ws, export_run(ws, rid, fmt="evidence"))[0]

    assert row["evidence_id"] == meta["evidence_id"]
    assert meta["claim_id"] in row["claim_ids"]
    assert row["locator_type"] == "text_span"
    assert row["exact_text"]


def test_citations_list_only_documents_the_run_actually_cited(complete_run):
    """The corpus holds what you gave it; the run rests on what it used. Exporting the corpus
    would overstate what the conclusions stand on — the same error as counting a related source
    as support. `complete_run` imports two documents and cites one."""
    ws, rid, meta = complete_run
    validate_run(ws, rid)
    rows = _rows(ws, export_run(ws, rid, fmt="citations"))

    assert len(rows) == 1, "a document nothing cited was exported as a citation"
    assert rows[0]["document_id"] == meta["doc"]["document_id"]
    assert int(rows[0]["cited_by_evidence_count"]) >= 1


def test_the_citation_table_says_where_its_title_came_from(complete_run):
    """The load-bearing honesty column.

    There is no BibTeX output because this package holds no bibliography — a PDF `/Title` is a
    string inside an untrusted file and a filename is what someone happened to save it as. Both
    are usable; neither is a verified bibliographic title. A `title` column that did not say which
    it was would invite exactly the assumption the export refuses to make.
    """
    ws, rid, _ = complete_run
    validate_run(ws, rid)
    row = _rows(ws, export_run(ws, rid, fmt="citations"))[0]

    # The EXACT value, not membership in the set of legal values. Accepting any of the three let a
    # mutation that always reported `pdf_metadata_title_unverified` pass — the column would have
    # been wrong in the one direction that matters, claiming a title came from inside the file when
    # it came from the filename. This fixture's PDF carries no `/Title`.
    assert row["title_source"] == "imported_filename"
    assert row["title_as_recorded"] == "text-paper.pdf"
    assert row["source_sha256"].startswith("sha256:"), (
        "the hash is the one identifying fact here that IS verified; it must travel with the row")


# --------------------------------------------------------------- and it refuses


def test_an_unvalidated_run_cannot_be_exported(complete_run):
    ws, rid, _ = complete_run
    with pytest.raises(ReportGatingError) as exc:
        export_run(ws, rid, fmt="claims")
    assert "has not been validated" in exc.value.message


def test_a_blocked_run_cannot_be_exported(complete_run):
    """The point of routing export through the publication gate. Without it, `--format claims`
    would be a way to circulate exactly the conclusions `research report` refused to print."""
    ws, rid, meta = complete_run
    meta["review_paths"]["independent_review"].unlink()
    validate_run(ws, rid)

    with pytest.raises(ReportGatingError) as exc:
        export_run(ws, rid, fmt="claims")
    assert any(b["check"] == "independent_review_complete" for b in exc.value.detail["blocking"])


def test_an_export_refuses_artifacts_the_verdict_was_not_computed_over(complete_run):
    """`report_eligible` is a boolean in a file; the rows are built by re-reading `claims/`. A
    claim edited after validation must not be exported under the old verdict."""
    ws, rid, meta = complete_run
    validate_run(ws, rid)
    claim = json.loads(meta["claim_path"].read_text(encoding="utf-8"))
    claim["claim"] = "Process-in-memory eliminates data movement."
    meta["claim_path"].write_text(json.dumps(stamp_artifact_hash(claim)), encoding="utf-8")

    with pytest.raises(ReportGatingError) as exc:
        export_run(ws, rid, fmt="claims")
    assert "not the artifacts that were validated" in exc.value.message


def test_a_draft_export_marks_every_row_not_just_the_filename(complete_run):
    """A filename is lost the moment someone opens the file in a spreadsheet and saves it
    elsewhere. The marking has to survive that, so it is a column."""
    ws, rid, _ = complete_run
    result = export_run(ws, rid, fmt="claims", draft=True)

    assert result.path.endswith("claims-draft.csv")
    rows = _rows(ws, result)
    assert rows and all(row["report_eligible"] == "false" for row in rows)


def test_an_unknown_format_is_refused(complete_run):
    ws, rid, _ = complete_run
    with pytest.raises(InvalidArguments) as exc:
        export_run(ws, rid, fmt="bibtex")
    assert "bibtex" in exc.value.message


# --------------------------------------------------------------- untrusted text in a spreadsheet
#
# `docs/security-model.md`: *"A document is data. There is no path from document content to
# execution."* This export opened one. `exact_text` is a verbatim slice of an attacker-controlled
# PDF and `claim` is text an agent wrote after reading one, and both go into a file whose purpose
# is to be opened in Excel, where a cell beginning `=` is a formula.


@pytest.mark.parametrize("cell", [
    "=1+1",
    "+cmd|'/c calc'!A1",
    "-2+3",
    "@SUM(1:9)",
    "\t=1+1",          # tab first: some importers strip it and then see the `=`
    "\r=1+1",
])
def test_a_cell_a_spreadsheet_would_execute_is_neutralized(cell):
    text, neutralized = render_csv(("v",), [{"v": cell}])
    assert neutralized == 1
    assert text.splitlines()[1].startswith("'") or '"\'' in text, text


@pytest.mark.parametrize("cell", ["normal text", "a-b", "3+4", "", "x@y.com"])
def test_ordinary_text_is_left_exactly_alone(cell):
    """A mitigation that mangles legitimate values teaches people to distrust the export. Only a
    LEADING trigger is a formula; a hyphen or `@` inside a cell is just text."""
    _text, neutralized = render_csv(("v",), [{"v": cell}])
    assert neutralized == 0


def test_quoting_still_handles_commas_quotes_and_newlines():
    """Neutralizing is a different problem from quoting, and adding it must not break quoting.
    Note that quoting alone would NOT have helped: `"=1+1"` is still a formula to Excel."""
    text, _ = render_csv(("a", "b", "c"),
                         [{"a": "has,comma", "b": 'has"quote', "c": "has\nnewline"}])
    row = list(csv.reader(io.StringIO(text)))[1]
    assert row == ["has,comma", 'has"quote', "has\nnewline"]


def test_the_export_says_when_it_altered_a_cell(complete_run):
    """Silently changing a quotation would break the one thing this package promises about
    quotations. The count travels back to the caller, and the CLI warns on it."""
    ws, rid, meta = complete_run
    claim = json.loads(meta["claim_path"].read_text(encoding="utf-8"))
    claim["claim"] = "=HYPERLINK(\"http://evil.invalid\",\"click\")"
    meta["claim_path"].write_text(json.dumps(stamp_artifact_hash(claim)), encoding="utf-8")
    re_review(meta)
    validate_run(ws, rid)

    result = export_run(ws, rid, fmt="claims")
    assert result.neutralized_cells >= 1
    body = (ws.root / result.path).read_text(encoding="utf-8")
    assert "'=HYPERLINK" in body
    # And the artifact itself is untouched — only the CSV rendering was changed.
    assert json.loads(meta["claim_path"].read_text(encoding="utf-8"))["claim"].startswith("=")


# --------------------------------------------------------------- determinism


def test_exporting_twice_produces_identical_bytes(complete_run):
    """Same artifacts in, same bytes out — the property that makes a CSV diffable between two runs
    of the same question, which is most of why anyone wants one."""
    ws, rid, _ = complete_run
    validate_run(ws, rid)
    first = (ws.root / export_run(ws, rid, fmt="claims").path).read_bytes()
    second = (ws.root / export_run(ws, rid, fmt="claims").path).read_bytes()
    assert first == second


# --------------------------------------------------------------- the row builders, directly
#
# `complete_run` holds ONE claim, ONE evidence record and ONE cited document, which makes ordering
# and the title-source branches unobservable through it — a mutation that stopped sorting, and one
# that mislabelled every title, both survived the fixture-driven tests above. These drive the
# builders with several out-of-order items instead. Not a substitute for the end-to-end tests: they
# check the shape of a table, which is the one thing a single-row fixture cannot.


class _Ctx:
    """The four attributes the row builders read. A real `RunContext` would drag a workspace,
    a profile and a lifecycle in for no gain."""

    def __init__(self, claims=(), evidence=(), documents=None, run_id="RUN-x"):
        self.claims = list(claims)
        self.evidence = list(evidence)
        self.documents = documents or {}
        self.run_id = run_id


def test_claim_rows_are_ordered_by_id_not_by_filesystem():
    """Directory order is not a promise any filesystem makes. An export that reordered between
    machines could not be diffed, which is most of why anyone wants a CSV."""
    ctx = _Ctx(claims=[{"claim_id": "CLM-c"}, {"claim_id": "CLM-a"}, {"claim_id": "CLM-b"}])
    assert [r["claim_id"] for r in _claim_rows(ctx, True)] == ["CLM-a", "CLM-b", "CLM-c"]


def test_evidence_rows_are_ordered_and_carry_every_citing_claim():
    ctx = _Ctx(
        claims=[{"claim_id": "CLM-2", "supporting_evidence_ids": ["EVD-b"]},
                {"claim_id": "CLM-1", "supporting_evidence_ids": ["EVD-b"],
                 "contradicting_evidence_ids": ["EVD-a"]}],
        evidence=[{"evidence_id": "EVD-b"}, {"evidence_id": "EVD-a"}])
    rows = _evidence_rows(ctx, True)

    assert [r["evidence_id"] for r in rows] == ["EVD-a", "EVD-b"]
    # Both citing claims, sorted — and a contradicting reference counts as a citation here, because
    # "which claims does this evidence bear on" is the question, not "which does it support".
    assert rows[1]["claim_ids"] == "CLM-1; CLM-2"
    assert rows[0]["claim_ids"] == "CLM-1"


@pytest.mark.parametrize("metadata,expected_title,expected_source", [
    ({"title": "A Real Paper Title"}, "A Real Paper Title", "pdf_metadata_title_unverified"),
    ({}, "saved-as.pdf", "imported_filename"),
    (None, "saved-as.pdf", "imported_filename"),
])
def test_the_title_column_names_its_own_provenance(metadata, expected_title, expected_source):
    """Every branch, because the column exists only to distinguish them.

    A PDF `/Title` is a string inside an untrusted file; a filename is what someone happened to
    save it as. Both are usable, neither is a verified bibliographic title, and a reader who cannot
    tell which one they have will assume the stronger.
    """
    ctx = _Ctx(
        evidence=[{"evidence_id": "EVD-a", "document_id": "DOC-1"}],
        documents={"DOC-1": {"document_id": "DOC-1", "metadata": metadata,
                             "original_filename_aliases": ["saved-as.pdf"]}})
    row = _citation_rows(ctx, True)[0]

    assert row["title_as_recorded"] == expected_title
    assert row["title_source"] == expected_source


def test_a_cited_document_missing_from_the_workspace_is_still_listed():
    """It must not vanish. A citation table that silently drops the source it cannot describe
    understates what the run rested on — and understating is still misreporting."""
    ctx = _Ctx(evidence=[{"evidence_id": "EVD-a", "document_id": "DOC-gone"}], documents={})
    rows = _citation_rows(ctx, True)

    assert len(rows) == 1
    assert rows[0]["document_id"] == "DOC-gone"
    assert rows[0]["title_source"] == "unknown"
    assert rows[0]["title_as_recorded"] == ""
