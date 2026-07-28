"""Extraction statuses.

WHY THIS IS ITS OWN MODULE. Spec §8.2: *"The import process must not claim successful extraction
merely because a source file was copied successfully."* Copying bytes always works. Reading them
often does not — a scanned page yields nothing, an encrypted PDF yields nothing, a parser can die
halfway through and leave nine pages of twenty.

The single most dangerous outcome in this platform is an empty extraction silently presenting as a
document with no relevant content, because "we found nothing" and "there is nothing to find" then
become indistinguishable to every downstream stage. Every document and every page therefore carries
an explicit status, and only one of the seven means the text can be trusted as evidence.
"""

from __future__ import annotations

from enum import StrEnum


class ExtractionStatus(StrEnum):
    """Spec §8.2. Exactly one value means "the text is usable as evidence"."""

    EXTRACTED = "extracted"
    PARTIALLY_EXTRACTED = "partially_extracted"
    AMBIGUOUS = "ambiguous"
    UNSUPPORTED_FORMAT = "unsupported_format"
    OCR_REQUIRED = "ocr_required"
    PROCESSING_FAILED = "processing_failed"
    HUMAN_REVIEW_REQUIRED = "human_review_required"

    @property
    def is_usable_as_evidence(self) -> bool:
        """Only fully-extracted content may back a citation without human review.

        `ocr_required` is deliberately NOT usable: no OCR engine ships in v1 (spec §5), so such a
        page can only become usable through a recorded human verification amendment. Treating it as
        readable text would fabricate evidence out of an image.
        """
        return self is ExtractionStatus.EXTRACTED

    @property
    def needs_human_review(self) -> bool:
        return self in {
            ExtractionStatus.AMBIGUOUS,
            ExtractionStatus.OCR_REQUIRED,
            ExtractionStatus.PARTIALLY_EXTRACTED,
            ExtractionStatus.HUMAN_REVIEW_REQUIRED,
        }

    @property
    def is_failure(self) -> bool:
        """A failure for exit-code purposes. Partial extraction counts: presenting partial
        processing as complete success is explicitly forbidden (spec §34)."""
        return self in {
            ExtractionStatus.PROCESSING_FAILED,
            ExtractionStatus.UNSUPPORTED_FORMAT,
        }


class RegionStatus(StrEnum):
    """Table and figure detection is fallible (spec §17). A missed region is NOT a failure of the
    import — the full-page render always remains available — but it must never be described as
    successfully extracted."""

    EXTRACTED = "extracted"
    PARTIALLY_EXTRACTED = "partially_extracted"
    NOT_DETECTED = "not_detected"
    AMBIGUOUS = "ambiguous"
    UNSUPPORTED = "unsupported"
    OCR_REQUIRED = "ocr_required"
    HUMAN_REVIEW_REQUIRED = "human_review_required"


def worst(statuses: list[ExtractionStatus]) -> ExtractionStatus:
    """Roll per-page statuses up to a document status, worst-case wins.

    A document whose twenty pages include one image-only page is not `extracted`. Taking the best or
    the most common status would let a single unreadable page disappear into an aggregate — exactly
    how an unsupported claim later acquires a citation to a page nobody could read.
    """
    if not statuses:
        return ExtractionStatus.PROCESSING_FAILED
    order = [
        ExtractionStatus.PROCESSING_FAILED,
        ExtractionStatus.UNSUPPORTED_FORMAT,
        ExtractionStatus.HUMAN_REVIEW_REQUIRED,
        ExtractionStatus.OCR_REQUIRED,
        ExtractionStatus.AMBIGUOUS,
        ExtractionStatus.PARTIALLY_EXTRACTED,
        ExtractionStatus.EXTRACTED,
    ]
    for candidate in order:
        if candidate in statuses:
            # "all pages extracted" only when every page is; otherwise the worst present status,
            # except that a mix of extracted and ocr_required is PARTIALLY extracted overall.
            if (candidate is ExtractionStatus.OCR_REQUIRED
                    and ExtractionStatus.EXTRACTED in statuses):
                return ExtractionStatus.PARTIALLY_EXTRACTED
            return candidate
    return ExtractionStatus.PROCESSING_FAILED
