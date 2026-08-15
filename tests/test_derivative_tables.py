import unittest

from stock_analyst.derivative_tables import (
    DerivativeOverviewRow,
    extract_derivative_overview_result_from_page_lines,
    extract_derivative_overview_rows_from_page_lines,
)


BASE_PAGE_LINES = (
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
)

METRICS_HEADER_LINES = (
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
)

BAYER_METRICS_LINES = (
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
)

CATERPILLAR_METRICS_LINES = (
    "50/25",
    "03.12.25",
    "0,32 €",
    "0,24 €*",
    "-25,0 %",
    "Verkauft",
    "•••••",
    "•••••",
    "Ausgestoppt",
)

EXTRA_METRICS_LINES = (
    "51/25",
    "10.12.25",
    "2,00 €",
    "2,20 €",
    "+10,0 %",
    "2,50 €",
    "1,80 €",
    "••••",
    "••••",
    "Halten",
)


class DerivativeOverviewTablesTest(unittest.TestCase):
    def test_pairs_mini_long_base_row_with_following_page_action(self) -> None:
        mini_long_base_lines = (
            *BASE_PAGE_LINES[:10],
            "Synthetic Index",
            "INDEX1",
            "Synthetic Issuer",
            "Mini-Long",
            "0,01",
            "6.500 Pkte.",
            "open end",
            "3,2",
            "Derivate-Tipps im Rückblick",
        )
        pages = (
            (62, mini_long_base_lines),
            (63, METRICS_HEADER_LINES + BAYER_METRICS_LINES),
        )

        result = extract_derivative_overview_result_from_page_lines(
            pages,
            issue_id="2026-W34",
        )
        rows = result.rows

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].direction, "Mini-Long")
        self.assertEqual(rows[0].recommendation, "Dabei- bleiben")
        self.assertEqual(rows[0].metrics_page, 63)
        self.assertEqual(rows[0].source_pages, (62, 63))
        self.assertEqual(result.exceptions, ())

    def test_extracts_mini_short_base_row(self) -> None:
        mini_short_base_lines = (
            *BASE_PAGE_LINES[:10],
            "Synthetic Index",
            "INDEX2",
            "Synthetic Issuer",
            "Mini-Short",
            "0,01",
            "6.000 Pkte.",
            "open end",
            "3,1",
            "Derivate-Tipps im Rückblick",
        )

        rows = extract_derivative_overview_rows_from_page_lines(
            ((62, mini_short_base_lines),),
            issue_id="2026-W34",
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].direction, "Mini-Short")
        self.assertEqual(rows[0].source_pages, (62,))

    def test_does_not_pair_non_adjacent_equal_count_tables(self) -> None:
        rows = extract_derivative_overview_rows_from_page_lines(
            (
                (62, BASE_PAGE_LINES),
                (
                    64,
                    METRICS_HEADER_LINES
                    + BAYER_METRICS_LINES
                    + CATERPILLAR_METRICS_LINES,
                ),
            ),
            issue_id="2026-W34",
        )

        self.assertEqual(len(rows), 2)
        for row in rows:
            self._assert_metrics_blank(row)
            self.assertEqual(row.source_pages, (62,))

    def test_pairs_multiple_independent_adjacent_spreads(self) -> None:
        second_base_page = tuple(
            line.replace("UG8QQ9", "PAIR01").replace("MM5XEN", "PAIR02")
            for line in BASE_PAGE_LINES
        )
        second_metrics_page = (
            METRICS_HEADER_LINES
            + BAYER_METRICS_LINES
            + EXTRA_METRICS_LINES
        )

        rows = extract_derivative_overview_rows_from_page_lines(
            (
                (62, BASE_PAGE_LINES),
                (
                    63,
                    METRICS_HEADER_LINES
                    + BAYER_METRICS_LINES
                    + CATERPILLAR_METRICS_LINES,
                ),
                (70, second_base_page),
                (71, second_metrics_page),
            ),
            issue_id="2026-W34",
        )

        self.assertEqual(len(rows), 4)
        self.assertEqual([row.source_pages for row in rows], [(62, 63), (62, 63), (70, 71), (70, 71)])
        self.assertTrue(all(row.recommendation for row in rows))

    def test_extracts_base_and_metrics_rows_from_overview_pages(self) -> None:
        rows = extract_derivative_overview_rows_from_page_lines(
            self._pages(BAYER_METRICS_LINES, CATERPILLAR_METRICS_LINES),
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

    def test_leaves_metrics_blank_when_retrospective_row_is_missing(self) -> None:
        result = extract_derivative_overview_result_from_page_lines(
            self._pages(BAYER_METRICS_LINES),
            issue_id="2026-W03",
        )
        rows = result.rows

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].underlying, "Bayer")
        self.assertEqual(rows[1].underlying, "Caterpillar")
        self._assert_metrics_blank(rows[0])
        self._assert_metrics_blank(rows[1])
        self.assertEqual(len(result.exceptions), 1)
        exception = result.exceptions[0]
        self.assertEqual(exception.reason, "adjacent_row_count_mismatch")
        self.assertEqual(exception.base_page, 62)
        self.assertEqual(exception.metrics_pages, (63,))
        self.assertEqual(exception.base_row_count, 2)
        self.assertEqual(exception.metrics_row_counts, (1,))

    def test_leaves_metrics_blank_when_retrospective_row_is_extra(self) -> None:
        rows = extract_derivative_overview_rows_from_page_lines(
            self._pages(
                BAYER_METRICS_LINES,
                CATERPILLAR_METRICS_LINES,
                EXTRA_METRICS_LINES,
            ),
            issue_id="2026-W03",
        )

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].underlying, "Bayer")
        self.assertEqual(rows[1].underlying, "Caterpillar")
        self._assert_metrics_blank(rows[0])
        self._assert_metrics_blank(rows[1])

    def test_reports_ambiguous_adjacent_metrics_tables_without_applying_either(self) -> None:
        metrics_page = (
            METRICS_HEADER_LINES
            + BAYER_METRICS_LINES
            + CATERPILLAR_METRICS_LINES
        )

        result = extract_derivative_overview_result_from_page_lines(
            (
                (61, metrics_page),
                (62, BASE_PAGE_LINES),
                (63, metrics_page),
            ),
            issue_id="2026-W03",
        )

        self.assertEqual(len(result.rows), 2)
        self.assertTrue(all(row.metrics_page is None for row in result.rows))
        self.assertEqual(len(result.exceptions), 1)
        exception = result.exceptions[0]
        self.assertEqual(exception.reason, "ambiguous_adjacent_metrics_table")
        self.assertEqual(exception.base_page, 62)
        self.assertEqual(exception.metrics_pages, (61, 63))
        self.assertEqual(exception.base_row_count, 2)
        self.assertEqual(exception.metrics_row_counts, (2, 2))

    def _pages(
        self,
        *metrics_rows: tuple[str, ...],
    ) -> tuple[tuple[int, tuple[str, ...]], ...]:
        return (
            (62, BASE_PAGE_LINES),
            (
                63,
                METRICS_HEADER_LINES
                + tuple(line for row in metrics_rows for line in row),
            ),
        )

    def _assert_metrics_blank(self, row: DerivativeOverviewRow) -> None:
        self.assertEqual(row.entry_price, "")
        self.assertEqual(row.current_price, "")
        self.assertEqual(row.performance_since_recommendation, "")
        self.assertEqual(row.target, "")
        self.assertEqual(row.stop, "")
        self.assertEqual(row.recommendation, "")


if __name__ == "__main__":
    unittest.main()
