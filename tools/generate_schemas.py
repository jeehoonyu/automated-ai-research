"""Emit src/research/schemas/v1/*.schema.json.

The schemas are checked-in artifacts; this script is how they are authored, so the shared fragments
(envelope, locators, id patterns) are written once rather than copied into fourteen files and drifting.

Run:  python tools/generate_schemas.py
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "src" / "research" / "schemas" / "v1"
BASE = "https://schemas.automated-ai-research.org/v1"

SHA = {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}
DOC_ID = {"type": "string", "pattern": "^DOC-sha256-[0-9a-f]{64}$"}
DVER_ID = {"type": "string", "pattern": "^DVER-sha256-[0-9a-f]{64}$"}
CHUNK_ID = {"type": "string", "pattern": "^CHK-sha256-[0-9a-f]{64}$"}
EVIDENCE_ID = {"type": "string", "pattern": "^EVD-sha256-[0-9a-f]{64}$"}
CLAIM_ID = {"type": "string", "pattern": "^CLM-[0-9a-fA-F-]{36}$"}
REVIEW_ID = {"type": "string", "pattern": "^REV-[0-9a-fA-F-]{36}$"}
RUN_ID = {"type": "string", "pattern": "^RUN-[0-9a-fA-F-]{36}$"}
CONTEXT_ID = {"type": "string", "pattern": "^CTX-sha256-[0-9a-f]{64}$"}

EXTRACTION_STATUS = ["extracted", "partially_extracted", "ambiguous", "unsupported_format",
                     "ocr_required", "processing_failed", "human_review_required"]
EVIDENCE_TYPES = ["direct_statement", "definition", "experimental_result", "statistical_result",
                  "method_description", "limitation", "table_value", "figure_observation",
                  "metadata_fact", "citation_relationship", "expert_opinion",
                  "derived_calculation"]
CLAIM_TYPES = ["direct_fact", "definition", "descriptive_result", "comparative_result",
               "methodological_claim", "causal_claim", "correlational_claim", "interpretation",
               "hypothesis", "recommendation", "insufficient_evidence_finding"]
CLAIM_STATUS = ["draft", "evidence_linked", "citation_checked", "methodology_reviewed",
                "independently_reviewed", "accepted", "rejected", "superseded"]
SUPPORT = ["verified", "strongly_supported", "moderately_supported", "weakly_supported",
           "conflicting_evidence", "unsupported", "unable_to_determine"]
# Spec §23.1: `verified` is reserved for DIRECTLY CHECKABLE facts. A causal, interpretive or
# generalising claim can never carry it, no matter how much evidence accumulates.
DIRECTLY_CHECKABLE = ["direct_fact", "definition", "descriptive_result"]
REVIEW_TYPES = ["citation_review", "methodology_review", "contradiction_review",
                "independent_review", "human_review"]
REVIEW_DECISIONS = ["passed", "passed_with_warnings", "failed", "incomplete",
                    "human_review_required"]
INDEPENDENCE = ["confirmed_independent", "procedurally_isolated", "not_confirmed",
                "not_independent"]
AMENDMENT_TYPES = ["metadata_correction", "locator_correction", "claim_rewording",
                   "evidence_reclassification", "human_visual_verification",
                   "human_ocr_verification", "review_override", "withdrawal"]
# `independent` was missing, which made `source_independence_established` unearnable honestly: the
# only way to reach `passed` was to record every pair as `cites` or `unknown`, neither of which
# asserts independence. Recording nothing correctly blocked, so the gate rewarded the shrug and
# punished the honest answer.
RELATIONSHIPS = ["independent", "duplicate", "republication", "revision_of", "translation_of",
                 "summarizes", "cites", "derived_from", "shares_primary_dataset",
                 "shares_experimental_result", "unknown"]
FACTORS = ["evidence_directness", "source_quality", "source_independence", "methodology_quality",
           "contradictory_evidence", "evidence_coverage", "citation_validity", "reviewer_agreement",
           "reviewer_independence", "visual_certainty", "ocr_dependency"]
RATINGS = ["high", "medium", "low", "unknown", "not_applicable"]
CITATION_STATUS = ["not_checked", "passed", "partially_supported", "related_not_supporting",
                   "failed"]
CONTRADICTION_STATUS = ["none_found", "resolved", "unresolved", "not_checked"]

ENVELOPE_PROPS = {
    "schema_name": {"type": "string"},
    "schema_version": {"type": "string", "pattern": r"^\d+\.\d+\.\d+$"},
    "artifact_id": {"type": "string", "minLength": 1},
    "artifact_hash": SHA,
    "created_at": {"type": "string", "minLength": 1},
    "created_by": {
        "type": "object",
        "required": ["actor_type"],
        "properties": {
            "actor_type": {"enum": ["cli", "host_agent", "human"]},
            "host": {"type": "string"},
            "model_identifier": {"type": "string"},
        },
        # Hidden chain-of-thought must never be recorded (spec §14, §29).
        "not": {"required": ["reasoning_trace"]},
    },
}
ENVELOPE_REQUIRED = ["schema_name", "schema_version", "artifact_id", "artifact_hash",
                     "created_at", "created_by"]

TEXT_LOCATOR = {
    "type": "object",
    "required": ["type", "start_offset", "end_offset", "span_sha256"],
    "properties": {
        "type": {"const": "text_span"},
        "page": {"type": ["integer", "null"], "minimum": 1},
        "section_path": {"type": "array", "items": {"type": "string"}},
        "chunk_id": {"anyOf": [CHUNK_ID, {"type": "null"}]},
        "start_offset": {"type": "integer", "minimum": 0},
        "end_offset": {"type": "integer", "minimum": 1},
        "source_line_start": {"type": ["integer", "null"], "minimum": 1},
        "source_line_end": {"type": ["integer", "null"], "minimum": 1},
        "span_sha256": SHA,
    },
}

VISUAL_LOCATOR = {
    "type": "object",
    "required": ["type", "page", "render_sha256", "coordinate_system", "bounding_box",
                 "render_width", "render_height"],
    "properties": {
        "type": {"const": "visual_region"},
        "page": {"type": "integer", "minimum": 1},
        "render_sha256": SHA,
        "coordinate_system": {"const": "normalized_top_left_0_to_1"},
        "bounding_box": {
            "type": "object",
            "required": ["x", "y", "width", "height"],
            "properties": {
                "x": {"type": "number", "minimum": 0, "maximum": 1},
                "y": {"type": "number", "minimum": 0, "maximum": 1},
                "width": {"type": "number", "exclusiveMinimum": 0, "maximum": 1},
                "height": {"type": "number", "exclusiveMinimum": 0, "maximum": 1},
            },
        },
        "render_width": {"type": "integer", "minimum": 1},
        "render_height": {"type": "integer", "minimum": 1},
    },
}


def schema(name: str, title: str, description: str, props: dict, required: list[str],
           extra: dict | None = None) -> dict:
    out = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"{BASE}/{name}.schema.json",
        "title": title,
        "description": description,
        "type": "object",
        "required": ENVELOPE_REQUIRED + required,
        "properties": {**ENVELOPE_PROPS, **props},
    }
    if extra:
        out.update(extra)
    return out


SCHEMAS: dict[str, dict] = {}

SCHEMAS["research-plan"] = schema(
    "research-plan", "ResearchPlan",
    "The plan produced by the planning stage. It must state, before any evidence is gathered, what "
    "would count as insufficient — otherwise 'unable_to_determine' becomes a judgement made after "
    "seeing how thin the evidence turned out to be.",
    {
        "run_id": RUN_ID,
        "main_question": {"type": "string", "minLength": 1},
        "subquestions": {"type": "array", "items": {"type": "string"}},
        "definitions": {"type": "object"},
        "scope": {"type": "string"},
        "inclusion_criteria": {"type": "array", "items": {"type": "string"}},
        "exclusion_criteria": {"type": "array", "items": {"type": "string"}},
        "search_terms": {"type": "array", "items": {"type": "string"}},
        "evidence_requirements": {"type": "array", "items": {"type": "string"}},
        "validation_criteria": {"type": "array", "items": {"type": "string"}},
        "expected_limitations": {"type": "array", "items": {"type": "string"}},
        "high_risk": {"type": "boolean"},
        "insufficient_evidence_conditions": {
            "type": "array", "items": {"type": "string"}, "minItems": 1,
            "description": "Stated up front. Spec §12.1.",
        },
    },
    ["run_id", "main_question", "subquestions", "insufficient_evidence_conditions"])

SCHEMAS["evidence"] = schema(
    "evidence", "Evidence",
    "An exact passage pinned to immutable source bytes. exact_text is copied verbatim, never "
    "paraphrased: citation review compares a report's paraphrase against this field, so if this "
    "field is already a paraphrase there is nothing left to check against.",
    {
        "evidence_id": EVIDENCE_ID,
        "document_id": DOC_ID,
        "document_version_id": DVER_ID,
        "evidence_type": {"enum": EVIDENCE_TYPES},
        "locator": {"oneOf": [TEXT_LOCATOR, VISUAL_LOCATOR]},
        "exact_text": {"type": "string"},
        "context_before": {"type": "string"},
        "context_after": {"type": "string"},
        "extraction_method": {"type": "string"},
        "extraction_status": {"enum": EXTRACTION_STATUS},
        "human_review_required": {"type": "boolean"},
        "interpretation_status": {
            "enum": ["not_applicable", "clear", "uncertain", "human_review_required"]},
        "caption": {"type": "string"},
        "region_type": {"enum": ["figure", "table", "chart", "diagram", "page", "other"]},
        "notes": {"type": "string"},
    },
    ["evidence_id", "document_id", "document_version_id", "evidence_type", "locator",
     "extraction_status", "human_review_required"],
    {
        "allOf": [
            {
                "$comment": "Text evidence must carry the exact passage.",
                "if": {"properties": {"locator": {"properties": {"type": {"const": "text_span"}}}}},
                "then": {"required": ["exact_text"],
                         "properties": {"exact_text": {"minLength": 1}}},
            },
            {
                "$comment": "Spec §12.3 / §21: visual content may not be silently interpreted. A "
                            "visual region must declare how confident the reading is.",
                "if": {"properties": {
                    "locator": {"properties": {"type": {"const": "visual_region"}}}}},
                "then": {"required": ["interpretation_status"]},
            },
            {
                "$comment": "Spec §26: evidence from an ocr_required page cannot be used without "
                            "human review. No OCR ships in v1, so its text is not readable.",
                "if": {"properties": {"extraction_status": {"const": "ocr_required"}}},
                "then": {"properties": {"human_review_required": {"const": True}}},
            },
        ]
    })

SCHEMAS["claim"] = schema(
    "claim", "Claim",
    "A statement the report may make. Claims and evidence are separate objects: a claim references "
    "evidence ids, and can therefore be checked against them.",
    {
        "claim_id": CLAIM_ID,
        "claim_version": {"type": "integer", "minimum": 1},
        "claim": {"type": "string", "minLength": 1},
        "claim_type": {"enum": CLAIM_TYPES},
        "claim_status": {"enum": CLAIM_STATUS},
        "support_classification": {"enum": SUPPORT},
        "supporting_evidence_ids": {"type": "array", "items": EVIDENCE_ID},
        "contradicting_evidence_ids": {"type": "array", "items": EVIDENCE_ID},
        "confidence_factors": {
            "type": "object",
            "propertyNames": {"enum": FACTORS},
            "additionalProperties": {"enum": RATINGS},
            "description": "Categorical factor ratings. Spec §23 forbids an aggregate numeric "
                           "confidence score in v1.",
        },
        "assumptions": {"type": "array", "items": {"type": "string"}},
        "scope": {"type": "string"},
        "limitations": {"type": "array", "items": {"type": "string"}},
        "citation_status": {"enum": CITATION_STATUS},
        "contradiction_status": {"enum": CONTRADICTION_STATUS},
        "methodology_status": {"type": "string"},
        "independent_review_status": {"enum": INDEPENDENCE + ["not_yet_reviewed"]},
        "human_review_required": {"type": "boolean"},
        "supersedes": {"anyOf": [CLAIM_ID, {"type": "null"}]},
        "run_id": RUN_ID,
    },
    ["claim_id", "claim", "claim_type", "claim_status", "support_classification",
     "supporting_evidence_ids", "citation_status", "contradiction_status",
     "human_review_required"],
    {
        "$comment": "A numeric confidence score is forbidden outright, not merely discouraged.",
        "not": {"anyOf": [{"required": ["confidence_score"]},
                          {"required": ["confidence"]},
                          {"required": ["certainty_score"]}]},
        "allOf": [
            {
                "$comment": "Spec §38.5: every claim except an explicit insufficient-evidence "
                            "finding must reference evidence.",
                "if": {"properties": {
                    "claim_type": {"not": {"const": "insufficient_evidence_finding"}}}},
                "then": {"properties": {"supporting_evidence_ids": {"minItems": 1}}},
            },
            {
                "$comment": "Spec §23.1: `verified` is reserved for directly checkable facts. A "
                            "causal, interpretive, or generalising claim can never be verified, no "
                            "matter how much evidence accumulates.",
                "if": {"properties": {"support_classification": {"const": "verified"}}},
                "then": {"properties": {
                    "claim_type": {"enum": DIRECTLY_CHECKABLE},
                    "citation_status": {"const": "passed"},
                    "contradiction_status": {"enum": ["none_found", "resolved"]},
                }},
            },
            {
                "$comment": "Spec §23.2: strongly_supported requires MULTIPLE evidence records and "
                            "citations that passed review.",
                "if": {"properties": {"support_classification": {"const": "strongly_supported"}}},
                "then": {"properties": {
                    "supporting_evidence_ids": {"minItems": 2},
                    "citation_status": {"enum": ["passed", "partially_supported"]},
                }},
            },
            {
                "$comment": "An insufficient-evidence finding must not also claim support.",
                "if": {"properties": {
                    "claim_type": {"const": "insufficient_evidence_finding"}}},
                "then": {"properties": {
                    "support_classification": {"const": "unable_to_determine"}}},
            },
        ],
    })

SCHEMAS["review"] = schema(
    "review", "Review",
    "A typed review artifact. The CLI enforces review decisions but never makes them: judging "
    "whether a passage supports a claim requires reading, which is the host agent's job.",
    {
        "review_id": REVIEW_ID,
        "review_type": {"enum": REVIEW_TYPES},
        "run_id": RUN_ID,
        "reviewed_artifact_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "reviewer": {
            "type": "object",
            "required": ["actor_type"],
            "properties": {"actor_type": {"enum": ["host_agent", "human"]},
                           "host": {"type": "string"},
                           "model_identifier": {"type": "string"}},
        },
        "review_independence": {
            "type": "object",
            "required": ["status"],
            "properties": {
                "primary_rationale_excluded": {"type": "boolean"},
                "primary_confidence_excluded": {"type": "boolean"},
                "prior_review_conclusions_excluded": {"type": "boolean"},
                "fresh_agent_context_requested": {"type": "boolean"},
                "host_confirmed_fresh_context": {"type": "boolean"},
                "status": {"enum": INDEPENDENCE},
            },
        },
        "decision": {"enum": REVIEW_DECISIONS},
        "findings": {"type": "array", "items": {"type": "string"}},
        "blocking_issues": {"type": "array", "items": {"type": "string"}},
        "warnings": {"type": "array", "items": {"type": "string"}},
        "required_amendments": {"type": "array", "items": {"type": "string"}},
        "per_claim": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["claim_id", "assessment"],
                "properties": {
                    "claim_id": CLAIM_ID,
                    "assessment": {"type": "string"},
                    "citation_support": {"enum": CITATION_STATUS},
                    "notes": {"type": "string"},
                },
            },
        },
    },
    ["review_id", "review_type", "run_id", "reviewed_artifact_ids", "reviewer", "decision"],
    {
        "allOf": [
            {
                "$comment": "Spec §13: an independent review must declare its independence status, "
                            "so the claim of independence is auditable rather than assumed.",
                "if": {"properties": {"review_type": {"const": "independent_review"}}},
                "then": {"required": ["review_independence"]},
            },
            {
                "$comment": "A failed review must say what blocked it.",
                "if": {"properties": {"decision": {"const": "failed"}}},
                "then": {"properties": {"blocking_issues": {"minItems": 1}},
                         "required": ["blocking_issues"]},
            },
        ]
    })

SCHEMAS["validation-result"] = schema(
    "validation-result", "ValidationResult",
    "The outcome of `research validate`. Records which checks RAN, not only which failed: 'not "
    "evaluated' and 'passed' must never be the same value.",
    {
        "run_id": RUN_ID,
        "validated_at": {"type": "string"},
        "report_eligible": {"type": "boolean"},
        "checks": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["check", "status"],
                "properties": {
                    "check": {"type": "string"},
                    "status": {"enum": ["passed", "failed", "not_evaluated", "not_applicable"]},
                    "detail": {"type": "string"},
                    "artifact_ids": {"type": "array", "items": {"type": "string"}},
                },
            },
            "minItems": 1,
        },
        "blocking_errors": {"type": "array", "items": {"type": "object"}},
        "warnings": {"type": "array", "items": {"type": "object"}},
        "human_review_required": {"type": "boolean"},
        "human_review_reasons": {"type": "array", "items": {"type": "string"}},
        "schema_versions_used": {"type": "object"},
        "validated_inputs": {
            "$comment": "The artifacts this verdict was computed over. Without it `report_eligible` "
                        "is a boolean bound to nothing: `research report` re-reads claims/ and "
                        "evidence/ from disk, so a claim written after `validate` was published "
                        "having never been validated.",
            "type": "object",
            "required": ["artifacts", "load_error_count", "inputs_hash"],
            "properties": {
                "artifacts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["artifact_id", "artifact_hash"],
                        "properties": {
                            "artifact_id": {"type": "string"},
                            "artifact_hash": SHA,
                        },
                    },
                },
                "load_error_count": {"type": "integer", "minimum": 0},
                "inputs_hash": SHA,
            },
        },
    },
    ["run_id", "report_eligible", "checks", "human_review_required", "validated_inputs"],
    {
        "allOf": [{
            "$comment": "Report eligibility requires no blocking errors and no outstanding human "
                        "review. The schema refuses the contradiction outright.",
            "if": {"properties": {"report_eligible": {"const": True}}},
            "then": {"properties": {
                "blocking_errors": {"maxItems": 0},
                "human_review_required": {"const": False},
            }},
        }]
    })

SCHEMAS["amendment"] = schema(
    "amendment", "Amendment",
    "A human correction. Canonical artifacts are never edited in place: an amendment records what "
    "was changed, why, and which artifact hash it replaces, so history stays intact.",
    {
        "amendment_id": {"type": "string", "pattern": "^AMD-[0-9a-fA-F-]{36}$"},
        "run_id": RUN_ID,
        "target_artifact_id": {"type": "string", "minLength": 1},
        "target_artifact_hash": SHA,
        "amendment_type": {"enum": AMENDMENT_TYPES},
        "changed_fields": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "reason": {"type": "string", "minLength": 1},
        "human": {
            "type": "object",
            "required": ["identifier"],
            "properties": {"identifier": {"type": "string"}, "role": {"type": "string"}},
        },
        "replacement_artifact_id": {"type": "string"},
        "replacement_artifact_hash": SHA,
        "requires_revalidation": {"type": "boolean"},
    },
    ["amendment_id", "target_artifact_id", "target_artifact_hash", "amendment_type",
     "changed_fields", "reason", "human", "requires_revalidation"],
    {
        "allOf": [{
            "$comment": "Spec §31: an amendment that replaces content must name the replacement, "
                        "and any amendment touching published content forces revalidation.",
            "if": {"properties": {"amendment_type": {"not": {"const": "withdrawal"}}}},
            "then": {"required": ["replacement_artifact_id", "replacement_artifact_hash"]},
        }]
    })

SCHEMAS["source-relationship"] = schema(
    "source-relationship", "SourceRelationship",
    "Spec §24: multiple documents are not automatically multiple independent sources. Unknown "
    "independence can never be promoted to independent.",
    {
        "source_document_id": DOC_ID,
        "related_document_id": DOC_ID,
        "relationship_type": {"enum": RELATIONSHIPS},
        "evidence_for_relationship": {"type": "string"},
        "confidence": {"enum": RATINGS},
        "human_review_status": {"enum": ["not_required", "required", "completed"]},
        "detected_by": {"enum": ["hash_identity", "metadata_identifier", "heuristic",
                                 "agent_review", "human"]},
    },
    ["source_document_id", "related_document_id", "relationship_type", "confidence",
     "detected_by"],
    {
        "allOf": [{
            "$comment": "A heuristic relationship is not definitive; only hash identity and "
                        "explicit metadata identifiers are.",
            "if": {"properties": {"detected_by": {"const": "heuristic"}}},
            "then": {"properties": {"confidence": {"enum": ["medium", "low", "unknown"]},
                                    "human_review_status": {"enum": ["required", "completed"]}}},
        }]
    })

# --- artifacts the CLI already emits -------------------------------------------------

SCHEMAS["document"] = schema(
    "document", "Document",
    "An immutable original plus one normalized extraction of it.",
    {
        "document_id": DOC_ID,
        "document_version_id": DVER_ID,
        "source_sha256": SHA,
        "media_type": {"type": "string"},
        "file_size_bytes": {"type": "integer", "minimum": 0},
        "original_filename_aliases": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "stored_original": {"type": "string"},
        "extraction_status": {"enum": EXTRACTION_STATUS},
        "extraction_toolchain": {"type": "object"},
        "extraction_warnings": {"type": "array", "items": {"type": "string"}},
        "ocr_required_pages": {"type": "array", "items": {"type": "integer", "minimum": 1}},
        "page_count": {"type": ["integer", "null"], "minimum": 0},
        "normalized_text_path": {"type": "string"},
        "normalized_text_sha256": SHA,
        "normalization_not_performed": {"type": "array", "items": {"type": "string"}},
        "page_map": {"type": "array", "items": {"type": "object"}},
        "chunk_set_path": {"type": "string"},
        "chunk_count": {"type": "integer", "minimum": 0},
        "index_eligible_chunk_count": {"type": "integer", "minimum": 0},
        "pages": {"type": "array", "items": {"type": "object"}},
        "sections": {"type": "array", "items": {"type": "object"}},
        "links": {"type": "array", "items": {"type": "object"}},
        "links_followed": {"const": False,
                           "description": "Spec §5/§18: links are recorded, never fetched."},
        "metadata": {"type": "object"},
        "tables_status": {"type": "string"},
        "figures_status": {"type": "string"},
    },
    ["document_id", "document_version_id", "source_sha256", "media_type",
     "original_filename_aliases", "stored_original", "extraction_status"])

SCHEMAS["chunk-set"] = schema(
    "chunk-set", "ChunkSet",
    "Retrieval units for one document version. A chunk is not evidence.",
    {
        "document_id": DOC_ID,
        "document_version_id": DVER_ID,
        "normalized_text_sha256": SHA,
        "chunking_config": {"type": "object"},
        "chunking_config_hash": SHA,
        "chunk_count": {"type": "integer", "minimum": 0},
        "index_eligible_count": {"type": "integer", "minimum": 0},
        "chunks": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["chunk_id", "document_id", "document_version_id", "text",
                             "text_sha256", "start_offset", "end_offset", "index_eligible",
                             "extraction_status"],
                "properties": {
                    "chunk_id": CHUNK_ID,
                    "document_id": DOC_ID,
                    "document_version_id": DVER_ID,
                    "text": {"type": "string"},
                    "text_sha256": SHA,
                    "start_offset": {"type": "integer", "minimum": 0},
                    "end_offset": {"type": "integer", "minimum": 1},
                    "page": {"type": ["integer", "null"], "minimum": 1},
                    "line_start": {"type": ["integer", "null"], "minimum": 1},
                    "line_end": {"type": ["integer", "null"], "minimum": 1},
                    "section_path": {"type": "array", "items": {"type": "string"}},
                    "index_eligible": {"type": "boolean"},
                    "extraction_status": {"enum": EXTRACTION_STATUS},
                    "overlap_before": {"type": "integer", "minimum": 0},
                    "overlap_after": {"type": "integer", "minimum": 0},
                    "warnings": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    },
    ["document_id", "document_version_id", "chunk_count", "chunks"])

SCHEMAS["run-manifest"] = schema(
    "run-manifest", "RunManifest",
    "Run state. `phase` is progress; `disposition` is whether it may advance.",
    {
        "run_id": RUN_ID,
        "research_question": {"type": "string", "minLength": 1},
        "profile": {"type": "string"},
        "phase": {"enum": ["initialized", "planned", "retrieved", "evidence_extracted",
                           "synthesized", "contradiction_reviewed", "citation_reviewed",
                           "methodology_reviewed", "independently_reviewed", "validation_passed",
                           "report_eligible", "published"]},
        "disposition": {"enum": ["active", "blocked", "review_pending", "human_review_required",
                                 "validation_failed", "superseded", "cancelled"]},
        "workflow_version": {"type": "string"},
        "config_hash": SHA,
        "host": {"type": ["string", "null"]},
        "source_collection": {
            "type": "object",
            "required": ["document_count", "documents"],
            "properties": {
                "document_count": {"type": "integer", "minimum": 0},
                "documents": {"type": "array", "items": {"type": "object"}},
                "index_hash": {"anyOf": [SHA, {"type": "null"}]},
            },
        },
        "packet_paths": {"type": "array", "items": {"type": "string"}},
        "started_at": {"type": "string"},
        "updated_at": {"type": "string"},
    },
    ["run_id", "research_question", "profile", "phase", "disposition", "config_hash",
     "source_collection"])

SCHEMAS["work-packet"] = schema(
    "work-packet", "WorkPacket",
    "The contract handed to a host agent for one stage.",
    {
        "packet_id": {"type": "string", "pattern": "^PKT-[0-9a-fA-F-]{36}$"},
        "run_id": RUN_ID,
        "stage": {"type": "string"},
        "workflow_version": {"type": "string"},
        "schema_versions": {"type": "object"},
        "research_question": {"type": "string"},
        "profile": {"type": "string"},
        "allowed_inputs": {"type": "array", "items": {"type": "string"}},
        "excluded_inputs": {"type": "array", "items": {"type": "string"}},
        "required_outputs": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "completion_criteria": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "failure_conditions": {"type": "array", "items": {"type": "string"}},
        "human_review_triggers": {"type": "array", "items": {"type": "string"}},
        "validation_command": {"type": "string", "minLength": 1},
        "trusted_instructions_header": {"const": "TRUSTED WORKFLOW INSTRUCTIONS"},
        "untrusted_content_header": {"const": "UNTRUSTED DOCUMENT CONTENT"},
        "untrusted_content_policy": {"type": "string"},
        "performed_by": {"enum": ["host_agent", "cli"]},
        "acceptance_note": {"type": "string"},
        "insufficient_evidence_note": {"type": "string"},
        "requires_fresh_context": {"type": "boolean"},
        "independence_note": {"type": "string"},
    },
    ["packet_id", "run_id", "stage", "workflow_version", "allowed_inputs", "excluded_inputs",
     "required_outputs", "completion_criteria", "validation_command",
     "trusted_instructions_header", "untrusted_content_header"],
    {
        "allOf": [{
            "$comment": "Spec §13: the independent-review packet must exclude the primary agent's "
                        "reasoning and confidence, or the review is not independent.",
            "if": {"properties": {"stage": {"const": "independent_review"}}},
            "then": {"properties": {
                "excluded_inputs": {"allOf": [
                    {"contains": {"const": "primary_rationale"}},
                    {"contains": {"const": "primary_confidence"}},
                    {"contains": {"const": "previous_review_conclusions"}},
                ]},
                "requires_fresh_context": {"const": True},
            }},
        }]
    })

SCHEMAS["index-manifest"] = schema(
    "index-manifest", "IndexManifest",
    "Everything needed to reproduce the index. index_hash covers the logical rows; the SQLite file "
    "hash is recorded separately because database bytes vary across builds.",
    {
        "index_hash": SHA,
        "sqlite_file_hash": SHA,
        "sqlite_version": {"type": "string"},
        "config": {
            "type": "object",
            "required": ["index_schema_version", "tokenizer", "ranking"],
            "properties": {
                "index_schema_version": {"type": "string"},
                "tokenizer": {"type": "string"},
                "tokenizer_args": {"type": "string"},
                "ranking": {"type": "string"},
                "chunking": {"type": "object"},
            },
        },
        "document_count": {"type": "integer", "minimum": 0},
        "chunk_count": {"type": "integer", "minimum": 0},
        "skipped_ineligible_chunks": {"type": "integer", "minimum": 0},
        "input_artifact_hashes": {"type": "array", "items": {"type": "object"}},
        "result_ordering": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "warnings": {"type": "array", "items": {"type": "string"}},
        "sqlite_file_hash_note": {"type": "string"},
    },
    ["index_hash", "sqlite_file_hash", "sqlite_version", "config", "chunk_count",
     "result_ordering"])

SCHEMAS["report-manifest"] = schema(
    "report-manifest", "ReportManifest",
    "Provenance for a generated report. A draft is visibly a draft and can never be published.",
    {
        "run_id": RUN_ID,
        "report_path": {"type": "string"},
        "report_sha256": SHA,
        "draft": {"type": "boolean"},
        "validation_result_hash": {"anyOf": [SHA, {"type": "null"}]},
        "claim_ids": {"type": "array", "items": CLAIM_ID},
        "evidence_ids": {"type": "array", "items": EVIDENCE_ID},
        "citation_index": {"type": "array", "items": {"type": "object"}},
        "schema_versions_used": {"type": "object"},
        "disclosures": {"type": "array", "items": {"type": "string"}},
    },
    ["run_id", "report_path", "report_sha256", "draft"],
    {
        "allOf": [{
            "$comment": "Spec §8.9: a draft must not claim validation. A published report must "
                        "name the validation result it rests on.",
            "if": {"properties": {"draft": {"const": False}}},
            "then": {"required": ["validation_result_hash"],
                     "properties": {"validation_result_hash": SHA}},
        }]
    })


SCHEMAS["review-context"] = schema(
    "review-context", "ReviewContext",
    "The context a host attests it handed to a reviewer. `reviewer_independence_sufficient` "
    "otherwise decides by reading a boolean the host wrote about itself; this artifact is the thing "
    "it can actually inspect. It records what was sent, not what should have been sent.",
    {
        "context_id": CONTEXT_ID,
        "run_id": RUN_ID,
        "review_id": REVIEW_ID,
        "stage": {"type": "string", "minLength": 1},
        "content": {"type": "string"},
        "content_sha256": SHA,
        "transmitted_to": {
            "type": "object",
            "required": ["actor_type"],
            "properties": {
                "actor_type": {"enum": ["host_agent", "human"]},
                "host": {"type": "string"},
                "model_identifier": {"type": "string"},
            },
        },
        "attestation": {
            "type": "object",
            "required": ["complete", "method"],
            "properties": {
                "complete": {"type": "boolean"},
                "method": {"enum": ["verbatim_transcript", "reconstructed", "partial"]},
                "note": {"type": "string"},
            },
        },
    },
    ["context_id", "run_id", "review_id", "content", "content_sha256", "attestation"],
    {
        "allOf": [{
            "$comment": "A context attested as COMPLETE must be the verbatim transcript. A "
                        "reconstructed or partial record cannot support the claim that nothing "
                        "else was sent, and a clean scan of a partial record proves nothing.",
            "if": {"properties": {"attestation": {"properties": {"complete": {"const": True}}}}},
            "then": {"properties": {"attestation": {"properties": {
                "method": {"const": "verbatim_transcript"}}}}},
        }]
    })


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, body in sorted(SCHEMAS.items()):
        path = OUT / f"{name}.schema.json"
        path.write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"  {path.relative_to(ROOT)}")
    print(f"{len(SCHEMAS)} schemas written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
