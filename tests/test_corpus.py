import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from stock_analyst.cli import run_corpus_status
from stock_analyst.corpus import build_local_corpus_status, parse_local_issue_filename


FORBIDDEN_OUTPUT_KEYS = {
    "content",
    "extractedText",
    "ocrText",
    "pdfText",
    "recommendations",
    "rowHash",
    "rows",
    "serviceAccountEmail",
    "sourceText",
    "spreadsheetId",
    "spreadsheetTitle",
    "workbookPlan",
}


def write_file(path: Path, content: bytes = b"not read by corpus status") -> Path:
    path.write_bytes(content)
    return path


def assert_no_source_content_fields(test_case: unittest.TestCase, value: object) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            test_case.assertNotIn(key, FORBIDDEN_OUTPUT_KEYS)
            assert_no_source_content_fields(test_case, nested)
    elif isinstance(value, list):
        for nested in value:
            assert_no_source_content_fields(test_case, nested)


class CorpusStatusTest(unittest.TestCase):
    def test_parse_local_issue_filename_is_anchored_and_deterministic(self) -> None:
        parsed = parse_local_issue_filename(Path("DA_2026_25.pdf"))

        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.issue_id, "DA_2026_25")
        self.assertIsNone(parse_local_issue_filename(Path("xDA_2026_25.pdf")))
        self.assertIsNone(parse_local_issue_filename(Path("DA_2026_2.pdf")))
        self.assertIsNone(parse_local_issue_filename(Path("DA_2026_25_notes.pdf")))

    def test_corpus_status_reports_latest_numerically_gaps_and_malformed_names(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            write_file(root / "DA_2026_03.pdf")
            write_file(root / "DA_2026_10.pdf")
            write_file(root / "DA_2026_25.pdf")
            write_file(root / "DA_2026_2.pdf")
            write_file(root / "DA_2026_xx.pdf")
            write_file(root / "notes.txt")

            status = build_local_corpus_status(root).to_dict()

        self.assertEqual(status["readinessStatus"], "local_corpus_files_available")
        self.assertEqual(status["readinessScope"], "local_corpus_file_metadata_only")
        self.assertIs(status["filePresenceOnly"], True)
        self.assertIs(status["available"], True)
        self.assertIs(status["blocking"], False)
        self.assertEqual(status["availableIssueCount"], 3)
        self.assertEqual(status["expectedIssueCount"], 23)
        self.assertEqual(
            status["expectedCountBasis"],
            "numeric_span_between_min_and_max_matched_issue_per_year",
        )
        self.assertEqual(status["missingIssueCount"], 20)
        self.assertEqual(status["latestIssueId"], "DA_2026_25")
        self.assertEqual(status["latestIssue"]["issueNumber"], 25)
        self.assertEqual(status["missingIssues"][0], "DA_2026_04")
        self.assertEqual(status["missingIssues"][-1], "DA_2026_24")
        self.assertEqual(status["malformedCount"], 2)
        self.assertEqual(status["ignoredPdfCount"], 2)
        self.assertEqual(status["malformedFilenames"], ["DA_2026_2.pdf", "DA_2026_xx.pdf"])
        self.assertIs(status["externalServicesEnabled"], False)
        self.assertIs(status["networkAccess"], False)
        self.assertIs(status["textExtractionEnabled"], False)
        self.assertIs(status["pdfContentsRead"], False)
        self.assertIs(status["extractionSuccessInferred"], False)
        self.assertIs(status["workbookReadinessInferred"], False)
        self.assertIs(status["recommendationCoverageInferred"], False)
        self.assertIs(status["marketDataReadinessInferred"], False)
        self.assertIs(status["familyVisibleReadinessInferred"], False)
        assert_no_source_content_fields(self, status)

    def test_corpus_status_reports_empty_directory_as_blocking_without_failure(self) -> None:
        with TemporaryDirectory() as directory:
            status = build_local_corpus_status(Path(directory)).to_dict()

        self.assertEqual(status["readinessStatus"], "no_valid_issue_files")
        self.assertIs(status["available"], False)
        self.assertIs(status["blocking"], True)
        self.assertEqual(status["blockingReason"], "no_valid_issue_files")
        self.assertEqual(status["blockingScope"], "local_corpus_file_availability")
        self.assertEqual(status["availableIssueCount"], 0)
        self.assertEqual(status["expectedIssueCount"], 0)
        self.assertEqual(status["malformedCount"], 0)
        self.assertEqual(status["commandExitCode"], 0)

    def test_corpus_status_reports_missing_directory_as_blocking_without_failure(self) -> None:
        with TemporaryDirectory() as directory:
            missing = Path(directory) / "missing"
            status = build_local_corpus_status(missing).to_dict()

        self.assertEqual(status["readinessStatus"], "missing_folder")
        self.assertIs(status["folderExists"], False)
        self.assertIs(status["available"], False)
        self.assertIs(status["blocking"], True)
        self.assertEqual(status["blockingReason"], "missing_folder")
        self.assertEqual(status["commandExitCode"], 0)

    def test_corpus_status_cli_returns_stable_json(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            write_file(root / "DA_2026_03.pdf")
            write_file(root / "DA_2026_25.pdf")

            result = run_corpus_status(root)

        self.assertEqual(result["readinessStatus"], "local_corpus_files_available")
        self.assertEqual(result["latestIssueId"], "DA_2026_25")
        self.assertEqual(result["availableIssueCount"], 2)
        self.assertIs(result["externalServicesEnabled"], False)
        assert_no_source_content_fields(self, result)

    def test_corpus_status_command_is_reachable_from_cli_module(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            write_file(root / "DA_2026_25.pdf")
            env = dict(os.environ)
            env["PYTHONPATH"] = "src"
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "stock_analyst.cli",
                    "corpus-status",
                    str(root),
                ],
                check=True,
                cwd=Path(__file__).resolve().parents[1],
                env=env,
                capture_output=True,
                text=True,
            )

        payload = json.loads(completed.stdout)
        self.assertEqual(payload["readinessStatus"], "local_corpus_files_available")
        self.assertEqual(payload["latestIssueId"], "DA_2026_25")
        self.assertEqual(payload["commandExitCode"], 0)
        assert_no_source_content_fields(self, payload)

    def test_corpus_status_cli_missing_directory_exits_zero_with_blocking_json(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "missing"
            env = dict(os.environ)
            env["PYTHONPATH"] = "src"
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "stock_analyst.cli",
                    "corpus-status",
                    str(root),
                ],
                check=True,
                cwd=Path(__file__).resolve().parents[1],
                env=env,
                capture_output=True,
                text=True,
            )

        payload = json.loads(completed.stdout)
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(payload["readinessStatus"], "missing_folder")
        self.assertIs(payload["blocking"], True)
        self.assertEqual(payload["commandExitCode"], 0)
        assert_no_source_content_fields(self, payload)

    def test_corpus_status_command_is_reachable_from_wrapper(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            write_file(root / "DA_2026_25.pdf")
            repo_root = Path(__file__).resolve().parents[1]
            completed = subprocess.run(
                ["scripts/stock-analyst", "corpus-status", str(root)],
                check=True,
                cwd=repo_root,
                capture_output=True,
                text=True,
            )

        payload = json.loads(completed.stdout)
        self.assertEqual(payload["readinessStatus"], "local_corpus_files_available")
        self.assertEqual(payload["latestIssueId"], "DA_2026_25")
        assert_no_source_content_fields(self, payload)


if __name__ == "__main__":
    unittest.main()
