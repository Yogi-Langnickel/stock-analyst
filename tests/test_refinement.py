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
        self.assertEqual(rows[3]["section"], "Impressum")
        self.assertEqual(rows[3]["useful_info"], "no")
        self.assertEqual(rows[3]["date_updated"], "2026-05-20")

    def test_recognizes_reviewer_seeded_news_title_story_and_ads(self) -> None:
        class StubExtractor:
            extractor_name = "stub"

            def extract_pages(self, _pdf_path: Path) -> tuple[RawPageText, ...]:
                return (
                    RawPageText(page_number=1, text="Titelbild\nDER AKTIONÄR"),
                    RawPageText(page_number=3, text="Editorial\nWillkommen"),
                    RawPageText(page_number=6, text="News\nKurzmeldungen\nAktienmarkt"),
                    RawPageText(page_number=14, text="Titelstory\nAktie\nWKN\nKursziel"),
                    RawPageText(page_number=23, text="Anzeige\nWerbung"),
                )

        with TemporaryDirectory() as directory:
            pdf = Path(directory) / "DA_2026_21.pdf"
            pdf.write_bytes(b"%PDF-1.7\nprivate synthetic fixture")
            plan = build_refinement_plan_from_pdf(
                pdf,
                extractor=StubExtractor(),
                current_utc_date="2026-05-21",
            )

        rows = plan.to_dict()["rows"]

        self.assertEqual(rows[0]["section"], "Cover")
        self.assertEqual(rows[0]["useful_info"], "no")
        self.assertEqual(rows[1]["section"], "Editorial")
        self.assertEqual(rows[1]["useful_info"], "no")
        self.assertEqual(rows[2]["section"], "News")
        self.assertEqual(rows[2]["useful_info"], "yes")
        self.assertEqual(rows[2]["suggested_destination"], "")
        self.assertEqual(rows[3]["section"], "Titelstory")
        self.assertEqual(rows[3]["useful_info"], "yes")
        self.assertEqual(rows[3]["suggested_destination"], "Stocks")
        self.assertEqual(rows[4]["section"], "Werbung")
        self.assertEqual(rows[4]["useful_info"], "no")
        self.assertEqual(rows[4]["parser_hint"], "ignore_or_manual_review")

    def test_reviewer_seeded_sections_beat_generic_keywords(self) -> None:
        class StubExtractor:
            extractor_name = "stub"

            def extract_pages(self, _pdf_path: Path) -> tuple[RawPageText, ...]:
                return (
                    RawPageText(
                        page_number=74,
                        text="Dax-Check\nIndizes\n52-Wochen-Hoch\nBörse",
                    ),
                    RawPageText(
                        page_number=78,
                        text="Rohstoff-Check\nGold\nCall\nHebel\nKursziel",
                    ),
                    RawPageText(
                        page_number=93,
                        text="Statistik\nAktie\nWKN\n52-Wochen-Hoch\nDividendenrendite",
                    ),
                    RawPageText(
                        page_number=118,
                        text="Bücher\nAktie\nWKN\nKGV\nRezension",
                    ),
                )

        with TemporaryDirectory() as directory:
            pdf = Path(directory) / "DA_2026_03.pdf"
            pdf.write_bytes(b"%PDF-1.7\nprivate synthetic fixture")
            rows = build_refinement_plan_from_pdf(
                pdf,
                extractor=StubExtractor(),
                current_utc_date="2026-05-21",
            ).to_dict()["rows"]

        self.assertEqual(rows[0]["section"], "Dax-Check")
        self.assertEqual(rows[0]["suggested_destination"], "Stocks")
        self.assertEqual(rows[0]["useful_info"], "yes")
        self.assertEqual(rows[1]["section"], "Rohstoff-Check")
        self.assertEqual(rows[1]["suggested_destination"], "Derivative Tips")
        self.assertEqual(rows[1]["useful_info"], "yes")
        self.assertEqual(rows[2]["section"], "Statistik")
        self.assertEqual(rows[2]["suggested_destination"], "Stocks")
        self.assertEqual(rows[2]["useful_info"], "yes")
        self.assertEqual(rows[3]["section"], "Bücher")
        self.assertEqual(rows[3]["suggested_destination"], "")
        self.assertEqual(rows[3]["useful_info"], "no")

    def test_ad_markers_do_not_override_full_article_pages(self) -> None:
        class StubExtractor:
            extractor_name = "stub"

            def extract_pages(self, _pdf_path: Path) -> tuple[RawPageText, ...]:
                article_lines = [
                    "Aktie",
                    "WKN ABC123",
                    "Kursziel 42 Euro",
                    "Anzeige im Umfeld",
                    "Der Artikel bleibt ein redaktioneller Beitrag.",
                ] + [f"Absatz {number}" for number in range(40)]
                return (
                    RawPageText(page_number=13, text="Anzeige\nWerbung\nCall\nWKN ABC123"),
                    RawPageText(page_number=54, text="\n".join(article_lines)),
                )

        with TemporaryDirectory() as directory:
            pdf = Path(directory) / "DA_2026_03.pdf"
            pdf.write_bytes(b"%PDF-1.7\nprivate synthetic fixture")
            rows = build_refinement_plan_from_pdf(
                pdf,
                extractor=StubExtractor(),
                current_utc_date="2026-05-21",
            ).to_dict()["rows"]

        self.assertEqual(rows[0]["section"], "Werbung")
        self.assertEqual(rows[0]["useful_info"], "no")
        self.assertEqual(rows[1]["section"], "Aktien")
        self.assertEqual(rows[1]["useful_info"], "yes")

    def test_generic_financial_pages_need_extraction_signal(self) -> None:
        class StubExtractor:
            extractor_name = "stub"

            def extract_pages(self, _pdf_path: Path) -> tuple[RawPageText, ...]:
                return (
                    RawPageText(page_number=40, text="Aktie\nMarktbericht ohne Kennzahlen"),
                    RawPageText(page_number=42, text="Aktie\nWKN ABC123\nKursziel 42 Euro"),
                    RawPageText(page_number=58, text="Bitcoin\nEthereum\nKrypto"),
                )

        with TemporaryDirectory() as directory:
            pdf = Path(directory) / "DA_2026_03.pdf"
            pdf.write_bytes(b"%PDF-1.7\nprivate synthetic fixture")
            rows = build_refinement_plan_from_pdf(
                pdf,
                extractor=StubExtractor(),
                current_utc_date="2026-05-21",
            ).to_dict()["rows"]

        self.assertEqual(rows[0]["section"], "Aktien")
        self.assertEqual(rows[0]["useful_info"], "no")
        self.assertEqual(rows[1]["section"], "Aktien")
        self.assertEqual(rows[1]["useful_info"], "yes")
        self.assertEqual(rows[2]["section"], "Kryptowährungen")
        self.assertEqual(rows[2]["suggested_destination"], "")
        self.assertEqual(rows[2]["useful_info"], "no")
        self.assertEqual(rows[2]["parser_hint"], "future_parser_needed")

    def test_article_without_explicit_recommendation_is_not_extractable(self) -> None:
        class StubExtractor:
            extractor_name = "stub"

            def extract_pages(self, _pdf_path: Path) -> tuple[RawPageText, ...]:
                article_lines = [
                    "Aktie",
                    "Ein redaktioneller Marktbericht mit Unternehmenserwaehnungen.",
                    "Der Text kann inhaltlich lesenswert sein.",
                ] + [f"Absatz {number}" for number in range(60)]
                return (RawPageText(page_number=44, text="\n".join(article_lines)),)

        with TemporaryDirectory() as directory:
            pdf = Path(directory) / "DA_2026_03.pdf"
            pdf.write_bytes(b"%PDF-1.7\nprivate synthetic fixture")
            row = build_refinement_plan_from_pdf(
                pdf,
                extractor=StubExtractor(),
                current_utc_date="2026-05-22",
            ).to_dict()["rows"][0]

        self.assertEqual(row["section"], "Aktien")
        self.assertEqual(row["useful_info"], "no")
        self.assertEqual(row["suggested_destination"], "")

    def test_front_stock_and_depot_pages_require_different_evidence(self) -> None:
        class StubExtractor:
            extractor_name = "stub"

            def extract_pages(self, _pdf_path: Path) -> tuple[RawPageText, ...]:
                front_stock_lines = ["Aktie", "Marktueberblick"] + [f"Absatz {number}" for number in range(40)]
                return (
                    RawPageText(page_number=10, text="\n".join(front_stock_lines)),
                    RawPageText(page_number=68, text="AKTIONÄR Depot\nHebel\nAnzeige"),
                    RawPageText(
                        page_number=69,
                        text="AKTIONÄR Depot\nWKN ABC123\nKursziel 42 Euro\nStopp 30 Euro",
                    ),
                )

        with TemporaryDirectory() as directory:
            pdf = Path(directory) / "DA_2026_03.pdf"
            pdf.write_bytes(b"%PDF-1.7\nprivate synthetic fixture")
            rows = build_refinement_plan_from_pdf(
                pdf,
                extractor=StubExtractor(),
                current_utc_date="2026-05-22",
            ).to_dict()["rows"]

        self.assertEqual(rows[0]["section"], "Aktien")
        self.assertEqual(rows[0]["useful_info"], "yes")
        self.assertEqual(rows[1]["section"], "AKTIONAER Depot")
        self.assertEqual(rows[1]["useful_info"], "no")
        self.assertEqual(rows[2]["section"], "AKTIONAER Depot")
        self.assertEqual(rows[2]["useful_info"], "yes")
        self.assertEqual(rows[2]["suggested_destination"], "Stocks")


if __name__ == "__main__":
    unittest.main()
