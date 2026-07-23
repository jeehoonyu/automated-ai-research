from __future__ import annotations

SCHEMA_VERSION = "1.0.0"
WORKFLOW_VERSION = "1.0.0"
RESULT_VERSION = "1.0.0"
NORMALIZATION_VERSION = "1.0.0"
CHUNKING_VERSION = "1.0.0"

PHASES = (
    "initialized",
    "planned",
    "retrieved",
    "evidence_extracted",
    "synthesized",
    "contradiction_reviewed",
    "citation_reviewed",
    "methodology_reviewed",
    "independently_reviewed",
    "validation_passed",
    "report_eligible",
    "published",
)

DISPOSITIONS = (
    "active",
    "blocked",
    "review_pending",
    "human_review_required",
    "validation_failed",
    "superseded",
    "cancelled",
)

STAGES = (
    "planning",
    "retrieval",
    "evidence_extraction",
    "synthesis",
    "contradiction_review",
    "citation_review",
    "methodology_review",
    "independent_review",
    "final_validation",
    "report",
)

STAGE_PHASES = {
    "planning": "planned",
    "retrieval": "retrieved",
    "evidence_extraction": "evidence_extracted",
    "synthesis": "synthesized",
    "contradiction_review": "contradiction_reviewed",
    "citation_review": "citation_reviewed",
    "methodology_review": "methodology_reviewed",
    "independent_review": "independently_reviewed",
    "final_validation": "validation_passed",
    "report": "published",
}

EXIT_SUCCESS = 0
EXIT_GENERAL = 1
EXIT_ARGUMENTS = 2
EXIT_SCHEMA = 3
EXIT_SOURCE = 4
EXIT_REPORT_GATE = 5
EXIT_HUMAN_REVIEW = 6
EXIT_SECURITY = 7
EXIT_UNSUPPORTED = 8
