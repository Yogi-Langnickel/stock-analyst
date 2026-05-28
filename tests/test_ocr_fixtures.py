import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from stock_analyst.cli import run_ocr_fixture_plan_command
from stock_analyst.ocr_fixtures import (
    DEFAULT_OCR_FIXTURE_ISSUE_ID,
    build_ocr_fixture_review_plan,
    expected_visual_ocr_artifact_paths,
    format_page_selection,
    load_ocr_fixture_definitions,
)


class OcrFixturePlanTest(unittest.TestCase):
    def test_default_plan_is_metadata_only_for_known_high_value_pages(self) -> None:
        plan = build_ocr_fixture_review_plan()
        payload = plan.to_dict()

        self.assertEqual(payload["issueId"], DEFAULT_OCR_FIXTURE_ISSUE_ID)
        self.assertEqual(payload["privacyMode"], "metadata_only")
        self.assertFalse(payload["externalServicesEnabled"])
        self.assertFalse(payload["networkAccess"])
        self.assertEqual(payload["fixtureCount"], 6)
        self.assertEqual(
            payload["uniquePages"],
            [18, 19, 22, 37, 61, 62, 63, 66, 78, 79, 80, 81, 82, 83, 84, 85, 86, 87, 88, 89],
        )
        self.assertIn("Dividend Focus", json.dumps(payload))
        target_sets = [
            fixture["intendedExtractionTargets"]
            for fixture in payload["fixtures"]
        ]
        flattened_targets = {target for targets in target_sets for target in targets}
        self.assertNotIn("Chart Check", flattened_targets)
        self.assertNotIn("Stock Quickcheck", flattened_targets)

    def test_artifact_metadata_reports_hashes_and_counts_without_ocr_text(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            pdf = root / "DA_2026_03.pdf"
            artifact_dir = root / "private" / "visual-ocr"
            artifact_dir.mkdir(parents=True)
            pdf.write_bytes(b"%PDF-1.7\nsynthetic fixture")
            render_path, ocr_text_path = expected_visual_ocr_artifact_paths(
                pdf,
                artifact_dir=artifact_dir,
                page_number=18,
            )
            render_path.write_bytes(b"synthetic-png-bytes")
            private_ocr_text = "synthetic private OCR line"
            ocr_text_path.write_text(private_ocr_text, encoding="utf-8")

            result = run_ocr_fixture_plan_command(pdf_path=pdf, artifact_dir=artifact_dir)

        payload_text = json.dumps(result)
        page_18 = result["fixtures"][0]["pageArtifacts"][0]
        self.assertEqual(
            result["pdfChecksumSha256"],
            "ce62805d3307ca85ba20ed243ca9ae1b814ccfd166cd99c82fe705f070281765",
        )
        self.assertEqual(page_18["render"]["status"], "available")
        self.assertEqual(page_18["render"]["byteCount"], 19)
        self.assertEqual(page_18["ocrText"]["status"], "available")
        self.assertEqual(page_18["ocrText"]["charCount"], len(private_ocr_text))
        self.assertNotIn(private_ocr_text, payload_text)

    def test_artifact_review_planning_lists_missing_pages_and_commands(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            pdf = root / "Synthetic Issue.pdf"
            artifact_dir = root / "private artifacts" / "visual-ocr"
            manifest = root / "fixtures.json"
            pdf.write_bytes(b"%PDF-1.7\nsynthetic fixture")
            artifact_dir.mkdir(parents=True)
            manifest.write_text(
                json.dumps(
                    {
                        "issueId": "SYNTHETIC_ISSUE",
                        "fixtures": [
                            {
                                "fixtureId": "synthetic-pages",
                                "pages": [1, 2, 3, 5, 6],
                                "expectedSectionLabels": ["Synthetic table"],
                                "intendedExtractionTargets": ["Extraction Audit"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            page_1_render, page_1_ocr = expected_visual_ocr_artifact_paths(
                pdf,
                artifact_dir=artifact_dir,
                page_number=1,
            )
            page_2_render, _page_2_ocr = expected_visual_ocr_artifact_paths(
                pdf,
                artifact_dir=artifact_dir,
                page_number=2,
            )
            page_1_render.write_bytes(b"synthetic-page-1-png")
            private_ocr_text = "synthetic private OCR line"
            page_1_ocr.write_text(private_ocr_text, encoding="utf-8")
            page_2_render.write_bytes(b"synthetic-page-2-png")

            result = run_ocr_fixture_plan_command(
                issue_id="SYNTHETIC_ISSUE",
                pdf_path=pdf,
                artifact_dir=artifact_dir,
                fixture_manifest=manifest,
            )

        planning = result["artifactReviewPlanning"]
        planning_text = json.dumps(planning)
        self.assertEqual(planning["status"], "missing_artifacts")
        self.assertEqual(planning["render"]["availablePages"], [1, 2])
        self.assertEqual(planning["render"]["missingPages"], [3, 5, 6])
        self.assertEqual(planning["ocrText"]["availablePages"], [1])
        self.assertEqual(planning["ocrText"]["missingPages"], [2, 3, 5, 6])
        self.assertEqual(
            planning["commands"],
            [
                {
                    "purpose": "render_missing_pages",
                    "pages": [3, 5, 6],
                    "pageSelection": "3,5-6",
                    "command": (
                        "scripts/stock-analyst visual-ocr-review "
                        f"{str(pdf)!r} --pages 3,5-6 --render --output-dir "
                        f"{str(artifact_dir)!r}"
                    ),
                },
                {
                    "purpose": "ocr_missing_pages",
                    "pages": [2, 3, 5, 6],
                    "pageSelection": "2-3,5-6",
                    "command": (
                        "scripts/stock-analyst visual-ocr-review "
                        f"{str(pdf)!r} --pages 2-3,5-6 --render --ocr "
                        f"--write-ocr-text --output-dir {str(artifact_dir)!r}"
                    ),
                },
            ],
        )
        self.assertNotIn(private_ocr_text, planning_text)
        self.assertNotIn("sha256", planning_text.lower())

    def test_artifact_review_planning_is_not_configured_without_private_paths(self) -> None:
        result = run_ocr_fixture_plan_command(artifact_dir=None)
        planning = result["artifactReviewPlanning"]

        self.assertEqual(planning["status"], "not_configured")
        self.assertEqual(planning["render"]["missingPages"], [])
        self.assertEqual(planning["render"]["notConfiguredPages"], result["uniquePages"])
        self.assertEqual(planning["ocrText"]["notConfiguredPages"], result["uniquePages"])
        self.assertEqual(planning["commands"], [])

    def test_page_selection_formatter_compacts_sorted_unique_ranges(self) -> None:
        self.assertEqual(format_page_selection((5, 2, 3, 5, 8, 9, 10)), "2-3,5,8-10")

    def test_private_fixture_manifest_can_define_metadata_only_fixtures(self) -> None:
        with TemporaryDirectory() as directory:
            manifest = Path(directory) / "fixtures.json"
            manifest.write_text(
                json.dumps(
                    {
                        "issueId": "SYNTHETIC_ISSUE",
                        "fixtures": [
                            {
                                "fixtureId": "synthetic-p001-p002",
                                "pages": [1, 2],
                                "expectedSectionLabels": ["Synthetic table"],
                                "intendedExtractionTargets": ["Extraction Audit"],
                                "priority": "medium",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            definitions = load_ocr_fixture_definitions(manifest)
            result = run_ocr_fixture_plan_command(
                issue_id="SYNTHETIC_ISSUE",
                fixture_manifest=manifest,
                artifact_dir=None,
            )

        self.assertEqual(definitions[0].fixture_id, "synthetic-p001-p002")
        self.assertEqual(result["fixtureCount"], 1)
        self.assertEqual(result["fixtures"][0]["pageArtifacts"][0]["render"]["status"], "not_configured")

    def test_private_fixture_manifest_rejects_text_fields(self) -> None:
        with TemporaryDirectory() as directory:
            manifest = Path(directory) / "fixtures.json"
            manifest.write_text(
                json.dumps(
                    {
                        "fixtures": [
                            {
                                "fixtureId": "bad",
                                "pages": [1],
                                "expectedSectionLabels": ["Synthetic"],
                                "intendedExtractionTargets": ["Extraction Audit"],
                                "ocrText": "do not store this",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "metadata-only"):
                load_ocr_fixture_definitions(manifest)


if __name__ == "__main__":
    unittest.main()
