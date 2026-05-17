import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from stock_analyst.dividend_strategy import DividendStrategyRow
from stock_analyst.depot_tables import DepotPositionRow, DepotTransactionRow
from stock_analyst.derivative_tables import DerivativeOverviewRow
from stock_analyst.extraction import RawPageText
from stock_analyst.google_access import DEFAULT_SHEET_TABS
from stock_analyst.recommendation_cards import RecommendationCard
from stock_analyst.quickcheck import QuickcheckRow
from stock_analyst.schemas import InstrumentType, ReviewStatus
from stock_analyst.section_inventory import (
    MagazineSectionCandidate,
    MagazineSectionKind,
)
from stock_analyst.workbook_export import (
    build_workbook_export_plan,
    build_workbook_export_plan_from_pdf,
)


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "workbook_export"


def headers_for(tab: str) -> tuple[str, ...]:
    for spec in DEFAULT_SHEET_TABS:
        if spec.title == tab:
            return spec.headers
    raise AssertionError(f"unknown tab: {tab}")


def load_workbook_fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


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
            {"Extraction Audit": 1, "Stocks": 1},
        )

    def test_pdf_plan_uses_filename_issue_date_for_stock_update_date(self) -> None:
        class StubExtractor:
            extractor_name = "stub"

            def extract_pages(self, _pdf_path: Path) -> tuple[RawPageText, ...]:
                return (
                    RawPageText(
                        page_number=1,
                        text="\n".join(
                            (
                                "Aktie",
                                "Banco Sabadell",
                                "Akt. Kurs",
                                "3,33 €",
                                "WKN",
                                "A0MRD4",
                                "Ziel",
                                "4,30 €",
                            )
                        ),
                    ),
                )

        with TemporaryDirectory() as directory:
            pdf = Path(directory) / "aktionaer-2026-05-14.pdf"
            pdf.write_bytes(b"%PDF-1.7\nprivate synthetic fixture")

            plan = build_workbook_export_plan_from_pdf(
                pdf,
                extractor=StubExtractor(),
                current_utc_date="2026-05-17",
            )

        stock_row = next(row for row in plan.to_dict()["rows"] if row["tab"] == "Stocks")

        self.assertEqual(stock_row["values"][-1], "2026-05-14")

    def test_routes_stock_card_to_stocks_sheet_row(self) -> None:
        plan = build_workbook_export_plan(
            pdf_path=Path("data/private/issues/DA_2026_03.pdf"),
            issue_id="2026-W03",
            stock_update_date="2026-05-17",
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
        stock_tab = next(tab for tab in result["tabs"] if tab["title"] == "Stocks")

        self.assertFalse(result["googleWritesEnabled"])
        self.assertFalse(result["externalServicesEnabled"])
        self.assertNotIn("pdfPath", result)
        self.assertIn("privateSourceId", result)
        self.assertTrue(result["manualReviewRequired"])
        self.assertEqual(result["approvedRows"], 0)
        self.assertEqual(row["tab"], "Stocks")
        self.assertEqual(row["rowKind"], "stock_recommendation")
        self.assertFalse(row["exportable"])
        self.assertTrue(row["requiresManualReview"])
        self.assertEqual(row["reviewStatus"], ReviewStatus.NEEDS_REVIEW.value)
        self.assertEqual(row["sourceBlock"], "manual_review_pending")
        self.assertEqual(len(row["values"]), len(headers_for("Stocks")))
        self.assertEqual(stock_tab["headerRow"], 3)
        self.assertEqual(stock_tab["frozenRows"], 3)
        self.assertEqual(stock_tab["frozenColumns"], 2)
        self.assertEqual(stock_tab["tableStartsAt"], "A3")
        self.assertEqual(stock_tab["parserStatus"], "parser_backed")
        self.assertTrue(stock_tab["layoutNotes"])
        self.assertEqual(stock_tab["metadataCells"], [])
        self.assertEqual(row["values"][0], "Banco Sabadell")
        self.assertEqual(row["values"][1], "A0MRD4")
        self.assertEqual(row["values"][2], "")
        self.assertEqual(row["values"][3], "3,33 EUR")
        self.assertEqual(row["values"][4], "18,6 %")
        self.assertEqual(row["values"][5], "16,8 Mrd. EUR")
        self.assertEqual(row["values"][6], "5/5")
        self.assertEqual(row["values"][7], "")
        self.assertEqual(row["values"][8], "10")
        self.assertEqual(row["values"][9], "4,30 EUR")
        self.assertEqual(row["values"][10], "2,70 EUR")
        self.assertEqual(row["values"][11], "new_recommendation")
        self.assertEqual(row["values"][12], "2026-W03")
        self.assertEqual(row["values"][13], "22")
        self.assertEqual(row["values"][14], "2026-05-17")
        self.assertIn("manual_review_required", row["warnings"][0])

    def test_stock_update_date_prefers_explicit_import_date(self) -> None:
        with TemporaryDirectory() as directory:
            pdf = Path(directory) / "aktionaer-2026-05-14.pdf"
            pdf.write_bytes(b"%PDF-1.7\nprivate synthetic fixture")

            plan = build_workbook_export_plan_from_pdf(
                pdf,
                extractor=_SingleStockExtractor(),
                import_date="2026-05-16",
                current_utc_date="2026-05-17",
            )

        stock_row = next(row for row in plan.to_dict()["rows"] if row["tab"] == "Stocks")

        self.assertEqual(stock_row["values"][-1], "2026-05-16")

    def test_stock_dividend_prefers_current_yield_over_per_share_trend(self) -> None:
        plan = build_workbook_export_plan(
            pdf_path=Path("data/private/issues/DA_2026_03.pdf"),
            issue_id="2026-W03",
            stock_update_date="2026-05-17",
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
                    dividend_per_share_trend="2023: 0,04; 2024: 0,11; 2025e: 0,36",
                ),
            ),
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
                ),
            ),
        )

        stock_row = next(row for row in plan.to_dict()["rows"] if row["tab"] == "Stocks")

        self.assertEqual(stock_row["values"][4], "18,6 %")
        self.assertNotIn("2023", stock_row["values"][4])

    def test_routes_derivative_cards_without_putting_name_in_source_id(self) -> None:
        plan = build_workbook_export_plan(
            pdf_path=Path("data/private/issues/DA_2026_03.pdf"),
            issue_id="2026-W03",
            stock_update_date="2026-05-17",
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
        self.assertEqual(row["values"][3], "Baidu")
        self.assertEqual(row["values"][4], "Call")
        self.assertNotIn("Baidu Call", row["sourceId"])

    def test_routes_explicit_asset_class_cards_to_dedicated_tabs(self) -> None:
        plan = build_workbook_export_plan(
            pdf_path=Path("data/private/issues/DA_2026_03.pdf"),
            issue_id="2026-W03",
            stock_update_date="2026-05-17",
            recommendation_cards=(
                RecommendationCard(
                    issue_id="2026-W03",
                    page=12,
                    instrument_name="MSCI World ETF",
                    instrument_type=InstrumentType.ETF,
                    wkn="A0RPWH",
                    current_price="115,00 EUR",
                    target=None,
                    stop=None,
                    chance=None,
                    risk=None,
                    recommendation_status="follow_up",
                    dividend_yield="1,8 %",
                ),
                RecommendationCard(
                    issue_id="2026-W03",
                    page=13,
                    instrument_name="Gold",
                    instrument_type=InstrumentType.COMMODITY,
                    wkn="GOLD01",
                    current_price="2.350 USD",
                    target="2.600 USD",
                    stop="2.100 USD",
                    chance=None,
                    risk=None,
                    recommendation_status="new_recommendation",
                ),
                RecommendationCard(
                    issue_id="2026-W03",
                    page=14,
                    instrument_name="Bitcoin",
                    instrument_type=InstrumentType.CRYPTO,
                    wkn="BTC123",
                    current_price="98.000 USD",
                    target="120.000 USD",
                    stop="82.000 USD",
                    chance=None,
                    risk=None,
                    recommendation_status="follow_up",
                ),
                RecommendationCard(
                    issue_id="2026-W03",
                    page=15,
                    instrument_name="EUR/USD",
                    instrument_type=InstrumentType.FOREX,
                    wkn="EURUSD",
                    current_price="1,0850",
                    target="1,1200",
                    stop="1,0650",
                    chance=None,
                    risk=None,
                    recommendation_status="follow_up",
                ),
            ),
        )

        rows = {row["tab"]: row for row in plan.to_dict()["rows"]}

        self.assertEqual(set(rows), {"ETF", "Commodities", "Crypto", "Forex"})
        self.assertEqual(rows["ETF"]["rowKind"], "etf_recommendation")
        self.assertEqual(rows["ETF"]["values"][0], "MSCI World ETF")
        self.assertEqual(rows["ETF"]["values"][1], "A0RPWH")
        self.assertEqual(rows["ETF"]["values"][-1], "2026-05-17")
        self.assertEqual(len(rows["ETF"]["values"]), len(headers_for("ETF")))
        self.assertEqual(rows["Commodities"]["rowKind"], "commodity_recommendation")
        self.assertEqual(rows["Crypto"]["rowKind"], "crypto_recommendation")
        self.assertEqual(rows["Forex"]["rowKind"], "forex_recommendation")
        for row in rows.values():
            self.assertEqual(row["reviewStatus"], ReviewStatus.NEEDS_REVIEW.value)
            self.assertEqual(row["values"][-1], "2026-05-17")
            self.assertEqual(len(row["values"]), len(headers_for(row["tab"])))

    def test_derivative_tip_fixtures_cover_option_and_discount_call_shapes(self) -> None:
        fixture = load_workbook_fixture("da_2026_03_other_tabs.json")
        expected_rows = [
            row for row in fixture["rows"]
            if row["tab"] == "Derivative Tips"
        ]
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
                RecommendationCard(
                    issue_id="2026-W03",
                    page=78,
                    instrument_name="Gold Discount-Call",
                    instrument_type=InstrumentType.DERIVATIVE,
                    wkn="MM4M60",
                    current_price=None,
                    target="13,50 EUR",
                    stop="6,50 EUR",
                    chance=None,
                    risk=None,
                    recommendation_status=None,
                    underlying_price="4.458,58 USD",
                    base_price="4.350 USD",
                    omega_hebel="",
                    runtime="20.03.2026",
                ),
            ),
        )

        actual_rows = [
            {
                "tab": row["tab"],
                "rowKind": row["rowKind"],
                "page": row["page"],
                "values": row["values"],
            }
            for row in plan.to_dict()["rows"]
        ]

        self.assertEqual(actual_rows, expected_rows)
        for row in actual_rows:
            self.assertEqual(len(row["values"]), len(headers_for("Derivative Tips")))
            self.assertEqual(row["values"][-2], ReviewStatus.NEEDS_REVIEW.value)
            self.assertTrue(row["values"][-1])

    def test_routes_derivative_overview_and_depot_tables_to_dedicated_tabs(self) -> None:
        plan = build_workbook_export_plan(
            pdf_path=Path("data/private/issues/DA_2026_03.pdf"),
            issue_id="2026-W03",
            stock_update_date="2026-05-17",
            derivative_overview=(
                DerivativeOverviewRow(
                    issue_id="2026-W03",
                    page=62,
                    underlying="Bayer",
                    product="Bayer",
                    direction="Discount-Call",
                    wkn="UG8QQ9",
                    issuer="UniCredit",
                    ratio="1,00",
                    strike_cap="33,00 EUR",
                    omega_hebel="",
                    runtime="17.06.26 (5,3 Monate)",
                    entry_price="1,03 EUR",
                    current_price="1,94 EUR",
                    performance_since_recommendation="+88,3 %",
                    target="3,00 EUR",
                    stop="1,40 EUR",
                    recommendation="Dabei- bleiben",
                ),
            ),
            depot_positions=(
                DepotPositionRow(
                    issue_id="2026-W03",
                    page=66,
                    instrument="Amazon",
                    wkn="906866",
                    quantity="60",
                    buy_date="31.03.20",
                    buy_price="89,85 EUR",
                    current_price="205,25 EUR",
                    value="12.315,00 EUR",
                    performance_since_buy="+128,4 %",
                    stop="",
                ),
            ),
            depot_transactions=(
                DepotTransactionRow(
                    issue_id="2026-W03",
                    page=66,
                    action="Keine Transaktionen",
                ),
            ),
        )

        rows = {row["tab"]: row for row in plan.to_dict()["rows"]}

        self.assertEqual(rows["Derivative Tips"]["rowKind"], "derivative_overview")
        self.assertEqual(rows["Derivative Tips"]["values"][3], "Bayer")
        self.assertEqual(rows["Derivative Tips"]["values"][4], "Discount-Call")
        self.assertEqual(rows["Derivative Tips"]["values"][14], "+88,3 %")
        self.assertEqual(len(rows["Derivative Tips"]["values"]), len(headers_for("Derivative Tips")))
        self.assertEqual(rows["AKTIONAER Depot"]["rowKind"], "aktionaer_depot_position")
        self.assertEqual(rows["AKTIONAER Depot"]["values"][2], "Amazon")
        self.assertEqual(len(rows["AKTIONAER Depot"]["values"]), len(headers_for("AKTIONAER Depot")))
        self.assertEqual(rows["Depot Transactions"]["rowKind"], "depot_transaction")
        self.assertEqual(rows["Depot Transactions"]["values"][2], "Keine Transaktionen")
        self.assertEqual(
            len(rows["Depot Transactions"]["values"]),
            len(headers_for("Depot Transactions")),
        )

    def test_routes_dividend_rows_to_dividend_focus(self) -> None:
        plan = build_workbook_export_plan(
            pdf_path=Path("data/private/issues/DA_2026_03.pdf"),
            issue_id="2026-W03",
            stock_update_date="2026-05-17",
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
        self.assertTrue(row["values"][-1])
        self.assertEqual(row["reviewStatus"], ReviewStatus.NEEDS_REVIEW.value)
        self.assertEqual(headers_for("Dividend Focus")[4], "Payout count")

    def test_dividend_focus_fixtures_cover_high_yield_decision_fields(self) -> None:
        fixture = load_workbook_fixture("da_2026_03_other_tabs.json")
        expected_rows = [
            row for row in fixture["rows"]
            if row["tab"] == "Dividend Focus"
        ]
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
                    payout_count="",
                    next_cum_day="",
                    next_pay_day="",
                    target="4,30 EUR",
                    stop="2,70 EUR",
                ),
                DividendStrategyRow(
                    issue_id="2026-W03",
                    page=18,
                    month="Mai",
                    company="RTL Group",
                    wkn="861149",
                    current_price="34,80 EUR",
                    market_cap_billions_eur=None,
                    dividend_yield="20,1 %",
                    kgv_2026e=None,
                    payout_count="",
                    next_cum_day="",
                    next_pay_day="",
                    target="42,00 EUR",
                    stop="25,00 EUR",
                ),
            ),
        )

        actual_rows = [
            {
                "tab": row["tab"],
                "rowKind": row["rowKind"],
                "page": row["page"],
                "values": row["values"],
            }
            for row in plan.to_dict()["rows"]
        ]

        self.assertEqual(actual_rows, expected_rows)
        for row in actual_rows:
            self.assertEqual(len(row["values"]), len(headers_for("Dividend Focus")))
            self.assertIn("%", row["values"][5])

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

            headers = headers_for(str(row["tab"]))
            if "Review status" in headers:
                review_status_index = headers.index("Review status")
                self.assertEqual(
                    row["values"][review_status_index],
                    ReviewStatus.NEEDS_REVIEW.value,
                )

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

    def test_extraction_audit_fixtures_cover_high_value_table_surfaces(self) -> None:
        fixture = load_workbook_fixture("da_2026_03_other_tabs.json")
        expected_rows = [
            row for row in fixture["rows"]
            if row["tab"] == "Extraction Audit"
        ]
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
                    reason="Derivative overview table with WKN, type, strike/cap, runtime, performance, target, and stop.",
                    wkns=("MM7PJ4",),
                ),
                MagazineSectionCandidate(
                    issue_id="2026-W03",
                    page=66,
                    section_kind=MagazineSectionKind.AKTIONAER_DEPOT_TRANSACTIONS,
                    section_title="Durchgeführte Transaktionen",
                    suggested_sheet="Depot Transactions",
                    priority="high",
                    reason="Publisher model-depot transaction table, including no-transaction weeks.",
                    wkns=(),
                ),
                MagazineSectionCandidate(
                    issue_id="2026-W03",
                    page=80,
                    section_kind=MagazineSectionKind.CHART_CHECK,
                    section_title="Chart Check",
                    suggested_sheet="Chart Check",
                    priority="medium",
                    reason="Chart-check section with multiple stocks, technical context, and recommendation metadata.",
                    wkns=("A0HL8N",),
                ),
            ),
        )

        actual_rows = [
            {
                "tab": row["tab"],
                "rowKind": row["rowKind"],
                "page": row["page"],
                "values": row["values"],
                "warnings": row["warnings"],
            }
            for row in plan.to_dict()["rows"]
        ]

        self.assertEqual(actual_rows, expected_rows)
        self.assertEqual(
            {row["values"][6] for row in actual_rows},
            {
                "review_for_Derivative Tips",
                "review_for_Depot Transactions",
                "review_for_Chart Check",
            },
        )

    def test_section_inventory_does_not_fan_out_index_or_table_wkns_to_stock_rows(self) -> None:
        plan = build_workbook_export_plan(
            pdf_path=Path("data/private/issues/DA_2026_03.pdf"),
            issue_id="2026-W03",
            stock_update_date="2026-05-17",
            section_inventory=(
                MagazineSectionCandidate(
                    issue_id="2026-W03",
                    page=86,
                    section_kind=MagazineSectionKind.QUICK_CHECK,
                    section_title="Aktien im Quick-Check",
                    suggested_sheet="Stock Quickcheck",
                    priority="medium",
                    reason="Broad table context with WKNs only.",
                    wkns=("A0HL8N", "A1EWWW", "A2QP7J"),
                ),
            ),
        )

        result = plan.to_dict()

        self.assertEqual(result["rowsByTab"], {"Extraction Audit": 1})
        self.assertTrue(all(row["tab"] != "Stocks" for row in result["rows"]))

    def test_routes_quickcheck_rows_to_dedicated_tab(self) -> None:
        plan = build_workbook_export_plan(
            pdf_path=Path("data/private/issues/DA_2026_03.pdf"),
            issue_id="2026-W03",
            quickcheck_rows=(
                QuickcheckRow(
                    issue_id="2026-W03",
                    page=90,
                    instrument="2G Energy",
                    wkn="A0HL8N",
                    current_price="36,70 EUR",
                    recommendation_price="34,80 EUR",
                    recommended_issue="52/25",
                    performance_since_recommendation="+5,5 %",
                    target="52,50 EUR",
                    stop="27,50 EUR !",
                    comment="Die Aktie hat zum Jahresstart ihren Aufwärtstrend wieder aufgenommen.",
                ),
            ),
        )

        row = plan.to_dict()["rows"][0]

        self.assertEqual(row["tab"], "Stock Quickcheck")
        self.assertEqual(row["rowKind"], "stock_quickcheck")
        self.assertEqual(row["values"][2], "2G Energy")
        self.assertEqual(row["values"][3], "A0HL8N")
        self.assertEqual(row["values"][4], "+5,5 %")
        self.assertIn("target=52,50 EUR", row["values"][5])
        self.assertIn("recommended=34,80 EUR", row["values"][5])
        self.assertIn("Aufwärtstrend", row["values"][6])
        self.assertEqual(len(row["values"]), len(headers_for("Stock Quickcheck")))


class _SingleStockExtractor:
    extractor_name = "stub"

    def extract_pages(self, _pdf_path: Path) -> tuple[RawPageText, ...]:
        return (
            RawPageText(
                page_number=1,
                text="\n".join(
                    (
                        "Aktie",
                        "Banco Sabadell",
                        "Akt. Kurs",
                        "3,33 €",
                        "WKN",
                        "A0MRD4",
                        "Ziel",
                        "4,30 €",
                    )
                ),
            ),
        )


if __name__ == "__main__":
    unittest.main()
