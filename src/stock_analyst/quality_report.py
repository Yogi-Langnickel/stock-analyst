"""Privacy-safe local extraction quality reports for imported PDFs."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Iterable

from stock_analyst.extraction import (
    OcrStatus,
    RawTextExtractor,
    TextExtractionStatus,
    extract_pdf_text,
)
from stock_analyst.pipeline import build_draft_review_status


@dataclass(frozen=True)
class ExtractionQualityItem:
    filename: str
    source_pdf_id: str | None
    checksum_sha256: str | None
    issue_date_guess: str | None
    stored_path: Path | None
    manifest_status: str | None
    extraction_status: str
    ready_for_draft_review: bool
    page_count: int
    extracted_page_count: int
    ocr_needed_page_count: int
    ocr_needed_pages: tuple[int, ...]
    blocking_reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "filename": self.filename,
            "extractionStatus": self.extraction_status,
            "readyForDraftReview": self.ready_for_draft_review,
            "pageCount": self.page_count,
            "extractedPageCount": self.extracted_page_count,
            "ocrNeededPageCount": self.ocr_needed_page_count,
            "ocrNeededPages": list(self.ocr_needed_pages),
            "blockingReasons": list(self.blocking_reasons),
        }

        if self.source_pdf_id is not None:
            result["sourcePdfId"] = self.source_pdf_id
        if self.checksum_sha256 is not None:
            result["checksumSha256"] = self.checksum_sha256
        if self.issue_date_guess is not None:
            result["issueDateGuess"] = self.issue_date_guess
        if self.stored_path is not None:
            result["storedPath"] = str(self.stored_path)
        if self.manifest_status is not None:
            result["manifestStatus"] = self.manifest_status

        return result


@dataclass(frozen=True)
class ExtractionQualityReport:
    manifest_path: Path
    total_manifest_records: int
    processed_count: int
    ready_for_draft_review_count: int
    needs_review_count: int
    missing_file_count: int
    extraction_failed_count: int
    ocr_needed_page_count: int
    external_services_enabled: bool
    items: tuple[ExtractionQualityItem, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "manifestPath": str(self.manifest_path),
            "totalManifestRecords": self.total_manifest_records,
            "processedCount": self.processed_count,
            "readyForDraftReviewCount": self.ready_for_draft_review_count,
            "needsReviewCount": self.needs_review_count,
            "missingFileCount": self.missing_file_count,
            "extractionFailedCount": self.extraction_failed_count,
            "ocrNeededPageCount": self.ocr_needed_page_count,
            "externalServicesEnabled": self.external_services_enabled,
            "items": [item.to_dict() for item in self.items],
        }


def read_jsonl_manifest(manifest_path: Path) -> tuple[dict[str, object], ...]:
    """Read a local upload manifest without interpreting private PDF contents."""

    if not manifest_path.is_file():
        raise FileNotFoundError(f"Manifest does not exist: {manifest_path}")

    records: list[dict[str, object]] = []
    with manifest_path.open("r", encoding="utf-8") as manifest:
        for line_number, line in enumerate(manifest, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"Manifest contains invalid JSON on line {line_number}."
                ) from error
            if not isinstance(record, dict):
                raise ValueError(f"Manifest line {line_number} is not a JSON object.")
            records.append(record)

    return tuple(records)


def build_extraction_quality_report(
    manifest_path: Path,
    *,
    upload_dir: Path | None = None,
    extractor: RawTextExtractor | None = None,
    min_embedded_chars: int = 40,
) -> ExtractionQualityReport:
    """Summarize local extraction quality for PDFs recorded in an intake manifest."""

    manifest_records = read_jsonl_manifest(manifest_path)
    base_upload_dir = upload_dir or manifest_path.parent
    items = tuple(
        _quality_item_from_record(
            record,
            base_upload_dir=base_upload_dir,
            extractor=extractor,
            min_embedded_chars=min_embedded_chars,
        )
        for record in manifest_records
    )

    ready_count = sum(1 for item in items if item.ready_for_draft_review)
    missing_count = sum(
        1 for item in items if "stored PDF file is missing" in item.blocking_reasons
    )
    failed_count = sum(
        1
        for item in items
        if item.extraction_status == TextExtractionStatus.EXTRACTION_FAILED.value
    )
    ocr_needed_pages = sum(item.ocr_needed_page_count for item in items)

    return ExtractionQualityReport(
        manifest_path=manifest_path,
        total_manifest_records=len(manifest_records),
        processed_count=len(items),
        ready_for_draft_review_count=ready_count,
        needs_review_count=len(items) - ready_count,
        missing_file_count=missing_count,
        extraction_failed_count=failed_count,
        ocr_needed_page_count=ocr_needed_pages,
        external_services_enabled=False,
        items=items,
    )


def _quality_item_from_record(
    record: dict[str, object],
    *,
    base_upload_dir: Path,
    extractor: RawTextExtractor | None,
    min_embedded_chars: int,
) -> ExtractionQualityItem:
    filename = _optional_string(record.get("filename")) or "unknown.pdf"
    source_pdf_id = _optional_string(record.get("sourcePdfId"))
    checksum_sha256 = _optional_string(record.get("checksumSha256"))
    issue_date_guess = _optional_string(record.get("issueDateGuess"))
    manifest_status = _optional_string(record.get("status"))
    stored_path = _resolve_stored_path(record.get("storedPath"), base_upload_dir)

    if stored_path is None or not stored_path.is_file():
        return ExtractionQualityItem(
            filename=filename,
            source_pdf_id=source_pdf_id,
            checksum_sha256=checksum_sha256,
            issue_date_guess=issue_date_guess,
            stored_path=stored_path,
            manifest_status=manifest_status,
            extraction_status="missing_file",
            ready_for_draft_review=False,
            page_count=0,
            extracted_page_count=0,
            ocr_needed_page_count=0,
            ocr_needed_pages=(),
            blocking_reasons=("stored PDF file is missing",),
        )

    extraction = extract_pdf_text(
        stored_path,
        extractor=extractor,
        min_embedded_chars=min_embedded_chars,
    )
    draft_status = build_draft_review_status(
        upload_status=manifest_status or "uploaded",
        extraction=extraction,
    )
    ready_for_draft_review = bool(draft_status["readyForDraftReview"])
    extracted_pages = sum(
        1
        for page in extraction.pages
        if page.embedded_text_status == TextExtractionStatus.EXTRACTED
    )
    ocr_needed_pages = sum(
        1 for page in extraction.pages if page.ocr_status == OcrStatus.NEEDED
    )
    ocr_needed_page_numbers = tuple(
        page.page_number for page in extraction.pages if page.ocr_status == OcrStatus.NEEDED
    )
    extraction_status = (
        TextExtractionStatus.EXTRACTION_FAILED.value
        if extraction.failure_reason is not None and extraction.page_count == 0
        else extraction.status.value
    )
    blocking_reasons = _blocking_reasons(
        extraction_status=extraction.status,
        extraction_failure=extraction.failure_reason,
        page_failure_reasons=(
            page.failure_reason for page in extraction.pages if page.failure_reason is not None
        ),
    )

    return ExtractionQualityItem(
        filename=filename,
        source_pdf_id=source_pdf_id,
        checksum_sha256=checksum_sha256,
        issue_date_guess=issue_date_guess,
        stored_path=stored_path,
        manifest_status=manifest_status,
        extraction_status=extraction_status,
        ready_for_draft_review=ready_for_draft_review,
        page_count=extraction.page_count,
        extracted_page_count=extracted_pages,
        ocr_needed_page_count=ocr_needed_pages,
        ocr_needed_pages=ocr_needed_page_numbers,
        blocking_reasons=blocking_reasons,
    )


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _resolve_stored_path(value: object, base_upload_dir: Path) -> Path | None:
    stored_name = _optional_string(value)
    if stored_name is None:
        return None

    stored_path = Path(stored_name)
    if stored_path.is_absolute():
        return stored_path

    return base_upload_dir / stored_path


def _blocking_reasons(
    *,
    extraction_status: TextExtractionStatus,
    extraction_failure: str | None,
    page_failure_reasons: Iterable[str],
) -> tuple[str, ...]:
    if extraction_status == TextExtractionStatus.EXTRACTED:
        return ()

    reasons = []
    if extraction_failure is not None:
        reasons.append(extraction_failure)
    reasons.extend(page_failure_reasons)

    return tuple(dict.fromkeys(reasons)) or ("local extraction needs review",)
