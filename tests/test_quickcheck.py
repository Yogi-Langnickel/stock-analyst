import unittest

from stock_analyst.quickcheck import extract_quickcheck_rows_from_lines


class QuickcheckTest(unittest.TestCase):
    def test_extracts_quickcheck_rows_from_grouped_page_text(self) -> None:
        rows = extract_quickcheck_rows_from_lines(
            (
                "2G Energy",
                "A0HL8N",
                "36,70 €",
                "34,80 €",
                "52/25",
                "+5,5 %",
                "Adidas",
                "A1EWWW",
                "163,10 €",
                "190,70 €",
                "43/25",
                "-14,5 %",
                "Aktien im Quick-Check",
                "52,50 €",
                "27,50 € !",
                "Die Aktie hat zum Jahresstart ihren Aufwärtstrend wieder aufgenommen.",
                "250,00 €",
                "110,00 €",
                "Die Adidas-Aktie kämpft mit der 50-Tage-Linie.",
                "Unternehmen",
                "WKN",
            ),
            issue_id="2026-W03",
            page_number=90,
        )

        self.assertEqual(len(rows), 2)
        first, second = rows
        self.assertEqual(first.instrument, "2G Energy")
        self.assertEqual(first.wkn, "A0HL8N")
        self.assertEqual(first.current_price, "36,70 EUR")
        self.assertEqual(first.recommendation_price, "34,80 EUR")
        self.assertEqual(first.recommended_issue, "52/25")
        self.assertEqual(first.performance_since_recommendation, "+5,5 %")
        self.assertEqual(first.target, "52,50 EUR")
        self.assertEqual(first.stop, "27,50 EUR !")
        self.assertIn("Aufwärtstrend", first.comment)
        self.assertEqual(second.instrument, "Adidas")
        self.assertEqual(second.target, "250,00 EUR")

    def test_returns_empty_when_quickcheck_title_is_missing(self) -> None:
        rows = extract_quickcheck_rows_from_lines(
            ("2G Energy", "A0HL8N"),
            issue_id="2026-W03",
            page_number=90,
        )

        self.assertEqual(rows, ())


if __name__ == "__main__":
    unittest.main()
