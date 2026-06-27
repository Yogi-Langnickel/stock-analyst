import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from stock_analyst.refinement import RefinementPageRow, RefinementPlan
from stock_analyst.refinement_summary import build_corpus_refinement_summary


def _row(
    *,
    issue_id: str,
    page_number: int,
    section: str,
    useful_info: str,
    destination: str,
    parser_hint: str,
) -> RefinementPageRow:
    return RefinementPageRow(
        issue_id=issue_id,
        page_number=page_number,
        section=section,
        page_title="PRIVATE TITLE SHOULD NOT LEAK",
        useful_info=useful_info,
        suggested_destination=destination,
        parser_hint=parser_hint,
        reason="PRIVATE SOURCE TEXT SHOULD NOT LEAK",
        reviewer_notes="PRIVATE REVIEW NOTE SHOULD NOT LEAK",
        date_updated="2026-06-27",
    )


class CorpusRefinementSummaryTest(unittest.TestCase):
    def test_summarizes_counts_without_page_text_or_titles(self) -> None:
        def plan_builder(pdf_path: Path, **kwargs: object) -> RefinementPlan:
            issue_id = str(kwargs["issue_id"])
            return RefinementPlan(
                issue_id=issue_id,
                pdf_path=pdf_path,
                external_services_enabled=False,
                rows=(
                    _row(
                        issue_id=issue_id,
                        page_number=1,
                        section="Inhalt/front-matter",
                        useful_info="no",
                        destination="review",
                        parser_hint="ignore_or_manual_review",
                    ),
                    _row(
                        issue_id=issue_id,
                        page_number=18,
                        section="Dividenden",
                        useful_info="yes",
                        destination="Dividend Focus",
                        parser_hint="section_inventory:dividend_strategy",
                    ),
                    _row(
                        issue_id=issue_id,
                        page_number=52,
                        section="Aktien",
                        useful_info="yes",
                        destination="Stocks",
                        parser_hint="manual_classification_seed",
                    ),
                ),
            )

        with TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "DA_2026_03.pdf").write_bytes(b"%PDF-1.7 synthetic")
            summary = build_corpus_refinement_summary(
                folder,
                plan_builder=plan_builder,
                current_utc_date="2026-06-27",
            ).to_dict()

        serialized = json.dumps(summary, sort_keys=True)
        self.assertEqual(summary["matchedIssueCount"], 1)
        self.assertEqual(summary["processedIssueCount"], 1)
        self.assertEqual(summary["totalPageCount"], 3)
        self.assertEqual(summary["usefulPageCount"], 2)
        self.assertEqual(summary["sectionCounts"]["Dividenden"], 1)
        self.assertEqual(summary["destinationCounts"]["Stocks"], 1)
        self.assertEqual(summary["parserHintCounts"]["manual_classification_seed"], 1)
        self.assertFalse(summary["sourcePdfTextIncluded"])
        self.assertFalse(summary["pageTitlesIncluded"])
        self.assertFalse(summary["pageRowsIncluded"])
        self.assertNotIn("PRIVATE TITLE SHOULD NOT LEAK", serialized)
        self.assertNotIn("PRIVATE SOURCE TEXT SHOULD NOT LEAK", serialized)
        self.assertNotIn("PRIVATE REVIEW NOTE SHOULD NOT LEAK", serialized)

    def test_limit_and_error_summary_are_safe(self) -> None:
        calls: list[str] = []

        def plan_builder(pdf_path: Path, **kwargs: object) -> RefinementPlan:
            calls.append(pdf_path.name)
            raise RuntimeError("private path or parser detail")

        with TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "DA_2026_03.pdf").write_bytes(b"%PDF-1.7 synthetic")
            (folder / "DA_2026_04.pdf").write_bytes(b"%PDF-1.7 synthetic")
            (folder / "notes.pdf").write_bytes(b"%PDF-1.7 synthetic")
            summary = build_corpus_refinement_summary(
                folder,
                limit=1,
                plan_builder=plan_builder,
            ).to_dict()

        serialized = json.dumps(summary, sort_keys=True)
        self.assertEqual(calls, ["DA_2026_03.pdf"])
        self.assertEqual(summary["matchedIssueCount"], 2)
        self.assertEqual(summary["processedIssueCount"], 1)
        self.assertEqual(summary["malformedFilenames"], ["notes.pdf"])
        self.assertEqual(summary["errorIssueCount"], 1)
        self.assertEqual(summary["issues"][0]["status"], "error")
        self.assertEqual(summary["issues"][0]["errorType"], "RuntimeError")
        self.assertNotIn("private path or parser detail", serialized)


if __name__ == "__main__":
    unittest.main()
