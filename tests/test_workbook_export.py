import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from stock_analyst.chart_check import ChartCheckRow
from stock_analyst.dividend_strategy import DividendStrategyRow
from stock_analyst.depot_tables import DepotPositionRow, DepotTransactionRow
from stock_analyst.derivative_tables import DerivativeOverviewRow
from stock_analyst.extraction import RawPageText
from stock_analyst.google_access import AKTUELL_DERIVATIVE_HEADERS, DEFAULT_SHEET_TABS
from stock_analyst.processing_policy import MagazineProcessingPolicy
from stock_analyst.recommendation_cards import RecommendationCard
from stock_analyst.quickcheck import QuickcheckRow
from stock_analyst.schemas import InstrumentType, ReviewStatus
from stock_analyst.section_inventory import (
    MagazineSectionCandidate,
    MagazineSectionKind,
)
from stock_analyst.workbook_export import (
    WorkbookDraftRow,
    WorkbookExportPlan,
    WorkbookExportPlanError,
    build_workbook_export_plan,
    build_workbook_export_plan_from_pdf,
)


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "workbook_export"


def headers_for(tab: str) -> tuple[str, ...]:
    for spec in DEFAULT_SHEET_TABS:
        if spec.title == tab:
            return spec.headers
    raise AssertionError(f"unknown tab: {tab}")


def value_for(row: dict[str, object], header: str, *, tab: str = "Stocks") -> str:
    values = row["values"]
    assert isinstance(values, list)
    return values[headers_for(tab).index(header)]


def load_workbook_fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


class WorkbookExportPlanTest(unittest.TestCase):
    def test_plan_rejects_stale_row_width_before_serialization(self) -> None:
        with self.assertRaisesRegex(
            WorkbookExportPlanError,
            r"workbook export row for Stocks must contain 20 values, got 19",
        ):
            WorkbookExportPlan(
                issue_id="2026-W03",
                pdf_path=Path("data/private/issues/DA_2026_03.pdf"),
                external_services_enabled=False,
                google_writes_enabled=False,
                rows=(
                    WorkbookDraftRow(
                        tab="Stocks",
                        row_kind="stock_recommendation",
                        source_id="card:2026-W03:p22:A0MRD4:test",
                        issue_id="2026-W03",
                        page=22,
                        values=tuple("" for _ in range(len(headers_for("Stocks")) - 1)),
                    ),
                ),
            )

    def test_plan_rejects_rows_for_inactive_workbook_tabs(self) -> None:
        with self.assertRaisesRegex(
            WorkbookExportPlanError,
            r"workbook export row targets unsupported tab 'Recommendation Cards'",
        ):
            WorkbookExportPlan(
                issue_id="2026-W03",
                pdf_path=Path("data/private/issues/DA_2026_03.pdf"),
                external_services_enabled=False,
                google_writes_enabled=False,
                rows=(
                    WorkbookDraftRow(
                        tab="Recommendation Cards",
                        row_kind="recommendation_card",
                        source_id="card:2026-W03:p22:A0MRD4:test",
                        issue_id="2026-W03",
                        page=22,
                        values=tuple("" for _ in range(15)),
                    ),
                ),
            )

    def test_plan_rejects_rows_for_layout_only_dashboard(self) -> None:
        with self.assertRaisesRegex(
            WorkbookExportPlanError,
            r"workbook export row targets layout-only tab 'Navigation Dashboard'",
        ):
            WorkbookExportPlan(
                issue_id="2026-W03",
                pdf_path=Path("data/private/issues/DA_2026_03.pdf"),
                external_services_enabled=False,
                google_writes_enabled=False,
                rows=(
                    WorkbookDraftRow(
                        tab="Navigation Dashboard",
                        row_kind="dashboard",
                        source_id="dashboard:2026-W03",
                        issue_id="2026-W03",
                        page=0,
                        values=tuple("" for _ in headers_for("Navigation Dashboard")),
                    ),
                ),
            )

    def test_pdf_plan_extracts_text_once_for_all_local_parsers(self) -> None:
        class StubExtractor:
            extractor_name = "stub"

            def __init__(self) -> None:
                self.calls = 0

            def extract_pages(self, _pdf_path: Path) -> tuple[RawPageText, ...]:
                self.calls += 1
                return (
                    RawPageText(
                        page_number=6,
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
        self.assertEqual(result["rowsByTab"], {"Extraction Audit": 1, "Stocks": 1})

    def test_pdf_plan_skips_front_matter_but_keeps_later_explicit_sections(self) -> None:
        class StubExtractor:
            extractor_name = "stub"

            def extract_pages(self, _pdf_path: Path) -> tuple[RawPageText, ...]:
                return (
                    RawPageText(
                        page_number=2,
                        text="\n".join(("Aktie", "Front Matter AG", "WKN", "ABC123")),
                    ),
                    RawPageText(
                        page_number=6,
                        text="\n".join(("Aktie", "Useful AG", "WKN", "USE123")),
                    ),
                    RawPageText(
                        page_number=7,
                        text="\n".join(("Statistik", "Die Woche im Überblick", "Indizes")),
                    ),
                    RawPageText(
                        page_number=8,
                        text="\n".join(("Aktie", "Back Matter AG", "WKN", "BCK123")),
                    ),
                )

        with TemporaryDirectory() as directory:
            pdf = Path(directory) / "DA_2026_03.pdf"
            pdf.write_bytes(b"%PDF-1.7\nprivate synthetic fixture")

            plan = build_workbook_export_plan_from_pdf(pdf, extractor=StubExtractor())

        result = plan.to_dict()
        stock_rows = [row for row in result["rows"] if row["tab"] == "Stocks"]

        self.assertEqual(len(stock_rows), 2)
        self.assertEqual(stock_rows[0]["values"][0], "Useful AG")
        self.assertEqual(stock_rows[0]["page"], 6)
        self.assertEqual(stock_rows[1]["values"][0], "Back Matter AG")
        self.assertEqual(stock_rows[1]["page"], 8)
        self.assertNotIn("Front Matter AG", json.dumps(result))

    def test_pdf_plan_routes_layout_table_new_recommendations_to_aktuell(self) -> None:
        class StubExtractor:
            extractor_name = "stub"

            def extract_pages(self, _pdf_path: Path) -> tuple[RawPageText, ...]:
                return (
                    RawPageText(
                        page_number=24,
                        text="\n".join(
                            (
                                "Aktie",
                                "Existing AG",
                                "Akt. Kurs",
                                "10,00 €",
                                "WKN",
                                "EXIST1",
                                "Ziel",
                                "15,00 €",
                                "Stopp",
                                "8,00 €",
                                "Neuempfehlung",
                            )
                        ),
                        layout_text="\n".join(
                            (
                                "Top-Empfehlungen",
                                "Unternehmen    WKN    Aktueller Kurs    Marktkap.    DR*    KUV    KGV    Empf.-    Ziel    Stopp    Chance    Risiko",
                                "Alpha Engineering AG    ENG001    81,25 €    3,0    3,5    0,5    12    Neuempfehlung    108,00 €    63,00 €    •••••    •••••",
                                "Beta Energy AG          NRG002    42,50 €    9,5    0,0    1,0    17    Neuempfehlung    55,00 €     33,00 €    •••••    •••••",
                                "Gamma Insurance AG      INS003    112,00 €   28,0   3,6    0,5    10    Neuempfehlung    136,00 €    93,00 €    •••••    •••••",
                            )
                        ),
                    ),
                )

        with TemporaryDirectory() as directory:
            pdf = Path(directory) / "DA_2026_30.pdf"
            pdf.write_bytes(b"%PDF-1.7\nprivate synthetic fixture")
            plan = build_workbook_export_plan_from_pdf(pdf, extractor=StubExtractor())

        result = plan.to_dict()
        stock_rows = [row for row in result["rows"] if row["tab"] == "Stocks"]
        aktuell_rows = [row for row in result["rows"] if row["tab"] == "Aktuell"]
        self.assertEqual(
            [value_for(row, "Company") for row in stock_rows],
            ["Existing AG", "Alpha Engineering AG", "Beta Energy AG", "Gamma Insurance AG"],
        )
        self.assertEqual(
            [value_for(row, "Recommendation") for row in stock_rows],
            ["new_recommendation"] * 4,
        )
        self.assertEqual(
            [value_for(row, "Company", tab="Aktuell") for row in aktuell_rows],
            ["Existing AG", "Alpha Engineering AG", "Beta Energy AG", "Gamma Insurance AG"],
        )
        self.assertEqual(
            [value_for(row, "Action", tab="Aktuell") for row in aktuell_rows],
            ["Buy"] * 4,
        )

    def test_pdf_plan_routes_all_explicit_dax_actions_to_aktuell(self) -> None:
        class StubExtractor:
            extractor_name = "stub"

            def extract_pages(self, _pdf_path: Path) -> tuple[RawPageText, ...]:
                return (
                    RawPageText(
                        page_number=26,
                        text="DAX overview",
                        layout_text="\n".join(
                            (
                                "Unternehmen    WKN    Aktueller Kurs    Ziel    Stopp",
                                "Alpha AG    ALPHA1    10,00 EUR    15,00 EUR    8,00 EUR",
                                "Beta AG    BETA01    20,00 EUR    –    –",
                                "Gamma AG    GAMMA1    30,00 EUR    40,00 EUR    20,00 EUR",
                                "Delta AG    DELTA1    40,00 EUR    –    –",
                            )
                        ),
                    ),
                    RawPageText(
                        page_number=27,
                        text="DAX overview",
                        layout_text="\n".join(
                            (
                                "Einschätzung    Kommentar    Unternehmen",
                                "Kaufen    Solide Perspektive    Alpha AG",
                                "Verkaufen    Keine Kaufargumente    Beta AG",
                                "Halten    Abwarten auf Zahlen    Gamma AG",
                                "Abwarten    Beobachten    Delta AG",
                            )
                        ),
                    ),
                )

        with TemporaryDirectory() as directory:
            pdf = Path(directory) / "DA_2026_30.pdf"
            pdf.write_bytes(b"%PDF-1.7\nprivate synthetic fixture")
            plan = build_workbook_export_plan_from_pdf(pdf, extractor=StubExtractor())

        rows = plan.to_dict()["rows"]
        stock_rows = [row for row in rows if row["tab"] == "Stocks"]
        aktuell_rows = [row for row in rows if row["tab"] == "Aktuell"]
        self.assertEqual(
            [value_for(row, "Recommendation") for row in stock_rows],
            ["new_recommendation", "verkauft", "hold", "wait"],
        )
        self.assertEqual(
            [value_for(row, "Company", tab="Aktuell") for row in aktuell_rows],
            ["Alpha AG", "Beta AG", "Gamma AG", "Delta AG"],
        )
        self.assertEqual(
            [value_for(row, "Action", tab="Aktuell") for row in aktuell_rows],
            ["Buy", "Sell", "Hold", "Wait"],
        )
        self.assertEqual(
            [value_for(row, "Issue:Page") for row in stock_rows],
            ["2026-W30:26 | 2026-W30:27"] * 4,
        )
        self.assertEqual(
            [value_for(row, "Source", tab="Aktuell") for row in aktuell_rows],
            ["2026-W30:26 | 2026-W30:27"] * 4,
        )

    def test_pdf_plan_surfaces_paired_table_mismatch_in_extraction_audit(self) -> None:
        class StubExtractor:
            extractor_name = "stub"

            def extract_pages(self, _pdf_path: Path) -> tuple[RawPageText, ...]:
                return (
                    RawPageText(
                        page_number=40,
                        text="Synthetic value table",
                        layout_text="\n".join(
                            (
                                "Unternehmen    WKN    Aktueller Kurs    Ziel    Stopp",
                                "Alpha AG    ALPHA1    10,00 EUR    15,00 EUR    8,00 EUR",
                            )
                        ),
                    ),
                    RawPageText(
                        page_number=41,
                        text="Synthetic action table",
                        layout_text="\n".join(
                            (
                                "Einschätzung    Kommentar    Unternehmen",
                                "Kaufen    Synthetischer Hinweis    Different AG",
                            )
                        ),
                    ),
                )

        with TemporaryDirectory() as directory:
            pdf = Path(directory) / "DA_2026_40.pdf"
            pdf.write_bytes(b"%PDF-1.7\nprivate synthetic fixture")
            plan = build_workbook_export_plan_from_pdf(pdf, extractor=StubExtractor())

        exception_rows = [
            row
            for row in plan.to_dict()["rows"]
            if row["rowKind"] == "paired_action_table_candidate_exception"
        ]
        self.assertEqual(len(exception_rows), 1)
        exception_row = exception_rows[0]
        self.assertEqual(exception_row["tab"], "Extraction Audit")
        self.assertEqual(
            exception_row["sourceBlock"],
            "paired_action_table_candidate_exception",
        )
        self.assertEqual(exception_row["values"][1], "2026-W40:40 | 2026-W40:41")
        self.assertIn("paired_table_name_mismatch", exception_row["values"][4])
        self.assertIn(
            "paired_action_table_candidate_exception=paired_table_name_mismatch",
            exception_row["warnings"],
        )

    def test_pdf_plan_can_still_use_strict_statistics_cutoff_policy(self) -> None:
        class StubExtractor:
            extractor_name = "stub"

            def extract_pages(self, _pdf_path: Path) -> tuple[RawPageText, ...]:
                return (
                    RawPageText(page_number=6, text="\n".join(("Aktie", "Useful AG", "WKN", "USE123"))),
                    RawPageText(page_number=7, text="\n".join(("Statistik", "Die Woche im Überblick", "Indizes"))),
                    RawPageText(page_number=8, text="\n".join(("Aktie", "Back Matter AG", "WKN", "BCK123"))),
                )

        with TemporaryDirectory() as directory:
            pdf = Path(directory) / "DA_2026_03.pdf"
            pdf.write_bytes(b"%PDF-1.7\nprivate synthetic fixture")

            plan = build_workbook_export_plan_from_pdf(
                pdf,
                extractor=StubExtractor(),
                processing_policy=MagazineProcessingPolicy(),
            )

        stock_rows = [row for row in plan.to_dict()["rows"] if row["tab"] == "Stocks"]

        self.assertEqual(len(stock_rows), 1)
        self.assertEqual(stock_rows[0]["values"][0], "Useful AG")
        self.assertNotIn("Back Matter AG", json.dumps(plan.to_dict()))

    def test_pdf_plan_uses_filename_issue_date_for_stock_update_date(self) -> None:
        class StubExtractor:
            extractor_name = "stub"

            def extract_pages(self, _pdf_path: Path) -> tuple[RawPageText, ...]:
                return (
                    RawPageText(
                        page_number=6,
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
        row = next(candidate for candidate in result["rows"] if candidate["tab"] == "Stocks")
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
        self.assertEqual(stock_tab["headerRow"], 1)
        self.assertEqual(stock_tab["frozenRows"], 1)
        self.assertEqual(stock_tab["frozenColumns"], 2)
        self.assertEqual(stock_tab["tableStartsAt"], "A1")
        self.assertEqual(stock_tab["parserStatus"], "parser_backed")
        self.assertTrue(stock_tab["layoutNotes"])
        self.assertEqual(stock_tab["metadataCells"], [])
        self.assertEqual(row["values"][0], "Banco Sabadell")
        self.assertEqual(row["values"][1], "A0MRD4")
        self.assertEqual(value_for(row, "Target"), "4,30 EUR")
        self.assertEqual(value_for(row, "Stop"), "2,70 EUR")
        self.assertEqual(value_for(row, "Current price"), "3,33 EUR")
        self.assertEqual(value_for(row, "Market Cap"), "16,8 Mrd. EUR")
        self.assertEqual(value_for(row, "Dividend Yield"), "18,6 %")
        self.assertEqual(value_for(row, "Recommendation"), "new_recommendation")
        self.assertEqual(value_for(row, "Held since"), "")
        self.assertEqual(value_for(row, "P/S Ratio 26e"), "")
        self.assertEqual(value_for(row, "P/E Ratio 26e"), "10")
        self.assertEqual(value_for(row, "Chance"), "★★★★★")
        self.assertEqual(value_for(row, "Risk"), "★★★★★")
        self.assertEqual(value_for(row, "Insider Activity"), "")
        self.assertEqual(value_for(row, "Issue:Page"), "2026-W03:22")
        self.assertEqual(value_for(row, "Enrichment status"), "not_started")
        self.assertEqual(value_for(row, "date updated"), "2026-05-17")
        self.assertIn("manual_review_required", row["warnings"][0])

    def test_plan_emits_latest_issue_recommendation_tab_from_stock_rows(self) -> None:
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
                    dividend_yield="18,6 %",
                ),
            ),
        )

        latest_row = next(
            row
            for row in plan.to_dict()["rows"]
            if row["tab"] == "Aktuell"
        )

        self.assertEqual(value_for(latest_row, "Source", tab="Aktuell"), "2026-W03:22")
        self.assertEqual(value_for(latest_row, "Action", tab="Aktuell"), "Buy")
        self.assertEqual(value_for(latest_row, "Company", tab="Aktuell"), "Banco Sabadell")
        self.assertEqual(value_for(latest_row, "WKN", tab="Aktuell"), "A0MRD4")
        self.assertEqual(
            value_for(latest_row, "Price at Print", tab="Aktuell"),
            "3,33 EUR",
        )
        self.assertEqual(value_for(latest_row, "Chance", tab="Aktuell"), "★★★★★")
        self.assertEqual(value_for(latest_row, "Risk", tab="Aktuell"), "★★★★★")
        self.assertEqual(value_for(latest_row, "Source", tab="Aktuell"), "2026-W03:22")
        self.assertEqual(
            value_for(latest_row, "Review status", tab="Aktuell"),
            ReviewStatus.NEEDS_REVIEW.value,
        )

    def test_plan_emits_hold_stock_in_latest_issue_reviewer_rows(self) -> None:
        plan = build_workbook_export_plan(
            pdf_path=Path("data/private/issues/DA_2026_30.pdf"),
            issue_id="2026-W30",
            stock_update_date="2026-07-17",
            recommendation_cards=(
                RecommendationCard(
                    issue_id="2026-W30",
                    page=40,
                    instrument_name="Example Automaker",
                    instrument_type=InstrumentType.STOCK,
                    wkn="A00002",
                    current_price="72,12 EUR",
                    target=None,
                    stop=None,
                    chance=4,
                    risk=3,
                    recommendation_status="hold",
                ),
            ),
        )

        rows = plan.to_dict()["rows"]
        stock_row = next(row for row in rows if row["tab"] == "Stocks")
        latest_row = next(row for row in rows if row["tab"] == "Aktuell")

        self.assertEqual(value_for(stock_row, "Recommendation"), "hold")
        self.assertEqual(value_for(latest_row, "Action", tab="Aktuell"), "Hold")
        self.assertEqual(value_for(latest_row, "Source", tab="Aktuell"), "2026-W30:40")

    def test_plan_groups_latest_issue_buy_sell_recommendations_by_asset_class(self) -> None:
        plan = build_workbook_export_plan(
            pdf_path=Path("data/private/issues/DA_2026_03.pdf"),
            issue_id="2026-W03",
            stock_update_date="2026-05-17",
            recommendation_cards=(
                RecommendationCard(
                    issue_id="2026-W03",
                    page=22,
                    instrument_name="Stock Buy AG",
                    instrument_type=InstrumentType.STOCK,
                    wkn="STOCK1",
                    current_price="10,00 EUR",
                    target="12,00 EUR",
                    stop="8,00 EUR",
                    chance=4,
                    risk=2,
                    recommendation_status="new_recommendation",
                ),
                RecommendationCard(
                    issue_id="2026-W03",
                    page=23,
                    instrument_name="Call on Stock Buy AG",
                    instrument_type=InstrumentType.DERIVATIVE,
                    wkn="DERIV1",
                    current_price="2,00 EUR",
                    target="3,00 EUR",
                    stop="1,00 EUR",
                    chance=3,
                    risk=5,
                    recommendation_status="new_recommendation",
                ),
                RecommendationCard(
                    issue_id="2026-W03",
                    page=24,
                    instrument_name="Crypto Buy",
                    instrument_type=InstrumentType.CRYPTO,
                    wkn="CRYPT1",
                    current_price="100,00 USD",
                    target=None,
                    stop=None,
                    chance=None,
                    risk=None,
                    recommendation_status="new_recommendation",
                ),
                RecommendationCard(
                    issue_id="2026-W03",
                    page=25,
                    instrument_name="ETF Sell",
                    instrument_type=InstrumentType.ETF,
                    wkn="ETF001",
                    current_price="50,00 EUR",
                    target=None,
                    stop=None,
                    chance=None,
                    risk=None,
                    recommendation_status="sold",
                ),
                RecommendationCard(
                    issue_id="2026-W03",
                    page=26,
                    instrument_name="Stock Hold AG",
                    instrument_type=InstrumentType.STOCK,
                    wkn="STOCK2",
                    current_price="10,00 EUR",
                    target=None,
                    stop=None,
                    chance=None,
                    risk=None,
                    recommendation_status="follow_up",
                ),
            ),
        )

        latest_rows = [row for row in plan.to_dict()["rows"] if row["tab"] == "Aktuell"]

        self.assertEqual(len(latest_rows), 4)
        self.assertEqual(
            [row["rowKind"] for row in latest_rows],
            [
                "latest_issue_stock_buy_sell_recommendation",
                "latest_issue_derivative_buy_sell_recommendation",
                "latest_issue_crypto_buy_sell_recommendation",
                "latest_issue_etf_buy_sell_recommendation",
            ],
        )
        self.assertEqual(
            [
                row["values"][AKTUELL_DERIVATIVE_HEADERS.index("Action")]
                if "derivative" in str(row["rowKind"])
                else value_for(row, "Action", tab="Aktuell")
                for row in latest_rows
            ],
            ["Buy", "Buy", "Buy", "Sell"],
        )
        derivative_row = next(
            row
            for row in latest_rows
            if row["rowKind"] == "latest_issue_derivative_buy_sell_recommendation"
        )
        self.assertEqual(
            derivative_row["values"][:3],
            ["DERIV1", "Call on Stock Buy AG", "Buy"],
        )
        self.assertEqual(
            derivative_row["values"][AKTUELL_DERIVATIVE_HEADERS.index("Issue:Page")],
            "2026-W03:23",
        )
        self.assertTrue(all(row["requiresManualReview"] for row in latest_rows))
        self.assertTrue(all(not row["exportable"] for row in latest_rows))

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

    def test_stock_price_cells_keep_thousands_and_strip_notes(self) -> None:
        plan = build_workbook_export_plan(
            pdf_path=Path("data/private/issues/DA_2026_03.pdf"),
            issue_id="2026-W03",
            stock_update_date="2026-05-17",
            recommendation_cards=(
                RecommendationCard(
                    issue_id="2026-W03",
                    page=22,
                    instrument_name="Large Price AG",
                    instrument_type=InstrumentType.STOCK,
                    wkn="ABC123",
                    current_price="1.234,56 EUR (Xetra)",
                    target="2.500,00 EUR Ziel",
                    stop="987,65 EUR !",
                    chance=None,
                    risk=None,
                    recommendation_status="new_recommendation",
                ),
            ),
        )

        stock_row = next(row for row in plan.to_dict()["rows"] if row["tab"] == "Stocks")

        self.assertEqual(value_for(stock_row, "Current price"), "1.234,56 EUR")
        self.assertEqual(value_for(stock_row, "Target"), "2.500,00 EUR")
        self.assertEqual(value_for(stock_row, "Stop"), "987,65 EUR")

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

        self.assertEqual(stock_row["values"][6], "18,6 %")
        self.assertNotIn("2023", stock_row["values"][6])

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
        self.assertEqual(row["values"][1], "Baidu")
        self.assertEqual(row["values"][2], "Call")
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

        self.assertEqual(plan.to_dict()["rows"], [])

    def test_derivative_tip_fixtures_cover_option_and_discount_call_shapes(self) -> None:
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

        self.assertEqual(len(actual_rows), 2)
        self.assertEqual(actual_rows[0]["values"][1], "Baidu")
        self.assertEqual(actual_rows[0]["values"][2], "Call")
        self.assertEqual(actual_rows[0]["values"][10], "2,15 EUR")
        self.assertEqual(actual_rows[0]["values"][11], "2,15 EUR")
        self.assertEqual(actual_rows[1]["values"][1], "Gold")
        self.assertEqual(actual_rows[1]["values"][2], "Discount-Call")
        for row in actual_rows:
            self.assertEqual(len(row["values"]), len(headers_for("Derivative Tips")))
            self.assertEqual(row["values"][-3], ReviewStatus.NEEDS_REVIEW.value)
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
                    recommendation="Tauschen",
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
        self.assertEqual(rows["Derivative Tips"]["values"][0], "Bayer")
        self.assertEqual(rows["Derivative Tips"]["values"][2], "Discount-Call")
        self.assertEqual(rows["Derivative Tips"]["values"][12], "+88,3 %")
        self.assertEqual(len(rows["Derivative Tips"]["values"]), len(headers_for("Derivative Tips")))
        self.assertEqual(rows["Aktuell"]["values"][2], "Sell")
        self.assertEqual(rows["Aktuell"]["values"][12], "")
        self.assertEqual(rows["Aktuell"]["values"][16], "Tauschen")
        self.assertEqual(rows["AKTIONAER Depot"]["rowKind"], "aktionaer_depot_position")
        self.assertEqual(rows["AKTIONAER Depot"]["values"][0], "Amazon")
        self.assertEqual(len(rows["AKTIONAER Depot"]["values"]), len(headers_for("AKTIONAER Depot")))
        self.assertEqual(rows["Depot Transactions"]["rowKind"], "depot_transaction")
        self.assertEqual(rows["Depot Transactions"]["values"][0], "Keine Transaktionen")
        self.assertEqual(
            len(rows["Depot Transactions"]["values"]),
            len(headers_for("Depot Transactions")),
        )

    def test_routes_derivative_hold_and_stop_literals_to_aktuell(self) -> None:
        def derivative_row(wkn: str, recommendation: str) -> DerivativeOverviewRow:
            return DerivativeOverviewRow(
                issue_id="2026-W40",
                page=60,
                underlying=f"Synthetic {wkn}",
                product=f"Synthetic {wkn}",
                direction="Call",
                wkn=wkn,
                issuer="Synthetic Issuer",
                ratio="1,00",
                strike_cap="10,00 EUR",
                omega_hebel="2,0",
                runtime="31.12.26",
                entry_price="1,00 EUR",
                current_price="1,20 EUR",
                performance_since_recommendation="+20,0 %",
                target="1,50 EUR",
                stop="0,80 EUR",
                recommendation=recommendation,
            )

        plan = build_workbook_export_plan(
            pdf_path=Path("data/private/issues/DA_2026_40.pdf"),
            issue_id="2026-W40",
            derivative_overview=(
                derivative_row("HOLD01", "Dabei- bleiben"),
                derivative_row("STOP01", "Ausgestoppt"),
            ),
            stock_update_date="2026-09-30",
        )

        aktuell_rows = [
            row for row in plan.to_dict()["rows"] if row["tab"] == "Aktuell"
        ]
        self.assertEqual(
            [
                row["values"][AKTUELL_DERIVATIVE_HEADERS.index("Action")]
                for row in aktuell_rows
            ],
            ["Hold", "Sell"],
        )
        self.assertEqual(
            [
                row["values"][AKTUELL_DERIVATIVE_HEADERS.index("Reviewer note")]
                for row in aktuell_rows
            ],
            ["Dabei- bleiben", "Ausgestoppt"],
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
        self.assertEqual(row["values"][0], "Banco Sabadell")
        self.assertEqual(row["values"][5], "18,6 %")
        self.assertTrue(row["values"][-1])
        self.assertEqual(row["reviewStatus"], ReviewStatus.NEEDS_REVIEW.value)
        self.assertEqual(headers_for("Dividend Focus")[7], "Payouts per year")

    def test_dividend_focus_fixtures_cover_high_yield_decision_fields(self) -> None:
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

        self.assertEqual(len(actual_rows), 2)
        self.assertEqual(actual_rows[0]["values"][0], "Banco Sabadell")
        self.assertEqual(actual_rows[0]["values"][7], "2")
        self.assertEqual(actual_rows[0]["values"][8], "14.04.26")
        self.assertEqual(actual_rows[0]["values"][9], "17.04.26")
        for row in actual_rows:
            self.assertEqual(len(row["values"]), len(headers_for("Dividend Focus")))
            self.assertIn("%", row["values"][5])
            self.assertTrue(all(value is not None for value in row["values"]))

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
            self.assertTrue(all(value is not None for value in row["values"]))

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
        self.assertEqual(row["values"][2], "derivative_tips_overview")
        self.assertEqual(row["values"][3], "warning")
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
                    suggested_sheet="Stocks",
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
            {row["values"][5] for row in actual_rows},
            {
                "review_for_Derivative Tips",
                "review_for_Depot Transactions",
                "review_for_Stocks",
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
                    suggested_sheet="Stocks",
                    priority="medium",
                    reason="Broad table context with WKNs only.",
                    wkns=("A0HL8N", "A1EWWW", "A2QP7J"),
                ),
            ),
        )

        result = plan.to_dict()

        self.assertEqual(result["rowsByTab"], {"Extraction Audit": 1})
        self.assertTrue(all(row["tab"] != "Stocks" for row in result["rows"]))

    def test_routes_quickcheck_rows_to_stock_tab_only(self) -> None:
        plan = build_workbook_export_plan(
            pdf_path=Path("data/private/issues/DA_2026_03.pdf"),
            issue_id="2026-W03",
            stock_update_date="2026-05-17",
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

        rows = plan.to_dict()["rows"]
        stock_row = next(row for row in rows if row["tab"] == "Stocks")

        self.assertEqual(stock_row["rowKind"], "stock_quickcheck_summary")
        self.assertEqual(value_for(stock_row, "Company"), "2G Energy")
        self.assertEqual(value_for(stock_row, "WKN"), "A0HL8N")
        self.assertEqual(value_for(stock_row, "Current price"), "36,70 EUR")
        self.assertEqual(value_for(stock_row, "Target"), "52,50 EUR")
        self.assertEqual(value_for(stock_row, "Stop"), "27,50 EUR")
        self.assertEqual(value_for(stock_row, "Performance since Recommendation"), "+5,5 %")
        self.assertEqual(value_for(stock_row, "Recommendation"), "hold")
        self.assertEqual(value_for(stock_row, "Held since"), "52/25")
        self.assertFalse(any(row["tab"] == "Aktuell" for row in rows))
        self.assertEqual(value_for(stock_row, "date updated"), "2026-05-17")
        self.assertEqual(len(stock_row["values"]), len(headers_for("Stocks")))
        self.assertFalse(any(row["tab"] == "Stock Quickcheck" for row in rows))

    def test_consolidates_duplicate_stock_mentions_by_wkn(self) -> None:
        plan = build_workbook_export_plan(
            pdf_path=Path("data/private/issues/DA_2026_03.pdf"),
            issue_id="2026-W03",
            stock_update_date="2026-05-17",
            recommendation_cards=(
                RecommendationCard(
                    issue_id="2026-W03",
                    page=42,
                    instrument_name="Tesla",
                    instrument_type=InstrumentType.STOCK,
                    wkn="A1CX3T",
                    current_price="381,15 EUR",
                    target="480,00 EUR",
                    stop="295,00 EUR",
                    chance=4,
                    risk=3,
                    recommendation_status="follow_up",
                    market_cap="1,27 Bio. EUR",
                    performance_since_recommendation="-2,2 %",
                    recommended_issue="02/2026 30.12.25",
                ),
            ),
            quickcheck_rows=(
                QuickcheckRow(
                    issue_id="2026-W03",
                    page=90,
                    instrument="Tesla",
                    wkn="A1CX3T",
                    current_price="371,90 EUR",
                    recommendation_price="398,00 EUR",
                    recommended_issue="02/26",
                    performance_since_recommendation="-6,6 %",
                    target="480,00 EUR",
                    stop="295,00 EUR",
                    comment="Vom Rekordhoch im Dezember hat die Aktie zuletzt korrigiert.",
                ),
            ),
        )

        stock_rows = [row for row in plan.to_dict()["rows"] if row["tab"] == "Stocks"]

        self.assertEqual(len(stock_rows), 1)
        values = stock_rows[0]["values"]
        row = stock_rows[0]
        self.assertEqual(value_for(row, "WKN"), "A1CX3T")
        self.assertEqual(value_for(row, "Current price"), "371,90 EUR")
        self.assertEqual(value_for(row, "Target"), "480,00 EUR")
        self.assertEqual(value_for(row, "Stop"), "295,00 EUR")
        self.assertEqual(value_for(row, "Performance since Recommendation"), "-6,6 %")
        self.assertEqual(value_for(row, "Recommendation"), "hold")
        self.assertEqual(value_for(row, "Held since"), "02/2026")
        self.assertFalse(any(row["tab"] == "Aktuell" for row in plan.to_dict()["rows"]))
        self.assertEqual(value_for(row, "Issue:Page"), "2026-W03:42 | 2026-W03:90")

    def test_consolidates_wkn_less_stock_mentions_by_normalized_name(self) -> None:
        plan = build_workbook_export_plan(
            pdf_path=Path("data/private/issues/DA_2026_03.pdf"),
            issue_id="2026-W03",
            stock_update_date="2026-05-17",
            quickcheck_rows=(
                QuickcheckRow(
                    issue_id="2026-W03",
                    page=90,
                    instrument="ACME Energy",
                    wkn="",
                    current_price="10,00 EUR",
                    recommendation_price="8,00 EUR",
                    recommended_issue="01/26",
                    performance_since_recommendation="+25,0 %",
                    target="12,00 EUR",
                    stop="7,00 EUR",
                    comment="Quick-check comment.",
                ),
                QuickcheckRow(
                    issue_id="2026-W03",
                    page=91,
                    instrument="Acme-Energy",
                    wkn="",
                    current_price="10,50 EUR",
                    recommendation_price="",
                    recommended_issue="",
                    performance_since_recommendation="+31,3 %",
                    target="12,50 EUR",
                    stop="",
                    comment="Follow-up wording.",
                ),
            ),
        )

        stock_rows = [row for row in plan.to_dict()["rows"] if row["tab"] == "Stocks"]

        self.assertEqual(len(stock_rows), 1)
        row = stock_rows[0]
        self.assertEqual(value_for(row, "Company"), "ACME Energy")
        self.assertEqual(value_for(row, "Current price"), "10,50 EUR")
        self.assertEqual(value_for(row, "Target"), "12,50 EUR")
        self.assertFalse(any(row["tab"] == "Aktuell" for row in plan.to_dict()["rows"]))
        self.assertEqual(value_for(row, "Issue:Page"), "2026-W03:90 | 2026-W03:91")

    def test_routes_chart_check_rows_to_stock_tab_only(self) -> None:
        plan = build_workbook_export_plan(
            pdf_path=Path("data/private/issues/DA_2026_03.pdf"),
            issue_id="2026-W03",
            chart_check_rows=(
                ChartCheckRow(
                    issue_id="2026-W03",
                    page=80,
                    instrument="Airbus",
                    wkn="938914",
                    sector="Luft- und Raumfahrt (NLD)",
                    signal="Luft- und Raumfahrt (NLD); Der Trend zeigt nach oben.",
                    current_price="199,00 EUR",
                    recommendation_price="278,00 EUR",
                    recommended_issue="37/25 03.09.25",
                    performance_since_recommendation="+39,7 %",
                    target="310,00 EUR",
                    stop="224,00 EUR",
                    dividend_yield="2026-05-27",
                    next_report_date="Quartalszahlen 16.01.26",
                    high_52w="284,50 EUR",
                    low_52w="114,00 EUR",
                    performance_1y="+34,1 %",
                    performance_5y="+224,8 %",
                ),
            ),
        )

        rows = plan.to_dict()["rows"]
        stock_row = next(row for row in rows if row["tab"] == "Stocks")

        self.assertEqual(stock_row["rowKind"], "stock_chart_check_summary")
        self.assertEqual(value_for(stock_row, "Current price"), "199,00 EUR")
        self.assertEqual(value_for(stock_row, "Target"), "310,00 EUR")
        self.assertEqual(value_for(stock_row, "Stop"), "224,00 EUR")
        self.assertEqual(value_for(stock_row, "Dividend Yield"), "")
        self.assertEqual(value_for(stock_row, "Performance since Recommendation"), "+39,7 %")
        self.assertEqual(value_for(stock_row, "Next Report"), "16.01.26")
        self.assertEqual(value_for(stock_row, "Report type"), "Quartalszahlen")
        self.assertEqual(value_for(stock_row, "Recommendation"), "hold")
        self.assertEqual(value_for(stock_row, "Held since"), "37/25")
        self.assertEqual(len(stock_row["values"]), len(headers_for("Stocks")))
        self.assertFalse(any(row["tab"] == "Chart Check" for row in rows))


class _SingleStockExtractor:
    extractor_name = "stub"

    def extract_pages(self, _pdf_path: Path) -> tuple[RawPageText, ...]:
        return (
            RawPageText(
                page_number=6,
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
