"""Pipeline skeleton for PDF ingestion through reviewed digest export."""

from __future__ import annotations

from pathlib import Path

from stock_analyst.extraction import PdfTextExtractionResult, TextExtractionStatus
from stock_analyst.schemas import RecommendationDraft


class PdfProcessingError(RuntimeError):
    """Raised when an uploaded PDF cannot be processed safely."""


def calculate_processing_steps(pdf_path: Path) -> list[str]:
    """Return the planned processing steps for a PDF.

    This is intentionally deterministic so the first tests can cover workflow
    ordering before vendor-specific PDF/OCR libraries are wired in.
    """

    if pdf_path.suffix.lower() != ".pdf":
        raise PdfProcessingError("Only PDF uploads are supported.")

    return [
        "store_source_pdf",
        "extract_embedded_text",
        "ocr_missing_text",
        "detect_layout_blocks",
        "extract_financial_entities",
        "generate_draft_digest",
        "manual_review_gate",
        "export_approved_rows",
    ]


def apply_manual_review_gate(rows: list[RecommendationDraft]) -> list[RecommendationDraft]:
    """Ensure all low-confidence or incomplete rows remain reviewer-gated."""

    for row in rows:
        row.mark_review_gate()
    return rows


def build_draft_review_status(
    *,
    upload_status: str,
    extraction: PdfTextExtractionResult | None = None,
) -> dict[str, object]:
    """Return a local status summary for upload through draft review readiness."""

    if upload_status == "duplicate":
        return {
            "stage": "intake",
            "status": "duplicate",
            "readyForDraftReview": False,
            "message": "This PDF is already in private local storage.",
        }

    if extraction is None:
        return {
            "stage": "text_extraction",
            "status": "pending",
            "readyForDraftReview": False,
            "message": "PDF is queued for local text extraction.",
        }

    if extraction.status == TextExtractionStatus.EXTRACTED:
        return {
            "stage": "draft_review",
            "status": "needs_review",
            "readyForDraftReview": True,
            "pageCount": extraction.page_count,
            "message": "Extracted text is ready for manual draft review.",
        }

    return {
        "stage": "text_extraction",
        "status": "needs_review",
        "readyForDraftReview": False,
        "pageCount": extraction.page_count,
        "message": extraction.failure_reason
        or "Local extraction needs reviewer attention before draft review.",
    }
