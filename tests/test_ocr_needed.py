import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from stock_analyst.cli import run_ocr_needed
from stock_analyst.extraction import RawPageText
from stock_analyst.intake import store_pdf_upload
from stock_analyst.ocr_needed import build_ocr_needed_report, build_ocr_needed_report_from_manifest
from stock_analyst.quality_report import build_extraction_quality_report


def write_pdf(path: Path, content: bytes = b"%PDF-1.7\nprivate synthetic") -> Path:
    path.write_bytes(content)
    return path


class StubExtractor:
    extractor_name = "stub"

    def __init__(self, pages: tuple[RawPageText, ...]) -> None:
        self.pages = pages

    def extract_pages(self, pdf_path: Path) -> tuple[RawPageText, ...]:
        return self.pages


class OcrNeededReportTest(unittest.TestCase):
    def test_report_lists_page_numbers_without_extracted_text(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            stored = store_pdf_upload(write_pdf(root / "scan.pdf"), root / "uploads")
            quality_report = build_extraction_quality_report(
                stored.manifest_path,
                extractor=StubExtractor(
                    (
                        RawPageText(page_number=1, text=""),
                        RawPageText(page_number=2, text="enough embedded text for review"),
                        RawPageText(page_number=3, text=""),
                        RawPageText(page_number=4, text=""),
                    )
                ),
                min_embedded_chars=20,
            )
            result = build_ocr_needed_report(
                quality_report,
                output_dir=root / "visual ocr",
            ).to_dict()

        self.assertEqual(result["pdfsNeedingOcrCount"], 1)
        self.assertEqual(result["ocrNeededPageCount"], 3)
        item = result["items"][0]
        self.assertEqual(item["ocrNeededPages"], [1, 3, 4])
        self.assertIn("--pages 1,3-4", item["localOcrCommand"])
        self.assertIn("--write-ocr-text", item["localOcrCommand"])
        self.assertNotIn("enough embedded text", json.dumps(result))
        self.assertFalse(result["externalServicesEnabled"])
        remote_contract = result["remoteOcrQueueContract"]
        self.assertEqual(remote_contract["schemaVersion"], "remote-ocr-queue/v1")
        self.assertEqual(remote_contract["provider"], "google_vision")
        self.assertFalse(remote_contract["externalServicesEnabled"])
        self.assertFalse(remote_contract["providerCallsPlanned"])
        self.assertEqual(remote_contract["monthlyPageBudget"], 900)
        self.assertEqual(remote_contract["requestedPageCount"], 3)
        self.assertEqual(remote_contract["budgetStatus"], "within_contract_budget")
        self.assertEqual(remote_contract["pageScope"], "selected_pages_only")
        self.assertEqual(remote_contract["items"][0]["pageSelection"], "1,3-4")
        self.assertEqual(
            remote_contract["items"][0]["status"],
            "contract_only_provider_disabled",
        )

    def test_cli_ocr_needed_returns_empty_items_when_no_pages_need_ocr(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            stored = store_pdf_upload(write_pdf(root / "issue.pdf"), root / "uploads")
            result = build_ocr_needed_report_from_manifest(
                stored.manifest_path,
                min_embedded_chars=20,
            ).to_dict()

        self.assertEqual(result["pdfsNeedingOcrCount"], 0)
        self.assertEqual(result["ocrNeededPageCount"], 0)
        self.assertEqual(result["items"], [])
        self.assertEqual(result["remoteOcrQueueContract"]["items"], [])

    def test_cli_helper_uses_privacy_safe_manifest_output(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            stored = store_pdf_upload(write_pdf(root / "scan.pdf"), root / "uploads")
            result = run_ocr_needed(stored.manifest_path, min_embedded_chars=5000)

        self.assertEqual(result["totalManifestRecords"], 1)
        self.assertGreaterEqual(result["ocrNeededPageCount"], 0)
        self.assertNotIn("text", json.dumps(result).lower())


if __name__ == "__main__":
    unittest.main()
