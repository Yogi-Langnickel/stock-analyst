import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from stock_analyst.extraction import RawPageText
from stock_analyst.refinement import build_refinement_plan_from_pdf


class RefinementPlanTest(unittest.TestCase):
    def test_classifies_pages_with_reviewer_columns(self) -> None:
        class StubExtractor:
            extractor_name = "stub"

            def extract_pages(self, _pdf_path: Path) -> tuple[RawPageText, ...]:
                return (
                    RawPageText(page_number=1, text="Inhalt\nDER AKTIONÄR"),
                    RawPageText(
                        page_number=18,
                        text="\n".join(
                            (
                                "Dividendenstrategie",
                                "Aktie",
                                "WKN",
                                "Dividendenrendite",
                                "Nächster Cum-Tag",
                                "Nächster Zahltag",
                            )
                        ),
                    ),
                    RawPageText(
                        page_number=80,
                        text="\n".join(
                            (
                                "Chart-Check",
                                "Airbus",
                                "WKN 938914",
                                "Der Trend zeigt nach oben.",
                            )
                        ),
                    ),
                    RawPageText(
                        page_number=122,
                        text="Impressum\nAbo\nApp herunterladen",
                    ),
                )

        with TemporaryDirectory() as directory:
            pdf = Path(directory) / "DA_2026_03.pdf"
            pdf.write_bytes(b"%PDF-1.7\nprivate synthetic fixture")
            plan = build_refinement_plan_from_pdf(
                pdf,
                extractor=StubExtractor(),
                current_utc_date="2026-05-20",
            )

        result = plan.to_dict()
        rows = result["rows"]

        self.assertEqual(result["issueId"], "2026-W03")
        self.assertEqual(result["rowCount"], 4)
        self.assertEqual(rows[0]["Page_number"], "1")
        self.assertIn("page_titel", rows[0])
        self.assertEqual(rows[0]["useful_info"], "no")
        self.assertEqual(rows[1]["section"], "Dividenden")
        self.assertEqual(rows[1]["suggested_destination"], "Dividend Focus")
        self.assertEqual(rows[1]["useful_info"], "yes")
        self.assertEqual(rows[2]["section"], "chart-check")
        self.assertEqual(rows[2]["suggested_destination"], "Stocks")
        self.assertEqual(rows[3]["section"], "back-matter")
        self.assertEqual(rows[3]["useful_info"], "no")
        self.assertEqual(rows[3]["date_updated"], "2026-05-20")


if __name__ == "__main__":
    unittest.main()
