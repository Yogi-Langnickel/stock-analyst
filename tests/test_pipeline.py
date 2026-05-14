from pathlib import Path

from stock_analyst.pipeline import PdfProcessingError, calculate_processing_steps
from stock_analyst.pipeline import apply_manual_review_gate
from stock_analyst.schemas import RecommendationDraft, ReviewStatus, SourceReference


def test_processing_plan_is_ordered_for_pdf() -> None:
    assert calculate_processing_steps(Path("aktionaer.pdf")) == [
        "store_source_pdf",
        "extract_embedded_text",
        "ocr_missing_text",
        "detect_layout_blocks",
        "extract_financial_entities",
        "generate_draft_digest",
        "manual_review_gate",
        "export_approved_rows",
    ]


def test_processing_plan_rejects_non_pdf() -> None:
    try:
        calculate_processing_steps(Path("notes.txt"))
    except PdfProcessingError:
        return

    raise AssertionError("non-PDF uploads must be rejected")


def test_manual_review_gate_flags_incomplete_rows() -> None:
    row = RecommendationDraft(source=SourceReference(issue_id="2026-05-14", page=1))

    [reviewed] = apply_manual_review_gate([row])

    assert reviewed.review_status == ReviewStatus.NEEDS_REVIEW
