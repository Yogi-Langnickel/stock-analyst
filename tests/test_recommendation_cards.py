import unittest

from stock_analyst.recommendation_cards import extract_recommendation_cards_from_lines


class RecommendationCardsTest(unittest.TestCase):
    def test_extracts_new_recommendation_stock_card(self) -> None:
        cards = extract_recommendation_cards_from_lines(
            (
                "Aktie",
                "Banco Sabadell",
                "Chance",
                "Risiko",
                "•••••",
                "•••••",
                "Akt. Kurs",
                "3,33 €",
                "WKN",
                "A0MRD4",
                "Ziel",
                "4,30 €",
                "Stopp",
                "2,70 €",
                "Markt-",
                "kapitalisierung",
                "16,8 Mrd. €",
                "Neuempfehlung",
                "2023",
                "2024",
                "2025",
                "2026e",
                "2027e",
                "0,07",
                "0,20",
                "0,23",
                "0,62*",
                "0,22",
            ),
            issue_id="2026-W03",
            page_number=22,
        )

        self.assertEqual(len(cards), 1)
        card = cards[0]
        self.assertEqual(card.instrument_name, "Banco Sabadell")
        self.assertEqual(card.wkn, "A0MRD4")
        self.assertEqual(card.current_price, "3,33 EUR")
        self.assertEqual(card.target, "4,30 EUR")
        self.assertEqual(card.stop, "2,70 EUR")
        self.assertEqual(card.market_cap, "16,8 Mrd. EUR")
        self.assertEqual(card.chance, 5)
        self.assertEqual(card.risk, 5)
        self.assertEqual(card.recommendation_status, "new_recommendation")
        self.assertEqual(
            card.dividend_per_share_trend,
            "2023=0,07 EUR; 2024=0,20 EUR; 2025=0,23 EUR; 2026e=0,62* EUR; 2027e=0,22 EUR",
        )

    def test_extracts_follow_up_fields_and_quarterly_report_date(self) -> None:
        cards = extract_recommendation_cards_from_lines(
            (
                "Aktie",
                "Baidu",
                "Chance",
                "Risiko",
                "•••••",
                "•••••",
                "Akt. Kurs",
                "126,00 €",
                "WKN",
                "A0F5DE",
                "Ziel",
                "180,00 €",
                "Stopp",
                "105,00 €",
                "Markt-",
                "kapitalisierung",
                "44,5 Mrd. €",
                "Dividendenrendite",
                "0,0 %",
                "KUV",
                "26e",
                "2,7",
                "KGV",
                "26e",
                "18",
                "Performance seit",
                "Erstempfehlung",
                "+21,5 %",
                "Empfohlen",
                "in Ausgabe",
                "52/2025 17.12.25",
                "Nächster",
                "Termin",
                "18.02.26",
                "Quartalszahlen",
            ),
            issue_id="2026-W03",
            page_number=37,
        )

        card = cards[0]
        self.assertEqual(card.recommendation_status, "follow_up")
        self.assertEqual(card.dividend_yield, "0,0 %")
        self.assertEqual(card.kuv_26e, "2,7")
        self.assertEqual(card.kgv_26e, "18")
        self.assertEqual(card.performance_since_recommendation, "+21,5 %")
        self.assertEqual(card.recommended_issue, "52/2025 17.12.25")
        self.assertEqual(card.next_report_date, "18.02.26 Quartalszahlen")

    def test_extracts_follow_up_when_labels_are_grouped_before_values(self) -> None:
        cards = extract_recommendation_cards_from_lines(
            (
                "Aktie",
                "RTL Group",
                "Chance",
                "Risiko",
                "•••••",
                "•••••",
                "Akt. Kurs",
                "34,80 €",
                "WKN",
                "861149",
                "Ziel",
                "42,00 €",
                "Stopp",
                "25,00 €",
                "Markt-",
                "kapitalisierung",
                "5,40 Mrd. €",
                "Performance seit",
                "Erstempfehlung",
                "Empfohlen",
                "in Ausgabe",
                "-5,7 %",
                "28/2025 02.07.25",
            ),
            issue_id="2026-W03",
            page_number=25,
        )

        self.assertEqual(len(cards), 1)
        card = cards[0]
        self.assertEqual(card.instrument_name, "RTL Group")
        self.assertEqual(card.performance_since_recommendation, "-5,7 %")
        self.assertEqual(card.recommended_issue, "28/2025 02.07.25")

    def test_extracts_derivative_specific_fields(self) -> None:
        cards = extract_recommendation_cards_from_lines(
            (
                "Baidu Call",
                "WKN",
                "MM7PJ4",
                "Akt. Kurs",
                "2,15 €",
                "Ziel",
                "4,00 €",
                "Stopp",
                "1,30 €",
                "Kurs Basiswert",
                "146,42 $",
                "Basispreis",
                "150,00 $",
                "Omega / Hebel",
                "3,1",
                "Laufzeit",
                "18.09.26",
                "8,5 Monate",
            ),
            issue_id="2026-W03",
            page_number=37,
        )

        card = cards[0]
        self.assertEqual(card.instrument_type.value, "derivative")
        self.assertEqual(card.wkn, "MM7PJ4")
        self.assertEqual(card.underlying_price, "146,42 USD")
        self.assertEqual(card.base_price, "150,00 USD")
        self.assertEqual(card.omega_hebel, "3,1")
        self.assertEqual(card.runtime, "18.09.26 (8,5 Monate)")

    def test_ignores_article_lines_that_mention_call_without_card_labels(self) -> None:
        cards = extract_recommendation_cards_from_lines(
            (
                "Der Baidu Call kann hohe Gewinne ermöglichen.",
                "Weitere Informationen",
                "WKN",
                "MM7PJ4",
            ),
            issue_id="2026-W03",
            page_number=37,
        )

        self.assertEqual(cards, ())

    def test_derivative_runtime_does_not_consume_unrelated_next_line(self) -> None:
        cards = extract_recommendation_cards_from_lines(
            (
                "Gold Discount-Call",
                "WKN",
                "MM4M60",
                "Laufzeit",
                "20.03.2026",
                "Allzeithoch bei 4.550 Dollar",
            ),
            issue_id="2026-W03",
            page_number=78,
        )

        self.assertEqual(cards[0].runtime, "20.03.2026")

    def test_ignores_invalid_wkn_values(self) -> None:
        cards = extract_recommendation_cards_from_lines(
            (
                "Aktie",
                "Stand: 07.01.26",
                "Akt. Kurs",
                "123,00 €",
                "WKN",
                "Kurs",
            ),
            issue_id="2026-W03",
            page_number=117,
        )

        self.assertEqual(cards, ())


if __name__ == "__main__":
    unittest.main()
