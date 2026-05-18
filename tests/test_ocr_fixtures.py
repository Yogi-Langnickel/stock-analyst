import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from stock_analyst.cli import run_ocr_fixture_plan_command
from stock_analyst.ocr_fixtures import (
    DEFAULT_OCR_FIXTURE_ISSUE_ID,
    build_ocr_fixture_review_plan,
    expected_visual_ocr_artifact_paths,
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
