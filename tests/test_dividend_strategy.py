import unittest

from stock_analyst.dividend_strategy import (
    extract_dividend_strategy_rows_from_lines,
    extract_dividend_strategy_rows_from_page_lines,
)


class DividendStrategyTest(unittest.TestCase):
    def test_extracts_row_major_dividend_strategy_rows(self) -> None:
        rows = extract_dividend_strategy_rows_from_lines(
            (
                "Dividende ohne Ende",
                "Monat",
                "Unternehmen",
                "WKN",
                "Aktueller Kurs",
                "Marktkap. in Milliarden €",
                "Dividendenrendite",
                "KGV 2026e",
                "Januar",
                "Enel",
                "928624",
                "9,41 €",
                "95,6",
                "5,1 %",
                "13",
                "März",
                "Banco Sabadell",
                "A0MRD4",
                "3,33 €",
                "16,8",
                "18,6 %",
                "10",
            ),
            issue_id="2026-W03",
            page_number=18,
        )

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].company, "Enel")
        self.assertEqual(rows[0].current_price, "9,41 EUR")
        self.assertEqual(rows[1].company, "Banco Sabadell")
        self.assertEqual(rows[1].wkn, "A0MRD4")
        self.assertEqual(rows[1].market_cap_billions_eur, "16,8")
        self.assertEqual(rows[1].dividend_yield, "18,6 %")
        self.assertEqual(rows[1].kgv_2026e, "10")

    def test_extracts_column_major_embedded_text_order(self) -> None:
        rows = extract_dividend_strategy_rows_from_lines(
            (
                "Monat",
                "Januar",
                "Februar",
                "Unternehmen",
                "Enel",
                "Blackstone",
                "WKN",
                "928624",
                "A2PM4W",
                "Aktueller Kurs",
                "9,41 €",
                "136,50 €",
                "Marktkap. in Milliarden €",
                "95,6",
                "99,9",
                "Dividendenrendite",
                "5,1 %",
                "3,3 %",
                "KGV 2026e",
                "13",
                "25",
            ),
            issue_id="2026-W03",
            page_number=18,
        )

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1].month, "Februar")
        self.assertEqual(rows[1].company, "Blackstone")
        self.assertEqual(rows[1].extraction_notes, ("column_major_text_order",))

    def test_extracts_inline_ocr_table_rows(self) -> None:
        rows = extract_dividend_strategy_rows_from_lines(
            (
                "Monat Unternehmen WKN Aktueller Marktkap. Dividenden- KGV",
                "Kurs in Milliarden € rendite 2026e",
                "März Banco Sabadell A0MRD4 3,33€ 16,8 18,6% 10",
                "Mai RTL Group 861149 34,80€ 5,4 20,1% 14",
            ),
            issue_id="2026-W03",
            page_number=18,
        )

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].company, "Banco Sabadell")
        self.assertEqual(rows[0].current_price, "3,33 EUR")
        self.assertEqual(rows[0].dividend_yield, "18,6 %")
        self.assertEqual(rows[0].extraction_notes, ("ocr_line_normalized",))
        self.assertEqual(rows[1].company, "RTL Group")
        self.assertEqual(rows[1].wkn, "861149")

    def test_keeps_rows_with_dash_optional_valuation_cells(self) -> None:
        rows = extract_dividend_strategy_rows_from_lines(
            (
                "Dividende ohne Ende",
                "Monat",
                "Unternehmen",
                "WKN",
                "Aktueller Kurs",
                "Marktkap. in Milliarden €",
                "Dividendenrendite",
                "KGV 2026e",
                "Mai",
                "RTL Group",
                "861149",
                "34,80 €",
                "–",
                "20,1 %",
                "k. A.",
            ),
            issue_id="2026-W03",
            page_number=18,
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].company, "RTL Group")
        self.assertEqual(rows[0].market_cap_billions_eur, "")
        self.assertEqual(rows[0].dividend_yield, "20,1 %")
        self.assertEqual(rows[0].kgv_2026e, "")

    def test_enriches_rows_from_following_page_continuation(self) -> None:
        rows = extract_dividend_strategy_rows_from_page_lines(
            (
                (
                    18,
                    (
                        "März",
                        "Banco Sabadell",
                        "A0MRD4",
                        "3,33 €",
                        "16,8",
                        "18,6 %",
                        "10",
                    ),
                ),
                (
                    19,
                    (
                        "März",
                        "Banco Sabadell",
                        "2",
                        "14.04.26",
                        "17.04.26",
                        "4,30 €",
                        "2,70 €",
                    ),
                ),
            ),
            issue_id="2026-W03",
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].payout_count, "2")
        self.assertEqual(rows[0].next_cum_day, "14.04.26")
        self.assertEqual(rows[0].next_pay_day, "17.04.26")
        self.assertEqual(rows[0].target, "4,30 EUR")
        self.assertEqual(rows[0].stop, "2,70 EUR")

    def test_enriches_rows_from_inline_ocr_continuation(self) -> None:
        rows = extract_dividend_strategy_rows_from_page_lines(
            (
                (
                    18,
                    (
                        "März Banco Sabadell A0MRD4 3,33€ 16,8 18,6% 10",
                    ),
                ),
                (
                    19,
                    (
                        "1 5.04.26 27.04.26 5,00€ 2,80€ BancoSabadell März",
                    ),
                ),
            ),
            issue_id="2026-W03",
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].payout_count, "1")
        self.assertEqual(rows[0].next_cum_day, "5.04.26")
        self.assertEqual(rows[0].target, "5,00 EUR")
        self.assertEqual(rows[0].stop, "2,80 EUR")
        self.assertEqual(rows[0].extraction_notes, ("ocr_line_normalized",))

    def test_ignores_nearby_article_lines_without_valid_table_shape(self) -> None:
        rows = extract_dividend_strategy_rows_from_lines(
            (
                "März",
                "Banco Sabadell erhöht die Dividende.",
                "A0MRD4",
                "Der aktuelle Kurs reagierte stark.",
                "18,6 %",
            ),
            issue_id="2026-W03",
            page_number=18,
        )

        self.assertEqual(rows, ())


if __name__ == "__main__":
    unittest.main()
