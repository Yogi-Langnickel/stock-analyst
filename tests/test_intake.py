import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from stock_analyst.cli import run_process_pdf
from stock_analyst.intake import IntakeError, preview_pdf_intake


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
        self.assertEqual(preview.status, "ready_for_review")

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
        self.assertEqual(result["steps"][0], "store_source_pdf")


if __name__ == "__main__":
    unittest.main()
