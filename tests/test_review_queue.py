import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from stock_analyst.extraction import PdfTextExtractionError, RawPageText
from stock_analyst.intake import store_pdf_upload
from stock_analyst.quality_report import build_extraction_quality_report
from stock_analyst.review_queue import build_review_queue


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


class ReviewQueueTest(unittest.TestCase):
    def test_queue_marks_ready_extraction_for_draft_review(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            stored = store_pdf_upload(write_pdf(root / "issue.pdf"), root / "uploads")
            report = build_extraction_quality_report(
                stored.manifest_path,
                extractor=StubExtractor(
                    (
                        RawPageText(
                            page_number=1,
                            text="Ausreichender eingebetteter Testinhalt fuer lokale Sichtung.",
                        ),
                    )
                ),
                min_embedded_chars=20,
            )

        queue = build_review_queue(report)

        self.assertEqual(queue.total_items, 1)
        self.assertEqual(queue.draft_review_count, 1)
        self.assertEqual(queue.reprocess_needed_count, 0)
        self.assertFalse(queue.external_services_enabled)
        item = queue.items[0].to_dict()
        self.assertEqual(item["action"], "draft_review")
        self.assertEqual(item["sourcePdfId"], stored.source_pdf_id)
        self.assertEqual(item["reasons"], ["ready for manual draft review"])
        self.assertNotIn("text", json.dumps(queue.to_dict()).lower())

    def test_queue_prioritizes_missing_files_before_local_reprocessing(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            missing = store_pdf_upload(write_pdf(root / "missing.pdf"), root / "uploads")
            missing.stored_path.unlink()
            report = build_extraction_quality_report(missing.manifest_path)

        queue = build_review_queue(report)

        self.assertEqual(queue.missing_file_count, 1)
        self.assertEqual(queue.reprocess_needed_count, 1)
        self.assertEqual(queue.items[0].action, "restore_missing_file")
        self.assertEqual(queue.items[0].priority, 10)
        self.assertEqual(queue.items[0].reasons, ("stored PDF file is missing",))

    def test_queue_marks_low_text_pages_for_local_ocr(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            stored = store_pdf_upload(write_pdf(root / "scan.pdf"), root / "uploads")
            report = build_extraction_quality_report(
                stored.manifest_path,
                extractor=StubExtractor((RawPageText(page_number=1, text=""),)),
                min_embedded_chars=20,
            )

        queue = build_review_queue(report)

        self.assertEqual(queue.ocr_needed_page_count, 1)
        self.assertEqual(queue.items[0].action, "queue_local_ocr")
        self.assertEqual(queue.items[0].ocr_needed_page_count, 1)
        self.assertEqual(queue.items[0].to_dict()["ocrNeededPageCount"], 1)
        self.assertIn("OCR should be queued", queue.items[0].reasons[0])

    def test_queue_marks_parse_failures_for_local_extraction_rerun(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            stored = store_pdf_upload(write_pdf(root / "broken.pdf"), root / "uploads")
            report = build_extraction_quality_report(
                stored.manifest_path,
                extractor=FailingExtractor(),
            )

        queue = build_review_queue(report)

        self.assertEqual(queue.items[0].action, "rerun_local_extraction")
        self.assertEqual(queue.items[0].reasons, ("synthetic parse failure",))


if __name__ == "__main__":
    unittest.main()
