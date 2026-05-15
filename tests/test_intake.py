import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from stock_analyst.cli import run_process_pdf
from stock_analyst.intake import (
    IntakeError,
    guess_issue_date,
    preview_pdf_intake,
    store_pdf_upload,
)


def write_file(path: Path, content: bytes) -> Path:
    path.write_bytes(content)
    return path


class IntakeTest(unittest.TestCase):
    def test_preview_pdf_intake_hashes_valid_pdf(self) -> None:
        with TemporaryDirectory() as directory:
            pdf = write_file(Path(directory) / "issue.pdf", b"%PDF-1.7\nprivate test")

            preview = preview_pdf_intake(pdf)

        self.assertEqual(preview.filename, "issue.pdf")
        self.assertEqual(preview.size_bytes, 21)
        self.assertEqual(len(preview.checksum_sha256), 64)
        self.assertTrue(preview.source_pdf_id.startswith("pdf_"))
        self.assertEqual(preview.status, "ready_for_review")

    def test_guess_issue_date_uses_filename_date_without_inference(self) -> None:
        self.assertEqual(guess_issue_date("aktionaer-2026-05-14.pdf"), "2026-05-14")
        self.assertEqual(guess_issue_date("Der_Aktionaer_14052026.pdf"), "2026-05-14")
        self.assertIsNone(guess_issue_date("aktionaer-2026-02-31.pdf"))
        self.assertIsNone(guess_issue_date("aktionaer-may-issue.pdf"))

    def test_preview_pdf_intake_rejects_wrong_extension(self) -> None:
        with TemporaryDirectory() as directory:
            text_file = write_file(Path(directory) / "issue.txt", b"%PDF-1.7")

            with self.assertRaises(IntakeError):
                preview_pdf_intake(text_file)

    def test_preview_pdf_intake_rejects_wrong_magic_bytes(self) -> None:
        with TemporaryDirectory() as directory:
            fake_pdf = write_file(Path(directory) / "issue.pdf", b"not a pdf")

            with self.assertRaises(IntakeError):
                preview_pdf_intake(fake_pdf)

    def test_process_pdf_dry_run_returns_steps_without_processing(self) -> None:
        with TemporaryDirectory() as directory:
            pdf = write_file(Path(directory) / "issue.pdf", b"%PDF-1.7\nprivate test")

            result = run_process_pdf(pdf, dry_run=True)

        self.assertIs(result["dryRun"], True)
        self.assertEqual(result["filename"], "issue.pdf")
        self.assertEqual(result["storage"], {"stored": False})
        self.assertEqual(result["processingStatus"]["status"], "dry_run")
        self.assertEqual(result["steps"][0], "store_source_pdf")

    def test_store_pdf_upload_copies_to_private_upload_dir_and_records_manifest(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            pdf = write_file(root / "issue.pdf", b"%PDF-1.7\nprivate test")
            upload_dir = root / "uploads"

            stored = store_pdf_upload(pdf, upload_dir)

            self.assertEqual(stored.status, "uploaded")
            self.assertFalse(stored.duplicate)
            self.assertTrue(stored.stored_path.exists())
            self.assertEqual(stored.stored_path.read_bytes(), b"%PDF-1.7\nprivate test")
            self.assertTrue(stored.manifest_path.exists())
            manifest = stored.manifest_path.read_text(encoding="utf-8")
            self.assertIn(stored.checksum_sha256, manifest)
            self.assertIn('"stage": "queued_for_text_extraction"', manifest)

    def test_store_pdf_upload_marks_duplicate_without_copying_again(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            pdf = write_file(root / "issue.pdf", b"%PDF-1.7\nprivate test")
            upload_dir = root / "uploads"

            first = store_pdf_upload(pdf, upload_dir)
            second = store_pdf_upload(pdf, upload_dir)

            self.assertEqual(first.status, "uploaded")
            self.assertEqual(second.status, "duplicate")
            self.assertTrue(second.duplicate)
            self.assertEqual(
                len(second.manifest_path.read_text(encoding="utf-8").splitlines()),
                1,
            )


if __name__ == "__main__":
    unittest.main()
