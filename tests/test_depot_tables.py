import unittest

from stock_analyst.depot_tables import (
    extract_depot_rows_from_page_lines, _parse_position_tail,
    _extract_transaction_rows,
)


class DepotTablesTest(unittest.TestCase):
    def test_full_dates_preserve_multiple_purchase_dates_and_values(self) -> None:
        for dates in ("01.02.25/03.04.26", "01.02./03.04.26"):
            with self.subTest(dates=dates):
                parsed, consumed = _parse_position_tail(
                    ("25", dates, "7,00 EUR*", "8,00 EUR", "200,00 EUR", "+14,3 %", "–"), 0)
                self.assertEqual(parsed["buy_date"], dates)
                self.assertEqual(parsed["buy_price"], "7,00 EUR*")
                self.assertEqual(parsed["quantity"], "25")
                self.assertEqual(consumed, 7)
        parsed, _ = _parse_position_tail(
            ("25", "01.02.25/unresolved", "7,00 EUR", "8,00 EUR", "200,00 EUR", "+14,3 %", "–"), 0)
        self.assertIsNone(parsed)

    def test_executed_partial_sale_retains_exact_source_fields(self) -> None:
        lines = ("Transaktion", "Wertpapier", "WKN", "Stück-", "zahl",
            "Transaktions-", "datum", "Kurs", "Performance", "seit Kauf",
            "Teilverkauf", "Invented Company", "ZZ0001", "25", "03.04.26",
            "8,00 EUR", "+14,3 %", "Aktie/Derivat")
        rows = _extract_transaction_rows(lines, issue_id="2099-W01", page_number=12)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].action, "Teilverkauf")
        self.assertEqual(rows[0].instrument, "Invented Company")
        self.assertEqual(rows[0].quantity, "25")
        self.assertEqual(rows[0].transaction_date, "03.04.26")
        self.assertEqual(rows[0].price, "8,00 EUR")
        self.assertEqual(rows[0].performance_since_buy, "+14,3 %")
        self.assertEqual(rows[0].review_status.value, "needs_review")

    def test_executed_transaction_rejects_ambiguous_identity_or_missing_values(self) -> None:
        header = ("Transaktion", "Wertpapier", "WKN", "Kurs", "Performance", "seit Kauf")
        for body in (
            ("Verkauf", "Invented Company", "Kauf", "ZZ0001", "25", "03.04.26", "8,00 EUR", "+14,3 %"),
            ("Verkauf", "Invented Company", "ZZ0001", "25", "03.04.26", "8,00 EUR"),
            ("Verkauf", "Invented Company", "ZZ0001", "25", "unresolved", "8,00 EUR", "+14,3 %"),
        ):
            with self.subTest(body=body), self.assertRaises(ValueError):
                _extract_transaction_rows(header + body, issue_id="2099-W01", page_number=12)
        self.assertEqual(_extract_transaction_rows(
            ("Prose mentions Verkauf",), issue_id="2099-W01", page_number=12), ())

    def test_extracts_depot_positions_and_no_transaction_marker(self) -> None:
        positions, transactions = extract_depot_rows_from_page_lines(
            (
                (
                    66,
                    (
                        "AKTIONÄR-Depot",
                        "Aktie/Derivat",
                        "WKN",
                        "Stück-",
                        "zahl",
                        "Kauf-",
                        "datum",
                        "Kauf-",
                        "kurs",
                        "Aktueller",
                        "Kurs",
                        "Kurswert",
                        "(07.01.26)",
                        "Performance",
                        "seit Kauf",
                        "Stopp-",
                        "kurs",
                        "Amazon",
                        "906866",
                        "60",
                        "31.03.20",
                        "89,85 €",
                        "205,25 €",
                        "12.315,00 €",
                        "+128,4 %",
                        "–",
                        "Nvidia",
                        "918422",
                        "120",
                        "28.01./11.03.25 106,33 €*",
                        "160,54 €",
                        "19.264,80 €",
                        "+51,0 %",
                        "–",
                        "Depotwert",
                        "210.986,90 €",
                        "Transaktion",
                        "Wertpapier",
                        "WKN",
                        "Diese Woche keine Transaktionen",
                        "Durchgeführte Transaktionen",
                    ),
                ),
            ),
            issue_id="2026-W03",
        )

        self.assertEqual(len(positions), 2)
        self.assertEqual(positions[0].instrument, "Amazon")
        self.assertEqual(positions[0].wkn, "906866")
        self.assertEqual(positions[0].value, "12.315,00 EUR")
        self.assertEqual(positions[1].instrument, "Nvidia")
        self.assertEqual(positions[1].buy_date, "28.01./11.03.25")
        self.assertEqual(positions[1].buy_price, "106,33 EUR*")
        self.assertEqual(transactions[0].action, "Keine Transaktionen")


if __name__ == "__main__":
    unittest.main()
