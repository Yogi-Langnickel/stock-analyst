import unittest

from stock_analyst.depot_tables import extract_depot_rows_from_page_lines


class DepotTablesTest(unittest.TestCase):
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
