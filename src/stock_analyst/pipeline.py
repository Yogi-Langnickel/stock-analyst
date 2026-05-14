"""Pipeline skeleton for PDF ingestion through reviewed digest export."""

from __future__ import annotations

from pathlib import Path

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
