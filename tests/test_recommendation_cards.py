import unittest

from stock_analyst.recommendation_cards import (
    _VisualChanceRiskPair,
    extract_recommendation_cards_from_lines,
)
from stock_analyst.schemas import InstrumentType


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

    def test_extracts_no_buy_recommendation_and_valuation_fields(self) -> None:
        cards = extract_recommendation_cards_from_lines(
            (
                "Aktie",
                "Meta",
                "Chance",
                "Risiko",
                "•••••",
                "•••••",
                "Akt. Kurs",
                "561,60 €",
                "WKN",
                "A1JWVX",
                "Markt-",
                "kapitalisierung",
                "1,42 Bio. €",
                "Dividendenrendite",
                "0,3 %",
                "KUV",
                "26e",
                "7,1",
                "KGV",
                "26e",
                "20",
                "Kein Kauf",
                "Nächster",
                "Termin",
                "29.01.26",
                "Quartalszahlen",
            ),
            issue_id="2026-W03",
            page_number=54,
        )

        card = cards[0]
        self.assertEqual(card.instrument_name, "Meta")
        self.assertEqual(card.recommendation_status, "no_buy")
        self.assertEqual(card.kuv_26e, "7,1")
        self.assertEqual(card.kgv_26e, "20")
        self.assertEqual(card.next_report_date, "29.01.26 Quartalszahlen")

    def test_visual_chance_risk_pairs_override_embedded_bullet_count(self) -> None:
        cards = extract_recommendation_cards_from_lines(
            (
                "Aktie",
                "Armour Residential",
                "Chance",
                "Risiko",
                "•••••",
                "•••••",
                "Akt. Kurs",
                "15,51 €",
                "WKN",
                "A3EUUD",
            ),
            issue_id="2026-W03",
            page_number=32,
            visual_chance_risk_pairs=(_VisualChanceRiskPair(chance=4, risk=3),),
        )

        self.assertEqual(cards[0].chance, 4)
        self.assertEqual(cards[0].risk, 3)
        self.assertIn("visual_rating_from_pdf", cards[0].extraction_notes)

    def test_extracts_duel_table_stock_rows(self) -> None:
        cards = extract_recommendation_cards_from_lines(
            (
                "Unternehmen",
                "WKN",
                "Aktueller",
                "Kurs",
                "Marktkap.",
                "in Mrd. €",
                "DR*",
                "in %",
                "KUV",
                "2026e",
                "KGV",
                "2026e",
                "Perf. seit",
                "Erstempf.",
                "Empf.-",
                "Ausgabe",
                "Ziel",
                "Stopp",
                "Chance",
                "Risiko",
                "Archer Aviation",
                "A3C3BQ",
                "8,82 $",
                "5,6",
                "0,0",
                "100,2",
                "–",
                "Neuempfehlung",
                "14,00 $",
                "6,50 $",
                "•••••",
                "•••••",
                "EHang Holdings",
                "A2PWWB",
                "14,34 $",
                "1,0",
                "0,0",
                "8,2",
                "156",
                "Kein Kauf",
                "•••••",
                "•••••",
            ),
            issue_id="2026-W03",
            page_number=51,
            visual_chance_risk_pairs=(
                _VisualChanceRiskPair(chance=5, risk=4),
                _VisualChanceRiskPair(chance=5, risk=5),
            ),
        )

        self.assertEqual([card.instrument_name for card in cards], ["Archer Aviation", "EHang Holdings"])
        archer, ehang = cards
        self.assertEqual(archer.wkn, "A3C3BQ")
        self.assertEqual(archer.current_price, "8,82 USD")
        self.assertEqual(archer.market_cap, "5,6 Mrd. EUR")
        self.assertEqual(archer.dividend_yield, "0,0 %")
        self.assertEqual(archer.kuv_26e, "100,2")
        self.assertIsNone(archer.kgv_26e)
        self.assertEqual(archer.target, "14,00 USD")
        self.assertEqual(archer.stop, "6,50 USD")
        self.assertEqual(archer.chance, 5)
        self.assertEqual(archer.risk, 4)
        self.assertEqual(archer.recommendation_status, "new_recommendation")
        self.assertEqual(ehang.recommendation_status, "no_buy")
        self.assertEqual(ehang.market_cap, "1,0 Mrd. EUR")
        self.assertEqual(ehang.kuv_26e, "8,2")
        self.assertEqual(ehang.kgv_26e, "156")

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
        self.assertEqual(card.recommendation_status, "new_recommendation")

    def test_extracts_derivative_omega_label_without_hebel_suffix(self) -> None:
        cards = extract_recommendation_cards_from_lines(
            (
                "ConocoPhillips Call",
                "WKN",
                "MM5GDA",
                "Akt. Kurs",
                "0,47 €",
                "Ziel",
                "1,10 €",
                "Stopp",
                "0,25 €",
                "Kurs Basiswert",
                "97,11 $",
                "Basispreis",
                "110,00 $",
                "Omega",
                "6,5",
                "Laufzeit",
                "18.09.26",
                "8,4 Monate",
            ),
            issue_id="2026-W03",
            page_number=61,
        )

        self.assertEqual(cards[0].instrument_name, "ConocoPhillips Call")
        self.assertEqual(cards[0].omega_hebel, "6,5")

    def test_extracts_explicit_non_stock_instrument_types(self) -> None:
        examples = (
            ("ETF", "MSCI World ETF", "A0RPWH", InstrumentType.ETF),
            ("Rohstoff", "Gold", "GOLD01", InstrumentType.COMMODITY),
            ("Krypto", "Bitcoin", "BTC123", InstrumentType.CRYPTO),
            ("Forex", "EUR/USD", "EURUSD", InstrumentType.FOREX),
        )

        for label, name, wkn, expected_type in examples:
            with self.subTest(label=label):
                cards = extract_recommendation_cards_from_lines(
                    (
                        label,
                        name,
                        "Akt. Kurs",
                        "123,00 €",
                        "WKN",
                        wkn,
                        "Ziel",
                        "150,00 €",
                    ),
                    issue_id="2026-W03",
                    page_number=42,
                )

                self.assertEqual(len(cards), 1)
                self.assertEqual(cards[0].instrument_name, name)
                self.assertEqual(cards[0].instrument_type, expected_type)
                self.assertEqual(cards[0].wkn, wkn)

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

    def test_extracts_turbo_long_option_card(self) -> None:
        cards = extract_recommendation_cards_from_lines(
            (
                "Silber Turbo-Long",
                "WKN",
                "JU2U7G",
                "Akt. Kurs",
                "34,43 €",
                "Empfehlungskurs",
                "03.12.2025",
                "16,76 €",
                "Performance",
                "+105,4 %",
                "Ziel",
                "40,00 € !",
                "Stopp",
                "25,00 € !",
                "Kurs Basiswert",
                "79,61 $",
                "Knock-out",
                "39,58 $",
                "Hebel",
                "2,0",
                "Laufzeit",
                "open end",
            ),
            issue_id="2026-W03",
            page_number=79,
        )

        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].instrument_name, "Silber Turbo-Long")
        self.assertEqual(cards[0].instrument_type.value, "derivative")
        self.assertEqual(cards[0].entry_price, "16,76 EUR")
        self.assertEqual(cards[0].performance_since_recommendation, "+105,4 %")
        self.assertEqual(cards[0].recommendation_status, "follow_up")
        self.assertEqual(cards[0].base_price, "39,58 USD")
        self.assertEqual(cards[0].omega_hebel, "2,0")

    def test_ignores_embedded_hebeltrader_ad_option_card(self) -> None:
        cards = extract_recommendation_cards_from_lines(
            (
                "www.hebeltrader.de",
                "MTU",
                "Optionsschein Call",
                "WKN",
                "MK9CNS",
                "Akt. Kurs**",
                "0,30 €",
                "HEBELTRADER-Anlagegrundsätze",
            ),
            issue_id="2026-W03",
            page_number=71,
        )

        self.assertEqual(cards, ())

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
