import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from stock_analyst.extraction import (
    OcrStatus,
    PdfTextExtractionError,
    RawPageText,
    TextExtractionStatus,
    extract_pdf_text,
)
from stock_analyst.pipeline import build_draft_review_status


def write_pdf(path: Path) -> Path:
    path.write_bytes(b"%PDF-1.7\nprivate synthetic fixture")
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
        raise PdfTextExtractionError("synthetic local parse failure")


class ExtractionTest(unittest.TestCase):
    def test_extract_pdf_text_records_page_hashes_and_review_metadata(self) -> None:
        with TemporaryDirectory() as directory:
            pdf = write_pdf(Path(directory) / "issue.pdf")
            result = extract_pdf_text(
                pdf,
                extractor=StubExtractor(
                    (
                        RawPageText(
                            page_number=1,
                            text="Dies ist ein langer eingebetteter Text mit Quellenbezug.",
                        ),
                    )
                ),
                min_embedded_chars=20,
            )

        self.assertEqual(result.status, TextExtractionStatus.EXTRACTED)
        self.assertFalse(result.external_services_enabled)
        self.assertEqual(result.page_count, 1)
        self.assertEqual(result.pages[0].embedded_text_status, TextExtractionStatus.EXTRACTED)
        self.assertEqual(result.pages[0].ocr_status, OcrStatus.NOT_REQUIRED)
        self.assertEqual(len(result.pages[0].text_hash), 64)

    def test_extract_pdf_text_marks_low_text_pages_for_ocr_without_running_ocr(self) -> None:
        with TemporaryDirectory() as directory:
            pdf = write_pdf(Path(directory) / "scan.pdf")
            result = extract_pdf_text(
                pdf,
                extractor=StubExtractor((RawPageText(page_number=1, text=""),)),
            )

        self.assertEqual(result.status, TextExtractionStatus.NEEDS_REVIEW)
        self.assertEqual(result.pages[0].ocr_status, OcrStatus.NEEDED)
        self.assertIn("OCR should be queued", result.pages[0].failure_reason)

    def test_extract_pdf_text_reports_local_dependency_or_parse_failure(self) -> None:
        with TemporaryDirectory() as directory:
            pdf = write_pdf(Path(directory) / "broken.pdf")
            result = extract_pdf_text(pdf, extractor=FailingExtractor())

        self.assertEqual(result.status, TextExtractionStatus.NEEDS_REVIEW)
        self.assertEqual(result.page_count, 0)
        self.assertEqual(result.failure_reason, "synthetic local parse failure")

    def test_build_draft_review_status_requires_successful_extraction(self) -> None:
        with TemporaryDirectory() as directory:
            pdf = write_pdf(Path(directory) / "issue.pdf")
            extraction = extract_pdf_text(
                pdf,
                extractor=StubExtractor(
                    (
                        RawPageText(
                            page_number=1,
                            text="Ausreichender eingebetteter Testtext fuer Draft Review.",
                        ),
                    )
                ),
                min_embedded_chars=20,
            )

        status = build_draft_review_status(upload_status="uploaded", extraction=extraction)

        self.assertEqual(status["stage"], "draft_review")
        self.assertTrue(status["readyForDraftReview"])
        self.assertEqual(status["status"], "needs_review")


if __name__ == "__main__":
    unittest.main()
