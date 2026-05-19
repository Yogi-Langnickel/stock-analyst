import unittest
from dataclasses import dataclass

from stock_analyst.processing_policy import (
    DEFAULT_REMOTE_OCR_MONTHLY_PAGE_BUDGET,
    build_magazine_processing_window,
    filter_magazine_processing_pages,
    remote_ocr_budget_status,
)


@dataclass(frozen=True)
class Page:
    page_number: int
    text: str


class ProcessingPolicyTest(unittest.TestCase):
    def test_filters_front_matter_and_pages_after_statistics(self) -> None:
        pages = tuple(
            Page(page, f"page {page}")
            for page in range(1, 11)
        ) + (
            Page(11, "Statistik\nDER AKTIONÄR\n03/2026\nDie Woche im Überblick\nIndizes"),
            Page(12, "book ad"),
            Page(13, "app promotion"),
        )

        filtered = filter_magazine_processing_pages(pages)
        window = build_magazine_processing_window(pages)

        self.assertEqual([page.page_number for page in filtered], [6, 7, 8, 9, 10, 11])
        self.assertEqual(window.skipped_front_matter_pages, (1, 2, 3, 4, 5))
        self.assertEqual(window.statistics_page, 11)
        self.assertEqual(window.skipped_back_matter_pages, (12, 13))

    def test_ignores_running_header_statistics_without_body_markers(self) -> None:
        pages = (
            Page(
                6,
                "Statistik\nDER AKTIONÄR\n03/2026\n"
                "Banco Sabadell\nA0MRD4\nKursziel 3,30 Euro",
            ),
            Page(7, "RTL Group\n861149\nDividendenrendite 20,1%"),
        )

        filtered = filter_magazine_processing_pages(pages)
        window = build_magazine_processing_window(pages)

        self.assertIsNone(window.statistics_page)
        self.assertEqual([page.page_number for page in filtered], [6, 7])

    def test_detects_statistics_body_after_running_header(self) -> None:
        pages = (
            Page(
                6,
                "Statistik\nDER AKTIONÄR\n03/2026\n"
                "Die Woche im Überblick\nIndizes\n52-Wochen",
            ),
            Page(7, "book ad"),
        )

        filtered = filter_magazine_processing_pages(pages)
        window = build_magazine_processing_window(pages)

        self.assertEqual(window.statistics_page, 6)
        self.assertEqual([page.page_number for page in filtered], [6])
        self.assertEqual(window.skipped_back_matter_pages, (7,))

    def test_remote_ocr_budget_guard_uses_900_page_monthly_cap(self) -> None:
        self.assertEqual(DEFAULT_REMOTE_OCR_MONTHLY_PAGE_BUDGET, 900)
        self.assertEqual(remote_ocr_budget_status(900), "within_contract_budget")
        self.assertEqual(
            remote_ocr_budget_status(901),
            "over_contract_budget_requires_manual_approval",
        )


if __name__ == "__main__":
    unittest.main()
