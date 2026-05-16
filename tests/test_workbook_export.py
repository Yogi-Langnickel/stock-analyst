import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from stock_analyst.dividend_strategy import DividendStrategyRow
from stock_analyst.extraction import RawPageText
from stock_analyst.google_access import DEFAULT_SHEET_TABS
from stock_analyst.recommendation_cards import RecommendationCard
from stock_analyst.schemas import InstrumentType, ReviewStatus
from stock_analyst.section_inventory import (
    MagazineSectionCandidate,
    MagazineSectionKind,
)
from stock_analyst.workbook_export import (
    build_workbook_export_plan,
    build_workbook_export_plan_from_pdf,
)


def headers_for(tab: str) -> tuple[str, ...]:
    for spec in DEFAULT_SHEET_TABS:
        if spec.title == tab:
            return spec.headers
    raise AssertionError(f"unknown tab: {tab}")


class WorkbookExportPlanTest(unittest.TestCase):
    def test_pdf_plan_extracts_text_once_for_all_local_parsers(self) -> None:
        class StubExtractor:
            extractor_name = "stub"

            def __init__(self) -> None:
                self.calls = 0

            def extract_pages(self, _pdf_path: Path) -> tuple[RawPageText, ...]:
                self.calls += 1
                return (
                    RawPageText(
                        page_number=1,
                        text="\n".join(
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
                                "Dividende",
                                "ohne Ende",
                            )
                        ),
                    ),
                )

        with TemporaryDirectory() as directory:
            pdf = Path(directory) / "DA_2026_03.pdf"
            pdf.write_bytes(b"%PDF-1.7\nprivate synthetic fixture")
            extractor = StubExtractor()

            plan = build_workbook_export_plan_from_pdf(pdf, extractor=extractor)

        result = plan.to_dict()
        self.assertEqual(extractor.calls, 1)
        self.assertEqual(result["issueId"], "2026-W03")
        self.assertEqual(result["rowCount"], 2)
        self.assertEqual(
            result["rowsByTab"],
            {"Extraction Audit": 1, "Recommendation Cards": 1},
        )

    def test_routes_stock_card_to_recommendation_card_sheet_row(self) -> None:
        plan = build_workbook_export_plan(
            pdf_path=Path("data/private/issues/DA_2026_03.pdf"),
            issue_id="2026-W03",
            recommendation_cards=(
                RecommendationCard(
                    issue_id="2026-W03",
                    page=22,
                    instrument_name="Banco Sabadell",
                    instrument_type=InstrumentType.STOCK,
                    wkn="A0MRD4",
                    current_price="3,33 EUR",
                    target="4,30 EUR",
                    stop="2,70 EUR",
                    chance=5,
                    risk=5,
                    recommendation_status="new_recommendation",
                    market_cap="16,8 Mrd. EUR",
                    dividend_yield="18,6 %",
                    kgv_26e="10",
                    kuv_26e="",
                ),
            ),
        )

        result = plan.to_dict()
        row = result["rows"][0]

        self.assertFalse(result["googleWritesEnabled"])
        self.assertNotIn("pdfPath", result)
        self.assertIn("privateSourceId", result)
        self.assertTrue(result["manualReviewRequired"])
        self.assertEqual(result["approvedRows"], 0)
        self.assertEqual(row["tab"], "Recommendation Cards")
        self.assertFalse(row["exportable"])
        self.assertTrue(row["requiresManualReview"])
        self.assertEqual(row["reviewStatus"], ReviewStatus.NEEDS_REVIEW.value)
        self.assertEqual(row["sourceBlock"], "manual_review_pending")
        self.assertEqual(len(row["values"]), len(headers_for("Recommendation Cards")))
        self.assertEqual(row["values"][3], "Banco Sabadell")
        self.assertEqual(row["values"][5], "5/5")
        self.assertIn("manual_review_required", row["warnings"][0])

    def test_routes_derivative_cards_without_putting_name_in_source_id(self) -> None:
        plan = build_workbook_export_plan(
            pdf_path=Path("data/private/issues/DA_2026_03.pdf"),
            issue_id="2026-W03",
            recommendation_cards=(
                RecommendationCard(
                    issue_id="2026-W03",
                    page=37,
                    instrument_name="Baidu Call",
                    instrument_type=InstrumentType.DERIVATIVE,
                    wkn="MM7PJ4",
                    current_price="2,15 EUR",
                    target="4,00 EUR",
                    stop="1,30 EUR",
                    chance=None,
                    risk=None,
                    recommendation_status=None,
                    underlying_price="146,42 USD",
                    base_price="150,00 USD",
                    omega_hebel="3,1",
                    runtime="18.09.26 (8,5 Monate)",
                ),
            ),
        )

        row = plan.to_dict()["rows"][0]

        self.assertEqual(row["tab"], "Derivative Tips")
        self.assertEqual(row["rowKind"], "derivative_card")
        self.assertEqual(len(row["values"]), len(headers_for("Derivative Tips")))
        self.assertEqual(row["values"][4], "Baidu Call")
        self.assertNotIn("Baidu Call", row["sourceId"])

    def test_routes_dividend_rows_to_dividend_focus(self) -> None:
        plan = build_workbook_export_plan(
            pdf_path=Path("data/private/issues/DA_2026_03.pdf"),
            issue_id="2026-W03",
            dividend_strategy=(
                DividendStrategyRow(
                    issue_id="2026-W03",
                    page=18,
                    month="März",
                    company="Banco Sabadell",
                    wkn="A0MRD4",
                    current_price="3,33 EUR",
                    market_cap_billions_eur="16,8",
                    dividend_yield="18,6 %",
                    kgv_2026e="10",
                    payout_count="2",
                    next_cum_day="14.04.26",
                    next_pay_day="17.04.26",
                    target="4,30 EUR",
                    stop="2,70 EUR",
                ),
            ),
        )

        row = plan.to_dict()["rows"][0]

        self.assertEqual(row["tab"], "Dividend Focus")
        self.assertEqual(row["rowKind"], "dividend_strategy")
        self.assertEqual(len(row["values"]), len(headers_for("Dividend Focus")))
        self.assertEqual(row["values"][2], "Banco Sabadell")
        self.assertEqual(row["values"][5], "18,6 %")
        self.assertEqual(row["reviewStatus"], ReviewStatus.NEEDS_REVIEW.value)
        self.assertEqual(headers_for("Dividend Focus")[4], "Payout count")

    def test_workbook_plan_downgrades_preapproved_inputs_to_needs_review(self) -> None:
        plan = build_workbook_export_plan(
            pdf_path=Path("data/private/issues/DA_2026_03.pdf"),
            issue_id="2026-W03",
            recommendation_cards=(
                RecommendationCard(
                    issue_id="2026-W03",
                    page=22,
                    instrument_name="Banco Sabadell",
                    instrument_type=InstrumentType.STOCK,
                    wkn="A0MRD4",
                    current_price=None,
                    target=None,
                    stop=None,
                    chance=None,
                    risk=None,
                    recommendation_status=None,
                    review_status=ReviewStatus.APPROVED,
                ),
            ),
            dividend_strategy=(
                DividendStrategyRow(
                    issue_id="2026-W03",
                    page=18,
                    month="März",
                    company="Banco Sabadell",
                    wkn="A0MRD4",
                    current_price=None,
                    market_cap_billions_eur=None,
                    dividend_yield="18,6 %",
                    kgv_2026e=None,
                    review_status=ReviewStatus.APPROVED,
                ),
            ),
            section_inventory=(
                MagazineSectionCandidate(
                    issue_id="2026-W03",
                    page=62,
                    section_kind=MagazineSectionKind.DERIVATIVE_TIPS_OVERVIEW,
                    section_title="Derivate tips overview",
                    suggested_sheet="Derivative Tips",
                    priority="high",
                    reason="Derivative overview table with WKN and runtime.",
                    wkns=(),
                    review_status=ReviewStatus.APPROVED,
                ),
            ),
        )

        result = plan.to_dict()

        self.assertEqual(result["approvedRows"], 0)
        for row in result["rows"]:
            self.assertEqual(row["reviewStatus"], ReviewStatus.NEEDS_REVIEW.value)
            self.assertFalse(row["exportable"])
            self.assertTrue(row["requiresManualReview"])
            self.assertEqual(row["sourceBlock"], "manual_review_pending")

    def test_routes_section_inventory_to_extraction_audit_with_suggested_sheet(self) -> None:
        plan = build_workbook_export_plan(
            pdf_path=Path("data/private/issues/DA_2026_03.pdf"),
            issue_id="2026-W03",
            section_inventory=(
                MagazineSectionCandidate(
                    issue_id="2026-W03",
                    page=62,
                    section_kind=MagazineSectionKind.DERIVATIVE_TIPS_OVERVIEW,
                    section_title="Derivate tips overview",
                    suggested_sheet="Derivative Tips",
                    priority="high",
                    reason="Derivative overview table with WKN and runtime.",
                    wkns=("UG8QQ9",),
                ),
            ),
        )

        row = plan.to_dict()["rows"][0]

        self.assertEqual(row["tab"], "Extraction Audit")
        self.assertEqual(row["rowKind"], "section_inventory")
        self.assertEqual(len(row["values"]), len(headers_for("Extraction Audit")))
        self.assertEqual(row["values"][3], "derivative_tips_overview")
        self.assertEqual(row["values"][4], "warning")
        self.assertIn("suggested_sheet=Derivative Tips", row["warnings"])


if __name__ == "__main__":
    unittest.main()
