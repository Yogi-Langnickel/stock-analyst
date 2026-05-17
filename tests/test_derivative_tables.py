import unittest

from stock_analyst.derivative_tables import extract_derivative_overview_rows_from_page_lines


class DerivativeOverviewTablesTest(unittest.TestCase):
    def test_extracts_base_and_metrics_rows_from_overview_pages(self) -> None:
        rows = extract_derivative_overview_rows_from_page_lines(
            (
                (
                    62,
                    (
                        "Basiswert",
                        "WKN",
                        "Emittent",
                        "Typ",
                        "Ratio",
                        "Strike /",
                        "Cap",
                        "Laufzeit",
                        "Hebel /",
                        "Omega",
                        "Bayer",
                        "UG8QQ9",
                        "UniCredit",
                        "Discount-",
                        "Call",
                        "1,00",
                        "33,00 €",
                        "17.06.26",
                        "5,3 Monate",
                        "–",
                        "Caterpillar",
                        "MM5XEN",
                        "Morgan",
                        "Stanley",
                        "Call",
                        "0,01",
                        "650,00 $",
                        "18.06.26",
                        "5,3 Monate",
                        "6,0",
                        "Derivate-Tipps im Rückblick",
                    ),
                ),
                (
                    63,
                    (
                        "Heft",
                        "Empf.",
                        "kurs",
                        "Aktueller",
                        "Kurs",
                        "Performance",
                        "seit Empf.",
                        "Ziel",
                        "Stopp",
                        "Chance",
                        "Risiko",
                        "Empfehlung",
                        "49/25",
                        "26.11.25",
                        "1,03 €",
                        "1,94 €",
                        "+88,3 %",
                        "3,00 €",
                        "1,40 €",
                        "•••••",
                        "•••••",
                        "Dabei-",
                        "bleiben",
                        "50/25",
                        "03.12.25",
                        "0,32 €",
                        "0,24 €*",
                        "-25,0 %",
                        "Verkauft",
                        "•••••",
                        "•••••",
                        "Ausgestoppt",
                    ),
                ),
            ),
            issue_id="2026-W03",
        )

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].underlying, "Bayer")
        self.assertEqual(rows[0].direction, "Discount-Call")
        self.assertEqual(rows[0].entry_price, "1,03 EUR")
        self.assertEqual(rows[0].current_price, "1,94 EUR")
        self.assertEqual(rows[0].performance_since_recommendation, "+88,3 %")
        self.assertEqual(rows[0].target, "3,00 EUR")
        self.assertEqual(rows[0].stop, "1,40 EUR")
        self.assertEqual(rows[0].recommendation, "Dabei- bleiben")
        self.assertEqual(rows[1].issuer, "Morgan Stanley")
        self.assertEqual(rows[1].omega_hebel, "6,0")
        self.assertEqual(rows[1].target, "")
        self.assertEqual(rows[1].stop, "")
        self.assertEqual(rows[1].recommendation, "Ausgestoppt")


if __name__ == "__main__":
    unittest.main()
