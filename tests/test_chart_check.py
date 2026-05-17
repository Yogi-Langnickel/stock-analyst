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
        self.assertEqual(second.instrument, "B2Gold")
        self.assertEqual(second.wkn, "A0M889")
        self.assertIn("Ruhe vor dem Sturm", second.signal)
        self.assertEqual(second.review_status.value, "needs_review")

    def test_returns_empty_when_chart_check_marker_is_missing(self) -> None:
        rows = extract_chart_check_rows_from_lines(
            ("Airbus", "938914"),
            issue_id="2026-W03",
            page_number=80,
        )

        self.assertEqual(rows, ())


if __name__ == "__main__":
    unittest.main()
