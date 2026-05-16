"""Local review queue summaries built from extraction quality reports."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from stock_analyst.quality_report import (
    ExtractionQualityItem,
    ExtractionQualityReport,
    build_extraction_quality_report,
)


@dataclass(frozen=True)
class ReviewQueueItem:
    filename: str
    source_pdf_id: str | None
    checksum_sha256: str | None
    issue_date_guess: str | None
    action: str
    priority: int
    ready_for_draft_review: bool
    page_count: int
    ocr_needed_page_count: int
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "filename": self.filename,
            "action": self.action,
            "priority": self.priority,
            "readyForDraftReview": self.ready_for_draft_review,
            "pageCount": self.page_count,
            "ocrNeededPageCount": self.ocr_needed_page_count,
            "reasons": list(self.reasons),
        }

        if self.source_pdf_id is not None:
            result["sourcePdfId"] = self.source_pdf_id
        if self.checksum_sha256 is not None:
            result["checksumSha256"] = self.checksum_sha256
        if self.issue_date_guess is not None:
            result["issueDateGuess"] = self.issue_date_guess

        return result


@dataclass(frozen=True)
class ReviewQueue:
    manifest_path: Path
    total_items: int
    draft_review_count: int
    reprocess_needed_count: int
    missing_file_count: int
    ocr_needed_page_count: int
    external_services_enabled: bool
    items: tuple[ReviewQueueItem, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "manifestPath": str(self.manifest_path),
            "totalItems": self.total_items,
            "draftReviewCount": self.draft_review_count,
            "reprocessNeededCount": self.reprocess_needed_count,
            "missingFileCount": self.missing_file_count,
            "ocrNeededPageCount": self.ocr_needed_page_count,
            "externalServicesEnabled": self.external_services_enabled,
            "items": [item.to_dict() for item in self.items],
        }


def build_review_queue_from_manifest(
    manifest_path: Path,
    *,
    upload_dir: Path | None = None,
    min_embedded_chars: int = 40,
) -> ReviewQueue:
    """Build a local review queue from an upload manifest and embedded-text quality."""

    quality_report = build_extraction_quality_report(
        manifest_path,
        upload_dir=upload_dir,
        min_embedded_chars=min_embedded_chars,
    )
    return build_review_queue(quality_report)


def build_review_queue(quality_report: ExtractionQualityReport) -> ReviewQueue:
    """Turn a quality report into reviewer-facing next actions."""

    items = tuple(
        sorted(
            (_review_queue_item(item) for item in quality_report.items),
            key=lambda item: (
                item.priority,
                item.issue_date_guess or "",
                item.filename.lower(),
            ),
        )
    )
    draft_review_count = sum(1 for item in items if item.action == "draft_review")
    missing_file_count = sum(1 for item in items if item.action == "restore_missing_file")

    return ReviewQueue(
        manifest_path=quality_report.manifest_path,
        total_items=len(items),
        draft_review_count=draft_review_count,
        reprocess_needed_count=len(items) - draft_review_count,
        missing_file_count=missing_file_count,
        ocr_needed_page_count=quality_report.ocr_needed_page_count,
        external_services_enabled=False,
        items=items,
    )


def _review_queue_item(item: ExtractionQualityItem) -> ReviewQueueItem:
    if item.ready_for_draft_review:
        action = "draft_review"
        priority = 30
        reasons = ("ready for manual draft review",)
    elif item.extraction_status == "missing_file":
        action = "restore_missing_file"
        priority = 10
        reasons = item.blocking_reasons
    elif item.ocr_needed_page_count > 0:
        action = "queue_local_ocr"
        priority = 20
        reasons = item.blocking_reasons
    else:
        action = "rerun_local_extraction"
        priority = 20
        reasons = item.blocking_reasons or ("local extraction should be rerun",)

    return ReviewQueueItem(
        filename=item.filename,
        source_pdf_id=item.source_pdf_id,
        checksum_sha256=item.checksum_sha256,
        issue_date_guess=item.issue_date_guess,
        action=action,
        priority=priority,
        ready_for_draft_review=item.ready_for_draft_review,
        page_count=item.page_count,
        ocr_needed_page_count=item.ocr_needed_page_count,
        reasons=reasons,
    )
