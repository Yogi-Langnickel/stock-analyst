"""Privacy-safe OCR-needed reports for local PDF processing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shlex

from stock_analyst.quality_report import (
    ExtractionQualityItem,
    ExtractionQualityReport,
    build_extraction_quality_report,
)


@dataclass(frozen=True)
class OcrNeededItem:
    filename: str
    source_pdf_id: str | None
    checksum_sha256: str | None
    issue_date_guess: str | None
    stored_path: Path | None
    page_count: int
    ocr_needed_pages: tuple[int, ...]
    reasons: tuple[str, ...]
    local_ocr_command: str | None

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "filename": self.filename,
            "pageCount": self.page_count,
            "ocrNeededPageCount": len(self.ocr_needed_pages),
            "ocrNeededPages": list(self.ocr_needed_pages),
            "reasons": list(self.reasons),
        }

        if self.source_pdf_id is not None:
            result["sourcePdfId"] = self.source_pdf_id
        if self.checksum_sha256 is not None:
            result["checksumSha256"] = self.checksum_sha256
        if self.issue_date_guess is not None:
            result["issueDateGuess"] = self.issue_date_guess
        if self.stored_path is not None:
            result["storedPath"] = str(self.stored_path)
        if self.local_ocr_command is not None:
            result["localOcrCommand"] = self.local_ocr_command

        return result


@dataclass(frozen=True)
class OcrNeededReport:
    manifest_path: Path
    total_manifest_records: int
    pdfs_needing_ocr_count: int
    ocr_needed_page_count: int
    external_services_enabled: bool
    items: tuple[OcrNeededItem, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "manifestPath": str(self.manifest_path),
            "totalManifestRecords": self.total_manifest_records,
            "pdfsNeedingOcrCount": self.pdfs_needing_ocr_count,
            "ocrNeededPageCount": self.ocr_needed_page_count,
            "externalServicesEnabled": self.external_services_enabled,
            "items": [item.to_dict() for item in self.items],
        }


def build_ocr_needed_report_from_manifest(
    manifest_path: Path,
    *,
    upload_dir: Path | None = None,
    min_embedded_chars: int = 40,
    output_dir: Path = Path("data/private/visual-ocr"),
) -> OcrNeededReport:
    """Build a local OCR queue report without running OCR or external services."""

    quality_report = build_extraction_quality_report(
        manifest_path,
        upload_dir=upload_dir,
        min_embedded_chars=min_embedded_chars,
    )
    return build_ocr_needed_report(quality_report, output_dir=output_dir)


def build_ocr_needed_report(
    quality_report: ExtractionQualityReport,
    *,
    output_dir: Path = Path("data/private/visual-ocr"),
) -> OcrNeededReport:
    """Convert extraction quality metadata into OCR-needed page commands."""

    items = tuple(
        _ocr_needed_item(item, output_dir=output_dir)
        for item in quality_report.items
        if item.ocr_needed_pages
    )

    return OcrNeededReport(
        manifest_path=quality_report.manifest_path,
        total_manifest_records=quality_report.total_manifest_records,
        pdfs_needing_ocr_count=len(items),
        ocr_needed_page_count=sum(len(item.ocr_needed_pages) for item in items),
        external_services_enabled=False,
        items=items,
    )


def _ocr_needed_item(
    item: ExtractionQualityItem,
    *,
    output_dir: Path,
) -> OcrNeededItem:
    local_ocr_command = None
    if item.stored_path is not None:
        local_ocr_command = (
            "scripts/stock-analyst visual-ocr-review "
            f"{shlex.quote(str(item.stored_path))} "
            f"--pages {shlex.quote(_page_selection(item.ocr_needed_pages))} "
            "--render --ocr --write-ocr-text "
            f"--output-dir {shlex.quote(str(output_dir))}"
        )

    return OcrNeededItem(
        filename=item.filename,
        source_pdf_id=item.source_pdf_id,
        checksum_sha256=item.checksum_sha256,
        issue_date_guess=item.issue_date_guess,
        stored_path=item.stored_path,
        page_count=item.page_count,
        ocr_needed_pages=item.ocr_needed_pages,
        reasons=item.blocking_reasons,
        local_ocr_command=local_ocr_command,
    )


def _page_selection(pages: tuple[int, ...]) -> str:
    """Compress page numbers into a CLI-friendly selection string."""

    if not pages:
        return ""

    sorted_pages = sorted(set(pages))
    ranges: list[str] = []
    start = previous = sorted_pages[0]
    for page in sorted_pages[1:]:
        if page == previous + 1:
            previous = page
            continue
        ranges.append(f"{start}-{previous}" if start != previous else str(start))
        start = previous = page
    ranges.append(f"{start}-{previous}" if start != previous else str(start))
    return ",".join(ranges)
