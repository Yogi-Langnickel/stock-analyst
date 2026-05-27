import unittest

from stock_analyst.chart_check import extract_chart_check_rows_from_lines


class ChartCheckTest(unittest.TestCase):
    def test_extracts_chart_check_instruments_and_bullets(self) -> None:
        rows = extract_chart_check_rows_from_lines(
            (
                "80",
                "DER AKTIONÄR 03/2026",
                "Chart-Check",
                "Im Aufwind",
                "Airbus bleibt klar auf Kurs.",
                "• Der Trend zeigt nach oben.",
                "Das Rekordhoch bleibt das nächste Ziel.",
                "von Lukas Meyer",
                "Bislang enttäuschend",
                "B2Gold bewegt sich seitwärts.",
                "• Ist es die Ruhe vor dem Sturm?",
                "Aus technischer Sicht würde der Ausbruch Potenzial freisetzen.",
                "von Markus Bußler",
                "in Euro",
                "in Kanadische Dollar (CAD) 1 € ~ 1,61 CAD",
                "Airbus",
                "938914",
                "B2Gold",
                "A0M889",
                "Luft- und Raumfahrt (NLD)",
                "Gold (CAN)",
                "Ziel",
            ),
            issue_id="2026-W03",
            page_number=80,
        )

        self.assertEqual(len(rows), 2)
        first, second = rows
        self.assertEqual(first.instrument, "Airbus")
        self.assertEqual(first.wkn, "938914")
        self.assertEqual(first.sector, "Luft- und Raumfahrt (NLD)")
        self.assertIn("Trend zeigt nach oben", first.signal)
        self.assertEqual(first.target, "")
        self.assertEqual(second.instrument, "B2Gold")
        self.assertEqual(second.wkn, "A0M889")
        self.assertIn("Ruhe vor dem Sturm", second.signal)
        self.assertEqual(second.review_status.value, "needs_review")

    def test_extracts_chart_check_table_fields(self) -> None:
        rows = extract_chart_check_rows_from_lines(
            (
                "Chart-Check",
                "in Euro",
                "TSMC",
                "909800",
                "Schaeffler",
                "SHA010",
                "Halbleiter (USA)",
                "Industrie (DEU)",
                "Ziel",
                "Ziel",
                "Akt.",
                "Kurs",
                "Akt.",
                "Kurs",
                "52-W.-",
                "Hoch",
                "52-W.-",
                "Hoch",
                "52-W.-",
                "Tief",
                "52-W.-",
                "Tief",
                "Perform.",
                "1 Jahr",
                "Perform.",
                "1 Jahr",
                "Perform.",
                "5 Jahre",
                "Perform.",
                "5 Jahre",
                "Stopp",
                "Stopp",
                "Empf.-",
                "Kurs",
                "Empf.-",
                "Kurs",
                "Empfehlung",
                "in Ausgabe",
                "Empfehlung",
                "in Ausgabe",
                "Perform.",
                "seit Empf.",
                "Perform.",
                "seit Empf.",
                "Dividenden-",
                "rendite",
                "Dividenden-",
                "rendite",
                "Nächster",
                "Termin",
                "Nächster",
                "Termin",
                "310,00 €",
                "10,50 €",
                "199,00 €",
                "6,21 €",
                "284,50 €",
                "8,83 €",
                "114,00 €",
                "3,15 €",
                "+34,1 %",
                "+112,6 %",
                "+224,8 %",
                "+81,8 %",
                "224,00 €",
                "7,25 €",
                "278,00 €",
                "8,73 €",
                "37/25",
                "42/25",
                "+39,7 %",
                "+40,5 %",
                "1,4 %",
                "2,9 %",
                "Quartalszahlen 16.01.26",
                "Quartalszahlen 03.03.26",
                "•••••",
                "•••••",
            ),
            issue_id="2026-W03",
            page_number=88,
        )

        self.assertEqual(rows[0].target, "310,00 EUR")
        self.assertEqual(rows[0].stop, "224,00 EUR")
        self.assertEqual(rows[0].current_price, "199,00 EUR")
        self.assertEqual(rows[0].recommendation_price, "278,00 EUR")
        self.assertEqual(rows[0].recommended_issue, "37/25")
        self.assertEqual(rows[0].next_report_date, "Quartalszahlen 16.01.26")
        self.assertEqual(rows[1].dividend_yield, "2,9 %")

    def test_returns_empty_when_chart_check_marker_is_missing(self) -> None:
        rows = extract_chart_check_rows_from_lines(
            ("Airbus", "938914"),
            issue_id="2026-W03",
            page_number=80,
        )

        self.assertEqual(rows, ())


if __name__ == "__main__":
    unittest.main()
