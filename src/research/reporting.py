from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, StrictUndefined

from research.artifacts import artifact_base, store_artifact
from research.canonical import prefixed_sha256
from research.constants import EXIT_REPORT_GATE
from research.errors import ResearchError
from research.identifiers import derived_identifier
from research.io import write_text_atomic
from research.runs import latest_artifact, load_run, transition_published
from research.validation import (
    _current_run_artifacts,
    publication_integrity_errors,
    validation_input_artifact_hashes,
)

REPORT_TEMPLATE = """{% if draft %}
> **DRAFT — NOT VALIDATED OR PUBLISHED**

{% endif %}# Research Report

## Research question

{{ question }}

## Scope and research method

- Profile: `{{ profile }}`
- Workflow version: `{{ workflow_version }}`
- Reviewer independence: `{{ independence_status }}`
- Human review status: `{{ human_review_status }}`

{% if plan %}- Scope: {{ plan.scope | tojson }}
- Inclusion criteria: {{ plan.inclusion_criteria | join('; ') }}
- Exclusion criteria: {{ plan.exclusion_criteria | join('; ') }}
- Search terms: {{ plan.search_terms | join('; ') }}
- Expected limitations: {{ plan.expected_limitations | join('; ') }}
{% else %}No validated research plan is available.{% endif %}

## Source summary

{% for source in sources %}- `{{ source.document_id }}` — {{ source.title }}
{% else %}- No canonical sources were referenced.
{% endfor %}

## Main findings

{% for claim in claims %}### {{ claim.claim_id }} — {{ claim.support_classification }}

{{ claim.claim }}

- Type: `{{ claim.claim_type }}`
- Status: `{{ claim.claim_status }}`
- Citation status: `{{ claim.citation_status }}`
- Contradiction status: `{{ claim.contradiction_status }}`
- Methodology status: `{{ claim.methodology_status }}`
- Independent-review status: `{{ claim.independent_review_status }}`
- Human review required: `{{ claim.human_review_required }}`

Uncertainty factors:

{% for name, value in claim.factors | dictsort %}- {{ name | replace('_', ' ') }}: `{{ value }}`
{% endfor %}

Supporting evidence: {% for evidence_id in claim.supporting_evidence_ids %}`{{ evidence_id }}`{% if not loop.last %}, {% endif %}{% endfor %}

{% if claim.contradicting_evidence_ids %}Contradictory evidence: {% for evidence_id in claim.contradicting_evidence_ids %}`{{ evidence_id }}`{% if not loop.last %}, {% endif %}{% endfor %}
{% endif %}
{% if claim.assumptions %}Assumptions: {{ claim.assumptions | join('; ') }}
{% endif %}
{% if claim.limitations %}Limitations: {{ claim.limitations | join('; ') }}
{% endif %}
{% else %}No canonical claims are available.
{% endfor %}

## Evidence and citation index

{% for item in citations %}- `{{ item.evidence_id }}` → `{{ item.document_id }}`{% if item.page %}, page {{ item.page }}{% endif %}{% if item.source_line_start %}, lines {{ item.source_line_start }}–{{ item.source_line_end }}{% endif %}{% if item.section %}, section {{ item.section }}{% endif %}; locator `{{ item.locator_type }}`{% if item.start_offset is not none %}, span {{ item.start_offset }}:{{ item.end_offset }}{% endif %}
{% else %}- No evidence records are available.
{% endfor %}

## Supporting evidence

{% for item in supporting_citations %}### {{ item.evidence_id }}

{% if item.exact_text %}> {{ item.exact_text | replace('\n', ' ') }}
{% else %}Visual evidence region on page {{ item.page }}; inspect the evidence ID to resolve the render and bounding box.
{% endif %}
{% else %}No evidence records are available.
{% endfor %}

## Contradictory evidence

{% for item in contradicting_citations %}### {{ item.evidence_id }}

{% if item.exact_text %}> {{ item.exact_text | replace('\n', ' ') }}
{% else %}Visual contradictory evidence region on page {{ item.page }}; inspect the evidence ID to resolve the render and bounding box.
{% endif %}
{% else %}No contradictory evidence records are linked to current claims.
{% endfor %}

## Contradictions and limitations

{% for claim in conflicting_claims %}- `{{ claim.claim_id }}`: {{ claim.contradiction_status }} — {{ claim.limitations | join('; ') }}
{% else %}- No material unresolved contradiction is recorded.
{% endfor %}

## Review summary

{% for review in reviews %}- `{{ review.review_type }}` / `{{ review.review_id }}`: {{ review.decision }}{% if review.warnings %}; warnings: {{ review.warnings | join('; ') }}{% endif %}
{% else %}- No canonical reviews are available.
{% endfor %}

## Methodological limitations

{% for review in methodology_reviews %}- `{{ review.review_id }}`: {{ review.findings | tojson }}{% if review.warnings %}; warnings: {{ review.warnings | join('; ') }}{% endif %}
{% else %}- No methodology-review findings are available.
{% endfor %}

## Unresolved questions and insufficient evidence

{% for claim in limited_claims %}- `{{ claim.claim_id }}` ({{ claim.support_classification }}): {{ claim.claim }}
{% else %}- None recorded.
{% endfor %}

## Validation summary

{% if validation %}- Validation result: `{{ validation.validation_result_id }}`
- Passed: `{{ validation.passed }}`
- Report eligible: `{{ validation.report_eligible }}`
- Blocking errors: {{ validation.blocking_errors | length }}
- Warnings: {{ validation.warnings | length }}
- Human-review requirements: {{ validation.human_review_requirements | length }}
{% else %}No validation result is available. This report is a draft.
{% endif %}

## References

{% for source in sources %}- `{{ source.document_id }}` — {{ source.title }}{% if source.authors %}; {{ source.authors }}{% endif %}{% if source.publication_date %}; {{ source.publication_date }}{% endif %}
{% else %}- No referenced source documents are available.
{% endfor %}

## Provenance summary

- Run ID: `{{ run_id }}`
- Canonical input artifact hashes: {{ input_hashes | length }}
- Host environment: `{{ host.environment }}`
- Model identifier: `{{ host.model_identifier or 'not recorded' }}`

This report is a rendering of canonical JSON artifacts. Original source files remain authoritative.
"""


def generate_report(workspace: Path, run_id: str, *, draft: bool = False) -> dict[str, Any]:
    run_dir, manifest = load_run(workspace, run_id)
    validation = latest_artifact(run_dir / "validation", "ValidationResult")
    current_hashes = validation_input_artifact_hashes(workspace, run_dir, manifest)
    if not draft:
        if validation is None or not validation.get("report_eligible"):
            raise ResearchError(
                "Report publication is blocked because no eligible validation result exists",
                category="report_gating_failure",
                exit_code=EXIT_REPORT_GATE,
            )
        if validation.get("validated_artifact_hashes") != current_hashes:
            raise ResearchError(
                "Canonical artifacts changed after validation; re-run `research validate`",
                category="stale_validation",
                exit_code=EXIT_REPORT_GATE,
            )
        integrity_errors = publication_integrity_errors(workspace, run_dir, manifest)
        if integrity_errors:
            raise ResearchError(
                "Source or locator integrity changed after validation; re-run `research validate`",
                category="stale_validation",
                exit_code=EXIT_REPORT_GATE,
                details={"integrity_errors": integrity_errors},
            )
        if manifest.get("phase") not in {"report_eligible", "published"} or not manifest.get(
            "report_eligible"
        ):
            raise ResearchError(
                "Run lifecycle is not report-eligible",
                category="report_gating_failure",
                exit_code=EXIT_REPORT_GATE,
            )
    artifacts = _current_run_artifacts(run_dir)
    report_input_hashes = [
        *current_hashes,
        *(
            [str(validation["artifact_hash"])]
            if validation and isinstance(validation.get("artifact_hash"), str)
            else []
        ),
    ]
    plan = next((item for item in artifacts if item.get("schema_name") == "ResearchPlan"), None)
    claims = sorted(
        (item for item in artifacts if item.get("schema_name") == "Claim"),
        key=lambda item: str(item["claim_id"]),
    )
    evidence = sorted(
        (item for item in artifacts if item.get("schema_name") == "Evidence"),
        key=lambda item: str(item["evidence_id"]),
    )
    reviews = sorted(
        (item for item in artifacts if item.get("schema_name") == "Review"),
        key=lambda item: (str(item["review_type"]), str(item["review_id"])),
    )
    citations = [_citation(item) for item in evidence]
    supporting_ids = {
        str(evidence_id)
        for claim in claims
        for evidence_id in claim.get("supporting_evidence_ids", [])
    }
    contradicting_ids = {
        str(evidence_id)
        for claim in claims
        for evidence_id in claim.get("contradicting_evidence_ids", [])
    }
    sources = _sources(workspace, evidence)
    independent_reviews = [
        item for item in reviews if item.get("review_type") == "independent_review"
    ]
    independence_status = (
        max(independent_reviews, key=lambda item: str(item["created_at"]))[
            "reviewer_independence_status"
        ]
        if independent_reviews
        else "missing"
    )
    environment = Environment(autoescape=True, undefined=StrictUndefined)
    template = environment.from_string(REPORT_TEMPLATE)
    report = (
        template.render(
            draft=draft,
            question=manifest["question"],
            profile=manifest["profile"],
            workflow_version=manifest["workflow_version"],
            run_id=run_id,
            host=manifest["host"],
            plan=plan,
            sources=sources,
            claims=claims,
            reviews=reviews,
            methodology_reviews=[
                item for item in reviews if item.get("review_type") == "methodology_review"
            ],
            citations=citations,
            supporting_citations=[
                item for item in citations if item["evidence_id"] in supporting_ids
            ],
            contradicting_citations=[
                item for item in citations if item["evidence_id"] in contradicting_ids
            ],
            conflicting_claims=[
                item
                for item in claims
                if item.get("contradicting_evidence_ids")
                or item.get("contradiction_status") == "unresolved"
            ],
            limited_claims=[
                item
                for item in claims
                if item.get("support_classification")
                in {
                    "weakly_supported",
                    "conflicting_evidence",
                    "unsupported",
                    "unable_to_determine",
                }
            ],
            validation=validation,
            human_review_status=(
                "required"
                if validation and validation.get("human_review_requirements")
                else "none_pending"
            ),
            independence_status=independence_status,
            input_hashes=report_input_hashes,
        ).strip()
        + "\n"
    )
    report_hash = prefixed_sha256(report.encode("utf-8"))
    suffix = report_hash.removeprefix("sha256:")[:16]
    filename = f"draft-{suffix}.md" if draft else f"report-{suffix}.md"
    path = run_dir / "report" / filename
    write_text_atomic(path, report, root=run_dir)
    write_text_atomic(
        run_dir / "report" / ("latest-draft.md" if draft else "latest.md"),
        report,
        root=run_dir,
    )
    report_id = derived_identifier(
        "RPT",
        {
            "run_id": run_id,
            "draft": draft,
            "report_sha256": report_hash,
            "inputs": report_input_hashes,
        },
    )
    report_manifest = artifact_base("ReportManifest", report_id)
    report_manifest.update(
        {
            "report_manifest_id": report_id,
            "run_id": run_id,
            "draft": draft,
            "report_path": str(path.relative_to(run_dir)),
            "report_sha256": report_hash,
            "validation_result_id": validation.get("validation_result_id") if validation else None,
            "input_artifact_hashes": report_input_hashes,
        }
    )
    stored, manifest_path = store_artifact(run_dir, report_manifest)
    if not draft:
        manifest = transition_published(run_dir, manifest, [stored["artifact_hash"], report_hash])
    return {
        "run_id": run_id,
        "draft": draft,
        "report_path": str(path),
        "report_sha256": report_hash,
        "report_manifest_path": str(manifest_path),
        "phase": manifest["phase"],
    }


def _citation(evidence: dict[str, Any]) -> dict[str, Any]:
    locator = evidence["locator"]
    section = locator.get("section_path") or []
    return {
        "evidence_id": evidence["evidence_id"],
        "document_id": evidence["document_id"],
        "page": locator.get("page"),
        "source_line_start": locator.get("source_line_start"),
        "source_line_end": locator.get("source_line_end"),
        "section": " > ".join(section) if isinstance(section, list) else str(section),
        "locator_type": locator.get("type"),
        "start_offset": locator.get("start_offset"),
        "end_offset": locator.get("end_offset"),
        "exact_text": evidence.get("exact_text"),
    }


def _sources(workspace: Path, evidence: list[dict[str, Any]]) -> list[dict[str, str]]:
    ids = {str(item["document_id"]) for item in evidence}
    result: list[dict[str, str]] = []
    from research.io import iter_json

    referenced_versions = {
        str(item["document_id"]): str(item["document_version_id"]) for item in evidence
    }
    versions = {
        str(item["document_id"]): item
        for item in iter_json(workspace / "documents" / "versions")
        if item.get("schema_name") == "DocumentVersion"
        and item.get("document_version_id") == referenced_versions.get(str(item.get("document_id")))
    }
    for document in iter_json(workspace / "documents" / "manifests"):
        if document.get("document_id") not in ids:
            continue
        metadata = dict(document.get("metadata", {}))
        metadata.update(versions.get(str(document["document_id"]), {}).get("metadata", {}))
        authors = metadata.get("authors") or metadata.get("author") or ""
        if isinstance(authors, list):
            authors = ", ".join(str(item) for item in authors)
        result.append(
            {
                "document_id": str(document["document_id"]),
                "title": str(
                    metadata.get("title") or metadata.get("original_filename") or "Untitled"
                ),
                "authors": str(authors),
                "publication_date": str(
                    metadata.get("publication_date") or metadata.get("date") or ""
                ),
            }
        )
    return sorted(result, key=lambda item: item["document_id"])
