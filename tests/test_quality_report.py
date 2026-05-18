import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from stock_analyst.extraction import PdfTextExtractionError, RawPageText
from stock_analyst.intake import store_pdf_upload
from stock_analyst.quality_report import (
    build_extraction_quality_report,
    read_jsonl_manifest,
)
from stock_analyst.cli import run_review_queue


def write_pdf(path: Path, content: bytes = b"%PDF-1.7\nprivate synthetic") -> Path:
    path.write_bytes(content)
    return path


class StubExtractor:
    extractor_name = "stub"

    def __init__(self, pages: tuple[RawPageText, ...]) -> None:
        self.pages = pages

    def extract_pages(self, pdf_path: Path) -> tuple[RawPageText, ...]:
        return self.pages


class FailingExtractor:
    extractor_name = "failing_stub"

    def extract_pages(self, pdf_path: Path) -> tuple[RawPageText, ...]:
        raise PdfTextExtractionError("synthetic parse failure")


class QualityReportTest(unittest.TestCase):
    def test_report_marks_imported_pdf_ready_without_exposing_extracted_text(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            upload_dir = root / "uploads"
            stored = store_pdf_upload(write_pdf(root / "issue.pdf"), upload_dir)

            report = build_extraction_quality_report(
                stored.manifest_path,
                extractor=StubExtractor(
                    (
                        RawPageText(
                            page_number=1,
                            text="Ausreichender eingebetteter Testinhalt fuer lokale Qualitaet.",
                        ),
                    )
                ),
                min_embedded_chars=20,
            )

        self.assertEqual(report.total_manifest_records, 1)
        self.assertEqual(report.ready_for_draft_review_count, 1)
        self.assertEqual(report.needs_review_count, 0)
        self.assertFalse(report.external_services_enabled)
        item = report.items[0].to_dict()
        self.assertEqual(item["sourcePdfId"], stored.source_pdf_id)
        self.assertEqual(item["extractionStatus"], "extracted")
        self.assertTrue(item["readyForDraftReview"])
        self.assertEqual(item["pageCount"], 1)
        self.assertNotIn("text", json.dumps(report.to_dict()).lower())

    def test_report_counts_ocr_needed_pages_as_review_blockers(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            upload_dir = root / "uploads"
            stored = store_pdf_upload(write_pdf(root / "scan.pdf"), upload_dir)

            report = build_extraction_quality_report(
                stored.manifest_path,
                extractor=StubExtractor((RawPageText(page_number=1, text=""),)),
                min_embedded_chars=20,
            )

        self.assertEqual(report.ready_for_draft_review_count, 0)
        self.assertEqual(report.needs_review_count, 1)
        self.assertEqual(report.ocr_needed_page_count, 1)
        self.assertEqual(report.items[0].ocr_needed_page_count, 1)
        self.assertEqual(report.items[0].ocr_needed_pages, (1,))
        self.assertIn("OCR should be queued", report.items[0].blocking_reasons[0])

    def test_report_surfaces_missing_stored_pdf_without_processing(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            upload_dir = root / "uploads"
            stored = store_pdf_upload(write_pdf(root / "missing.pdf"), upload_dir)
            stored.stored_path.unlink()

            report = build_extraction_quality_report(stored.manifest_path)

        self.assertEqual(report.missing_file_count, 1)
        self.assertEqual(report.extraction_failed_count, 0)
        self.assertEqual(report.items[0].extraction_status, "missing_file")
        self.assertEqual(report.items[0].blocking_reasons, ("stored PDF file is missing",))

    def test_report_counts_local_parse_failure(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            upload_dir = root / "uploads"
            stored = store_pdf_upload(write_pdf(root / "broken.pdf"), upload_dir)

            report = build_extraction_quality_report(
                stored.manifest_path,
                extractor=FailingExtractor(),
            )

        self.assertEqual(report.extraction_failed_count, 1)
        self.assertEqual(report.needs_review_count, 1)
        self.assertEqual(report.items[0].extraction_status, "extraction_failed")
        self.assertEqual(report.items[0].blocking_reasons, ("synthetic parse failure",))

    def test_manifest_reader_rejects_non_object_lines(self) -> None:
        with TemporaryDirectory() as directory:
            manifest = Path(directory) / "uploads.jsonl"
            manifest.write_text("[]\n", encoding="utf-8")

            with self.assertRaises(ValueError):
                read_jsonl_manifest(manifest)

    def test_cli_review_queue_returns_privacy_safe_counts(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            upload_dir = root / "uploads"
            stored = store_pdf_upload(write_pdf(root / "missing.pdf"), upload_dir)
            stored.stored_path.unlink()

            result = run_review_queue(stored.manifest_path)

        self.assertEqual(result["totalItems"], 1)
        self.assertEqual(result["missingFileCount"], 1)
        self.assertEqual(result["externalServicesEnabled"], False)
        self.assertEqual(result["items"][0]["action"], "restore_missing_file")
        self.assertNotIn("text", json.dumps(result).lower())


if __name__ == "__main__":
    unittest.main()
