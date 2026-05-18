"""Local-only Google Sheets workbook export planning.

This module converts draft extraction artifacts into tab-routed row DTOs.
It does not call Google APIs or write export files; every row remains gated
for manual review.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path
import re
from typing import Iterable, Sequence

from stock_analyst.chart_check import (
    ChartCheckRow,
    extract_chart_check_rows_from_page_lines,
)
from stock_analyst.dividend_strategy import (
    DividendStrategyExtraction,
    DividendStrategyRow,
    extract_dividend_strategy_rows_from_page_lines,
)
from stock_analyst.depot_tables import (
    DepotPositionRow,
    DepotTransactionRow,
    extract_depot_rows_from_page_lines,
)
from stock_analyst.derivative_tables import (
    DerivativeOverviewRow,
    extract_derivative_overview_rows_from_page_lines,
)
from stock_analyst.extraction import RawTextExtractor, extract_pdf_text
from stock_analyst.google_access import DEFAULT_SHEET_TABS
from stock_analyst.intake import guess_issue_date
from stock_analyst.quickcheck import (
    QuickcheckRow,
    extract_quickcheck_rows_from_page_lines,
)
from stock_analyst.recommendation_cards import (
    RecommendationCard,
    RecommendationCardExtraction,
    extract_recommendation_cards_from_pdf,
    extract_recommendation_cards_from_lines,
)
from stock_analyst.schemas import InstrumentType, ReviewStatus
from stock_analyst.section_inventory import (
    MagazineSectionCandidate,
    MagazineSectionInventory,
    extract_section_candidates_from_lines,
)


MANUAL_REVIEW_WARNING = "manual_review_required_before_family_visible_export"


class WorkbookExportPlanError(ValueError):
    """Raised when a local workbook export plan does not match tab schemas."""


@dataclass(frozen=True)
class WorkbookDraftRow:
    tab: str
    row_kind: str
    source_id: str
    issue_id: str
    page: int
    values: tuple[str, ...]
    review_status: ReviewStatus = ReviewStatus.NEEDS_REVIEW
    exportable: bool = False
    warnings: tuple[str, ...] = (MANUAL_REVIEW_WARNING,)
    source_block: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "tab": self.tab,
            "rowKind": self.row_kind,
            "sourceId": self.source_id,
            "issueId": self.issue_id,
            "page": self.page,
            "reviewStatus": self.review_status.value,
            "exportable": self.exportable,
            "requiresManualReview": True,
            "sourceBlock": self.source_block,
            "values": list(self.values),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class WorkbookExportPlan:
    issue_id: str
    pdf_path: Path
    external_services_enabled: bool
    google_writes_enabled: bool
    rows: tuple[WorkbookDraftRow, ...]

    def __post_init__(self) -> None:
        _validate_workbook_rows(self.rows)

    def to_dict(self) -> dict[str, object]:
        rows_by_tab = Counter(row.tab for row in self.rows)
        tabs = _tabs_for_rows(self.rows)
        return {
            "issueId": self.issue_id,
        "privateSourceId": _private_source_id(self.pdf_path, self.issue_id),
            "externalServicesEnabled": self.external_services_enabled,
            "googleWritesEnabled": self.google_writes_enabled,
            "manualReviewRequired": True,
            "approvedRows": 0,
            "rowCount": len(self.rows),
            "rowsByTab": dict(sorted(rows_by_tab.items())),
            "tabs": [
                {
                    "title": title,
                    "headers": list(_headers_for_tab(title)),
                    "headerRow": _header_row_for_tab(title),
                    "metadataCells": [
                        {"cell": cell, "value": value}
                        for cell, value in _metadata_cells_for_tab(title)
                    ],
                    "frozenRows": _frozen_rows_for_tab(title),
                    "frozenColumns": _frozen_columns_for_tab(title),
                    "tableStartsAt": _table_starts_at_for_tab(title),
                    "parserStatus": _parser_status_for_tab(title),
                    "layoutNotes": list(_layout_notes_for_tab(title)),
                }
                for title in tabs
            ],
            "rows": [row.to_dict() for row in self.rows],
        }


def build_workbook_export_plan_from_pdf(
    pdf_path: Path,
    *,
    issue_id: str | None = None,
    extractor: RawTextExtractor | None = None,
    min_embedded_chars: int = 40,
    import_date: date | str | None = None,
    current_utc_date: date | str | None = None,
) -> WorkbookExportPlan:
    """Build a dry-run workbook row plan from local embedded PDF text."""

    extraction = extract_pdf_text(
        pdf_path,
        extractor=extractor,
        min_embedded_chars=min_embedded_chars,
    )
    resolved_issue_id = issue_id or _issue_id_from_filename(pdf_path)
    stock_update_date = _resolve_stock_update_date(
        issue_date=guess_issue_date(pdf_path.name),
        import_date=import_date,
        current_utc_date=current_utc_date,
    )
    pages = tuple((page.page_number, page.text.splitlines()) for page in extraction.pages)
    cards: list[RecommendationCard] = (
        list(
            extract_recommendation_cards_from_pdf(
                pdf_path,
                issue_id=resolved_issue_id,
                min_embedded_chars=min_embedded_chars,
            ).cards
        )
        if extractor is None
        else []
    )
    sections: list[MagazineSectionCandidate] = []
    for page_number, lines in pages:
        if extractor is not None:
            cards.extend(
                extract_recommendation_cards_from_lines(
                    lines,
                    issue_id=resolved_issue_id,
                    page_number=page_number,
                )
            )
        sections.extend(
            extract_section_candidates_from_lines(
                lines,
                issue_id=resolved_issue_id,
                page_number=page_number,
            )
        )
    dividends = extract_dividend_strategy_rows_from_page_lines(
        pages,
        issue_id=resolved_issue_id,
    )
    derivative_overview_rows = extract_derivative_overview_rows_from_page_lines(
        pages,
        issue_id=resolved_issue_id,
    )
    depot_positions, depot_transactions = extract_depot_rows_from_page_lines(
        pages,
        issue_id=resolved_issue_id,
    )
    chart_check_rows = extract_chart_check_rows_from_page_lines(
        pages,
        issue_id=resolved_issue_id,
    )
    quickcheck_rows = extract_quickcheck_rows_from_page_lines(
        pages,
        issue_id=resolved_issue_id,
    )
    return build_workbook_export_plan(
        pdf_path=pdf_path,
        issue_id=resolved_issue_id,
        recommendation_cards=tuple(cards),
        dividend_strategy=dividends,
        derivative_overview=derivative_overview_rows,
        depot_positions=depot_positions,
        depot_transactions=depot_transactions,
        chart_check_rows=chart_check_rows,
        quickcheck_rows=quickcheck_rows,
        section_inventory=tuple(sections),
        stock_update_date=stock_update_date,
    )


def build_workbook_export_plan(
    *,
    pdf_path: Path,
    issue_id: str,
    recommendation_cards: RecommendationCardExtraction | Sequence[RecommendationCard] = (),
    dividend_strategy: DividendStrategyExtraction | Sequence[DividendStrategyRow] = (),
    derivative_overview: Sequence[DerivativeOverviewRow] = (),
    depot_positions: Sequence[DepotPositionRow] = (),
    depot_transactions: Sequence[DepotTransactionRow] = (),
    chart_check_rows: Sequence[ChartCheckRow] = (),
    quickcheck_rows: Sequence[QuickcheckRow] = (),
    section_inventory: MagazineSectionInventory | Sequence[MagazineSectionCandidate] = (),
    stock_update_date: date | str | None = None,
) -> WorkbookExportPlan:
    """Convert local extraction outputs into reviewer-gated workbook rows."""

    resolved_stock_update_date = _date_cell_value(stock_update_date) or _current_utc_date()
    dividend_yield_by_wkn = {
        row.wkn: row.dividend_yield
        for row in _dividend_rows_from(dividend_strategy)
        if row.wkn and row.dividend_yield
    }
    card_rows = _card_rows(
        _cards_from(recommendation_cards),
        stock_update_date=resolved_stock_update_date,
        dividend_yield_by_wkn=dividend_yield_by_wkn,
    )
    stock_rows = _consolidate_stock_rows(
        [row for row in card_rows if row.tab == "Stocks"]
        + _quickcheck_stock_rows(
            quickcheck_rows,
            stock_update_date=resolved_stock_update_date,
        )
        + _chart_check_stock_rows(
            chart_check_rows,
            stock_update_date=resolved_stock_update_date,
        )
    )
    non_stock_card_rows = [row for row in card_rows if row.tab != "Stocks"]
    rows = tuple(
        stock_rows
        + non_stock_card_rows
        + _dividend_rows(
            _dividend_rows_from(dividend_strategy),
            instrument_update_date=resolved_stock_update_date,
        )
        + _derivative_overview_rows(
            derivative_overview,
            instrument_update_date=resolved_stock_update_date,
        )
        + _depot_position_rows(
            depot_positions,
            instrument_update_date=resolved_stock_update_date,
        )
        + _depot_transaction_rows(
            depot_transactions,
            instrument_update_date=resolved_stock_update_date,
        )
        + _chart_check_rows(chart_check_rows)
        + _quickcheck_rows(quickcheck_rows)
        + _section_audit_rows(_sections_from(section_inventory))
    )
    return WorkbookExportPlan(
        issue_id=issue_id,
        pdf_path=pdf_path,
        external_services_enabled=False,
        google_writes_enabled=False,
        rows=rows,
    )


def _card_rows(
    cards: Sequence[RecommendationCard],
    *,
    stock_update_date: str,
    dividend_yield_by_wkn: dict[str, str],
) -> list[WorkbookDraftRow]:
    rows: list[WorkbookDraftRow] = []
    for card in cards:
        if card.instrument_type == InstrumentType.DERIVATIVE:
            rows.append(_derivative_card_row(card, instrument_update_date=stock_update_date))
        elif card.instrument_type == InstrumentType.STOCK:
            rows.append(
                _recommendation_card_row(
                    card,
                    stock_update_date=stock_update_date,
                    dividend_yield=card.dividend_yield
                    or dividend_yield_by_wkn.get(card.wkn or "")
                    or "",
                )
            )
        elif card.instrument_type in {
            InstrumentType.ETF,
            InstrumentType.FUND,
            InstrumentType.COMMODITY,
            InstrumentType.CRYPTO,
            InstrumentType.FOREX,
        }:
            continue
        else:
            rows.append(_generic_recommendation_card_row(card))
    return rows


def _recommendation_card_row(
    card: RecommendationCard,
    *,
    stock_update_date: str,
    dividend_yield: str = "",
) -> WorkbookDraftRow:
    return WorkbookDraftRow(
        tab="Stocks",
        row_kind="stock_recommendation",
        source_id=_source_id("card", card.issue_id, card.page, card.wkn),
        issue_id=card.issue_id,
        page=card.page,
        review_status=ReviewStatus.NEEDS_REVIEW,
        source_block="manual_review_pending",
        values=(
            card.instrument_name,
            card.wkn or "",
            "",
            card.current_price or "",
            stock_update_date if card.current_price else "",
            card.current_price if card.recommendation_status == "new_recommendation" else "",
            dividend_yield,
            card.market_cap or "",
            _chance_risk(card.chance, card.risk),
            card.kuv_26e or "",
            card.kgv_26e or "",
            card.target or "",
            card.stop or "",
            card.performance_since_recommendation or "",
            "",
            "",
            "",
            "",
            card.next_report_date or "",
            card.recommended_issue or card.recommendation_status or "",
            "",
            card.issue_id,
            str(card.page),
            stock_update_date,
        ),
    )


def _derivative_card_row(
    card: RecommendationCard,
    *,
    instrument_update_date: str,
) -> WorkbookDraftRow:
    source_id = _source_id("derivative", card.issue_id, card.page, card.wkn)
    product, direction = _split_derivative_direction(card.instrument_name)
    return WorkbookDraftRow(
        tab="Derivative Tips",
        row_kind="derivative_card",
        source_id=source_id,
        issue_id=card.issue_id,
        page=card.page,
        review_status=ReviewStatus.NEEDS_REVIEW,
        source_block="manual_review_pending",
        values=(
            "",
            product,
            direction,
            card.wkn or "",
            "",
            "",
            card.underlying_price or "",
            card.base_price or "",
            card.omega_hebel or "",
            card.runtime or "",
            card.entry_price or card.current_price or "",
            card.current_price or "",
            card.performance_since_recommendation or "",
            card.target or "",
            card.stop or "",
            card.recommendation_status or "",
            ReviewStatus.NEEDS_REVIEW.value,
            card.issue_id,
            str(card.page),
            instrument_update_date,
        ),
    )


def _etf_card_row(
    card: RecommendationCard,
    *,
    instrument_update_date: str,
) -> WorkbookDraftRow:
    dividend = _join_non_empty((card.dividend_yield, card.dividend_per_share_trend))
    return WorkbookDraftRow(
        tab="ETF",
        row_kind="etf_recommendation",
        source_id=_source_id("etf", card.issue_id, card.page, card.wkn),
        issue_id=card.issue_id,
        page=card.page,
        review_status=ReviewStatus.NEEDS_REVIEW,
        source_block="manual_review_pending",
        values=(
            card.instrument_name,
            card.wkn or "",
            "",
            card.current_price or "",
            dividend,
            card.recommendation_status or "",
            card.issue_id,
            str(card.page),
            ReviewStatus.NEEDS_REVIEW.value,
            instrument_update_date,
        ),
    )


def _commodity_card_row(
    card: RecommendationCard,
    *,
    instrument_update_date: str,
) -> WorkbookDraftRow:
    return WorkbookDraftRow(
        tab="Commodities",
        row_kind="commodity_recommendation",
        source_id=_source_id("commodity", card.issue_id, card.page, card.wkn),
        issue_id=card.issue_id,
        page=card.page,
        review_status=ReviewStatus.NEEDS_REVIEW,
        source_block="manual_review_pending",
        values=(
            card.instrument_name,
            card.wkn or "",
            "",
            card.recommendation_status or "",
            _join_non_empty((card.target, card.stop)),
            card.issue_id,
            str(card.page),
            ReviewStatus.NEEDS_REVIEW.value,
            instrument_update_date,
        ),
    )


def _crypto_card_row(
    card: RecommendationCard,
    *,
    instrument_update_date: str,
) -> WorkbookDraftRow:
    return WorkbookDraftRow(
        tab="Crypto",
        row_kind="crypto_recommendation",
        source_id=_source_id("crypto", card.issue_id, card.page, card.wkn),
        issue_id=card.issue_id,
        page=card.page,
        review_status=ReviewStatus.NEEDS_REVIEW,
        source_block="manual_review_pending",
        values=(
            card.instrument_name,
            card.wkn or "",
            "",
            card.current_price or "",
            card.recommendation_status or "",
            _join_non_empty((card.target, card.stop)),
            card.issue_id,
            str(card.page),
            ReviewStatus.NEEDS_REVIEW.value,
            instrument_update_date,
        ),
    )


def _forex_card_row(
    card: RecommendationCard,
    *,
    instrument_update_date: str,
) -> WorkbookDraftRow:
    return WorkbookDraftRow(
        tab="Forex",
        row_kind="forex_recommendation",
        source_id=_source_id("forex", card.issue_id, card.page, card.wkn),
        issue_id=card.issue_id,
        page=card.page,
        review_status=ReviewStatus.NEEDS_REVIEW,
        source_block="manual_review_pending",
        values=(
            card.instrument_name,
            "",
            card.recommendation_status or "",
            _join_non_empty((card.current_price, card.target, card.stop)),
            card.issue_id,
            str(card.page),
            ReviewStatus.NEEDS_REVIEW.value,
            instrument_update_date,
        ),
    )


def _generic_recommendation_card_row(card: RecommendationCard) -> WorkbookDraftRow:
    source_id = _source_id("card", card.issue_id, card.page, card.wkn)
    return WorkbookDraftRow(
        tab="Recommendation Cards",
        row_kind="recommendation_card",
        source_id=source_id,
        issue_id=card.issue_id,
        page=card.page,
        review_status=ReviewStatus.NEEDS_REVIEW,
        source_block="manual_review_pending",
        values=(
            source_id,
            card.issue_id,
            str(card.page),
            card.instrument_name,
            card.wkn or "",
            _chance_risk(card.chance, card.risk),
            card.recommendation_status or "",
            card.current_price or "",
            card.target or "",
            card.stop or "",
            card.market_cap or "",
            card.kgv_26e or "",
            card.kuv_26e or "",
            _join_non_empty((card.dividend_yield, card.dividend_per_share_trend)),
            ReviewStatus.NEEDS_REVIEW.value,
        ),
    )


def _dividend_rows(
    rows: Sequence[DividendStrategyRow],
    *,
    instrument_update_date: str,
) -> list[WorkbookDraftRow]:
    draft_rows: list[WorkbookDraftRow] = []
    for row in rows:
        source_id = _source_id("dividend", row.issue_id, row.page, row.wkn)
        draft_rows.append(
            WorkbookDraftRow(
                tab="Dividend Focus",
                row_kind="dividend_strategy",
                source_id=source_id,
                issue_id=row.issue_id,
                page=row.page,
                review_status=ReviewStatus.NEEDS_REVIEW,
                source_block="manual_review_pending",
                values=(
                    row.company,
                    row.wkn,
                    row.month,
                    row.current_price or "",
                    row.market_cap_billions_eur or "",
                    row.dividend_yield or "",
                    row.kgv_2026e or "",
                    row.payout_count or "",
                    row.next_cum_day or "",
                    row.next_pay_day or "",
                    row.target or "",
                    row.stop or "",
                    ReviewStatus.NEEDS_REVIEW.value,
                    row.issue_id,
                    str(row.page),
                    instrument_update_date,
                ),
            )
        )
    return draft_rows


def _derivative_overview_rows(
    rows: Sequence[DerivativeOverviewRow],
    *,
    instrument_update_date: str,
) -> list[WorkbookDraftRow]:
    draft_rows: list[WorkbookDraftRow] = []
    for row in rows:
        source_id = _source_id("derivative-overview", row.issue_id, row.page, row.wkn)
        draft_rows.append(
            WorkbookDraftRow(
                tab="Derivative Tips",
                row_kind="derivative_overview",
                source_id=source_id,
                issue_id=row.issue_id,
                page=row.page,
                review_status=ReviewStatus.NEEDS_REVIEW,
                source_block="manual_review_pending",
                values=(
                    row.underlying,
                    row.product,
                    row.direction,
                    row.wkn,
                    row.issuer,
                    row.ratio,
                    "",
                    row.strike_cap,
                    row.omega_hebel,
                    row.runtime,
                    row.entry_price,
                    row.current_price,
                    row.performance_since_recommendation,
                    row.target,
                    row.stop,
                    row.recommendation,
                    ReviewStatus.NEEDS_REVIEW.value,
                    row.issue_id,
                    str(row.page),
                    instrument_update_date,
                ),
            )
        )
    return draft_rows


def _depot_position_rows(
    rows: Sequence[DepotPositionRow],
    *,
    instrument_update_date: str,
) -> list[WorkbookDraftRow]:
    draft_rows: list[WorkbookDraftRow] = []
    for row in rows:
        source_id = _source_id("aktionaer-depot", row.issue_id, row.page, row.wkn)
        draft_rows.append(
            WorkbookDraftRow(
                tab="AKTIONAER Depot",
                row_kind="aktionaer_depot_position",
                source_id=source_id,
                issue_id=row.issue_id,
                page=row.page,
                review_status=ReviewStatus.NEEDS_REVIEW,
                source_block="manual_review_pending",
                values=(
                    row.instrument,
                    row.wkn,
                    row.quantity,
                    row.buy_date,
                    row.buy_price,
                    row.current_price,
                    row.value,
                    row.performance_since_buy,
                    row.stop,
                    ReviewStatus.NEEDS_REVIEW.value,
                    row.issue_id,
                    str(row.page),
                    instrument_update_date,
                ),
            )
        )
    return draft_rows


def _depot_transaction_rows(
    rows: Sequence[DepotTransactionRow],
    *,
    instrument_update_date: str,
) -> list[WorkbookDraftRow]:
    draft_rows: list[WorkbookDraftRow] = []
    for row in rows:
        source_id = _source_id(
            "depot-transaction",
            row.issue_id,
            row.page,
            row.wkn or row.action,
        )
        draft_rows.append(
            WorkbookDraftRow(
                tab="Depot Transactions",
                row_kind="depot_transaction",
                source_id=source_id,
                issue_id=row.issue_id,
                page=row.page,
                review_status=ReviewStatus.NEEDS_REVIEW,
                source_block="manual_review_pending",
                values=(
                    row.action,
                    row.instrument,
                    row.wkn,
                    row.quantity,
                    row.transaction_date,
                    row.price,
                    row.performance_since_buy,
                    ReviewStatus.NEEDS_REVIEW.value,
                    row.issue_id,
                    str(row.page),
                    instrument_update_date,
                ),
            )
        )
    return draft_rows


def _quickcheck_rows(rows: Sequence[QuickcheckRow]) -> list[WorkbookDraftRow]:
    draft_rows: list[WorkbookDraftRow] = []
    for row in rows:
        source_id = _source_id("quickcheck", row.issue_id, row.page, row.wkn)
        draft_rows.append(
            WorkbookDraftRow(
                tab="Stock Quickcheck",
                row_kind="stock_quickcheck",
                source_id=source_id,
                issue_id=row.issue_id,
                page=row.page,
                review_status=ReviewStatus.NEEDS_REVIEW,
                source_block="manual_review_pending",
                values=(
                    row.issue_id,
                    str(row.page),
                    row.instrument,
                    row.wkn,
                    row.current_price,
                    row.recommendation_price,
                    row.recommended_issue,
                    row.performance_since_recommendation,
                    row.target,
                    row.stop,
                    row.comment,
                    row.review_status.value,
                ),
            )
        )
    return draft_rows


def _quickcheck_stock_rows(
    rows: Sequence[QuickcheckRow],
    *,
    stock_update_date: str,
) -> list[WorkbookDraftRow]:
    draft_rows: list[WorkbookDraftRow] = []
    for row in rows:
        source_id = _source_id("quickcheck-stock", row.issue_id, row.page, row.wkn)
        draft_rows.append(
            WorkbookDraftRow(
                tab="Stocks",
                row_kind="stock_quickcheck_summary",
                source_id=source_id,
                issue_id=row.issue_id,
                page=row.page,
                review_status=ReviewStatus.NEEDS_REVIEW,
                source_block="manual_review_pending",
                values=(
                    row.instrument,
                    row.wkn,
                    "",
                    row.current_price,
                    stock_update_date if row.current_price else "",
                    row.recommendation_price,
                    "",
                    "",
                    "",
                    "",
                    "",
                    row.target,
                    row.stop,
                    row.performance_since_recommendation,
                    "",
                    "",
                    "",
                    "",
                    "",
                    row.recommended_issue,
                    row.comment,
                    row.issue_id,
                    str(row.page),
                    stock_update_date,
                ),
            )
        )
    return draft_rows


def _chart_check_stock_rows(
    rows: Sequence[ChartCheckRow],
    *,
    stock_update_date: str,
) -> list[WorkbookDraftRow]:
    draft_rows: list[WorkbookDraftRow] = []
    for row in rows:
        source_id = _source_id("chart-check-stock", row.issue_id, row.page, row.wkn)
        draft_rows.append(
            WorkbookDraftRow(
                tab="Stocks",
                row_kind="stock_chart_check_summary",
                source_id=source_id,
                issue_id=row.issue_id,
                page=row.page,
                review_status=ReviewStatus.NEEDS_REVIEW,
                source_block="manual_review_pending",
                values=(
                    row.instrument,
                    row.wkn,
                    "",
                    row.current_price,
                    stock_update_date if row.current_price else "",
                    row.recommendation_price,
                    row.dividend_yield,
                    "",
                    "",
                    "",
                    "",
                    row.target,
                    row.stop,
                    row.performance_since_recommendation,
                    row.high_52w,
                    row.low_52w,
                    row.performance_1y,
                    row.performance_5y,
                    row.next_report_date,
                    row.recommended_issue,
                    row.signal,
                    row.issue_id,
                    str(row.page),
                    stock_update_date,
                ),
            )
        )
    return draft_rows


def _consolidate_stock_rows(rows: Sequence[WorkbookDraftRow]) -> list[WorkbookDraftRow]:
    grouped: dict[str, WorkbookDraftRow] = {}
    order: list[str] = []
    for row in rows:
        key = _stock_identity_key(row.values)
        if key not in grouped:
            grouped[key] = row
            order.append(key)
            continue
        grouped[key] = _merge_stock_rows(grouped[key], row)
    return [grouped[key] for key in order]


def _stock_identity_key(values: Sequence[str]) -> str:
    wkn = values[1].strip() if len(values) > 1 else ""
    if wkn:
        return f"wkn:{wkn.casefold()}"
    name = values[0].strip() if values else ""
    return f"name:{name.casefold()}"


def _merge_stock_rows(existing: WorkbookDraftRow, incoming: WorkbookDraftRow) -> WorkbookDraftRow:
    values = list(existing.values)
    incoming_values = list(incoming.values)
    _ensure_width(values, len(incoming_values))

    latest_wins_indexes = {2, 3, 4, 5, 11, 12, 13, 14, 15, 16, 17, 18}
    fill_only_indexes = {0, 1, 6, 7, 8, 9, 10, 19, 23}
    for index in latest_wins_indexes:
        if index < len(incoming_values) and incoming_values[index]:
            values[index] = incoming_values[index]
    for index in fill_only_indexes:
        if index < len(incoming_values) and incoming_values[index] and not values[index]:
            values[index] = incoming_values[index]

    recommendation_index = 19
    if recommendation_index < len(incoming_values) and incoming_values[recommendation_index]:
        current = values[recommendation_index]
        candidate = incoming_values[recommendation_index]
        if not current or _looks_like_richer_recommendation(candidate, current):
            values[recommendation_index] = candidate

    comment_parts = _split_comment(values[20]) if len(values) > 20 else []
    if len(incoming_values) > 20 and incoming_values[20]:
        comment_parts.append(incoming_values[20])
    if len(values) > 20:
        values[20] = _join_unique(comment_parts)

    if len(values) > 21 and len(incoming_values) > 21:
        values[21] = _join_unique((values[21], incoming_values[21]))
    if len(values) > 22 and len(incoming_values) > 22:
        values[22] = _join_unique((values[22], incoming_values[22]), separator=", ")

    return WorkbookDraftRow(
        tab="Stocks",
        row_kind="stock_consolidated",
        source_id=_source_id("stock", existing.issue_id, existing.page, values[1] or values[0]),
        issue_id=existing.issue_id,
        page=existing.page,
        values=tuple(values),
        review_status=ReviewStatus.NEEDS_REVIEW,
        source_block="manual_review_pending",
    )


def _ensure_width(values: list[str], width: int) -> None:
    if len(values) < width:
        values.extend("" for _ in range(width - len(values)))


def _looks_like_richer_recommendation(candidate: str, current: str) -> bool:
    return (_contains_date(candidate), len(candidate)) > (_contains_date(current), len(current))


def _contains_date(value: str) -> bool:
    return bool(re.search(r"\d{2}\.\d{2}\.\d{2,4}", value))


def _split_comment(value: str) -> list[str]:
    return [part.strip() for part in value.split(" | ") if part.strip()]


def _join_unique(values: Iterable[str], *, separator: str = " | ") -> str:
    result: list[str] = []
    for value in values:
        stripped = value.strip()
        if stripped and stripped not in result:
            result.append(stripped)
    return separator.join(result)


def _chart_check_rows(rows: Sequence[ChartCheckRow]) -> list[WorkbookDraftRow]:
    draft_rows: list[WorkbookDraftRow] = []
    for row in rows:
        source_id = _source_id("chart-check", row.issue_id, row.page, row.wkn)
        draft_rows.append(
            WorkbookDraftRow(
                tab="Chart Check",
                row_kind="chart_check",
                source_id=source_id,
                issue_id=row.issue_id,
                page=row.page,
                review_status=ReviewStatus.NEEDS_REVIEW,
                source_block="manual_review_pending",
                values=(
                    row.issue_id,
                    str(row.page),
                    row.instrument,
                    row.wkn,
                    row.sector,
                    row.signal,
                    row.current_price,
                    row.recommendation_price,
                    row.recommended_issue,
                    row.performance_since_recommendation,
                    row.target,
                    row.stop,
                    row.dividend_yield,
                    row.next_report_date,
                    row.high_52w,
                    row.low_52w,
                    row.performance_1y,
                    row.performance_5y,
                    row.trend,
                    row.support,
                    row.resistance,
                    row.review_status.value,
                ),
            )
        )
    return draft_rows


def _section_audit_rows(sections: Sequence[MagazineSectionCandidate]) -> list[WorkbookDraftRow]:
    rows: list[WorkbookDraftRow] = []
    for section in sections:
        source_id = _source_id(
            "section",
            section.issue_id,
            section.page,
            section.section_kind.value,
        )
        rows.append(
            WorkbookDraftRow(
                tab="Extraction Audit",
                row_kind="section_inventory",
                source_id=source_id,
                issue_id=section.issue_id,
                page=section.page,
                review_status=ReviewStatus.NEEDS_REVIEW,
                source_block="manual_review_pending",
                warnings=(
                    MANUAL_REVIEW_WARNING,
                    f"suggested_sheet={section.suggested_sheet}",
                ),
                values=(
                    "local-dry-run",
                    section.issue_id,
                    str(section.page),
                    section.section_kind.value,
                    _severity_for_priority(section.priority),
                    section.reason,
                    f"review_for_{section.suggested_sheet}",
                    "",
                ),
            )
        )
    return rows


def _cards_from(
    extraction: RecommendationCardExtraction | Sequence[RecommendationCard],
) -> tuple[RecommendationCard, ...]:
    if isinstance(extraction, RecommendationCardExtraction):
        return extraction.cards
    return tuple(extraction)


def _dividend_rows_from(
    extraction: DividendStrategyExtraction | Sequence[DividendStrategyRow],
) -> tuple[DividendStrategyRow, ...]:
    if isinstance(extraction, DividendStrategyExtraction):
        return extraction.rows
    return tuple(extraction)


def _sections_from(
    inventory: MagazineSectionInventory | Sequence[MagazineSectionCandidate],
) -> tuple[MagazineSectionCandidate, ...]:
    if isinstance(inventory, MagazineSectionInventory):
        return inventory.sections
    return tuple(inventory)


def _source_id(prefix: str, issue_id: str, page: int, stable_key: str | None) -> str:
    key = stable_key or "missing-key"
    digest = sha256(f"{prefix}|{issue_id}|{page}|{key}".encode("utf-8")).hexdigest()[:10]
    visible_key = key if stable_key else "review"
    return f"{prefix}:{issue_id}:p{page}:{visible_key}:{digest}"


def _split_derivative_direction(name: str) -> tuple[str, str]:
    normalized = " ".join(name.split())
    for direction in (
        "Discount-Call",
        "Discount-Put",
        "Turbo-Call",
        "Turbo-Put",
        "Turbo-Long",
        "Turbo-Short",
        "Index-Zertifikat",
        "Call",
        "Put",
        "Zertifikat",
    ):
        suffix = f" {direction}"
        if normalized.endswith(suffix):
            return normalized[: -len(suffix)].strip(), direction
        if normalized == direction:
            return "", direction
    return normalized, ""


def _private_source_id(pdf_path: Path, issue_id: str) -> str:
    digest = sha256(f"{issue_id}|{pdf_path.name}".encode("utf-8")).hexdigest()[:12]
    return f"pdf:{issue_id}:{digest}"


def _headers_for_tab(title: str) -> tuple[str, ...]:
    for spec in DEFAULT_SHEET_TABS:
        if spec.title == title:
            return spec.headers
    return ()


def _header_row_for_tab(title: str) -> int:
    for spec in DEFAULT_SHEET_TABS:
        if spec.title == title:
            return spec.header_row
    return 1


def _metadata_cells_for_tab(title: str) -> tuple[tuple[str, str], ...]:
    for spec in DEFAULT_SHEET_TABS:
        if spec.title == title:
            return spec.metadata_cells
    return ()


def _frozen_rows_for_tab(title: str) -> int:
    for spec in DEFAULT_SHEET_TABS:
        if spec.title == title:
            return spec.frozen_rows
    return 1


def _frozen_columns_for_tab(title: str) -> int:
    for spec in DEFAULT_SHEET_TABS:
        if spec.title == title:
            return spec.frozen_columns
    return 0


def _table_starts_at_for_tab(title: str) -> str:
    for spec in DEFAULT_SHEET_TABS:
        if spec.title == title:
            return spec.table_starts_at
    return "A1"


def _parser_status_for_tab(title: str) -> str:
    for spec in DEFAULT_SHEET_TABS:
        if spec.title == title:
            return spec.parser_status
    return "planned"


def _layout_notes_for_tab(title: str) -> tuple[str, ...]:
    for spec in DEFAULT_SHEET_TABS:
        if spec.title == title:
            return spec.layout_notes
    return ()


def _tabs_for_rows(rows: Iterable[WorkbookDraftRow]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for row in rows:
        if row.tab not in seen:
            seen.add(row.tab)
            ordered.append(row.tab)
    return tuple(ordered)


def _validate_workbook_rows(rows: Sequence[WorkbookDraftRow]) -> None:
    specs_by_title = {spec.title: spec for spec in DEFAULT_SHEET_TABS}
    for row in rows:
        spec = specs_by_title.get(row.tab)
        if spec is None:
            raise WorkbookExportPlanError(
                f"workbook export row targets unsupported tab {row.tab!r}"
            )
        expected_width = len(spec.headers)
        actual_width = len(row.values)
        if actual_width != expected_width:
            raise WorkbookExportPlanError(
                f"workbook export row for {row.tab} must contain "
                f"{expected_width} values, got {actual_width}"
            )


def _chance_risk(chance: int | None, risk: int | None) -> str:
    if chance is None and risk is None:
        return ""
    return f"{chance or ''}/{risk or ''}"


def _join_non_empty(values: Sequence[str | None]) -> str:
    return "; ".join(value for value in values if value)


def _resolve_stock_update_date(
    *,
    issue_date: str | None,
    import_date: date | str | None,
    current_utc_date: date | str | None,
) -> str:
    return (
        _date_cell_value(import_date)
        or _date_cell_value(issue_date)
        or _date_cell_value(current_utc_date)
        or _current_utc_date()
    )


def _date_cell_value(value: date | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, date):
        return value.isoformat()
    return value.strip()


def _current_utc_date() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _severity_for_priority(priority: str) -> str:
    if priority == "high":
        return "warning"
    if priority == "medium":
        return "info"
    return "low"


def _issue_id_from_filename(pdf_path: Path) -> str:
    stem = pdf_path.stem
    parts = stem.split("_")
    if len(parts) >= 3 and parts[0] == "DA" and parts[1].isdigit() and parts[2].isdigit():
        return f"{parts[1]}-W{parts[2]}"
    return stem
