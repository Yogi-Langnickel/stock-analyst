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
from typing import Iterable, Sequence

from stock_analyst.dividend_strategy import (
    DividendStrategyExtraction,
    DividendStrategyRow,
    extract_dividend_strategy_rows_from_page_lines,
)
from stock_analyst.extraction import RawTextExtractor, extract_pdf_text
from stock_analyst.google_access import DEFAULT_SHEET_TABS
from stock_analyst.intake import guess_issue_date
from stock_analyst.recommendation_cards import (
    RecommendationCard,
    RecommendationCardExtraction,
    extract_recommendation_cards_from_lines,
)
from stock_analyst.schemas import InstrumentType, ReviewStatus
from stock_analyst.section_inventory import (
    MagazineSectionCandidate,
    MagazineSectionInventory,
    extract_section_candidates_from_lines,
)


MANUAL_REVIEW_WARNING = "manual_review_required_before_family_visible_export"


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
    cards: list[RecommendationCard] = []
    sections: list[MagazineSectionCandidate] = []
    for page_number, lines in pages:
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
    return build_workbook_export_plan(
        pdf_path=pdf_path,
        issue_id=resolved_issue_id,
        recommendation_cards=tuple(cards),
        dividend_strategy=dividends,
        section_inventory=tuple(sections),
        stock_update_date=stock_update_date,
    )


def build_workbook_export_plan(
    *,
    pdf_path: Path,
    issue_id: str,
    recommendation_cards: RecommendationCardExtraction | Sequence[RecommendationCard] = (),
    dividend_strategy: DividendStrategyExtraction | Sequence[DividendStrategyRow] = (),
    section_inventory: MagazineSectionInventory | Sequence[MagazineSectionCandidate] = (),
    stock_update_date: date | str | None = None,
) -> WorkbookExportPlan:
    """Convert local extraction outputs into reviewer-gated workbook rows."""

    resolved_stock_update_date = _date_cell_value(stock_update_date) or _current_utc_date()
    rows = tuple(
        _card_rows(
            _cards_from(recommendation_cards),
            stock_update_date=resolved_stock_update_date,
        )
        + _dividend_rows(_dividend_rows_from(dividend_strategy))
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
) -> list[WorkbookDraftRow]:
    rows: list[WorkbookDraftRow] = []
    for card in cards:
        if card.instrument_type == InstrumentType.DERIVATIVE:
            rows.append(_derivative_card_row(card))
        else:
            rows.append(_recommendation_card_row(card, stock_update_date=stock_update_date))
    return rows


def _recommendation_card_row(
    card: RecommendationCard,
    *,
    stock_update_date: str,
) -> WorkbookDraftRow:
    dividend = _join_non_empty((card.dividend_yield, card.dividend_per_share_trend))
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
            dividend,
            card.target or "",
            card.stop or "",
            card.recommendation_status or "",
            stock_update_date,
            card.issue_id,
            str(card.page),
        ),
    )


def _derivative_card_row(card: RecommendationCard) -> WorkbookDraftRow:
    source_id = _source_id("derivative", card.issue_id, card.page, card.wkn)
    return WorkbookDraftRow(
        tab="Derivative Tips",
        row_kind="derivative_card",
        source_id=source_id,
        issue_id=card.issue_id,
        page=card.page,
        review_status=ReviewStatus.NEEDS_REVIEW,
        source_block="manual_review_pending",
        values=(
            source_id,
            card.issue_id,
            str(card.page),
            "",
            card.instrument_name,
            card.wkn or "",
            card.underlying_price or "",
            card.base_price or "",
            card.omega_hebel or "",
            card.runtime or "",
            card.target or "",
            card.stop or "",
            ReviewStatus.NEEDS_REVIEW.value,
        ),
    )


def _dividend_rows(rows: Sequence[DividendStrategyRow]) -> list[WorkbookDraftRow]:
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
                    row.issue_id,
                    str(row.page),
                    row.company,
                    row.wkn,
                    row.payout_count or "",
                    row.dividend_yield,
                    row.month,
                    row.next_cum_day or "",
                    ReviewStatus.NEEDS_REVIEW.value,
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


def _tabs_for_rows(rows: Iterable[WorkbookDraftRow]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for row in rows:
        if row.tab not in seen:
            seen.add(row.tab)
            ordered.append(row.tab)
    return tuple(ordered)


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
