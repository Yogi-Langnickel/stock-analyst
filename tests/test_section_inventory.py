import unittest

from stock_analyst.section_inventory import (
    MagazineSectionKind,
    extract_section_candidates_from_lines,
)


class SectionInventoryTest(unittest.TestCase):
    def test_detects_dividend_strategy_table(self) -> None:
        sections = extract_section_candidates_from_lines(
            (
                "Dividende",
                "ohne Ende",
                "Monat",
                "Unternehmen",
                "WKN",
                "Dividenden-",
                "rendite",
                "Banco Sabadell",
                "A0MRD4",
            ),
            issue_id="2026-W03",
            page_number=18,
        )

        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0].section_kind, MagazineSectionKind.DIVIDEND_STRATEGY)
        self.assertEqual(sections[0].suggested_sheet, "Dividend Focus")
        self.assertEqual(sections[0].priority, "high")
        self.assertIn("A0MRD4", sections[0].wkns)

    def test_detects_derivative_overview_pages(self) -> None:
        sections = extract_section_candidates_from_lines(
            (
                "Derivate | Rückblick",
                "Basiswert",
                "WKN",
                "Emittent",
                "Typ",
                "Strike /",
                "Cap",
                "Laufzeit",
                "Hebel /",
                "Omega",
                "Bayer",
                "UG8QQ9",
            ),
            issue_id="2026-W03",
            page_number=62,
        )

        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0].section_kind, MagazineSectionKind.DERIVATIVE_TIPS_OVERVIEW)
        self.assertEqual(sections[0].suggested_sheet, "Derivative Tips")
        self.assertIn("UG8QQ9", sections[0].wkns)

    def test_detects_depot_positions_and_transactions_on_same_page(self) -> None:
        sections = extract_section_candidates_from_lines(
            (
                "AKTIONÄR-Depot",
                "Aktie/Derivat",
                "WKN",
                "Stück-",
                "zahl",
                "Kauf-",
                "datum",
                "Amazon",
                "906866",
                "Durchgeführte Transaktionen",
                "Transaktion",
                "Wertpapier",
                "Diese Woche keine Transaktionen",
            ),
            issue_id="2026-W03",
            page_number=66,
        )

        kinds = {section.section_kind for section in sections}
        self.assertEqual(
            kinds,
            {
                MagazineSectionKind.AKTIONAER_DEPOT_POSITIONS,
                MagazineSectionKind.AKTIONAER_DEPOT_TRANSACTIONS,
            },
        )

    def test_detects_chart_check_and_quick_check_as_stock_attachable(self) -> None:
        chart_sections = extract_section_candidates_from_lines(
            (
                "Chart-Check",
                "Ebay",
                "916529",
                "Deutsche Bank",
                "514000",
                "Ziel",
                "Stopp",
                "Perform.",
                "seit Empf.",
            ),
            issue_id="2026-W03",
            page_number=82,
        )
        quick_sections = extract_section_candidates_from_lines(
            (
                "2G Energy",
                "A0HL8N",
                "Adidas",
                "A1EWWW",
                "Coinbase",
                "A2QP7J",
                "Tesla",
                "A1CX3T",
                "Aktien im Quick-Check",
            ),
            issue_id="2026-W03",
            page_number=90,
        )

        self.assertEqual(chart_sections[0].section_kind, MagazineSectionKind.CHART_CHECK)
        self.assertEqual(chart_sections[0].extraction_notes, ("attach_to_stock_when_wkn_matches",))
        self.assertEqual(quick_sections[0].section_kind, MagazineSectionKind.QUICK_CHECK)
        self.assertEqual(quick_sections[0].suggested_sheet, "Stock Quickcheck")

    def test_detects_statistics_as_context_only(self) -> None:
        sections = extract_section_candidates_from_lines(
            (
                "Statistik",
                "Die Woche im Überblick",
                "Indizes",
                "Deutschland",
                "Stand:",
                "07.01.2026",
                "52-Wochen-",
                "Hoch",
            ),
            issue_id="2026-W03",
            page_number=93,
        )

        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0].section_kind, MagazineSectionKind.STATISTICS_CONTEXT)
        self.assertEqual(sections[0].priority, "low")
        self.assertEqual(sections[0].extraction_notes, ("context_only",))

    def test_flags_late_back_matter_as_low_priority(self) -> None:
        sections = extract_section_candidates_from_lines(
            (
                "Bücher",
                "DER AKTIONÄR 03/2026",
                "Mary Buffett, David Clark",
            ),
            issue_id="2026-W03",
            page_number=118,
        )

        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0].section_kind, MagazineSectionKind.LOW_PRIORITY_BACK_MATTER)
        self.assertEqual(sections[0].suggested_sheet, "Extraction Audit")

    def test_filters_common_header_words_from_wkns(self) -> None:
        sections = extract_section_candidates_from_lines(
            (
                "Chart-Check",
                "DER AKTIONÄR",
                "CRISPR Therapeutics",
                "A2AT0Z",
                "Tesla",
                "A1CX3T",
            ),
            issue_id="2026-W03",
            page_number=80,
        )

        self.assertEqual(sections[0].wkns, ("A2AT0Z", "A1CX3T"))


if __name__ == "__main__":
    unittest.main()
