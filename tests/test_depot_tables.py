import unittest
from pathlib import Path

from stock_analyst.depot_tables import (
    extract_depot_rows_from_page_lines, _parse_position_tail,
    _extract_transaction_rows,
)
from stock_analyst.workbook_export import build_workbook_export_plan


class DepotTablesTest(unittest.TestCase):
    def test_executed_transactions_preserve_purchase_and_booking_with_printed_dashes(self) -> None:
        header = ("Transaktion", "Wertpapier", "WKN", "Kurs", "Performance", "seit Kauf")
        for dash in ("-", "–"):
            with self.subTest(dash=dash):
                lines = header + (
                    "Verkauf", "Invented Seller", "ZZ0001", "25", "03.04.26", "8,00 EUR", "-14,3 %",
                    "Kauf", "Invented Buyer", "ZZ0002", "30", "03.04.26", "9,00 EUR", dash,
                    "Einbuchung Invented Booking", "ZZ0003", "40", "03.04.26", "7,00 EUR", dash,
                    "Durchgeführte Transaktionen",
                )
                rows = _extract_transaction_rows(lines, issue_id="2099-W01", page_number=12)
                self.assertEqual([row.action for row in rows], ["Verkauf", "Kauf", "Einbuchung"])
                self.assertEqual([row.price for row in rows], ["8,00 EUR", "9,00 EUR", "7,00 EUR"])
                self.assertEqual(rows[-1].instrument, "Invented Booking")
                self.assertEqual([row.performance_since_buy for row in rows], ["-14,3 %", "", ""])
                self.assertEqual([row.quantity for row in rows], ["25", "30", "40"])
                self.assertTrue(all(row.review_status.value == "needs_review" for row in rows))
                plan = build_workbook_export_plan(
                    pdf_path=Path("data/private/issues/DA_2099_01.pdf"),
                    issue_id="2099-W01", stock_update_date="2099-01-01",
                    depot_transactions=rows,
                ).to_dict()
                transactions = [row for row in plan["rows"] if row["tab"] == "Depot Transactions"]
                self.assertEqual([row["values"][0] for row in transactions],
                    ["Verkauf", "Kauf", "Einbuchung"])
                self.assertEqual(transactions[-1]["values"][5:7], ["7,00 EUR", ""])
                self.assertFalse(any(row["tab"] == "Aktuell" for row in plan["rows"]))

    def test_transaction_dashes_do_not_accept_missing_or_malformed_cells(self) -> None:
        header = ("Transaktion", "Wertpapier", "WKN", "Kurs", "Performance", "seit Kauf")
        for body in (
            ("Kauf", "Invented Buyer", "ZZ0001", "25", "03.04.26", "8,00 EUR"),
            ("Einbuchung", "Invented Booking", "ZZ0001", "25", "03.04.26", "–"),
            ("Einbuchung Invented Booking", "ZZ0001", "25", "03.04.26", "–", "–"),
            ("Einbuchung", "ZZ0001", "25", "03.04.26", "7,00 EUR", "–"),
            ("Einbuchungen Invented Booking", "ZZ0001", "25", "03.04.26", "7,00 EUR", "–"),
            ("Einbuchung Kauf", "ZZ0001", "25", "03.04.26", "7,00 EUR", "–"),
            ("Einbuchung Invented Missing", "Einbuchung Invented Complete", "ZZ0001", "25", "03.04.26", "7,00 EUR", "–"),
            ("Einbuchung", "Invented Booking", "ZZ0001", "25", "03.04.26", "", "–"),
            ("Kauf", "Invented Buyer", "ZZ0001", "25", "03.04.26", "–", "–"),
            ("Verkauf", "Invented Seller", "ZZ0001", "25", "03.04.26", "–", "–"),
            ("Einbuchung", "Invented Booking", "ZZ0001", "25", "03.04.26", "unknown", "–"),
            ("Einbuchung", "Invented Booking", "ZZ0001", "25", "03.04.26", "–", "unknown"),
            ("Einbuchung", "Invented Booking", "ZZ0001", "25", "invalid", "–", "–"),
            ("Einbuchung", "Invented Booking", "ZZ0001", "unknown", "03.04.26", "–", "–"),
            ("Unknown", "Invented Booking", "ZZ0001", "25", "03.04.26", "–", "–"),
            ("Einbuchung", "Invented Booking", "Kauf", "ZZ0001", "25", "03.04.26", "–", "–"),
        ):
            with self.subTest(body=body), self.assertRaises(ValueError):
                _extract_transaction_rows(header + body + ("Durchgeführte Transaktionen",),
                    issue_id="2099-W01", page_number=12)

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
