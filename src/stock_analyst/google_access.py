"""Google Drive/Sheets access configuration and metadata-only helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import os
import re

from stock_analyst.review_approvals import (
    ReviewApprovalError,
    approved_workbook_rows_fingerprint,
)


GOOGLE_DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
GOOGLE_SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"

LEGACY_AKTUELL_DERIVATIVE_HEADERS = (
    "WKN",
    "Derivative",
    "Action",
    "Magazine Current Price",
    "Target",
    "Stop",
    "Underlying / Price",
    "Strike / KO",
    "Leverage",
    "Runtime",
    "Chance",
    "Risk",
    "Comment",
    "date updated",
    "Issue:Page",
    "Review status",
    "Reviewer note",
)

AKTUELL_DERIVATIVE_HEADERS = tuple(
    header
    for header in LEGACY_AKTUELL_DERIVATIVE_HEADERS
    if header not in {"Chance", "Risk"}
)
AKTUELL_DERIVATIVE_HEADERS = tuple(
    "Import date" if header == "date updated" else header
    for header in AKTUELL_DERIVATIVE_HEADERS
)


def _project_legacy_aktuell_derivative_values(
    values: Sequence[object],
) -> list[object]:
    values_by_header = dict(zip(LEGACY_AKTUELL_DERIVATIVE_HEADERS, values))
    return [
        values_by_header.get(
            "date updated" if header == "Import date" else header,
            "",
        )
        for header in AKTUELL_DERIVATIVE_HEADERS
    ]

# The compact reviewer tabs deliberately use separate schemas for their
# stacked stock and derivative tables.  Keep these layout facts beside the
# derivative headers so format rules keep their distinct table widths even
# though Action is column C in both reviewer tables.
REVIEWER_STOCK_COLUMN_COUNT = 16  # A:P
REVIEWER_STOCK_ACTION_COLUMN_INDEX = 2  # C
REVIEWER_DERIVATIVE_COLUMN_COUNT = len(AKTUELL_DERIVATIVE_HEADERS)  # A:O
REVIEWER_DERIVATIVE_ACTION_COLUMN_INDEX = 2  # C

# Stable reviewer widths prevent numeric values and long labels from visually
# overlapping after Sheets auto-resize. These apply to both Aktuell and issue
# tabs, whose stacked stock/derivative tables share columns A:P.
REVIEWER_COLUMN_WIDTHS = (
    130, 220, 90, 130, 105, 105, 150, 130, 105,
    110, 100, 110, 180, 125, 190, 160,
)

REVIEWER_ACTION_FORMATS = (
    ("Buy", {"red": 0.85, "green": 0.94, "blue": 0.85}),
    ("Hold", {"red": 1.0, "green": 0.95, "blue": 0.75}),
    ("Sell", {"red": 0.98, "green": 0.84, "blue": 0.84}),
)

INSIDER_DIRECTION_FORMATS = (
    ("Acquired", {"red": 0.85, "green": 0.94, "blue": 0.85}),
    ("Disposed", {"red": 0.98, "green": 0.84, "blue": 0.84}),
)

LEGACY_INSIDER_ACTIVITY_HEADERS = (
    "Company", "WKN", "Ticker", "CIK", "Insider", "Relationship",
    "Transaction date", "Transaction code", "Direction", "Shares", "Price",
    "Transaction value", "Shares owned after", "Filing date", "SEC filing URL",
    "Signal", "Review status", "Issue:Page", "date updated",
)

ISSUE_TAB_TITLE_RE = re.compile(r"^DA_(?P<year>20\d{2})_(?P<number>\d{2})$")
ISSUE_ID_RE = re.compile(r"^(?P<year>20\d{2})-W(?P<number>\d{1,2})$")
SOURCE_PAGE_RE = re.compile(r"20\d{2}-W\d{1,2}:(?P<page>\d+)")
MANAGED_PROTECTION_DESCRIPTION_PREFIX = "Stock Analyst managed protection:"
MANAGED_INSIDER_FILTER_VIEW_TITLES = (
    "Alle Insider-Trades",
    "Käufe (Acquired)",
    "Verkäufe (Disposed)",
)
INSIDER_ACTIVITY_HEADER_ROW = 3
INSIDER_ACTIVITY_INSTRUCTIONS = (
    (
        "A1",
        "English — Data → Filter views → choose ‘Alle Insider-Trades’, ‘Käufe’ "
        "or ‘Verkäufe’. Close the view to return; data stays unchanged.",
    ),
    (
        "A2",
        "Deutsch — Daten → Filteransichten → ‘Alle Insider-Trades’, ‘Käufe’ oder "
        "‘Verkäufe’ wählen. Zum Zurückkehren Ansicht schließen; Daten bleiben "
        "unverändert.",
    ),
)
NAVIGATION_DASHBOARD_HEADER_ROW = 2
NAVIGATION_DASHBOARD_START_ROW = NAVIGATION_DASHBOARD_HEADER_ROW + 1
ISSUE_RECOMMENDATION_TABLE_BLANK_ROWS = 2
REVIEWER_GRID_TRAILING_ROWS = 1

GOOGLE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{10,}$")
SHEET_MONEY_WITH_CURRENCY_RE = re.compile(
    r"(?:(EUR|USD|CHF|GBP|GBX|AUD|CAD|JPY|HKD|CNY|NOK|SEK|DKK|€|\$)\s*"
    r"([+-]?(?:\d{1,3}(?:[.,]\d{3})+|\d+)(?:[.,]\d+)?)|"
    r"([+-]?(?:\d{1,3}(?:[.,]\d{3})+|\d+)(?:[.,]\d+)?)\s*"
    r"(EUR|USD|CHF|GBP|GBX|AUD|CAD|JPY|HKD|CNY|NOK|SEK|DKK|€|\$)\b)",
    re.IGNORECASE,
)
SHEET_UNSIGNED_PERCENT_VALUE_RE = re.compile(r"^\s*\d+(?:[,.]\d+)?\s*%\s*$")
SHEET_RATIO_VALUE_RE = re.compile(r"^\s*\d+(?:[,.]\d+)?\s*$")


class GoogleAccessError(ValueError):
    """Raised when Google Drive/Sheets access is not configured correctly."""


def _redacted_identifier(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return f"redacted:{sha256(text.encode('utf-8')).hexdigest()[:12]}"


def redact_google_identifier(value: object) -> str | None:
    """Return a stable non-reversible identifier for stdout-safe Google results."""

    return _redacted_identifier(value)


@dataclass(frozen=True)
class GoogleAccessConfig:
    drive_folder_id: str
    sheets_spreadsheet_id: str
    credentials_path: Path
    service_account_email: str | None = None

    def to_public_dict(self) -> dict[str, object]:
        return {
            "driveFolderId": _redacted_identifier(self.drive_folder_id),
            "sheetsSpreadsheetId": _redacted_identifier(self.sheets_spreadsheet_id),
            "credentialsPath": "redacted",
            "serviceAccountEmail": _redacted_identifier(self.service_account_email),
        }


@dataclass(frozen=True)
class DrivePdfMetadata:
    drive_file_id: str
    name: str
    mime_type: str
    size_bytes: int | None
    md5_checksum: str | None
    created_time: str | None
    modified_time: str | None
    web_view_link: str | None

    @property
    def source_pdf_id(self) -> str:
        return f"drive_{sha256(self.drive_file_id.encode('utf-8')).hexdigest()[:16]}"

    def to_dict(self, *, include_private_identifiers: bool = False) -> dict[str, object]:
        result: dict[str, object] = {
            "sourcePdfId": self.source_pdf_id,
            "driveFileId": self.drive_file_id
            if include_private_identifiers
            else _redacted_identifier(self.drive_file_id),
            "name": self.name,
            "mimeType": self.mime_type,
            "processingStatus": {
                "stage": "drive_metadata_imported",
                "status": "pending_local_download",
                "externalServicesEnabled": True,
            },
        }
        if self.size_bytes is not None:
            result["sizeBytes"] = self.size_bytes
        if self.md5_checksum is not None:
            result["md5Checksum"] = self.md5_checksum
        if self.created_time is not None:
            result["createdTime"] = self.created_time
        if self.modified_time is not None:
            result["modifiedTime"] = self.modified_time
        if self.web_view_link is not None:
            result["webViewLink"] = (
                self.web_view_link
                if include_private_identifiers
                else _redacted_identifier(self.web_view_link)
            )
        return result


@dataclass(frozen=True)
class GoogleSheetTabSpec:
    title: str
    headers: tuple[str, ...]
    purpose: str
    header_row: int = 1
    metadata_cells: tuple[tuple[str, str], ...] = ()
    frozen_rows: int = 1
    frozen_columns: int = 0
    table_starts_at: str = "A1"
    parser_status: str = "planned"
    layout_notes: tuple[str, ...] = ()


SEARCH_SHEET_TAB = GoogleSheetTabSpec(
    "Search",
    ("Search company or WKN",),
    "Issue-history lookup across generated DA_YYYY_NN reviewer tabs.",
    header_row=1,
    metadata_cells=(
        (
            "A2",
            "Searches issue tabs and Insider Activity. Aktuell is excluded to avoid duplicate current-issue results.",
        ),
    ),
    frozen_rows=0,
    frozen_columns=0,
    table_starts_at="A1",
    layout_notes=(
        "Enter a company name or WKN in the merged C1:E1 field.",
        "Source is the first result column for stock and derivative matches.",
        "Insider Activity results use their dedicated 12-column display schema; Aktuell is excluded.",
        "Issue matches sort newest-first; insider matches sort by transaction date.",
    ),
    parser_status="layout_only",
)


DATA_BACKED_TAB_TITLES = {
    "Navigation Dashboard",
    "Aktuell",
    "Stocks",
    "Derivative Tips",
    "AKTIONAER Depot",
    "Depot Transactions",
    "Insider Activity",
    "Dividend Focus",
    "Extraction Audit",
}


NAVIGATION_DASHBOARD_ROWS: tuple[tuple[str, ...], ...] = (
    ("Core review", "__sheet_link__:Aktuell", "Current import recommendations for quick reviewer triage.", "Start here after each issue import.", "=COUNTA('Aktuell'!A2:A)", "parser-backed; review required", "Source-linked magazine rows only; not investment advice."),
    ("Core review", "__sheet_link__:Stocks", "Canonical equity rows merged from recommendation cards, Quick Check, and Chart Check.", "Review stock identity and current source fields.", "=COUNTA('Stocks'!A2:A)", "parser-backed; review required", "Price, target, stop, yield, and ratio columns are shape-sanitized."),
    ("Core review", "__sheet_link__:Dividend Focus", "Dividend table rows and multi-period dividend context.", "Validate yield/date/price fields.", "=COUNTA('Dividend Focus'!A2:A)", "parser-backed; review required", "Dividend yield is source context, not a guaranteed future payout."),
    ("Core review", "__sheet_link__:Derivative Tips", "Calls, puts, certificates, and derivative overview rows.", "Check derivative WKN/product terms.", "=COUNTA('Derivative Tips'!A2:A)", "parser-backed; review required", "Highest risk surface; do not group rows by underlying alone."),
    ("Publisher portfolio", "__sheet_link__:AKTIONAER Depot", "Publisher model-depot position snapshots.", "Treat as source context, not advice.", "=COUNTA('AKTIONAER Depot'!A2:A)", "parser-backed; review required", "This is the publisher's model portfolio, not a household portfolio."),
    ("Publisher portfolio", "__sheet_link__:Depot Transactions", "Publisher transaction and no-transaction ledger.", "Check event history.", "=COUNTA('Depot Transactions'!A2:A)", "parser-backed; review required", "Use for source history and transaction evidence."),
    ("Source detail", "__sheet_link__:Insider Activity", "SEC Form 4 insider activity rows and stock-level signal context.", "Review filing links and transaction classification.", "=COUNTA('Insider Activity'!A4:A)", "parser-backed; review required", "Signals are context only and must link to source filings."),
    ("QA", "__sheet_link__:Extraction Audit", "Parser warnings, skipped sections, OCR-needed pages, and review notes.", "Fix blockers before relying on rows.", "=COUNTA('Extraction Audit'!A2:A)", "parser-backed; internal", "Check this tab after each import."),
)
NAVIGATION_DASHBOARD_CELLS: tuple[tuple[str, str], ...] = tuple(
    (f"{column}{NAVIGATION_DASHBOARD_START_ROW + row_index}", value)
    for row_index, row in enumerate(NAVIGATION_DASHBOARD_ROWS)
    for column, value in zip("ABCDEFG", row)
)
ISSUE_ARCHIVE_START_ROW = NAVIGATION_DASHBOARD_START_ROW + len(NAVIGATION_DASHBOARD_ROWS) + 2


DEFAULT_SHEET_TABS: tuple[GoogleSheetTabSpec, ...] = (
    GoogleSheetTabSpec(
        "Navigation Dashboard",
        ("Area", "Open", "What this tab is for", "Reviewer action", "Row count", "Status", "Notes"),
        "Low-clutter entrypoint for active workbook tabs.",
        header_row=NAVIGATION_DASHBOARD_HEADER_ROW,
        metadata_cells=NAVIGATION_DASHBOARD_CELLS,
        frozen_rows=NAVIGATION_DASHBOARD_HEADER_ROW,
        frozen_columns=2,
        table_starts_at=f"A{NAVIGATION_DASHBOARD_HEADER_ROW}",
        layout_notes=(
            "Use this tab as a dashboard index for currently active parser-backed tabs.",
            "Keep financial decision detail on source tabs; this tab should stay concise.",
            "Preserve this layout during data clears because it contains static navigation rows.",
        ),
        parser_status="layout_only",
    ),
    GoogleSheetTabSpec(
        "Refinement",
        (
            "Page_number",
            "section",
            "page_titel",
            "useful_info",
            "suggested_destination",
            "parser_hint",
            "reason",
            "reviewer_notes",
            "issue",
            "date_updated",
        ),
        "Page-by-page reviewer classification map for parser refinement.",
        header_row=3,
        metadata_cells=(
            ("A1", "Der Aktionär Summaries"),
            ("A2", "Refinement"),
            ("B2", "Review and correct page classification before parser tuning."),
        ),
        frozen_rows=3,
        frozen_columns=1,
        table_starts_at="A3",
        layout_notes=(
            "Reviewer-facing page map; use this to decide which pages feed which parsers.",
            "The assistant seeds all rows, then reviewer_notes can be filled manually.",
            "This tab is not an investment-row export and does not trigger enrichment.",
        ),
        parser_status="parser_backed",
    ),
    GoogleSheetTabSpec(
        "Aktuell",
        (
            "WKN",
            "Company",
            "Action",
            "Price at Print",
            "Target",
            "Stop",
            "Dividend",
            "KUV",
            "KGV",
            "Chance",
            "Risk",
            "Comment",
            "Import date",
            "Source",
            "Review status",
            "Reviewer note",
        ),
        "Aktuelle Ausgabe: source-linked explicit publisher actions only.",
        # Start with the actual stock-table headers.  A persistent title block
        # above the generated table caused an unused first row and made stale
        # table spacing appear to be recommendation rows in the reviewer view.
        header_row=1,
        frozen_rows=1,
        frozen_columns=3,
        table_starts_at="A1",
        layout_notes=(
            "Aktuell / Latest: contains explicit publisher Buy, Sell, Hold, and Wait actions from the current issue.",
            "Table groups Stocks, Derivatives, Crypto, and ETFs when a matching recommendation exists.",
            "Use for quick triage; canonical merged stock state remains in Stocks.",
            "Rows are source-linked, reviewer-gated, and not investment advice.",
        ),
        parser_status="parser_backed",
    ),
    GoogleSheetTabSpec(
        "Stocks",
        (
            "Company",
            "WKN",
            "Target",
            "Stop",
            "Current price",
            "Market Cap",
            "Dividend Yield",
            "Recommendation",
            "Held since",
            "Performance since Recommendation",
            "Next Report",
            "Report type",
            "P/S Ratio 26e",
            "P/E Ratio 26e",
            "Chance",
            "Risk",
            "Insider Activity",
            "Issue:Page",
            "Enrichment status",
            "Import date",
        ),
        "Equity dashboard and reviewed stock mentions.",
        header_row=1,
        frozen_rows=1,
        frozen_columns=2,
        table_starts_at="A1",
        layout_notes=(
            "Only explicit stock mentions become rows; do not fan out index constituents.",
            "Quick-check and chart-check stock rows also surface here with atomic source refs.",
            "Current price preserves printed Akt. Kurs as amount and currency until reviewed enrichment refreshes it.",
            "Target, Stop, and Current price must contain only amount and currency.",
            "Next Report stores only the date; Report type stores the event label.",
            "Recommendation stores the current action/status; Held since stores the source issue for holds.",
            "Insider Activity is reserved for SEC Form 4 signal links from the dedicated tab.",
            "Comments stay on Aktuell; Stocks keeps canonical identity and enrichment status fields.",
            "Import date is the last field and advances on enrichment or a newer mention.",
        ),
        parser_status="parser_backed",
    ),
    GoogleSheetTabSpec(
        "ETF",
        (
            "ETF",
            "WKN",
            "Current price",
            "Price at Recommendation",
            "Distribution/Yield",
            "Recommendation",
            "Issue",
            "Page",
            "Review status",
            "Import date",
        ),
        "ETF recommendations and fund-specific context.",
        frozen_rows=2,
        frozen_columns=2,
        table_starts_at="A2",
        layout_notes=(
            "Reserve row 1 for fund family, holdings, fee, and distribution context.",
            "Rows remain review-gated until ETF parser/export is implemented.",
            "Import date is the last field.",
        ),
    ),
    GoogleSheetTabSpec(
        "Commodities",
        (
            "Commodity",
            "Instrument",
            "Current price",
            "Recommendation",
            "Context",
            "Issue",
            "Page",
            "Review status",
            "Import date",
        ),
        "Commodity recommendations and context.",
        frozen_rows=2,
        frozen_columns=1,
        table_starts_at="A2",
        layout_notes=(
            "Reserve row 1 for commodity spot/futures context.",
            "Rows remain review-gated until commodity parser/export is implemented.",
            "Import date is the last field.",
        ),
    ),
    GoogleSheetTabSpec(
        "Options",
        (
            "Underlying",
            "Derivative WKN",
            "Type",
            "Base price",
            "Omega/Hebel",
            "Runtime",
            "Recommendation",
            "Issue",
            "Page",
            "Review status",
            "Import date",
        ),
        "Option and derivative recommendations.",
        frozen_rows=2,
        frozen_columns=1,
        table_starts_at="A2",
        layout_notes=(
            "Reserve row 1 for option risk notes and stale-data warnings.",
            "Detailed option and derivative rows emit to Derivative Tips to avoid split review queues.",
            "Import date is the last field.",
        ),
    ),
    GoogleSheetTabSpec(
        "Crypto",
        (
            "Crypto",
            "Symbol",
            "Current price",
            "Price at Recommendation",
            "Recommendation",
            "Context",
            "Issue",
            "Page",
            "Review status",
            "Import date",
        ),
        "Crypto recommendations and digital-asset context.",
        frozen_rows=2,
        frozen_columns=1,
        table_starts_at="A2",
        layout_notes=(
            "Reserve row 1 for exchange, liquidity, and risk context.",
            "Rows remain review-gated until crypto parser/export is implemented.",
            "Import date is the last field.",
        ),
    ),
    GoogleSheetTabSpec(
        "Forex",
        (
            "Pair",
            "Current Rate*",
            "Recommendation",
            "Macro context",
            "Issue",
            "Page",
            "Review status",
            "Import date",
        ),
        "Currency-pair recommendations and macro context.",
        frozen_rows=2,
        frozen_columns=1,
        table_starts_at="A2",
        layout_notes=(
            "Reserve row 1 for macro/calendar context.",
            "Rows remain review-gated until forex parser/export is implemented.",
            "Import date is the last field.",
        ),
    ),
    GoogleSheetTabSpec(
        "Example Portfolios",
        ("Portfolio", "Instrument", "WKN", "Position", "Stop", "Issue", "Page", "Review status"),
        "Publisher model portfolio snapshots.",
        frozen_rows=2,
        frozen_columns=2,
        table_starts_at="A2",
        layout_notes=(
            "Use for publisher portfolio context only, not direct app advice.",
            "Detailed AKTIONAER Depot and transaction tables stay in dedicated tabs.",
        ),
    ),
    GoogleSheetTabSpec(
        "Review Queue",
        ("Source ID", "Issue", "Page", "Section", "Problem", "Suggested action", "Status"),
        "Reviewer-only draft extraction queue.",
        frozen_columns=1,
        layout_notes=(
            "Reviewer-only queue for draft issues and parser warnings.",
            "No family-facing export should read directly from this tab.",
        ),
    ),
    GoogleSheetTabSpec(
        "Reviewed Magazine Mentions",
        (
            "Source ID",
            "Issue",
            "Page",
            "Asset class",
            "Name",
            "WKN",
            "ISIN",
            "Recommendation",
            "Magazine Price",
            "Target",
            "Stop",
            "Approved by",
            "Approved at",
        ),
        "Approved stock-centric export rows.",
        frozen_columns=1,
        layout_notes=(
            "Approved source-linked rows only after manual review.",
            "Use neutral source wording such as printed in issue/page.",
        ),
    ),
    GoogleSheetTabSpec(
        "Recommendation Cards",
        (
            "Source ID",
            "Issue",
            "Page",
            "Name",
            "WKN",
            "Chance/Risk",
            "Recommendation type",
            "Magazine Price",
            "Target",
            "Stop",
            "Market cap",
            "P/E Ratio",
            "P/S Ratio",
            "Dividend Yield",
            "Review status",
        ),
        "Structured labelled recommendation-card fields.",
        frozen_columns=1,
        layout_notes=(
            "Parser-backed raw card fields for reviewer traceability.",
            "Stock cards are also mapped into Stocks for dashboard review.",
        ),
        parser_status="planned",
    ),
    GoogleSheetTabSpec(
        "Derivative Tips",
        (
            "Underlying",
            "Derivative",
            "Direction",
            "WKN",
            "Issuer",
            "Ratio",
            "Base value",
            "Strike/Cap",
            "Omega/Hebel",
            "Runtime",
            "Magazine Entry Price",
            "Magazine Current Price",
            "Performance",
            "Target",
            "Stop",
            "Recommendation",
            "Review status",
            "Issue:Page",
            "Import date",
        ),
        "Derivative overview tables and option cards.",
        frozen_columns=2,
        layout_notes=(
            "Parser-backed for derivative recommendation cards and the Derivate-Tipps im Rueckblick table.",
            "Derivative Source IDs stay in row metadata; Issue:Page is visible provenance.",
            "Import date is the last field.",
        ),
        parser_status="parser_backed",
    ),
    GoogleSheetTabSpec(
        "AKTIONAER Depot",
        (
            "Instrument",
            "WKN",
            "Quantity",
            "Buy date",
            "Sale date",
            "Magazine Buy Price",
            "Magazine Current Price",
            "Value",
            "Performance since buy",
            "Stop",
            "Review status",
            "Issue:Page",
            "Import date",
        ),
        "Publisher model-depot position snapshots.",
        frozen_columns=2,
        layout_notes=(
            "Parser-backed for the weekly publisher model-depot snapshot.",
            "Use one row per issue/position once parser-backed.",
            "Import date is the last field.",
        ),
        parser_status="parser_backed",
    ),
    GoogleSheetTabSpec(
        "Depot Transactions",
        (
            "Action",
            "Instrument",
            "WKN",
            "Quantity",
            "Transaction date",
            "Magazine Transaction Price",
            "Performance since buy",
            "Review status",
            "Issue:Page",
            "Import date",
        ),
        "Publisher model-depot transaction ledger.",
        frozen_columns=2,
        layout_notes=(
            "Parser-backed for explicit no-transaction weeks and future transaction rows.",
            "Include explicit no-transaction weeks once parser-backed.",
            "Import date is the last field.",
        ),
        parser_status="parser_backed",
    ),
    GoogleSheetTabSpec(
        "Insider Activity",
        (
            "Company",
            "WKN",
            "Ticker",
            "Insider",
            "Relationship",
            "Shares owned after",
            "Transaction date",
            "Transaction",
            "Direction",
            "Shares",
            "Price in USD",
            "Transaction value",
        ),
        "SEC Form 4 insider activity context for magazine-backed stock candidates.",
        header_row=INSIDER_ACTIVITY_HEADER_ROW,
        metadata_cells=INSIDER_ACTIVITY_INSTRUCTIONS,
        frozen_rows=INSIDER_ACTIVITY_HEADER_ROW,
        frozen_columns=3,
        table_starts_at=f"A{INSIDER_ACTIVITY_HEADER_ROW}",
        layout_notes=(
            "Cumulative SEC EDGAR Form 4 enrichment ledger refreshed on issue import.",
            "Company cells retain direct SEC filing hyperlinks for source provenance.",
            "Filing-transaction identity prevents duplicate rows across weekly imports.",
            "Rows remain private reviewer context until separately approved; Search does not imply review.",
        ),
        parser_status="parser_backed",
    ),
    GoogleSheetTabSpec(
        "Statistics Context",
        ("Issue:Page", "Context type", "Name", "Value", "Period", "Source note", "Review status"),
        "Context-only market, index, sector, and stock statistics.",
        frozen_columns=3,
        layout_notes=(
            "Currently audit-hinted, not row-emitted.",
            "Never create recommendation rows from statistics alone.",
        ),
        parser_status="audit_hint",
    ),
    GoogleSheetTabSpec(
        "Dividend Focus",
        (
            "Instrument",
            "WKN",
            "Period",
            "Magazine Price",
            "Market Cap EUR bn",
            "Dividend Yield",
            "P/E Ratio 26e",
            "Payouts per year",
            "Cum date",
            "Pay date",
            "Target",
            "Stop",
            "Review status",
            "Issue:Page",
            "Import date",
        ),
        "Dividend section and multi-period dividend data.",
        frozen_columns=3,
        layout_notes=(
            "Parser-backed for dividend strategy table rows today.",
            "Keep multi-period dividend context here and concise dividend decision data in Stocks.",
            "Import date is the last field.",
        ),
        parser_status="parser_backed",
    ),
    GoogleSheetTabSpec(
        "Extraction Audit",
        ("Run ID", "Issue:Page", "Section", "Severity", "Message", "Action", "Created at"),
        "Extraction warnings, skipped pages, and parser audit rows.",
        frozen_columns=3,
        layout_notes=(
            "Parser-backed audit destination for section inventory today.",
            "Use as first stop for planned tabs before row emitters exist.",
        ),
        parser_status="parser_backed",
    ),
)

ALL_SHEET_TABS = DEFAULT_SHEET_TABS
RETIRED_GENERATED_SHEET_TAB_TITLES = {
    "Chart Check",
    "Latest Issue",
    "Latest Issue Recommendations",
    "Stock Quickcheck",
}
LEGACY_AKTUELL_TAB_TITLES = ("Latest Issue", "Latest Issue Recommendations")
GENERATED_SHEET_TAB_TITLES = {
    spec.title for spec in ALL_SHEET_TABS
} | RETIRED_GENERATED_SHEET_TAB_TITLES | {SEARCH_SHEET_TAB.title}


DEFAULT_SHEET_TABS = tuple(
    spec for spec in DEFAULT_SHEET_TABS if spec.title in DATA_BACKED_TAB_TITLES
)
ACTIVE_GOOGLE_SHEET_TABS = (
    SEARCH_SHEET_TAB,
    next(spec for spec in DEFAULT_SHEET_TABS if spec.title == "Aktuell"),
    next(spec for spec in DEFAULT_SHEET_TABS if spec.title == "Insider Activity"),
)
REFINEMENT_SHEET_TABS = tuple(spec for spec in ALL_SHEET_TABS if spec.title == "Refinement")


def load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        raise GoogleAccessError(f"env file does not exist: {path}")

    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise GoogleAccessError(f"invalid env line {line_number}: expected KEY=VALUE")

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key:
            raise GoogleAccessError(f"invalid env line {line_number}: key is empty")
        values[key] = value

    return values


def load_google_access_config(
    *,
    env: Mapping[str, str] | None = None,
    env_file: Path | None = None,
) -> GoogleAccessConfig:
    merged = dict(env or os.environ)
    if env_file is not None:
        merged.update(load_env_file(env_file))

    drive_folder_id = _required_value(merged, "GOOGLE_DRIVE_FOLDER_ID")
    spreadsheet_id = _required_value(merged, "GOOGLE_SHEETS_SPREADSHEET_ID")
    credentials_path = Path(_required_value(merged, "GOOGLE_APPLICATION_CREDENTIALS")).expanduser()

    _validate_google_id("GOOGLE_DRIVE_FOLDER_ID", drive_folder_id)
    _validate_google_id("GOOGLE_SHEETS_SPREADSHEET_ID", spreadsheet_id)
    if not credentials_path.exists():
        raise GoogleAccessError(
            f"GOOGLE_APPLICATION_CREDENTIALS does not exist: {credentials_path}"
        )
    service_account_email = (
        str(merged.get("GOOGLE_SERVICE_ACCOUNT_EMAIL") or "").strip()
        or _service_account_email_from_credentials(credentials_path)
    )

    return GoogleAccessConfig(
        drive_folder_id=drive_folder_id,
        sheets_spreadsheet_id=spreadsheet_id,
        credentials_path=credentials_path,
        service_account_email=service_account_email,
    )


def run_google_access_smoke(
    config: GoogleAccessConfig,
    *,
    drive_service_factory=None,
    sheets_service_factory=None,
) -> dict[str, object]:
    """Check scoped access to the configured Drive folder and Sheet."""

    if drive_service_factory is None or sheets_service_factory is None:
        drive_service_factory, sheets_service_factory = _google_service_factories(config)

    drive = drive_service_factory()
    sheets = sheets_service_factory()
    try:
        folder = (
            drive.files()
            .get(fileId=config.drive_folder_id, fields="id,mimeType", supportsAllDrives=True)
            .execute()
        )
        spreadsheet = (
            sheets.spreadsheets()
            .get(
                spreadsheetId=config.sheets_spreadsheet_id,
                fields="spreadsheetId,sheets.properties.sheetId",
            )
            .execute()
        )
    except Exception as error:
        raise GoogleAccessError(
            "Google Drive/Sheets smoke check failed. Verify network access, API enablement, "
            "service-account sharing, and configured folder/sheet IDs."
        ) from error

    if folder.get("mimeType") != "application/vnd.google-apps.folder":
        raise GoogleAccessError("GOOGLE_DRIVE_FOLDER_ID is accessible but is not a Drive folder")

    return {
        "ok": True,
        "externalServicesEnabled": True,
        "serviceAccountEmail": _redacted_identifier(config.service_account_email),
        "drive": {
            "folderId": _redacted_identifier(folder.get("id")),
            "mimeType": folder.get("mimeType"),
        },
        "sheets": {
            "spreadsheetId": _redacted_identifier(spreadsheet.get("spreadsheetId")),
            "tabCount": len(spreadsheet.get("sheets", [])),
        },
    }


def bootstrap_google_sheet(
    config: GoogleAccessConfig,
    *,
    sheets_service_factory=None,
    tab_specs: tuple[GoogleSheetTabSpec, ...] = ACTIVE_GOOGLE_SHEET_TABS,
    write_headers: bool = True,
    prune_extra_tabs: bool = True,
) -> dict[str, object]:
    """Create missing workbook tabs and write stable header rows.

    The operation only writes sheet structure and header labels. It does not
    export recommendations or private PDF-derived rows.
    """

    if sheets_service_factory is None:
        _drive_service_factory, sheets_service_factory = _google_service_factories(config)

    sheets = sheets_service_factory()
    try:
        spreadsheet = (
            sheets.spreadsheets()
            .get(
                spreadsheetId=config.sheets_spreadsheet_id,
                fields=(
                    "spreadsheetId,properties.title,"
                    "sheets(properties(sheetId,title),conditionalFormats)"
                ),
            )
            .execute()
        )
        sheet_properties = _sheet_properties_with_formats(spreadsheet)
        renamed_tabs: list[dict[str, str]] = []
        existing_title_set = {str(properties.get("title")) for properties in sheet_properties}
        requests_current_insider_schema = any(
            spec.title == "Insider Activity"
            and spec.headers != LEGACY_INSIDER_ACTIVITY_HEADERS
            for spec in tab_specs
        )
        if requests_current_insider_schema and "Insider Activity" in existing_title_set:
            current_header = _sheet_values_get(
                sheets,
                spreadsheet_id=config.sheets_spreadsheet_id,
                range_name=f"'Insider Activity'!A1:S{INSIDER_ACTIVITY_HEADER_ROW}",
                value_render_option="FORMULA",
            )
            insider_spec = next(
                spec for spec in tab_specs if spec.title == "Insider Activity"
            )
            existing_schema, header_index = _insider_header_location(
                current_header,
                spec=insider_spec,
            )
            if existing_schema == "legacy":
                raise GoogleAccessError(
                    "Legacy Insider Activity schema must be migrated before bootstrap"
                )
            if existing_schema == "current" and header_index != insider_spec.header_row - 1:
                raise GoogleAccessError(
                    "Insider Activity instructions must be migrated through the "
                    "insider writer before bootstrap"
                )
        if "Aktuell" not in existing_title_set:
            legacy_properties = next(
                (
                    properties
                    for legacy_title in LEGACY_AKTUELL_TAB_TITLES
                    for properties in sheet_properties
                    if properties.get("title") == legacy_title and "sheetId" in properties
                ),
                None,
            )
            if legacy_properties is not None:
                legacy_title = str(legacy_properties["title"])
                sheets.spreadsheets().batchUpdate(
                    spreadsheetId=config.sheets_spreadsheet_id,
                    body={
                        "requests": [
                            {
                                "updateSheetProperties": {
                                    "properties": {
                                        "sheetId": int(legacy_properties["sheetId"]),
                                        "title": "Aktuell",
                                        "index": 1,
                                    },
                                    "fields": "title,index",
                                }
                            }
                        ]
                    },
                ).execute()
                renamed_tabs.append({"from": legacy_title, "to": "Aktuell"})
                spreadsheet = (
                    sheets.spreadsheets()
                    .get(
                        spreadsheetId=config.sheets_spreadsheet_id,
                        fields=(
                            "spreadsheetId,properties.title,"
                            "sheets(properties(sheetId,title),conditionalFormats)"
                        ),
                    )
                    .execute()
                )
                sheet_properties = _sheet_properties_with_formats(spreadsheet)
        existing_titles = tuple(str(properties.get("title")) for properties in sheet_properties)
        missing_titles = tuple(
            spec.title for spec in tab_specs if spec.title not in set(existing_titles)
        )
        desired_titles = {spec.title for spec in tab_specs}
        delete_sheet_ids = tuple(
            int(properties["sheetId"])
            for properties in sheet_properties
            if prune_extra_tabs
            and properties.get("title") not in desired_titles
            and properties.get("title") in GENERATED_SHEET_TAB_TITLES
            and "sheetId" in properties
        )

        structure_requests = [
            {"addSheet": {"properties": {"title": title}}}
            for title in missing_titles
        ] + [
            {"deleteSheet": {"sheetId": sheet_id}}
            for sheet_id in delete_sheet_ids
        ]
        if structure_requests:
            sheets.spreadsheets().batchUpdate(
                spreadsheetId=config.sheets_spreadsheet_id,
                body={"requests": structure_requests},
            ).execute()
            spreadsheet = (
                sheets.spreadsheets()
                .get(
                    spreadsheetId=config.sheets_spreadsheet_id,
                    fields=(
                        "spreadsheetId,properties.title,"
                        "sheets(properties(sheetId,title),conditionalFormats)"
                    ),
                )
                .execute()
            )
            sheet_properties = _sheet_properties_with_formats(spreadsheet)

        primary_tab_titles = tuple(spec.title for spec in ACTIVE_GOOGLE_SHEET_TABS)
        existing_primary_titles = [
            str(properties.get("title"))
            for properties in sheet_properties
            if properties.get("title") in primary_tab_titles
        ]
        desired_primary_titles = [
            title
            for title in primary_tab_titles
            if any(properties.get("title") == title for properties in sheet_properties)
        ]
        if existing_primary_titles != desired_primary_titles or [
            str(properties.get("title"))
            for properties in sheet_properties[: len(desired_primary_titles)]
        ] != desired_primary_titles:
            primary_properties = {
                str(properties["title"]): properties
                for properties in sheet_properties
                if properties.get("title") in desired_primary_titles
                and "sheetId" in properties
            }
            sheets.spreadsheets().batchUpdate(
                spreadsheetId=config.sheets_spreadsheet_id,
                body={
                    "requests": [
                        {
                            "updateSheetProperties": {
                                "properties": {
                                    "sheetId": int(primary_properties[title]["sheetId"]),
                                    "index": index,
                                },
                                "fields": "index",
                            }
                        }
                        for index, title in enumerate(desired_primary_titles)
                    ]
                },
            ).execute()

        pre_header_clear_ranges = (
            _build_sheet_pre_header_clear_ranges(tab_specs) if write_headers else ()
        )
        for range_name in pre_header_clear_ranges:
            sheets.spreadsheets().values().clear(
                spreadsheetId=config.sheets_spreadsheet_id,
                range=range_name,
                body={},
            ).execute()
        header_ranges = (
            _build_sheet_header_ranges(tab_specs, sheet_properties=sheet_properties)
            if write_headers
            else ()
        )
        if header_ranges:
            sheets.spreadsheets().values().batchUpdate(
                spreadsheetId=config.sheets_spreadsheet_id,
                body={
                    "valueInputOption": "USER_ENTERED",
                    "data": list(header_ranges),
                },
            ).execute()
        grid_property_requests = _build_sheet_grid_property_requests(
            tab_specs,
            sheet_properties,
        )
        format_requests = _build_conditional_format_requests(tab_specs, sheet_properties)
        layout_requests = grid_property_requests + format_requests
        if layout_requests:
            sheets.spreadsheets().batchUpdate(
                spreadsheetId=config.sheets_spreadsheet_id,
                body={"requests": list(layout_requests)},
            ).execute()
        insider_instruction_presentation: dict[str, int] | None = None
        insider_sheet_id = next(
            (
                int(properties["sheetId"])
                for properties in sheet_properties
                if properties.get("title") == "Insider Activity"
                and "sheetId" in properties
                and any(spec.title == "Insider Activity" for spec in tab_specs)
            ),
            None,
        )
        if write_headers and insider_sheet_id is not None:
            insider_instruction_presentation = _apply_insider_instruction_presentation(
                sheets,
                spreadsheet_id=config.sheets_spreadsheet_id,
                sheet_id=insider_sheet_id,
            )
    except GoogleAccessError:
        raise
    except Exception as error:
        raise GoogleAccessError(
            "Google Sheets bootstrap failed. Verify network access, API enablement, "
            "service-account sheet sharing, and configured spreadsheet ID."
        ) from error

    return {
        "ok": True,
        "externalServicesEnabled": True,
        "spreadsheetId": _redacted_identifier(config.sheets_spreadsheet_id),
        "existingTabs": list(existing_titles),
        "createdTabs": list(missing_titles),
        "renamedTabs": renamed_tabs,
        "deletedTabCount": len(delete_sheet_ids),
        "headerRowsWritten": len(tab_specs) if write_headers else 0,
        "preHeaderRangesCleared": list(pre_header_clear_ranges)
        if "pre_header_clear_ranges" in locals()
        else [],
        "gridPropertiesWritten": len(grid_property_requests)
        if "grid_property_requests" in locals()
        else 0,
        "formatRulesWritten": len(format_requests) if "format_requests" in locals() else 0,
        "insiderInstructionPresentation": insider_instruction_presentation,
        "tabs": [
            {
                "title": spec.title,
                "headers": list(spec.headers),
                "headerRow": spec.header_row,
                "metadataCells": [
                    {"cell": cell, "value": value}
                    for cell, value in spec.metadata_cells
                ],
                "frozenRows": spec.frozen_rows,
                "frozenColumns": spec.frozen_columns,
                "tableStartsAt": spec.table_starts_at,
                "parserStatus": spec.parser_status,
                "layoutNotes": list(spec.layout_notes),
                "purpose": spec.purpose,
            }
            for spec in tab_specs
        ],
    }


def clear_google_sheet_data_rows(
    config: GoogleAccessConfig,
    *,
    sheets_service_factory=None,
    tab_specs: tuple[GoogleSheetTabSpec, ...] = ACTIVE_GOOGLE_SHEET_TABS,
    write_headers: bool = True,
) -> dict[str, object]:
    """Clear all configured workbook data rows while preserving headers.

    This is a hard reset for generated/review rows. It clears only values below
    each tab's configured header row, then optionally rewrites headers so a
    fresh scan starts from a stable workbook structure.
    """

    if sheets_service_factory is None:
        _drive_service_factory, sheets_service_factory = _google_service_factories(config)

    sheets = sheets_service_factory()
    bootstrap_result = bootstrap_google_sheet(
        config,
        sheets_service_factory=sheets_service_factory,
        tab_specs=tab_specs,
        write_headers=write_headers,
    )
    clear_ranges = _build_sheet_body_clear_ranges(tab_specs)
    try:
        for range_name in clear_ranges:
            sheets.spreadsheets().values().clear(
                spreadsheetId=config.sheets_spreadsheet_id,
                range=range_name,
                body={},
            ).execute()
    except Exception as error:
        raise GoogleAccessError(
            "Google Sheets data reset failed. Verify network access, API enablement, "
            "service-account sheet sharing, and configured spreadsheet ID."
        ) from error

    return {
        "ok": True,
        "externalServicesEnabled": True,
        "spreadsheetId": _redacted_identifier(config.sheets_spreadsheet_id),
        "clearedRanges": list(clear_ranges),
        "clearedTabCount": len(clear_ranges),
        "headersRewritten": write_headers,
        "bootstrap": bootstrap_result,
    }


def refresh_google_sheet_search(
    config: GoogleAccessConfig,
    *,
    sheets_service_factory=None,
) -> dict[str, object]:
    """Refresh issue and insider Search data without exporting magazine rows."""

    if sheets_service_factory is None:
        _drive_service_factory, sheets_service_factory = _google_service_factories(config)

    sheets = sheets_service_factory()
    bootstrap_result = bootstrap_google_sheet(
        config,
        sheets_service_factory=sheets_service_factory,
        tab_specs=ACTIVE_GOOGLE_SHEET_TABS,
        write_headers=True,
    )
    sheet_ids_by_title = _fetch_sheet_ids_by_title(
        sheets,
        spreadsheet_id=config.sheets_spreadsheet_id,
    )
    try:
        indexed_row_count = _refresh_issue_search_sheet(
            sheets,
            spreadsheet_id=config.sheets_spreadsheet_id,
            sheet_ids_by_title=sheet_ids_by_title,
        )
        protected_tabs = _apply_managed_sheet_protections(
            sheets,
            spreadsheet_id=config.sheets_spreadsheet_id,
            editor_email=config.service_account_email,
        )
    except Exception as error:
        raise GoogleAccessError(
            "Google Sheets search refresh failed. Verify network access, API enablement, "
            "service-account sheet sharing, and configured spreadsheet ID."
        ) from error
    return {
        "ok": True,
        "externalServicesEnabled": True,
        "spreadsheetId": _redacted_identifier(config.sheets_spreadsheet_id),
        "searchIndexedRows": indexed_row_count,
        "protectedTabs": protected_tabs,
        "bootstrap": bootstrap_result,
    }


def write_insider_activity_rows_to_google_sheet(
    config: GoogleAccessConfig,
    rows: Sequence[Sequence[object]],
    *,
    source_urls: Sequence[str] = (),
    excluded_source_urls: Sequence[str] = (),
    sheets_service_factory=None,
) -> dict[str, object]:
    """Merge deduplicated SEC Form 4 rows and refresh the unified Search tab."""

    if sheets_service_factory is None:
        _drive_service_factory, sheets_service_factory = _google_service_factories(config)
    spec = next(
        candidate
        for candidate in ACTIVE_GOOGLE_SHEET_TABS
        if candidate.title == "Insider Activity"
    )
    incoming = [
        _normalize_sheet_row_values(list(row), width=len(spec.headers))
        for row in rows
    ]
    for row in rows:
        _validate_sheet_row_width(spec.title, list(row), width=len(spec.headers))
    if source_urls and len(source_urls) != len(incoming):
        raise GoogleAccessError("Insider Activity source URL count does not match rows")
    incoming_urls = list(source_urls) if source_urls else ["" for _ in incoming]
    excluded_urls = {
        str(source_url or "").strip()
        for source_url in excluded_source_urls
        if str(source_url or "").strip()
    }
    incoming_with_urls = [
        (row, source_url)
        for row, source_url in zip(incoming, incoming_urls)
        if _is_importable_insider_transaction(row, spec=spec)
        and str(source_url or "").strip() not in excluded_urls
    ]
    incoming_excluded_count = len(incoming) - len(incoming_with_urls)
    incoming = [row for row, _source_url in incoming_with_urls]
    incoming_urls = [source_url for _row, source_url in incoming_with_urls]

    sheets = sheets_service_factory()
    existing_sheet_ids = _fetch_sheet_ids_by_title(
        sheets,
        spreadsheet_id=config.sheets_spreadsheet_id,
    )
    existing_raw = (
        _sheet_values_get(
            sheets,
            spreadsheet_id=config.sheets_spreadsheet_id,
            range_name="'Insider Activity'!A1:S",
            value_render_option="FORMULA",
        )
        if spec.title in existing_sheet_ids
        else []
    )
    existing_schema, existing_header_index = _insider_header_location(
        existing_raw,
        spec=spec,
    )
    existing = _insider_records_from_sheet_values(existing_raw, spec=spec)
    existing_retained = [
        record
        for record in existing
        if _is_importable_insider_transaction(record["values"], spec=spec)
        and str(record.get("source_url") or "").strip() not in excluded_urls
    ]
    existing_excluded_count = len(existing) - len(existing_retained)
    existing = existing_retained
    legacy_existing = existing_schema == "legacy"
    layout_migration_required = (
        existing_schema != "empty"
        and existing_header_index != spec.header_row - 1
    )
    bootstrap_specs = (
        tuple(candidate for candidate in ACTIVE_GOOGLE_SHEET_TABS if candidate.title != spec.title)
        if layout_migration_required
        else ACTIVE_GOOGLE_SHEET_TABS
    )
    bootstrap_result = bootstrap_google_sheet(
        config,
        sheets_service_factory=sheets_service_factory,
        tab_specs=bootstrap_specs,
        write_headers=True,
        prune_extra_tabs=not layout_migration_required,
    )
    sheet_ids_by_title = _fetch_sheet_ids_by_title(
        sheets,
        spreadsheet_id=config.sheets_spreadsheet_id,
    )
    sheet_id = sheet_ids_by_title.get(spec.title)
    if sheet_id is None:
        raise GoogleAccessError("Insider Activity tab is missing after workbook bootstrap")
    wkn_index = spec.headers.index("WKN")
    merged = {
        _insider_record_identity(record, spec=spec): record
        for record in existing
    }
    added_count = 0
    updated_count = 0
    for row, source_url in zip(incoming, incoming_urls):
        record = {"values": list(row), "source_url": str(source_url or "").strip()}
        key = _insider_record_identity(record, spec=spec)
        if key not in merged:
            merged[key] = record
            added_count += 1
            continue
        current = merged[key]
        current_values = list(current["values"])
        incoming_values = list(row)
        merged_wkn = _join_unique_sheet_values(
            (current_values[wkn_index], row[wkn_index]), separator=" | "
        )
        incoming_values[wkn_index] = merged_wkn
        merged[key] = {
            # The freshly generated SEC projection is authoritative. This also
            # repairs an interrupted prior write whose row was only partially
            # populated, while retaining identity aliases and provenance.
            "values": incoming_values,
            "source_url": str(source_url or current.get("source_url") or "").strip(),
        }
        updated_count += 1

    transaction_date_index = spec.headers.index("Transaction date")
    company_index = spec.headers.index("Company")
    combined = sorted(
        merged.values(),
        key=lambda record: (
            record["values"][transaction_date_index],
            record["values"][company_index].casefold(),
        ),
        reverse=True,
    )
    basic_filter = _fetch_basic_filter_for_sheet(
        sheets,
        spreadsheet_id=config.sheets_spreadsheet_id,
        sheet_id=sheet_id,
    )
    basic_filter["range"] = {
        "sheetId": sheet_id,
        "startRowIndex": spec.header_row - 1,
        "endRowIndex": len(combined) + spec.header_row,
        "startColumnIndex": 0,
        "endColumnIndex": len(spec.headers),
    }
    body_start = spec.header_row + 1
    body_end = spec.header_row + len(combined)
    try:
        sheets.spreadsheets().batchUpdate(
            spreadsheetId=config.sheets_spreadsheet_id,
            body={
                "requests": [
                    {
                        "updateSheetProperties": {
                            "properties": {
                                "sheetId": sheet_id,
                                "index": 2,
                                "gridProperties": {
                                    "rowCount": max(
                                        100,
                                        len(combined) + spec.header_row + 9,
                                    ),
                                    "columnCount": (
                                        len(LEGACY_INSIDER_ACTIVITY_HEADERS)
                                        if legacy_existing
                                        else len(spec.headers)
                                    ),
                                    "frozenRowCount": spec.frozen_rows,
                                    "frozenColumnCount": spec.frozen_columns,
                                },
                            },
                            "fields": (
                                "index,gridProperties.rowCount,"
                                "gridProperties.columnCount,"
                                "gridProperties.frozenRowCount,"
                                "gridProperties.frozenColumnCount"
                            ),
                        }
                    }
                ]
            },
        ).execute()
        user_entered_ranges = list(_build_sheet_header_ranges((spec,)))
        if combined:
            user_entered_ranges.append(
                {
                    "range": f"'Insider Activity'!A{body_start}:A{body_end}",
                    "values": [
                        [
                            _insider_company_formula(
                                record["values"][company_index],
                                str(record.get("source_url") or ""),
                            )
                        ]
                        for record in combined
                    ],
                }
            )
        sheets.spreadsheets().values().batchUpdate(
            spreadsheetId=config.sheets_spreadsheet_id,
            body={
                "valueInputOption": "USER_ENTERED",
                "data": user_entered_ranges,
            },
        ).execute()
        if combined:
            sheets.spreadsheets().values().batchUpdate(
                spreadsheetId=config.sheets_spreadsheet_id,
                body={
                    "valueInputOption": "RAW",
                    "data": [
                        {
                            "range": f"'Insider Activity'!B{body_start}:L{body_end}",
                            "values": [record["values"][1:] for record in combined],
                        }
                    ],
                },
            ).execute()
        # A legacy row-1 ledger leaves its former headers and first record to
        # the right of the A:C instruction merge. Clear that unmerged area only
        # after all replacement values have been written successfully.
        sheets.spreadsheets().values().clear(
            spreadsheetId=config.sheets_spreadsheet_id,
            range="'Insider Activity'!D1:L2",
            body={},
        ).execute()
        sheets.spreadsheets().values().clear(
            spreadsheetId=config.sheets_spreadsheet_id,
            range=f"'Insider Activity'!A{body_end + 1}:L",
            body={},
        ).execute()
        if legacy_existing:
            sheets.spreadsheets().values().clear(
                spreadsheetId=config.sheets_spreadsheet_id,
                range="'Insider Activity'!M:S",
                body={},
            ).execute()
        if layout_migration_required:
            bootstrap_result = bootstrap_google_sheet(
                config,
                sheets_service_factory=sheets_service_factory,
                tab_specs=ACTIVE_GOOGLE_SHEET_TABS,
                write_headers=True,
            )
        sheets.spreadsheets().batchUpdate(
            spreadsheetId=config.sheets_spreadsheet_id,
            body={
                "requests": [
                    {
                        "updateSheetProperties": {
                            "properties": {
                                "sheetId": sheet_id,
                                "gridProperties": {
                                    "columnCount": len(spec.headers),
                                },
                            },
                            "fields": "gridProperties.columnCount",
                        }
                    },
                    {
                        "autoResizeDimensions": {
                            "dimensions": {
                                "sheetId": sheet_id,
                                "dimension": "COLUMNS",
                                "startIndex": 0,
                                "endIndex": len(spec.headers),
                            }
                        }
                    },
                    {"setBasicFilter": {"filter": basic_filter}},
                ]
            },
        ).execute()
        managed_filter_views = _apply_managed_insider_filter_views(
            sheets,
            spreadsheet_id=config.sheets_spreadsheet_id,
            sheet_id=sheet_id,
            data_row_count=len(combined),
        )
        search_indexed_row_count = _refresh_issue_search_sheet(
            sheets,
            spreadsheet_id=config.sheets_spreadsheet_id,
            sheet_ids_by_title=sheet_ids_by_title,
        )
        protected_tabs = _apply_managed_sheet_protections(
            sheets,
            spreadsheet_id=config.sheets_spreadsheet_id,
            editor_email=config.service_account_email,
        )
    except Exception as error:
        raise GoogleAccessError(
            "Google Sheets insider activity merge failed. Verify network access, "
            "service-account sheet sharing, and workbook protections."
        ) from error
    return {
        "ok": True,
        "externalServicesEnabled": True,
        "rowsAdded": added_count,
        "rowsUpdated": updated_count,
        "rowsRetained": len(combined),
        "rowsExcludedByTransactionType": (
            incoming_excluded_count + existing_excluded_count
        ),
        "duplicateRowsPrevented": updated_count,
        "searchIndexedRows": search_indexed_row_count,
        "protectedTabs": protected_tabs,
        "managedFilterViews": managed_filter_views,
        "bootstrap": bootstrap_result,
    }


def _insider_records_from_sheet_values(
    raw_values: Sequence[Sequence[object]],
    *,
    spec: GoogleSheetTabSpec,
) -> list[dict[str, object]]:
    schema, header_index = _insider_header_location(raw_values, spec=spec)
    if schema == "empty":
        return []
    if schema == "legacy":
        source_headers = LEGACY_INSIDER_ACTIVITY_HEADERS
    else:
        source_headers = spec.headers
    header_indexes = {header: index for index, header in enumerate(source_headers)}
    result: list[dict[str, object]] = []
    assert header_index is not None
    for raw_row in raw_values[header_index + 1:]:
        if not any(str(value or "").strip() for value in raw_row):
            continue

        def value(header: str) -> str:
            index = header_indexes.get(header)
            return str(raw_row[index] or "").strip() if index is not None and index < len(raw_row) else ""

        company, formula_url = _parse_insider_company_formula(value("Company"))
        transaction = _simplify_insider_transaction(
            value("Transaction") or value("Transaction code")
        )
        values = [
            company,
            value("WKN"),
            value("Ticker"),
            value("Insider"),
            value("Relationship"),
            value("Shares owned after"),
            value("Transaction date"),
            transaction,
            value("Direction"),
            value("Shares"),
            value("Price in USD") or value("Price"),
            value("Transaction value"),
        ]
        result.append(
            {
                "values": values,
                "source_url": formula_url or value("SEC filing URL"),
            }
        )
    return result


def _insider_header_schema(
    raw_values: Sequence[Sequence[object]],
    *,
    spec: GoogleSheetTabSpec,
) -> str:
    """Classify the ledger header without accepting partial or drifted schemas."""

    return _insider_header_location(raw_values, spec=spec)[0]


def _insider_header_location(
    raw_values: Sequence[Sequence[object]],
    *,
    spec: GoogleSheetTabSpec,
) -> tuple[str, int | None]:
    """Return the recognized schema and its zero-based header row."""

    if not raw_values:
        return "empty", None
    for header_index in (0, spec.header_row - 1):
        if header_index >= len(raw_values):
            continue
        normalized = [
            str(value or "").strip()
            for value in raw_values[header_index]
        ]
        while normalized and not normalized[-1]:
            normalized.pop()
        headers = tuple(normalized)
        if headers == LEGACY_INSIDER_ACTIVITY_HEADERS:
            return "legacy", header_index
        if headers == spec.headers:
            return "current", header_index
    if not any(
        str(value or "").strip()
        for row in raw_values
        for value in row
    ):
        return "empty", None
    raise GoogleAccessError(
        "Insider Activity header does not match the current or recognized legacy schema"
    )


def _insider_record_identity(
    record: Mapping[str, object],
    *,
    spec: GoogleSheetTabSpec,
) -> str:
    source_url = str(record.get("source_url") or "").strip()
    if source_url:
        return source_url
    values = record.get("values")
    row = list(values) if isinstance(values, Sequence) and not isinstance(values, str) else []
    return "|".join(
        str(row[index] if index < len(row) else "").strip()
        for index in range(len(spec.headers))
        if index != spec.headers.index("WKN")
    )


def _simplify_insider_transaction(code: str) -> str:
    normalized = code.strip()
    return {
        "P": "purchase",
        "S": "sale",
        "M": "Conversion",
        "F": "Payment",
        "G": "Gift",
        "A": "Awarded",
        "J": "Other",
        "PURCHASE": "purchase",
        "SALE": "sale",
        "CONVERSION": "Conversion",
        "PAYMENT": "Payment",
        "GIFT": "Gift",
        "AWARDED": "Awarded",
        "OTHER": "Other",
    }.get(normalized.upper(), "Other")


def _is_importable_insider_transaction(
    values: Sequence[object],
    *,
    spec: GoogleSheetTabSpec,
) -> bool:
    transaction_index = spec.headers.index("Transaction")
    transaction = str(
        values[transaction_index] if transaction_index < len(values) else ""
    )
    return _simplify_insider_transaction(transaction) in {"purchase", "sale"}


def _insider_company_formula(company: str, source_url: str) -> str:
    safe_company = company.replace('"', '""')
    safe_url = source_url.replace('"', '""')
    if safe_url:
        return f'=HYPERLINK("{safe_url}","{safe_company}")'
    return f'=T("{safe_company}")'


def _parse_insider_company_formula(value: str) -> tuple[str, str]:
    match = re.fullmatch(
        r'=HYPERLINK\("(?P<url>(?:[^"]|"")*)","(?P<company>(?:[^"]|"")*)"\)',
        value.strip(),
        flags=re.IGNORECASE,
    )
    if match is None:
        return value, ""
    return (
        match.group("company").replace('""', '"'),
        match.group("url").replace('""', '"'),
    )


def preflight_workbook_plan_google_sheet_export(
    workbook_plan: Mapping[str, object],
    *,
    tab_specs: tuple[GoogleSheetTabSpec, ...] = DEFAULT_SHEET_TABS,
    allow_draft_rows: bool = False,
) -> None:
    """Validate a workbook plan without creating clients or mutating Sheets."""

    issue_id = str(workbook_plan.get("issueId") or "").strip()
    raw_rows = workbook_plan.get("rows")
    if not issue_id:
        raise GoogleAccessError("workbook plan is missing issueId")
    if not isinstance(raw_rows, list):
        raise GoogleAccessError("workbook plan is missing rows list")
    _issue_tab_title(issue_id)
    if not allow_draft_rows:
        _require_family_export_approval_audit(workbook_plan, raw_rows)

    specs_by_title = {spec.title: spec for spec in tab_specs}
    if "Aktuell" not in specs_by_title:
        raise GoogleAccessError("workbook export tab specs are missing Aktuell")
    if not allow_draft_rows:
        _require_no_unresolved_family_rows(raw_rows, specs_by_title=specs_by_title)
    for raw_row in raw_rows:
        if not isinstance(raw_row, Mapping):
            continue
        if not allow_draft_rows and not _is_approved_export_row(raw_row):
            continue
        tab = str(raw_row.get("tab") or "").strip()
        spec = specs_by_title.get(tab)
        values = raw_row.get("values")
        if spec is None or spec.parser_status == "layout_only" or not isinstance(values, list):
            continue
        aktuell_derivative_row = tab == "Aktuell" and "derivative" in str(
            raw_row.get("rowKind") or ""
        )
        row_width = (
            len(AKTUELL_DERIVATIVE_HEADERS)
            if aktuell_derivative_row
            else len(spec.headers)
        )
        legacy_derivative_row = (
            aktuell_derivative_row
            and len(values) == len(LEGACY_AKTUELL_DERIVATIVE_HEADERS)
        )
        if not (
            legacy_derivative_row
            or (
                aktuell_derivative_row
                and len(values) == len(spec.headers)
                and len(values) != row_width
            )
        ):
            _validate_sheet_row_width(tab, values, width=row_width)


def write_workbook_plan_to_google_sheet(
    config: GoogleAccessConfig,
    workbook_plan: Mapping[str, object],
    *,
    sheets_service_factory=None,
    tab_specs: tuple[GoogleSheetTabSpec, ...] = DEFAULT_SHEET_TABS,
    replace_issue: bool = True,
    allow_draft_rows: bool = False,
) -> dict[str, object]:
    """Write approved workbook-plan rows to configured Google Sheet.

    This only writes rows already produced by local magazine extraction. It does
    not call enrichment providers and does not mark rows as approved. Draft
    rows require an explicit reviewer-workbook opt-in.
    """

    preflight_workbook_plan_google_sheet_export(
        workbook_plan,
        tab_specs=tab_specs,
        allow_draft_rows=allow_draft_rows,
    )
    if sheets_service_factory is None:
        _drive_service_factory, sheets_service_factory = _google_service_factories(config)

    issue_id = str(workbook_plan.get("issueId") or "").strip()
    raw_rows = workbook_plan.get("rows")
    assert isinstance(raw_rows, list)  # established by the pure preflight above

    specs_by_title = {spec.title: spec for spec in tab_specs}
    rows_by_tab: dict[str, list[list[str]]] = {}
    aktuell_rows: list[tuple[str, list[str]]] = []
    skipped_count = 0
    omitted_inactive_tab_count = 0
    for raw_row in raw_rows:
        if not isinstance(raw_row, Mapping):
            skipped_count += 1
            continue
        if not allow_draft_rows and not _is_approved_export_row(raw_row):
            skipped_count += 1
            continue
        tab = str(raw_row.get("tab") or "").strip()
        spec = specs_by_title.get(tab)
        values = raw_row.get("values")
        if spec is None or spec.parser_status == "layout_only" or not isinstance(values, list):
            skipped_count += 1
            continue
        aktuell_derivative_row = tab == "Aktuell" and "derivative" in str(
            raw_row.get("rowKind") or ""
        )
        row_width = (
            len(AKTUELL_DERIVATIVE_HEADERS)
            if aktuell_derivative_row
            else len(spec.headers)
        )
        if aktuell_derivative_row and len(values) == len(LEGACY_AKTUELL_DERIVATIVE_HEADERS):
            normalized_values = _project_legacy_aktuell_derivative_values(values)
        elif (
            aktuell_derivative_row
            and len(values) == len(spec.headers)
            and len(values) != row_width
        ):
            normalized_values = _normalize_sheet_row_values(values, width=row_width)
        else:
            _validate_sheet_row_width(tab, values, width=row_width)
            normalized_values = _normalize_sheet_row_values(values, width=row_width)
        if tab == "Stocks":
            normalized_values = _sanitize_stock_sheet_row(normalized_values, spec=spec)
        if tab != "Aktuell":
            omitted_inactive_tab_count += 1
            continue
        if tab == "Aktuell":
            aktuell_rows.append((str(raw_row.get("rowKind") or ""), normalized_values))
        else:
            rows_by_tab.setdefault(tab, []).append(normalized_values)

    sheets = sheets_service_factory()
    bootstrap_result = bootstrap_google_sheet(
        config,
        sheets_service_factory=sheets_service_factory,
        tab_specs=ACTIVE_GOOGLE_SHEET_TABS,
        write_headers=True,
    )
    sheet_ids_by_title = _fetch_sheet_ids_by_title(
        sheets,
        spreadsheet_id=config.sheets_spreadsheet_id,
    )
    issue_tab_title = _issue_tab_title(issue_id)
    issue_tab_spec = _issue_review_tab_spec(issue_tab_title, specs_by_title["Aktuell"])
    _ensure_issue_review_tab(
        sheets,
        spreadsheet_id=config.sheets_spreadsheet_id,
        spec=issue_tab_spec,
        sheet_ids_by_title=sheet_ids_by_title,
    )
    reordered_issue_tabs = _reorder_issue_review_tabs_newest_first(
        sheets,
        spreadsheet_id=config.sheets_spreadsheet_id,
    )
    sheet_ids_by_title = _fetch_sheet_ids_by_title(
        sheets,
        spreadsheet_id=config.sheets_spreadsheet_id,
    )
    latest_issue_tab_title = _latest_issue_tab_title(sheet_ids_by_title)
    updates_aktuell = issue_tab_title == latest_issue_tab_title
    try:
        write_ranges: list[dict[str, object]] = []
        post_write_clear_ranges: list[str] = []
        cleared_tabs: list[str] = []
        restored_existing_count = 0
        stock_rows = [values for kind, values in aktuell_rows if "stock" in kind]
        derivative_rows = [values for kind, values in aktuell_rows if "stock" not in kind]
        aktuell_layouts: list[tuple[str, tuple[int, int, int, int, int]]] = []
        issue_layout = _append_issue_recommendation_table_write_ranges(
            write_ranges,
            tab_title=issue_tab_title,
            spec=issue_tab_spec,
            stock_rows=stock_rows,
            derivative_rows=derivative_rows,
        )
        aktuell_layouts.append((issue_tab_title, issue_layout))
        post_write_clear_ranges.extend(
            _issue_recommendation_table_clear_ranges(issue_tab_title, issue_layout)
        )
        cleared_tabs.append(issue_tab_title)
        if updates_aktuell:
            aktuell_layout = _append_issue_recommendation_table_write_ranges(
                write_ranges,
                tab_title="Aktuell",
                spec=specs_by_title["Aktuell"],
                stock_rows=stock_rows,
                derivative_rows=derivative_rows,
            )
            aktuell_layouts.append(("Aktuell", aktuell_layout))
            post_write_clear_ranges.extend(
                _issue_recommendation_table_clear_ranges("Aktuell", aktuell_layout)
            )
            cleared_tabs.append("Aktuell")
        for tab, new_rows in rows_by_tab.items():
            spec = specs_by_title[tab]
            body_start = spec.header_row + 1
            body_range = (
                f"{_quote_sheet_title(tab)}!A{body_start}:"
                f"{_column_letter(len(spec.headers))}"
            )
            existing_rows = _sheet_values_get(
                sheets,
                spreadsheet_id=config.sheets_spreadsheet_id,
                range_name=body_range,
            )
            if tab == "Aktuell" and replace_issue:
                kept_rows = []
            elif replace_issue:
                kept_rows = [
                    _normalize_sheet_row_values(row, width=len(spec.headers))
                    for row in existing_rows
                    if not _row_has_issue_id(row, spec, issue_id=issue_id)
                ]
            else:
                kept_rows = [
                    _normalize_sheet_row_values(row, width=len(spec.headers))
                    for row in existing_rows
                ]
            if tab == "Stocks":
                kept_rows = [
                    _sanitize_stock_sheet_row(row, spec=spec)
                    for row in kept_rows
                    if not _is_header_row(row, spec=spec)
                ]
            restored_existing_count += len(kept_rows)
            combined_rows = (
                _merge_stock_sheet_rows(kept_rows + new_rows, spec=spec)
                if tab == "Stocks"
                else kept_rows + new_rows
            )
            if tab == "Stocks":
                combined_rows = [
                    _sanitize_stock_sheet_row(
                        row,
                        spec=spec,
                        sheet_ids_by_title=sheet_ids_by_title,
                    )
                    for row in combined_rows
                ]
            if replace_issue:
                cleared_tabs.append(tab)
                post_write_clear_ranges.extend(
                    _stale_sheet_tail_clear_ranges(
                        tab,
                        spec=spec,
                        body_start=body_start,
                        existing_row_count=len(existing_rows),
                        replacement_row_count=len(combined_rows),
                    )
                )
            if combined_rows:
                write_ranges.append(
                    {
                        "range": (
                            f"{_quote_sheet_title(tab)}!A{body_start}:"
                            f"{_column_letter(len(spec.headers))}"
                            f"{body_start + len(combined_rows) - 1}"
                        ),
                        "values": combined_rows,
                    }
                )

        export_phase = "expanding reviewer-grid capacity"
        reviewer_grid_tabs_expanded = _ensure_reviewer_tab_grid_capacity(
            sheets,
            spreadsheet_id=config.sheets_spreadsheet_id,
            sheet_ids_by_title=sheet_ids_by_title,
            tab_layouts=aktuell_layouts,
        )
        if write_ranges:
            export_phase = "writing workbook values"
            sheets.spreadsheets().values().batchUpdate(
                spreadsheetId=config.sheets_spreadsheet_id,
                body={
                    "valueInputOption": "RAW",
                    "data": write_ranges,
                },
            ).execute()
        export_phase = "clearing stale reviewer rows"
        for range_name in post_write_clear_ranges:
            sheets.spreadsheets().values().clear(
                spreadsheetId=config.sheets_spreadsheet_id,
                range=range_name,
                body={},
            ).execute()
        export_phase = "refreshing issue and insider search"
        search_indexed_row_count = _refresh_issue_search_sheet(
            sheets,
            spreadsheet_id=config.sheets_spreadsheet_id,
            sheet_ids_by_title=sheet_ids_by_title,
            current_issue_title=issue_tab_title,
            current_issue_values=_current_issue_search_source_values(
                stock_headers=specs_by_title["Aktuell"].headers,
                stock_rows=stock_rows,
                derivative_rows=derivative_rows,
            ),
        )
        export_phase = "formatting reviewer tables"
        for tab_title, (
            stock_header_row,
            _stock_data_end_row,
            derivative_label_row,
            derivative_header_row,
            _derivative_data_end_row,
        ) in aktuell_layouts:
            aktuell_sheet_id = sheet_ids_by_title.get(tab_title)
            if aktuell_sheet_id is not None:
                sheets.spreadsheets().batchUpdate(
                    spreadsheetId=config.sheets_spreadsheet_id,
                    body={
                        "requests": _build_aktuell_table_format_requests(
                            sheet_id=aktuell_sheet_id,
                            stock_header_row=stock_header_row,
                            derivative_label_row=derivative_label_row,
                            derivative_header_row=derivative_header_row,
                        )
                    },
                ).execute()
        export_phase = "reconciling reviewer action colours"
        reviewer_action_format_requests = _build_reviewer_action_format_requests(
            _fetch_sheet_properties_with_formats(
                sheets,
                spreadsheet_id=config.sheets_spreadsheet_id,
            )
        )
        if reviewer_action_format_requests:
            sheets.spreadsheets().batchUpdate(
                spreadsheetId=config.sheets_spreadsheet_id,
                body={"requests": reviewer_action_format_requests},
            ).execute()
        export_phase = "trimming reviewer grids"
        reviewer_grid_tabs_synced = _sync_reviewer_tab_grid_properties(
            sheets,
            spreadsheet_id=config.sheets_spreadsheet_id,
            sheet_ids_by_title=sheet_ids_by_title,
            tab_layouts=aktuell_layouts,
            tab_specs_by_title=specs_by_title,
            issue_tab_spec=issue_tab_spec,
        )
        export_phase = "auto-sizing reviewer columns"
        auto_resized_tabs = _auto_resize_issue_review_tab_columns(
            sheets,
            spreadsheet_id=config.sheets_spreadsheet_id,
            sheet_ids_by_title=sheet_ids_by_title,
        )
        export_phase = "protecting generated workbook tabs"
        protected_tabs = _apply_managed_sheet_protections(
            sheets,
            spreadsheet_id=config.sheets_spreadsheet_id,
            editor_email=config.service_account_email,
        )
    except Exception as error:
        raise GoogleAccessError(
            f"Google Sheets workbook row export failed during {export_phase}. "
            "Verify network access, "
            "API enablement, service-account sheet sharing, and configured spreadsheet ID."
        ) from error

    written_count = sum(len(rows) for rows in rows_by_tab.values()) + len(aktuell_rows)
    tabs_written = sorted(
        (*rows_by_tab, issue_tab_title, *(("Aktuell",) if updates_aktuell else ()))
    )
    return {
        "ok": True,
        "externalServicesEnabled": True,
        "enrichmentProviderCalls": 0,
        "spreadsheetId": _redacted_identifier(config.sheets_spreadsheet_id),
        "issueId": issue_id,
        "replaceIssue": replace_issue,
        "exportMode": (
            "private_draft_review_export"
            if allow_draft_rows
            else "approved_family_export"
        ),
        "familyVisibleSafe": not allow_draft_rows,
        "privateDraftReviewOnly": allow_draft_rows,
        "draftRowsAllowed": allow_draft_rows,
        "issueTab": issue_tab_title,
        "issueTabsReordered": reordered_issue_tabs,
        "reviewerGridTabsExpanded": reviewer_grid_tabs_expanded,
        "reviewerGridTabsSynced": reviewer_grid_tabs_synced,
        "reviewerActionFormatRulesWritten": len(reviewer_action_format_requests),
        "aktuellUpdated": updates_aktuell,
        "tabsWritten": tabs_written,
        "rowsWritten": written_count,
        "rowsSkipped": skipped_count,
        "rowsOmittedFromCleanSheet": omitted_inactive_tab_count,
        "searchIndexedRows": search_indexed_row_count,
        "clearedTabs": sorted(cleared_tabs),
        "staleRangesCleared": post_write_clear_ranges,
        "restoredExistingRows": restored_existing_count,
        "autoResizedTabs": auto_resized_tabs,
        "protectedTabs": protected_tabs,
        "bootstrap": bootstrap_result,
    }


def write_refinement_plan_to_google_sheet(
    config: GoogleAccessConfig,
    refinement_plan: Mapping[str, object],
    *,
    sheets_service_factory=None,
    tab_specs: tuple[GoogleSheetTabSpec, ...] = REFINEMENT_SHEET_TABS,
) -> dict[str, object]:
    """Write page-by-page refinement rows into the configured Sheet."""

    if sheets_service_factory is None:
        _drive_service_factory, sheets_service_factory = _google_service_factories(config)

    issue_id = str(refinement_plan.get("issueId") or "").strip()
    raw_rows = refinement_plan.get("rows")
    if not issue_id:
        raise GoogleAccessError("refinement plan is missing issueId")
    if not isinstance(raw_rows, list):
        raise GoogleAccessError("refinement plan is missing rows list")

    spec = next((candidate for candidate in tab_specs if candidate.title == "Refinement"), None)
    if spec is None:
        raise GoogleAccessError("Refinement tab spec is not configured")

    rows = [
        _refinement_row_values(raw_row, spec=spec)
        for raw_row in raw_rows
        if isinstance(raw_row, Mapping)
    ]
    rows.sort(key=_refinement_page_sort_key)

    sheets = sheets_service_factory()
    bootstrap_result = bootstrap_google_sheet(
        config,
        sheets_service_factory=sheets_service_factory,
        tab_specs=tab_specs,
        write_headers=True,
        prune_extra_tabs=False,
    )
    body_start = spec.header_row + 1
    body_range = f"{_quote_sheet_title(spec.title)}!A{body_start}:{_column_letter(len(spec.headers))}"

    try:
        existing_rows = [
            _normalize_sheet_row_values(row, width=len(spec.headers))
            for row in _sheet_values_get(
                sheets,
                spreadsheet_id=config.sheets_spreadsheet_id,
                range_name=body_range,
            )
        ]
        rows = _preserve_refinement_reviewer_notes(rows, existing_rows, spec=spec)
        sheets.spreadsheets().values().clear(
            spreadsheetId=config.sheets_spreadsheet_id,
            range=body_range,
            body={},
        ).execute()
        if rows:
            sheets.spreadsheets().values().batchUpdate(
                spreadsheetId=config.sheets_spreadsheet_id,
                body={
                    "valueInputOption": "RAW",
                    "data": [
                        {
                            "range": (
                                f"{_quote_sheet_title(spec.title)}!A{body_start}:"
                                f"{_column_letter(len(spec.headers))}"
                                f"{body_start + len(rows) - 1}"
                            ),
                            "values": rows,
                        }
                    ],
                },
            ).execute()
    except Exception as error:
        raise GoogleAccessError(
            "Google Sheets refinement export failed. Verify network access, API enablement, "
            "service-account sheet sharing, and configured spreadsheet ID."
        ) from error

    return {
        "ok": True,
        "externalServicesEnabled": True,
        "spreadsheetId": _redacted_identifier(config.sheets_spreadsheet_id),
        "issueId": issue_id,
        "tabWritten": spec.title,
        "rowsWritten": len(rows),
        "reviewerNotesPreserved": _count_non_empty_reviewer_notes(rows, spec=spec),
        "bootstrap": bootstrap_result,
    }


def list_drive_pdf_metadata(
    config: GoogleAccessConfig,
    *,
    drive_service_factory=None,
    page_size: int = 100,
) -> tuple[DrivePdfMetadata, ...]:
    """List PDF metadata from the configured Drive folder without downloading files."""

    if page_size < 1 or page_size > 1000:
        raise GoogleAccessError("page_size must be between 1 and 1000")

    if drive_service_factory is None:
        drive_service_factory, _sheets_service_factory = _google_service_factories(config)

    drive = drive_service_factory()
    files_resource = drive.files()
    fields = (
        "nextPageToken,files(id,name,mimeType,md5Checksum,size,createdTime,"
        "modifiedTime,webViewLink)"
    )
    query = (
        f"'{config.drive_folder_id}' in parents and "
        "mimeType = 'application/pdf' and trashed = false"
    )
    page_token: str | None = None
    files: list[DrivePdfMetadata] = []

    try:
        while True:
            response = (
                files_resource.list(
                    q=query,
                    fields=fields,
                    pageSize=page_size,
                    pageToken=page_token,
                    orderBy="modifiedTime desc,name",
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                )
                .execute()
            )
            files.extend(_drive_file_metadata_from_payload(item) for item in response.get("files", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break
    except Exception as error:
        raise GoogleAccessError(
            "Google Drive PDF metadata listing failed. Verify network access, API enablement, "
            "service-account sharing, and configured folder ID."
        ) from error

    return tuple(files)


def build_drive_pdf_metadata_result(
    config: GoogleAccessConfig,
    *,
    drive_service_factory=None,
    page_size: int = 100,
    include_private_identifiers: bool = False,
) -> dict[str, object]:
    files = list_drive_pdf_metadata(
        config,
        drive_service_factory=drive_service_factory,
        page_size=page_size,
    )
    return {
        "ok": True,
        "externalServicesEnabled": True,
        "driveFolderId": config.drive_folder_id
        if include_private_identifiers
        else _redacted_identifier(config.drive_folder_id),
        "listedAt": datetime.now(timezone.utc).isoformat(),
        "fileCount": len(files),
        "files": [
            file.to_dict(include_private_identifiers=include_private_identifiers)
            for file in files
        ],
    }


def write_drive_pdf_metadata_manifest(
    result: Mapping[str, object],
    manifest_path: Path,
) -> Path:
    """Write metadata-only Drive PDF rows to a private local JSONL manifest."""

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    listed_at = result.get("listedAt")
    rows = result.get("files", [])
    if not isinstance(rows, list):
        raise GoogleAccessError("Drive metadata result does not contain a files list")

    with manifest_path.open("w", encoding="utf-8") as manifest:
        for row in rows:
            if not isinstance(row, dict):
                raise GoogleAccessError("Drive metadata row must be an object")
            manifest_row = dict(row)
            manifest_row["listedAt"] = listed_at
            manifest.write(f"{json.dumps(manifest_row, sort_keys=True)}\n")

    return manifest_path


def _build_sheet_header_ranges(
    tab_specs: tuple[GoogleSheetTabSpec, ...],
    *,
    sheet_properties: tuple[Mapping[str, object], ...] = (),
) -> tuple[dict[str, object], ...]:
    sheet_ids_by_title = {
        str(properties.get("title")): int(properties["sheetId"])
        for properties in sheet_properties
        if properties.get("title") and "sheetId" in properties
    }
    metadata_ranges = tuple(
        {
            "range": f"{_quote_sheet_title(spec.title)}!{cell}",
            "values": [[_resolve_metadata_cell_value(value, sheet_ids_by_title)]],
        }
        for spec in tab_specs
        for cell, value in spec.metadata_cells
    )
    header_ranges = tuple(
        {
            "range": (
                f"{_quote_sheet_title(spec.title)}!A{spec.header_row}:"
                f"{_column_letter(len(spec.headers))}{spec.header_row}"
            ),
            "values": [list(spec.headers)],
        }
        for spec in tab_specs
    )
    return metadata_ranges + header_ranges


def _is_approved_export_row(row: Mapping[str, object]) -> bool:
    return (
        row.get("reviewStatus") == "approved"
        and row.get("exportable") is True
        and row.get("requiresManualReview") is False
        and bool(str(row.get("reviewedBy") or "").strip())
        and _has_valid_reviewed_at(row.get("reviewedAt"))
        and bool(str(row.get("sourceBlock") or "").strip())
    )


def _require_family_export_approval_audit(
    workbook_plan: Mapping[str, object],
    raw_rows: list[object],
) -> None:
    approval_audit = workbook_plan.get("approvalAudit")
    if not isinstance(approval_audit, Mapping):
        raise GoogleAccessError(
            "family-visible workbook export requires workbook-approval-audit provenance"
        )

    required_boolean_fields = (
        "externalServicesEnabled",
        "networkAccess",
        "staleApprovalDetected",
    )
    required_counter_fields = (
        "rowCount",
        "approvalRowsImported",
        "matchedApprovalRows",
        "unmatchedApprovalRows",
        "approvedRows",
        "rejectedRows",
        "needsReviewRows",
        "hashMismatchRows",
        "invalidEvidenceRows",
    )
    required_fields = (
        *required_boolean_fields,
        "approvalSource",
        *required_counter_fields,
        "approvedRowsFingerprint",
    )
    if set(approval_audit) != set(required_fields):
        unexpected = sorted(set(approval_audit) - set(required_fields))
        if unexpected:
            raise GoogleAccessError(
                "family-visible workbook export approval audit contains unsupported fields: "
                + ", ".join(unexpected)
            )
    for field in required_fields:
        if field not in approval_audit:
            raise GoogleAccessError(
                f"family-visible workbook export approval audit is missing required field {field}"
            )
    for field in required_boolean_fields:
        if not isinstance(approval_audit[field], bool):
            raise GoogleAccessError(
                f"family-visible workbook export approval audit field {field} must be boolean"
            )
    for field in required_counter_fields:
        value = approval_audit[field]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise GoogleAccessError(
                f"family-visible workbook export approval audit field {field} "
                "must be a non-negative integer"
            )
    approved_rows_fingerprint = approval_audit["approvedRowsFingerprint"]
    if not isinstance(approved_rows_fingerprint, str) or re.fullmatch(
        r"[0-9a-f]{64}", approved_rows_fingerprint
    ) is None:
        raise GoogleAccessError(
            "family-visible workbook export approval audit field "
            "approvedRowsFingerprint must be a SHA-256 hex digest"
        )

    if approval_audit.get("approvalSource") != "private_reviewer_csv":
        raise GoogleAccessError(
            "family-visible workbook export requires private reviewer CSV approval provenance"
        )
    if approval_audit["externalServicesEnabled"] is not False:
        raise GoogleAccessError(
            "family-visible workbook export approval audit must be local-only"
        )
    if approval_audit["networkAccess"] is not False:
        raise GoogleAccessError(
            "family-visible workbook export approval audit cannot use network access"
        )
    if approval_audit["staleApprovalDetected"] is not False:
        raise GoogleAccessError(
            "family-visible workbook export cannot use stale or unchecked approval hashes"
        )
    if approval_audit["hashMismatchRows"] != 0:
        raise GoogleAccessError(
            "family-visible workbook export cannot include approval hash mismatches"
        )
    if approval_audit["invalidEvidenceRows"] != 0:
        raise GoogleAccessError(
            "family-visible workbook export cannot include invalid approval evidence"
        )
    if approval_audit["unmatchedApprovalRows"] != 0:
        raise GoogleAccessError(
            "family-visible workbook export cannot include unmatched approval rows"
        )
    if approval_audit["rowCount"] != len(raw_rows):
        raise GoogleAccessError(
            "family-visible workbook export approval audit row count does not match rows"
        )
    if approval_audit["approvalRowsImported"] != (
        approval_audit["matchedApprovalRows"]
        + approval_audit["unmatchedApprovalRows"]
    ):
        raise GoogleAccessError(
            "family-visible workbook export imported approval count is inconsistent"
        )
    if approval_audit["matchedApprovalRows"] > approval_audit["rowCount"]:
        raise GoogleAccessError(
            "family-visible workbook export matched approval count exceeds rows"
        )
    if (
        approval_audit["approvedRows"]
        + approval_audit["rejectedRows"]
        + approval_audit["needsReviewRows"]
        != approval_audit["rowCount"]
    ):
        raise GoogleAccessError(
            "family-visible workbook export approval disposition counts are inconsistent"
        )
    if approval_audit["matchedApprovalRows"] < (
        approval_audit["approvedRows"] + approval_audit["rejectedRows"]
    ):
        raise GoogleAccessError(
            "family-visible workbook export final approval count exceeds matched approvals"
        )

    approved_row_count = sum(
        1 for row in raw_rows if isinstance(row, Mapping) and _is_approved_export_row(row)
    )
    if approval_audit["approvedRows"] != approved_row_count:
        raise GoogleAccessError(
            "family-visible workbook export approved row count does not match approval audit"
        )
    try:
        current_fingerprint = approved_workbook_rows_fingerprint(raw_rows)
    except ReviewApprovalError as error:
        raise GoogleAccessError(
            "family-visible workbook export approved rows are structurally invalid"
        ) from error
    if approved_rows_fingerprint != current_fingerprint:
        raise GoogleAccessError(
            "family-visible workbook export approved row fingerprint does not match current rows"
        )


def _require_no_unresolved_family_rows(
    raw_rows: Sequence[object],
    *,
    specs_by_title: Mapping[str, GoogleSheetTabSpec],
) -> None:
    audit_spec = specs_by_title.get("Extraction Audit")
    for raw_row in raw_rows:
        if not isinstance(raw_row, Mapping):
            continue
        tab = str(raw_row.get("tab") or "").strip()
        review_status = str(raw_row.get("reviewStatus") or "").strip()
        if tab == "Aktuell" and review_status == "needs_review":
            raise GoogleAccessError(
                "family-visible workbook export cannot include actionable Aktuell needs_review rows"
            )
        if tab != "Extraction Audit" or review_status == "approved":
            continue
        values = raw_row.get("values")
        if (
            audit_spec is None
            or not isinstance(values, list)
            or len(values) != len(audit_spec.headers)
        ):
            raise GoogleAccessError(
                "family-visible workbook export contains an unresolved malformed Extraction Audit row"
            )
        lookup = dict(zip(audit_spec.headers, values))
        actionable = bool(str(lookup.get("Action") or "").strip())
        blocker = str(lookup.get("Severity") or "").strip().casefold() == "blocker"
        if actionable or blocker:
            raise GoogleAccessError(
                "family-visible workbook export contains an unresolved actionable Extraction Audit blocker"
            )


def _has_valid_reviewed_at(value: object) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _stale_sheet_tail_clear_ranges(
    tab: str,
    *,
    spec: GoogleSheetTabSpec,
    body_start: int,
    existing_row_count: int,
    replacement_row_count: int,
) -> list[str]:
    if existing_row_count <= replacement_row_count:
        return []
    if replacement_row_count <= 0:
        return [
            (
                f"{_quote_sheet_title(tab)}!A{body_start}:"
                f"{_column_letter(len(spec.headers))}{body_start + existing_row_count - 1}"
            )
        ]
    stale_start = body_start + replacement_row_count
    stale_end = body_start + existing_row_count - 1
    return [
        (
            f"{_quote_sheet_title(tab)}!A{stale_start}:"
            f"{_column_letter(len(spec.headers))}{stale_end}"
        )
    ]


def _resolve_metadata_cell_value(value: str, sheet_ids_by_title: Mapping[str, int]) -> str:
    prefix = "__sheet_link__:"
    if not value.startswith(prefix):
        return value
    title = value[len(prefix) :]
    sheet_id = sheet_ids_by_title.get(title)
    if sheet_id is None:
        return title
    return f'=HYPERLINK("#gid={sheet_id}","{title}")'


def _build_sheet_pre_header_clear_ranges(
    tab_specs: tuple[GoogleSheetTabSpec, ...],
) -> tuple[str, ...]:
    return tuple(
        f"{_quote_sheet_title(spec.title)}!A1:{_column_letter(len(spec.headers))}{spec.header_row - 1}"
        for spec in tab_specs
        if spec.header_row > 1 and not spec.metadata_cells
    )


def _build_sheet_body_clear_ranges(
    tab_specs: tuple[GoogleSheetTabSpec, ...],
) -> tuple[str, ...]:
    return tuple(
        (
            f"{_quote_sheet_title(spec.title)}!A{spec.header_row + 1}:"
            f"{_column_letter(len(spec.headers))}"
        )
        for spec in tab_specs
        if spec.parser_status != "layout_only"
    )


def _build_sheet_grid_property_requests(
    tab_specs: tuple[GoogleSheetTabSpec, ...],
    sheet_properties: tuple[Mapping[str, object], ...],
) -> tuple[dict[str, object], ...]:
    sheet_ids_by_title = {
        str(properties.get("title")): int(properties["sheetId"])
        for properties in sheet_properties
        if properties.get("title") and "sheetId" in properties
    }
    requests: list[dict[str, object]] = []
    for spec in tab_specs:
        sheet_id = sheet_ids_by_title.get(spec.title)
        if sheet_id is None:
            continue
        requests.append(
            {
                "updateSheetProperties": {
                    "properties": {
                        "sheetId": sheet_id,
                        "gridProperties": {
                            "frozenRowCount": spec.frozen_rows,
                            "frozenColumnCount": spec.frozen_columns,
                        },
                    },
                    "fields": (
                        "gridProperties.frozenRowCount,"
                        "gridProperties.frozenColumnCount"
                    ),
                }
            }
        )
    return tuple(requests)


def _issue_tab_title(issue_id: str) -> str:
    match = ISSUE_ID_RE.fullmatch(issue_id)
    if match is None:
        raise GoogleAccessError(
            "workbook issueId must use YYYY-WNN so its source issue tab can be named"
        )
    return f"DA_{match.group('year')}_{int(match.group('number')):02d}"


def _issue_review_tab_spec(title: str, aktuell_spec: GoogleSheetTabSpec) -> GoogleSheetTabSpec:
    return replace(
        aktuell_spec,
        title=title,
        purpose="Source-linked explicit publisher actions for this imported issue.",
    )


def _ensure_issue_review_tab(
    sheets,
    *,
    spreadsheet_id: str,
    spec: GoogleSheetTabSpec,
    sheet_ids_by_title: Mapping[str, int],
) -> None:
    if spec.title not in sheet_ids_by_title:
        sheets.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={
                "requests": [
                    {
                        "addSheet": {
                            "properties": {
                                "title": spec.title,
                                "gridProperties": {
                                    "columnCount": REVIEWER_STOCK_COLUMN_COUNT,
                                    "frozenRowCount": spec.frozen_rows,
                                    "frozenColumnCount": spec.frozen_columns,
                                },
                            }
                        }
                    }
                ]
            },
        ).execute()


def _latest_issue_tab_title(sheet_ids_by_title: Mapping[str, int]) -> str | None:
    issue_tabs = _issue_tab_titles_newest_first(sheet_ids_by_title)
    if not issue_tabs:
        return None
    return issue_tabs[0]


def _issue_tab_titles_newest_first(sheet_ids_by_title: Mapping[str, int]) -> list[str]:
    return sorted(
        (
            title
            for title in sheet_ids_by_title
            if ISSUE_TAB_TITLE_RE.fullmatch(title) is not None
        ),
        key=lambda title: (
            int(ISSUE_TAB_TITLE_RE.fullmatch(title).group("year")),  # type: ignore[union-attr]
            int(ISSUE_TAB_TITLE_RE.fullmatch(title).group("number")),  # type: ignore[union-attr]
        ),
        reverse=True,
    )


def _reorder_issue_review_tabs_newest_first(
    sheets,
    *,
    spreadsheet_id: str,
) -> list[str]:
    """Keep core tab positions and order issue tabs newest-to-oldest.

    Only issue-review tabs are moved. The first existing issue-tab position is
    retained, so the fixed Search and Aktuell tabs do not move when a newly
    imported issue is inserted at the left of the issue-tab block.
    """

    sheet_properties = _fetch_sheet_properties(sheets, spreadsheet_id=spreadsheet_id)
    issue_properties = [
        properties
        for properties in sheet_properties
        if ISSUE_TAB_TITLE_RE.fullmatch(str(properties.get("title") or "")) is not None
        and "sheetId" in properties
    ]
    if not issue_properties:
        return []

    target_index = min(
        index
        for index, properties in enumerate(sheet_properties)
        if properties in issue_properties
    )
    desired_titles = _issue_tab_titles_newest_first(
        {
            str(properties["title"]): int(properties["sheetId"])
            for properties in issue_properties
        }
    )
    current_titles = [str(properties["title"]) for properties in issue_properties]
    if current_titles == desired_titles:
        return []

    properties_by_title = {
        str(properties["title"]): properties for properties in issue_properties
    }
    requests = [
        {
            "updateSheetProperties": {
                "properties": {
                    "sheetId": int(properties_by_title[title]["sheetId"]),
                    "index": target_index + offset,
                },
                "fields": "index",
            }
        }
        for offset, title in enumerate(desired_titles)
    ]
    sheets.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": requests},
    ).execute()
    return desired_titles


def _auto_resize_issue_review_tab_columns(
    sheets,
    *,
    spreadsheet_id: str,
    sheet_ids_by_title: Mapping[str, int],
) -> list[str]:
    """Size every generated recommendation column to its current content."""

    tab_titles = ["Aktuell", *_issue_tab_titles_newest_first(sheet_ids_by_title)]
    resize_requests = [
        {
            "autoResizeDimensions": {
                "dimensions": {
                    "sheetId": sheet_ids_by_title[title],
                    "dimension": "COLUMNS",
                    "startIndex": 0,
                    "endIndex": max(
                        REVIEWER_STOCK_COLUMN_COUNT,
                        REVIEWER_DERIVATIVE_COLUMN_COUNT,
                    ),
                }
            }
        }
        for title in tab_titles
        if title in sheet_ids_by_title
    ]
    width_requests = [
        {
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet_ids_by_title[title],
                    "dimension": "COLUMNS",
                    "startIndex": column_index,
                    "endIndex": column_index + 1,
                },
                "properties": {"pixelSize": pixel_size},
                "fields": "pixelSize",
            }
        }
        for title in tab_titles
        if title in sheet_ids_by_title
        for column_index, pixel_size in enumerate(REVIEWER_COLUMN_WIDTHS)
    ]
    requests = [*resize_requests, *width_requests]
    if not requests:
        return []
    sheets.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": requests},
    ).execute()
    return [title for title in tab_titles if title in sheet_ids_by_title]


def _sync_reviewer_tab_grid_properties(
    sheets,
    *,
    spreadsheet_id: str,
    sheet_ids_by_title: Mapping[str, int],
    tab_layouts: Sequence[tuple[str, tuple[int, int, int, int, int]]],
    tab_specs_by_title: Mapping[str, GoogleSheetTabSpec],
    issue_tab_spec: GoogleSheetTabSpec,
) -> list[str]:
    """Keep reviewer grids compact after their generated tail is cleared.

    Issue tabs can predate the current compact layout, so their column count
    and frozen panes cannot be configured only when a sheet is created. This
    runs after the value clear requests, ensuring reduced grid dimensions only
    trim cleared, generated space and leave one trailing row for navigation.
    """

    requests: list[dict[str, object]] = []
    synced_titles: list[str] = []
    for title, layout in tab_layouts:
        sheet_id = sheet_ids_by_title.get(title)
        if sheet_id is None:
            continue
        spec = tab_specs_by_title.get(title, issue_tab_spec)
        derivative_data_end_row = layout[4]
        row_count = max(
            spec.frozen_rows,
            derivative_data_end_row + REVIEWER_GRID_TRAILING_ROWS,
        )
        requests.append(
            {
                "updateSheetProperties": {
                    "properties": {
                        "sheetId": sheet_id,
                        "gridProperties": {
                            "columnCount": REVIEWER_STOCK_COLUMN_COUNT,
                            "frozenRowCount": spec.frozen_rows,
                            "frozenColumnCount": spec.frozen_columns,
                            "rowCount": row_count,
                        },
                    },
                    "fields": (
                        "gridProperties.columnCount,"
                        "gridProperties.frozenRowCount,"
                        "gridProperties.frozenColumnCount,"
                        "gridProperties.rowCount"
                    ),
                }
            }
        )
        synced_titles.append(title)
    if not requests:
        return []
    sheets.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": requests},
    ).execute()
    return synced_titles


def _ensure_reviewer_tab_grid_capacity(
    sheets,
    *,
    spreadsheet_id: str,
    sheet_ids_by_title: Mapping[str, int],
    tab_layouts: Sequence[tuple[str, tuple[int, int, int, int, int]]],
) -> list[str]:
    """Expand compact reviewer grids before writing a larger issue plan.

    A prior export intentionally shrinks the grid. Google Sheets does not
    expand it for a values batch update, so ensure the final generated row and
    one trailing reviewer row exist before any values are written. This helper
    never reduces a grid; post-write trimming happens separately after stale
    generated rows have been cleared.
    """

    current_row_counts = _fetch_sheet_row_counts_by_title(
        sheets,
        spreadsheet_id=spreadsheet_id,
    )
    requests: list[dict[str, object]] = []
    expanded_titles: list[str] = []
    for title, layout in tab_layouts:
        current_row_count = current_row_counts.get(title, 0)
        required_row_count = layout[4] + REVIEWER_GRID_TRAILING_ROWS
        if current_row_count >= required_row_count:
            continue
        sheet_id = sheet_ids_by_title.get(title)
        if sheet_id is None:
            continue
        requests.append(
            {
                "updateSheetProperties": {
                    "properties": {
                        "sheetId": sheet_id,
                        "gridProperties": {"rowCount": required_row_count},
                    },
                    "fields": "gridProperties.rowCount",
                }
            }
        )
        expanded_titles.append(title)
    if not requests:
        return []
    sheets.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": requests},
    ).execute()
    return expanded_titles


def _append_issue_recommendation_table_write_ranges(
    write_ranges: list[dict[str, object]],
    *,
    tab_title: str,
    spec: GoogleSheetTabSpec,
    stock_rows: list[list[str]],
    derivative_rows: list[list[str]],
) -> tuple[int, int, int, int, int]:
    stock_header_row = spec.header_row
    stock_data_end_row = stock_header_row + len(stock_rows)
    derivative_label_row = stock_data_end_row + ISSUE_RECOMMENDATION_TABLE_BLANK_ROWS + 1
    derivative_header_row = derivative_label_row + 1
    derivative_data_end_row = derivative_header_row + len(derivative_rows)
    quoted_title = _quote_sheet_title(tab_title)
    stock_column = _column_letter(len(spec.headers))
    derivative_column = _column_letter(len(AKTUELL_DERIVATIVE_HEADERS))
    write_ranges.extend(
        {
            "range": f"{quoted_title}!{cell}",
            "values": [[value]],
        }
        for cell, value in spec.metadata_cells
    )
    write_ranges.extend(
        (
            {
                "range": (
                    f"{quoted_title}!A{stock_header_row}:"
                    f"{stock_column}{stock_header_row}"
                ),
                "values": [list(spec.headers)],
            },
            {
                "range": (
                    f"{quoted_title}!A{derivative_label_row}:"
                    f"{derivative_column}{derivative_label_row}"
                ),
                "values": [["Derivatives", *([""] * (len(AKTUELL_DERIVATIVE_HEADERS) - 1))]],
            },
            {
                "range": (
                    f"{quoted_title}!A{derivative_header_row}:"
                    f"{derivative_column}{derivative_header_row}"
                ),
                "values": [list(AKTUELL_DERIVATIVE_HEADERS)],
            },
        )
    )
    if stock_rows:
        write_ranges.append(
            {
                "range": (
                    f"{quoted_title}!A{stock_header_row + 1}:"
                    f"{stock_column}{stock_data_end_row}"
                ),
                "values": stock_rows,
            }
        )
    if derivative_rows:
        write_ranges.append(
            {
                "range": (
                    f"{quoted_title}!A{derivative_header_row + 1}:"
                    f"{derivative_column}{derivative_data_end_row}"
                ),
                "values": derivative_rows,
            }
        )
    return (
        stock_header_row,
        stock_data_end_row,
        derivative_label_row,
        derivative_header_row,
        derivative_data_end_row,
    )


def _issue_recommendation_table_clear_ranges(
    tab_title: str,
    layout: tuple[int, int, int, int, int],
) -> tuple[str, ...]:
    (
        _stock_header_row,
        stock_data_end_row,
        derivative_label_row,
        _derivative_header_row,
        derivative_data_end_row,
    ) = layout
    return (
        f"{_quote_sheet_title(tab_title)}!A{stock_data_end_row + 1}:P{derivative_label_row - 1}",
        f"{_quote_sheet_title(tab_title)}!P{derivative_label_row}:P{derivative_data_end_row}",
        f"{_quote_sheet_title(tab_title)}!A{derivative_data_end_row + 1}:P",
    )


SEARCH_INDEX_HEADERS = (
    "Type",
    "Issue sort key",
    "Source page sort",
    "Search key",
    *tuple(f"Value {index}" for index in range(1, 20)),
)


def _build_issue_search_index_rows(
    *,
    issue_tab_values_by_title: Mapping[str, Sequence[Sequence[object]]],
    sheet_ids_by_title: Mapping[str, int],
    insider_activity_values: Sequence[Sequence[object]] = (),
) -> list[list[object]]:
    """Preserve full issue rows for Search without indexing Aktuell twice."""

    index_rows: list[list[object]] = []
    for title in _issue_tab_titles_newest_first(sheet_ids_by_title):
        title_match = ISSUE_TAB_TITLE_RE.fullmatch(title)
        if title_match is None:
            continue
        issue_sort_key = (
            int(title_match.group("year")) * 100
            + int(title_match.group("number"))
        )
        rows = issue_tab_values_by_title.get(title, ())
        row_kind: str | None = None
        header_indexes: dict[str, int] = {}
        for row_number, raw_row in enumerate(rows, 1):
            row = [str(value or "") for value in raw_row]
            trimmed_row = [value.strip() for value in row]
            first_three = tuple(trimmed_row[:3])
            if first_three == ("WKN", "Company", "Action"):
                row_kind = "Stock"
                header_indexes = {
                    header: index for index, header in enumerate(trimmed_row)
                }
                continue
            if first_three == ("WKN", "Derivative", "Action"):
                row_kind = "Derivative"
                header_indexes = {
                    header: index for index, header in enumerate(trimmed_row)
                }
                continue
            if row_kind is None or not any(trimmed_row):
                continue
            if trimmed_row[0] == "Derivatives":
                row_kind = None
                header_indexes = {}
                continue

            name_header = "Company" if row_kind == "Stock" else "Derivative"

            def value_for(header: str) -> str:
                index = header_indexes.get(header)
                if index is None and header == "Import date":
                    index = header_indexes.get("updated")
                if index is None and header == "Import date":
                    index = header_indexes.get("date updated")
                if index is None or index >= len(trimmed_row):
                    return ""
                return trimmed_row[index]

            wkn = value_for("WKN")
            name = value_for(name_header)
            if not wkn and not name:
                continue
            source_header = "Source" if row_kind == "Stock" else "Issue:Page"
            source_value = value_for(source_header)
            source_page_match = SOURCE_PAGE_RE.search(source_value)
            source_page_sort = (
                int(source_page_match.group("page"))
                if source_page_match is not None
                else row_number
            )
            target_headers = (
                next(
                    spec.headers
                    for spec in DEFAULT_SHEET_TABS
                    if spec.title == "Aktuell"
                )
                if row_kind == "Stock"
                else AKTUELL_DERIVATIVE_HEADERS
            )
            row_values = [value_for(header) for header in target_headers]
            row_values.extend([""] * (19 - len(row_values)))
            index_rows.append(
                [
                    row_kind,
                    issue_sort_key,
                    source_page_sort,
                    f"{wkn} {name}".strip().casefold(),
                    *row_values,
                ]
            )
    insider_spec = next(
        spec for spec in DEFAULT_SHEET_TABS if spec.title == "Insider Activity"
    )
    insider_headers: dict[str, int] = {}
    for raw_row in insider_activity_values:
        row = [str(value or "") for value in raw_row]
        if tuple(row[: len(insider_spec.headers)]) == insider_spec.headers:
            insider_headers = {header: index for index, header in enumerate(row)}
            continue
        if not insider_headers or not any(value.strip() for value in row):
            continue

        def insider_value(header: str) -> str:
            index = insider_headers.get(header)
            return row[index].strip() if index is not None and index < len(row) else ""

        company = insider_value("Company")
        wkn = insider_value("WKN")
        ticker = insider_value("Ticker")
        insider = insider_value("Insider")
        if not any((company, wkn, ticker, insider)):
            continue
        transaction_date = insider_value("Transaction date")
        try:
            sort_key = int(transaction_date.replace("-", ""))
        except ValueError:
            sort_key = 0
        row_values = _normalize_sheet_row_values(row, width=19)
        index_rows.append(
            [
                "Insider",
                sort_key,
                0,
                f"{wkn} {company} {ticker} {insider}".strip().casefold(),
                *row_values,
            ]
        )
    return index_rows


def _build_issue_search_results_formula() -> str:
    def array_row(values: Sequence[str]) -> str:
        return "{" + ",".join(json.dumps(value) for value in values) + "}"

    stock_source_headers = [
        *next(spec.headers for spec in DEFAULT_SHEET_TABS if spec.title == "Aktuell"),
        "", "", "",
    ]
    derivative_source_headers = [*AKTUELL_DERIVATIVE_HEADERS]
    derivative_source_headers.extend(
        [""] * (19 - len(derivative_source_headers))
    )
    insider_source_headers = list(
        next(
            spec.headers
            for spec in DEFAULT_SHEET_TABS
            if spec.title == "Insider Activity"
        )
    )
    insider_source_headers.extend([""] * (19 - len(insider_source_headers)))

    def source_first_headers(
        headers: Sequence[str],
        *,
        source_header: str,
    ) -> list[str]:
        source_index = headers.index(source_header)
        return [
            "Source",
            *(header for index, header in enumerate(headers) if index != source_index),
        ]

    def source_first_columns(
        headers: Sequence[str],
        *,
        source_header: str,
    ) -> str:
        source_index = headers.index(source_header)
        sorted_array_columns = list(range(3, len(headers) + 3))
        source_column = sorted_array_columns.pop(source_index)
        return ",".join(str(column) for column in [source_column, *sorted_array_columns])

    stock_headers = source_first_headers(
        stock_source_headers,
        source_header="Source",
    )
    derivative_headers = source_first_headers(
        derivative_source_headers,
        source_header="Issue:Page",
    )
    insider_headers = insider_source_headers
    stock_columns = source_first_columns(
        stock_source_headers,
        source_header="Source",
    )
    derivative_columns = source_first_columns(
        derivative_source_headers,
        source_header="Issue:Page",
    )
    insider_columns = ",".join(str(column) for column in range(3, 22))
    blank_row = array_row([""] * 19)
    stock_no_match = array_row(
        ["", "", "", "No stock matches", *([""] * 17)]
    )
    derivative_no_match = array_row(
        ["", "", "", "No derivative matches", *([""] * 17)]
    )
    insider_no_match = array_row(
        ["", "", "", "No insider matches", *([""] * 17)]
    )
    return (
        '=IF(LEN(TRIM($C$1))=0,"Enter a company or WKN above",'
        "LET("
        "q,LOWER(TRIM($C$1)),"
        "matches,ARRAYFORMULA(ISNUMBER(SEARCH(q,LOWER($X$2:$X)))),"
        "stockSorted,IFERROR(SORT(FILTER({$V$2:$W,$Y$2:$AQ},"
        f'$U$2:$U="Stock",matches),1,FALSE,2,TRUE),{stock_no_match}),'
        "derivativeSorted,IFERROR(SORT(FILTER({$V$2:$W,$Y$2:$AQ},"
        f'$U$2:$U="Derivative",matches),1,FALSE,2,TRUE),{derivative_no_match}),'
        "insiderSorted,IFERROR(SORT(FILTER({$V$2:$W,$Y$2:$AQ},"
        f'$U$2:$U="Insider",matches),1,FALSE,2,TRUE),{insider_no_match}),'
        f"stocks,CHOOSECOLS(stockSorted,{stock_columns}),"
        f"derivatives,CHOOSECOLS(derivativeSorted,{derivative_columns}),"
        f"insiders,CHOOSECOLS(insiderSorted,{insider_columns}),"
        f'VSTACK({array_row(["Stocks", *([""] * 18)])},'
        f"{array_row(stock_headers)},stocks,{blank_row},"
        f'{array_row(["Derivatives", *([""] * 18)])},'
        f"{array_row(derivative_headers)},derivatives,{blank_row},"
        f'{array_row(["Insider Activity", *([""] * 18)])},'
        f"{array_row(insider_headers)},insiders)))"
    )


def _build_search_format_requests(
    *,
    sheet_id: int,
    existing_rule_count: int,
) -> list[dict[str, object]]:
    data_range = {
        "sheetId": sheet_id,
        "startRowIndex": 3,
        "startColumnIndex": 0,
        "endColumnIndex": 19,
    }
    requests: list[dict[str, object]] = [
        {
            "deleteConditionalFormatRule": {
                "sheetId": sheet_id,
                "index": index,
            }
        }
        for index in range(existing_rule_count - 1, -1, -1)
    ]
    requests.append(
        {
            "repeatCell": {
                "range": data_range,
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0},
                        "horizontalAlignment": "LEFT",
                        "textFormat": {
                            "bold": False,
                            "foregroundColor": {"red": 0.0, "green": 0.0, "blue": 0.0},
                        },
                    }
                },
                "fields": (
                    "userEnteredFormat.backgroundColor,"
                    "userEnteredFormat.horizontalAlignment,"
                    "userEnteredFormat.textFormat.bold,"
                    "userEnteredFormat.textFormat.foregroundColor"
                ),
            }
        }
    )

    def add_rule(formula: str, cell_format: Mapping[str, object]) -> dict[str, object]:
        return {
            "addConditionalFormatRule": {
                "rule": {
                    "ranges": [data_range],
                    "booleanRule": {
                        "condition": {
                            "type": "CUSTOM_FORMULA",
                            "values": [{"userEnteredValue": formula}],
                        },
                        "format": dict(cell_format),
                    },
                },
                "index": 0,
            }
        }

    requests.extend(
        (
            add_rule(
                '=OR($A4="Stocks",$A4="Derivatives",$A4="Insider Activity")',
                {
                    "backgroundColor": {"red": 0.15, "green": 0.16, "blue": 0.42},
                    "textFormat": {
                        "bold": True,
                        "foregroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0},
                    },
                },
            ),
            add_rule(
                '=AND($A4="Source",$B4="WKN",$C4="Company",$D4="Action")',
                {
                    "backgroundColor": {"red": 0.0, "green": 0.45, "blue": 0.55},
                    "textFormat": {
                        "bold": True,
                        "foregroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0},
                    },
                },
            ),
            add_rule(
                '=AND($A4="Source",$B4="WKN",$C4="Derivative",$D4="Action")',
                {
                    "backgroundColor": {"red": 0.35, "green": 0.24, "blue": 0.65},
                    "textFormat": {
                        "bold": True,
                        "foregroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0},
                    },
                },
            ),
            *(
                add_rule(
                    f'=$D4="{action}"',
                    {"backgroundColor": color},
                )
                for action, color in REVIEWER_ACTION_FORMATS
            ),
            *(
                add_rule(
                    f'=$I4="{direction}"',
                    {"backgroundColor": color},
                )
                for direction, color in INSIDER_DIRECTION_FORMATS
            ),
        )
    )
    return requests


def _current_issue_search_source_values(
    *,
    stock_headers: Sequence[str],
    stock_rows: Sequence[Sequence[str]],
    derivative_rows: Sequence[Sequence[str]],
) -> list[list[str]]:
    values = [list(stock_headers), *[list(row) for row in stock_rows]]
    values.extend([[], []])
    values.append(["Derivatives", *([""] * (len(AKTUELL_DERIVATIVE_HEADERS) - 1))])
    values.append(list(AKTUELL_DERIVATIVE_HEADERS))
    values.extend([list(row) for row in derivative_rows])
    return values


def _refresh_issue_search_sheet(
    sheets,
    *,
    spreadsheet_id: str,
    sheet_ids_by_title: Mapping[str, int],
    current_issue_title: str | None = None,
    current_issue_values: Sequence[Sequence[str]] = (),
) -> int:
    search_sheet_id = sheet_ids_by_title.get("Search")
    if search_sheet_id is None:
        raise GoogleAccessError("Search tab is missing after workbook bootstrap")
    existing_input_values = _sheet_values_get(
        sheets,
        spreadsheet_id=spreadsheet_id,
        range_name="'Search'!B1:C1",
    )
    existing_input_row = existing_input_values[0] if existing_input_values else []
    legacy_search_input = (
        str(existing_input_row[0]) if len(existing_input_row) >= 1 else ""
    )
    current_search_input = (
        str(existing_input_row[1]) if len(existing_input_row) >= 2 else ""
    )
    search_input = current_search_input or legacy_search_input

    issue_titles = _issue_tab_titles_newest_first(sheet_ids_by_title)
    issue_end_column = _column_letter(REVIEWER_STOCK_COLUMN_COUNT)
    ranges = [
        f"{_quote_sheet_title(title)}!A:{issue_end_column}"
        for title in issue_titles
    ]
    issue_values_by_title: dict[str, Sequence[Sequence[object]]] = {}
    if ranges:
        response = (
            sheets.spreadsheets()
            .values()
            .batchGet(
                spreadsheetId=spreadsheet_id,
                ranges=ranges,
                majorDimension="ROWS",
            )
            .execute()
        )
        for title, value_range in zip(issue_titles, response.get("valueRanges", [])):
            issue_values_by_title[title] = value_range.get("values", [])
    if current_issue_title is not None:
        issue_values_by_title[current_issue_title] = current_issue_values

    insider_activity_values = _sheet_values_get(
        sheets,
        spreadsheet_id=spreadsheet_id,
        range_name="'Insider Activity'!A:L",
    ) if "Insider Activity" in sheet_ids_by_title else []

    index_rows = _build_issue_search_index_rows(
        issue_tab_values_by_title=issue_values_by_title,
        sheet_ids_by_title=sheet_ids_by_title,
        insider_activity_values=insider_activity_values,
    )
    search_properties = next(
        (
            properties
            for properties in _fetch_sheet_properties_with_formats(
                sheets,
                spreadsheet_id=spreadsheet_id,
            )
            if properties.get("title") == "Search"
        ),
        {},
    )
    existing_rule_count = len(search_properties.get("conditionalFormats", []))
    sheets.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={
            "requests": [
                {
                    "updateSheetProperties": {
                        "properties": {
                            "sheetId": search_sheet_id,
                            "gridProperties": {
                                "frozenRowCount": SEARCH_SHEET_TAB.frozen_rows,
                                "columnCount": 43,
                                "rowCount": max(100, len(index_rows) + 10),
                            },
                        },
                        "fields": (
                            "gridProperties.frozenRowCount,"
                            "gridProperties.columnCount,"
                            "gridProperties.rowCount"
                        ),
                    }
                },
                {
                    "updateDimensionProperties": {
                        "range": {
                            "sheetId": search_sheet_id,
                            "dimension": "COLUMNS",
                            "startIndex": 0,
                            "endIndex": 19,
                        },
                        "properties": {"hiddenByUser": False},
                        "fields": "hiddenByUser",
                    }
                },
                {
                    "updateDimensionProperties": {
                        "range": {
                            "sheetId": search_sheet_id,
                            "dimension": "COLUMNS",
                            "startIndex": 19,
                            "endIndex": 43,
                        },
                        "properties": {"hiddenByUser": True},
                        "fields": "hiddenByUser",
                    }
                },
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": search_sheet_id,
                            "startRowIndex": 0,
                            "endRowIndex": 1,
                            "startColumnIndex": 1,
                            "endColumnIndex": 2,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": {
                                    "red": 1.0,
                                    "green": 1.0,
                                    "blue": 1.0,
                                }
                            },
                            "note": None,
                        },
                        "fields": "userEnteredFormat.backgroundColor,note",
                    }
                },
                {
                    "unmergeCells": {
                        "range": {
                            "sheetId": search_sheet_id,
                            "startRowIndex": 0,
                            "endRowIndex": 1,
                            "startColumnIndex": 2,
                            "endColumnIndex": 5,
                        }
                    }
                },
                {
                    "mergeCells": {
                        "range": {
                            "sheetId": search_sheet_id,
                            "startRowIndex": 0,
                            "endRowIndex": 1,
                            "startColumnIndex": 2,
                            "endColumnIndex": 5,
                        },
                        "mergeType": "MERGE_ALL",
                    }
                },
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": search_sheet_id,
                            "startRowIndex": 0,
                            "endRowIndex": 1,
                            "startColumnIndex": 2,
                            "endColumnIndex": 5,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": {
                                    "red": 1.0,
                                    "green": 0.95,
                                    "blue": 0.75,
                                },
                                "horizontalAlignment": "LEFT",
                            },
                            "note": "Enter a company name or WKN.",
                        },
                        "fields": (
                            "userEnteredFormat.backgroundColor,"
                            "userEnteredFormat.horizontalAlignment,note"
                        ),
                    }
                },
                *[
                    {
                        "updateDimensionProperties": {
                            "range": {
                                "sheetId": search_sheet_id,
                                "dimension": "COLUMNS",
                                "startIndex": start_index,
                                "endIndex": start_index + 1,
                            },
                            "properties": {"pixelSize": pixel_size},
                            "fields": "pixelSize",
                        }
                    }
                    for start_index, pixel_size in enumerate(
                        (
                            130,
                            90,
                            220,
                            85,
                            100,
                            100,
                            150,
                            110,
                            100,
                            100,
                            100,
                            150,
                            160,
                            120,
                            180,
                            180,
                            140,
                            160,
                            160,
                        )
                    )
                ],
            ]
        },
    ).execute()
    sheets.spreadsheets().values().clear(
        spreadsheetId=spreadsheet_id,
        range="'Search'!J:S",
        body={},
    ).execute()
    sheets.spreadsheets().values().clear(
        spreadsheetId=spreadsheet_id,
        range="'Search'!T:AQ",
        body={},
    ).execute()
    sheets.spreadsheets().values().clear(
        spreadsheetId=spreadsheet_id,
        range="'Search'!B1",
        body={},
    ).execute()
    sheets.spreadsheets().values().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={
            "valueInputOption": "USER_ENTERED",
            "data": [
                {
                    "range": "'Search'!C1",
                    "values": [[search_input]],
                },
                {
                    "range": "'Search'!A4",
                    "values": [[_build_issue_search_results_formula()]],
                }
            ],
        },
    ).execute()
    index_write_ranges: list[dict[str, object]] = [
        {
            "range": "'Search'!U1:AQ1",
            "values": [list(SEARCH_INDEX_HEADERS)],
        },
    ]
    if index_rows:
        index_write_ranges.append(
            {
                "range": f"'Search'!U2:AQ{len(index_rows) + 1}",
                "values": index_rows,
            }
        )
    sheets.spreadsheets().values().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"valueInputOption": "RAW", "data": index_write_ranges},
    ).execute()
    sheets.spreadsheets().values().clear(
        spreadsheetId=spreadsheet_id,
        range=f"'Search'!U{len(index_rows) + 2}:AQ",
        body={},
    ).execute()
    sheets.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={
            "requests": _build_search_format_requests(
                sheet_id=search_sheet_id,
                existing_rule_count=existing_rule_count,
            )
        },
    ).execute()
    return len(index_rows)


def _dashboard_issue_index_values(
    *,
    sheet_ids_by_title: Mapping[str, int],
) -> dict[str, object]:
    issue_titles = sorted(
        (
            title
            for title in sheet_ids_by_title
            if ISSUE_TAB_TITLE_RE.fullmatch(title) is not None
        ),
        key=lambda title: (
            int(ISSUE_TAB_TITLE_RE.fullmatch(title).group("year")),  # type: ignore[union-attr]
            int(ISSUE_TAB_TITLE_RE.fullmatch(title).group("number")),  # type: ignore[union-attr]
        ),
        reverse=True,
    )
    archive_rows = [["Issue archive", "", "Issue-specific reviewer tabs", "", "", "", ""]]
    archive_rows.extend(
        [
            "Issue archive",
            _resolve_metadata_cell_value(f"__sheet_link__:{title}", sheet_ids_by_title),
            "Source-linked recommendation review for this imported issue.",
            "Open and review against page references.",
            f"=COUNTA({_quote_sheet_title(title)}!A:A)",
            "parser-backed; review required",
            title,
        ]
        for title in issue_titles
    )
    return {
        "range": (
            f"'Navigation Dashboard'!A{ISSUE_ARCHIVE_START_ROW}:G"
            f"{ISSUE_ARCHIVE_START_ROW + len(archive_rows) - 1}"
        ),
        "values": archive_rows,
    }


def _build_aktuell_table_format_requests(
    *,
    sheet_id: int,
    stock_header_row: int,
    derivative_label_row: int,
    derivative_header_row: int,
) -> tuple[dict[str, object], ...]:
    """Return the reviewer-facing visual treatment for the stacked Aktuell tables."""

    def row_range(row_number: int) -> dict[str, int]:
        return {
            "sheetId": sheet_id,
            "startRowIndex": row_number - 1,
            "endRowIndex": row_number,
            "startColumnIndex": 0,
            "endColumnIndex": max(
                REVIEWER_STOCK_COLUMN_COUNT,
                REVIEWER_DERIVATIVE_COLUMN_COUNT,
            ),
        }

    def header_request(
        row_number: int,
        color: dict[str, float],
        *,
        end_column_index: int,
    ) -> dict[str, object]:
        return {
            "repeatCell": {
                "range": {
                    **row_range(row_number),
                    "endColumnIndex": end_column_index,
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": color,
                        "horizontalAlignment": "CENTER",
                        "textFormat": {
                            "bold": True,
                            "foregroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0},
                        },
                    }
                },
                "fields": "userEnteredFormat(backgroundColor,horizontalAlignment,textFormat)",
            }
        }

    return (
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": stock_header_row,
                    "startColumnIndex": 0,
                    "endColumnIndex": max(
                        REVIEWER_STOCK_COLUMN_COUNT,
                        REVIEWER_DERIVATIVE_COLUMN_COUNT,
                    ),
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0},
                        "horizontalAlignment": "LEFT",
                        "textFormat": {
                            "bold": False,
                            "foregroundColor": {"red": 0.0, "green": 0.0, "blue": 0.0},
                        },
                    }
                },
                "fields": (
                    "userEnteredFormat.backgroundColor,"
                    "userEnteredFormat.horizontalAlignment,"
                    "userEnteredFormat.textFormat.bold,"
                    "userEnteredFormat.textFormat.foregroundColor"
                ),
            }
        },
        header_request(
            stock_header_row,
            {"red": 0.0, "green": 0.45, "blue": 0.55},
            end_column_index=REVIEWER_STOCK_COLUMN_COUNT,
        ),
        {
            "repeatCell": {
                "range": row_range(derivative_label_row),
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": {"red": 0.15, "green": 0.16, "blue": 0.42},
                        "textFormat": {
                            "bold": True,
                            "foregroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0},
                        },
                    }
                },
                "fields": "userEnteredFormat(backgroundColor,textFormat)",
            }
        },
        header_request(
            derivative_header_row,
            {"red": 0.35, "green": 0.24, "blue": 0.65},
            end_column_index=REVIEWER_DERIVATIVE_COLUMN_COUNT,
        ),
    )


def _build_conditional_format_requests(
    tab_specs: tuple[GoogleSheetTabSpec, ...],
    sheet_properties: tuple[Mapping[str, object], ...],
) -> tuple[dict[str, object], ...]:
    sheet_ids_by_title = {
        str(properties.get("title")): int(properties["sheetId"])
        for properties in sheet_properties
        if properties.get("title") and "sheetId" in properties
    }
    properties_by_title = {
        str(properties.get("title")): properties
        for properties in sheet_properties
        if properties.get("title")
    }
    requests: list[dict[str, object]] = []
    for spec in tab_specs:
        if spec.title == "Insider Activity":
            sheet_id = sheet_ids_by_title.get(spec.title)
            if sheet_id is None:
                continue
            existing_rules = properties_by_title.get(spec.title, {}).get(
                "conditionalFormats", []
            )
            requests.extend(
                {
                    "deleteConditionalFormatRule": {
                        "sheetId": sheet_id,
                        "index": index,
                    }
                }
                for index in range(len(existing_rules) - 1, -1, -1)
                if _is_owned_insider_direction_format_rule(
                    existing_rules[index], sheet_id=sheet_id
                )
            )
            direction_column = _column_letter(spec.headers.index("Direction") + 1)
            data_start_row = spec.header_row + 1
            data_range = {
                "sheetId": sheet_id,
                "startRowIndex": spec.header_row,
                "startColumnIndex": 0,
                "endColumnIndex": len(spec.headers),
            }
            requests.extend(
                {
                    "addConditionalFormatRule": {
                        "rule": {
                            "ranges": [data_range],
                            "booleanRule": {
                                "condition": {
                                    "type": "CUSTOM_FORMULA",
                                    "values": [
                                        {
                                            "userEnteredValue": (
                                                f'=${direction_column}{data_start_row}="{direction}"'
                                            )
                                        }
                                    ],
                                },
                                "format": {"backgroundColor": color},
                            },
                        },
                        "index": 0,
                    }
                }
                for direction, color in INSIDER_DIRECTION_FORMATS
            )
            continue
        if spec.title not in {"AKTIONAER Depot", "Depot Transactions"}:
            continue
        sheet_id = sheet_ids_by_title.get(spec.title)
        if sheet_id is None or "Performance since buy" not in spec.headers:
            continue
        existing_rule_count = len(properties_by_title.get(spec.title, {}).get("conditionalFormats", []))
        requests.extend(
            {
                "deleteConditionalFormatRule": {
                    "sheetId": sheet_id,
                    "index": index,
                }
            }
            for index in range(existing_rule_count - 1, -1, -1)
        )
        column_index = spec.headers.index("Performance since buy")
        data_range = {
            "sheetId": sheet_id,
            "startRowIndex": spec.header_row,
            "startColumnIndex": column_index,
            "endColumnIndex": column_index + 1,
        }
        requests.extend(
            (
                _conditional_format_request(
                    data_range=data_range,
                    starts_with="+",
                    background_color={"red": 0.85, "green": 0.94, "blue": 0.85},
                    index=0,
                ),
                _conditional_format_request(
                    data_range=data_range,
                    starts_with="-",
                    background_color={"red": 0.98, "green": 0.84, "blue": 0.84},
                    index=0,
                ),
            )
        )
    return tuple(requests)


def _is_owned_insider_direction_format_rule(
    rule: object,
    *,
    sheet_id: int,
) -> bool:
    if not isinstance(rule, Mapping):
        return False
    ranges = rule.get("ranges")
    boolean_rule = rule.get("booleanRule")
    if not isinstance(ranges, list) or len(ranges) != 1 or not isinstance(boolean_rule, Mapping):
        return False
    raw_range = ranges[0]
    if raw_range not in (
        {
            "sheetId": sheet_id,
            "startRowIndex": 1,
            "startColumnIndex": 0,
            "endColumnIndex": 12,
        },
        {
            "sheetId": sheet_id,
            "startRowIndex": INSIDER_ACTIVITY_HEADER_ROW,
            "startColumnIndex": 0,
            "endColumnIndex": 12,
        },
    ):
        return False
    condition = boolean_rule.get("condition")
    if not isinstance(condition, Mapping):
        return False
    values = condition.get("values")
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], Mapping):
        return False
    return values[0].get("userEnteredValue") in {
        '=$I2="Acquired"',
        '=$I2="Disposed"',
        f'=$I{INSIDER_ACTIVITY_HEADER_ROW + 1}="Acquired"',
        f'=$I{INSIDER_ACTIVITY_HEADER_ROW + 1}="Disposed"',
    }


def _build_reviewer_action_format_requests(
    sheet_properties: tuple[Mapping[str, object], ...],
) -> tuple[dict[str, object], ...]:
    """Reconcile generated reviewer action colours without touching user rules.

    Reviewer stock and derivative rows use Action in column C. Their ranges
    differ (A:P and A:O respectively), and both remain open ended from row 2
    so they still apply after a compact reviewer tab expands on a later import.

    The ownership signature is deliberately narrow (one of this feature's
    formulas plus its exact table-wide range), so unrelated user conditional
    formatting remains untouched.  Delete indexes in descending order because
    Google Sheets renumbers rules after each deletion.
    """

    requests: list[dict[str, object]] = []
    for properties in sheet_properties:
        title = str(properties.get("title") or "")
        if title != "Aktuell" and ISSUE_TAB_TITLE_RE.fullmatch(title) is None:
            continue
        raw_sheet_id = properties.get("sheetId")
        if raw_sheet_id is None:
            continue
        sheet_id = int(raw_sheet_id)
        conditional_formats = properties.get("conditionalFormats", [])
        existing_rules = conditional_formats if isinstance(conditional_formats, list) else []
        requests.extend(
            {
                "deleteConditionalFormatRule": {"sheetId": sheet_id, "index": index},
            }
            for index in range(len(existing_rules) - 1, -1, -1)
            if _is_owned_reviewer_action_format_rule(existing_rules[index], sheet_id=sheet_id)
        )
        for action, color in REVIEWER_ACTION_FORMATS:
            requests.extend(
                (
                    _reviewer_action_conditional_format_request(
                        sheet_id=sheet_id,
                        action=action,
                        background_color=color,
                        action_column_index=REVIEWER_STOCK_ACTION_COLUMN_INDEX,
                        end_column_index=REVIEWER_STOCK_COLUMN_COUNT,
                    ),
                    _reviewer_action_conditional_format_request(
                        sheet_id=sheet_id,
                        action=action,
                        background_color=color,
                        action_column_index=REVIEWER_DERIVATIVE_ACTION_COLUMN_INDEX,
                        end_column_index=REVIEWER_DERIVATIVE_COLUMN_COUNT,
                    ),
                )
            )
    return tuple(requests)


def _reviewer_action_conditional_format_request(
    *,
    sheet_id: int,
    action: str,
    background_color: dict[str, float],
    action_column_index: int,
    end_column_index: int,
) -> dict[str, object]:
    action_column = _column_letter(action_column_index + 1)
    return {
        "addConditionalFormatRule": {
            "rule": {
                "ranges": [
                    {
                        "sheetId": sheet_id,
                        "startRowIndex": 1,
                        "startColumnIndex": 0,
                        "endColumnIndex": end_column_index,
                    }
                ],
                "booleanRule": {
                    "condition": {
                        "type": "CUSTOM_FORMULA",
                        "values": [{"userEnteredValue": f'=${action_column}2="{action}"'}],
                    },
                    "format": {"backgroundColor": background_color},
                },
            },
            "index": 0,
        }
    }


def _is_owned_reviewer_action_format_rule(rule: object, *, sheet_id: int) -> bool:
    if not isinstance(rule, Mapping):
        return False
    raw_ranges = rule.get("ranges")
    boolean_rule = rule.get("booleanRule")
    if not isinstance(raw_ranges, list) or len(raw_ranges) != 1 or not isinstance(boolean_rule, Mapping):
        return False
    raw_range = raw_ranges[0]
    if not isinstance(raw_range, Mapping):
        return False
    condition = boolean_rule.get("condition")
    if not isinstance(condition, Mapping) or condition.get("type") != "CUSTOM_FORMULA":
        return False
    values = condition.get("values")
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], Mapping):
        return False
    formula = values[0].get("userEnteredValue")
    if not isinstance(formula, str):
        return False
    owned_formula_ranges = {
        (f'=$C2="{action}"', REVIEWER_STOCK_COLUMN_COUNT)
        for action, _color in REVIEWER_ACTION_FORMATS
    } | {
        (f'=$C2="{action}"', REVIEWER_DERIVATIVE_COLUMN_COUNT)
        for action, _color in REVIEWER_ACTION_FORMATS
    } | {
        (f'=$C2="{action}"', len(LEGACY_AKTUELL_DERIVATIVE_HEADERS))
        for action, _color in REVIEWER_ACTION_FORMATS
    } | {
        # Legacy derivative formatting used Action in column A. Remove it on
        # the next export instead of leaving conflicting colour rules behind.
        (f'=$A2="{action}"', width)
        for action, _color in REVIEWER_ACTION_FORMATS
        for width in (
            REVIEWER_DERIVATIVE_COLUMN_COUNT,
            len(LEGACY_AKTUELL_DERIVATIVE_HEADERS),
        )
    }
    return (
        (formula, raw_range.get("endColumnIndex")) in owned_formula_ranges
        and raw_range.get("sheetId") == sheet_id
        and raw_range.get("startRowIndex") == 1
        and raw_range.get("startColumnIndex") == 0
    )


def _sheet_properties_with_formats(
    spreadsheet: Mapping[str, object],
) -> tuple[dict[str, object], ...]:
    sheet_properties: list[dict[str, object]] = []
    for sheet in spreadsheet.get("sheets", []):
        if not isinstance(sheet, Mapping):
            continue
        raw_properties = sheet.get("properties", {})
        if not isinstance(raw_properties, Mapping) or not raw_properties.get("title"):
            continue
        properties = dict(raw_properties)
        conditional_formats = sheet.get("conditionalFormats", [])
        if isinstance(conditional_formats, list):
            properties["conditionalFormats"] = conditional_formats
        sheet_properties.append(properties)
    return tuple(sheet_properties)


def _conditional_format_request(
    *,
    data_range: dict[str, object],
    starts_with: str,
    background_color: dict[str, float],
    index: int,
) -> dict[str, object]:
    return {
        "addConditionalFormatRule": {
            "rule": {
                "ranges": [data_range],
                "booleanRule": {
                    "condition": {
                        "type": "TEXT_STARTS_WITH",
                        "values": [{"userEnteredValue": starts_with}],
                    },
                    "format": {"backgroundColor": background_color},
                },
            },
            "index": index,
        }
    }


def _sheet_values_get(
    sheets,
    *,
    spreadsheet_id: str,
    range_name: str,
    value_render_option: str | None = None,
) -> list[list[object]]:
    request = {"spreadsheetId": spreadsheet_id, "range": range_name}
    if value_render_option is not None:
        request["valueRenderOption"] = value_render_option
    response = (
        sheets.spreadsheets()
        .values()
        .get(**request)
        .execute()
    )
    values = response.get("values", [])
    return values if isinstance(values, list) else []


def _fetch_sheet_properties(sheets, *, spreadsheet_id: str) -> tuple[Mapping[str, object], ...]:
    response = (
        sheets.spreadsheets()
        .get(spreadsheetId=spreadsheet_id, fields="sheets.properties(sheetId,title)")
        .execute()
    )
    return tuple(
        properties
        for properties in (
            sheet.get("properties", {})
            for sheet in response.get("sheets", [])
            if isinstance(sheet, Mapping)
        )
        if isinstance(properties, Mapping)
    )


def _fetch_sheet_properties_with_formats(
    sheets,
    *,
    spreadsheet_id: str,
) -> tuple[dict[str, object], ...]:
    response = (
        sheets.spreadsheets()
        .get(
            spreadsheetId=spreadsheet_id,
            fields="sheets(properties(sheetId,title),conditionalFormats)",
        )
        .execute()
    )
    return _sheet_properties_with_formats(response)


def _fetch_basic_filter_for_sheet(
    sheets,
    *,
    spreadsheet_id: str,
    sheet_id: int,
) -> dict[str, object]:
    """Return a copy of the native filter so criteria and sorting survive resizing."""

    response = (
        sheets.spreadsheets()
        .get(
            spreadsheetId=spreadsheet_id,
            fields="sheets(properties.sheetId,basicFilter)",
        )
        .execute()
    )
    for sheet in response.get("sheets", []):
        if not isinstance(sheet, Mapping):
            continue
        properties = sheet.get("properties", {})
        if not isinstance(properties, Mapping) or properties.get("sheetId") != sheet_id:
            continue
        basic_filter = sheet.get("basicFilter")
        return dict(basic_filter) if isinstance(basic_filter, Mapping) else {}
    return {}


def _managed_insider_filter_view_specs(
    *,
    sheet_id: int,
    data_row_count: int,
) -> tuple[dict[str, object], ...]:
    start_row_index = INSIDER_ACTIVITY_HEADER_ROW - 1
    end_row_index = max(
        INSIDER_ACTIVITY_HEADER_ROW + 1,
        data_row_count + INSIDER_ACTIVITY_HEADER_ROW,
    )
    view_range = {
        "sheetId": sheet_id,
        "startRowIndex": start_row_index,
        "endRowIndex": end_row_index,
        "startColumnIndex": 0,
        "endColumnIndex": 12,
    }
    sort_specs = [{"dimensionIndex": 6, "sortOrder": "DESCENDING"}]
    specs: list[dict[str, object]] = []
    for title, direction in zip(
        MANAGED_INSIDER_FILTER_VIEW_TITLES,
        (None, "Acquired", "Disposed"),
    ):
        view: dict[str, object] = {
            "title": title,
            "range": dict(view_range),
            "sortSpecs": list(sort_specs),
        }
        if direction is not None:
            view["criteria"] = {
                "8": {
                    "condition": {
                        "type": "TEXT_EQ",
                        "values": [{"userEnteredValue": direction}],
                    }
                }
            }
        specs.append(view)
    return tuple(specs)


def _apply_insider_instruction_presentation(
    sheets,
    *,
    spreadsheet_id: str,
    sheet_id: int,
) -> dict[str, int]:
    """Merge and format the compact bilingual banner above the ledger."""

    response = (
        sheets.spreadsheets()
        .get(
            spreadsheetId=spreadsheet_id,
            fields="sheets(properties(sheetId,title),merges)",
        )
        .execute()
    )
    insider_sheet = next(
        (
            sheet
            for sheet in response.get("sheets", [])
            if isinstance(sheet, Mapping)
            and isinstance(sheet.get("properties"), Mapping)
            and sheet["properties"].get("sheetId") == sheet_id
            and sheet["properties"].get("title") == "Insider Activity"
        ),
        None,
    )
    if insider_sheet is None:
        raise GoogleAccessError(
            "Insider Activity tab is missing while formatting instructions"
        )

    expected_merges = tuple(
        {
            "sheetId": sheet_id,
            "startRowIndex": row_index,
            "endRowIndex": row_index + 1,
            "startColumnIndex": 0,
            "endColumnIndex": 3,
        }
        for row_index in range(INSIDER_ACTIVITY_HEADER_ROW - 1)
    )
    existing_merges = insider_sheet.get("merges", [])
    existing = [
        merge for merge in existing_merges if isinstance(merge, Mapping)
    ] if isinstance(existing_merges, list) else []
    for expected in expected_merges:
        incompatible = next(
            (
                merge
                for merge in existing
                if dict(merge) != expected
                and _grid_ranges_overlap(merge, expected)
            ),
            None,
        )
        if incompatible is not None:
            raise GoogleAccessError(
                "Insider Activity has an incompatible merge in the instruction area"
            )

    requests: list[dict[str, object]] = [
        {"mergeCells": {"range": expected, "mergeType": "MERGE_ALL"}}
        for expected in expected_merges
        if expected not in existing
    ]
    instruction_colors = (
        {"red": 0.91, "green": 0.94, "blue": 0.99},
        {"red": 0.91, "green": 0.97, "blue": 0.93},
    )
    requests.extend(
        {
            "repeatCell": {
                "range": expected,
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": color,
                        "horizontalAlignment": "LEFT",
                        "verticalAlignment": "MIDDLE",
                        "wrapStrategy": "WRAP",
                        "textFormat": {
                            "bold": True,
                            "fontSize": 10,
                            "foregroundColor": {
                                "red": 0.12,
                                "green": 0.16,
                                "blue": 0.22,
                            },
                        },
                    }
                },
                "fields": "userEnteredFormat",
            }
        }
        for expected, color in zip(expected_merges, instruction_colors)
    )
    header_range = {
        "sheetId": sheet_id,
        "startRowIndex": INSIDER_ACTIVITY_HEADER_ROW - 1,
        "endRowIndex": INSIDER_ACTIVITY_HEADER_ROW,
        "startColumnIndex": 0,
        "endColumnIndex": 12,
    }
    requests.extend(
        (
            {
                "repeatCell": {
                    "range": header_range,
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": {
                                "red": 0.0,
                                "green": 0.45,
                                "blue": 0.55,
                            },
                            "horizontalAlignment": "CENTER",
                            "verticalAlignment": "MIDDLE",
                            "wrapStrategy": "WRAP",
                            "textFormat": {
                                "bold": True,
                                "foregroundColor": {
                                    "red": 1.0,
                                    "green": 1.0,
                                    "blue": 1.0,
                                },
                            },
                        }
                    },
                    "fields": "userEnteredFormat",
                }
            },
            {
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "ROWS",
                        "startIndex": 0,
                        "endIndex": INSIDER_ACTIVITY_HEADER_ROW - 1,
                    },
                    "properties": {"pixelSize": 54},
                    "fields": "pixelSize",
                }
            },
            {
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "ROWS",
                        "startIndex": INSIDER_ACTIVITY_HEADER_ROW - 1,
                        "endIndex": INSIDER_ACTIVITY_HEADER_ROW,
                    },
                    "properties": {"pixelSize": 30},
                    "fields": "pixelSize",
                }
            },
        )
    )
    sheets.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": requests},
    ).execute()
    return {
        "mergeCount": len(expected_merges),
        "mergesAdded": sum("mergeCells" in request for request in requests),
    }


def _grid_ranges_overlap(
    left: Mapping[str, object],
    right: Mapping[str, object],
) -> bool:
    if left.get("sheetId") != right.get("sheetId"):
        return False
    return (
        int(left.get("startRowIndex", 0)) < int(right.get("endRowIndex", 0))
        and int(right.get("startRowIndex", 0)) < int(left.get("endRowIndex", 0))
        and int(left.get("startColumnIndex", 0))
        < int(right.get("endColumnIndex", 0))
        and int(right.get("startColumnIndex", 0))
        < int(left.get("endColumnIndex", 0))
    )


def _apply_managed_insider_filter_views(
    sheets,
    *,
    spreadsheet_id: str,
    sheet_id: int,
    data_row_count: int,
) -> dict[str, int]:
    """Reconcile reusable family filter views without touching custom views."""

    response = (
        sheets.spreadsheets()
        .get(
            spreadsheetId=spreadsheet_id,
            fields=(
                "sheets(properties(sheetId,title),"
                "filterViews(filterViewId,title,range,criteria,sortSpecs))"
            ),
        )
        .execute()
    )
    insider_sheet = next(
        (
            sheet
            for sheet in response.get("sheets", [])
            if isinstance(sheet, Mapping)
            and isinstance(sheet.get("properties"), Mapping)
            and sheet["properties"].get("sheetId") == sheet_id
            and sheet["properties"].get("title") == "Insider Activity"
        ),
        None,
    )
    if insider_sheet is None:
        raise GoogleAccessError(
            "Insider Activity tab is missing while reconciling filter views"
        )

    existing_views = insider_sheet.get("filterViews", [])
    existing_by_title: dict[str, list[Mapping[str, object]]] = {}
    if isinstance(existing_views, list):
        for view in existing_views:
            if not isinstance(view, Mapping):
                continue
            title = str(view.get("title") or "")
            if title in MANAGED_INSIDER_FILTER_VIEW_TITLES:
                existing_by_title.setdefault(title, []).append(view)

    requests: list[dict[str, object]] = []
    added = 0
    updated = 0
    deleted = 0
    expected_views = _managed_insider_filter_view_specs(
        sheet_id=sheet_id,
        data_row_count=data_row_count,
    )
    for expected in expected_views:
        title = str(expected["title"])
        matches = existing_by_title.get(title, [])
        current = matches[0] if matches else None
        if current is None or not isinstance(current.get("filterViewId"), int):
            requests.append({"addFilterView": {"filter": expected}})
            added += 1
        else:
            current_shape = {
                "title": current.get("title"),
                "range": current.get("range"),
                "sortSpecs": current.get("sortSpecs") or [],
            }
            expected_shape = {
                "title": expected.get("title"),
                "range": expected.get("range"),
                "sortSpecs": expected.get("sortSpecs") or [],
            }
            if (current.get("criteria") or {}) != (expected.get("criteria") or {}):
                current_shape["criteria"] = current.get("criteria") or {}
                expected_shape["criteria"] = expected.get("criteria") or {}
            if current_shape != expected_shape:
                requests.append(
                    {
                        "updateFilterView": {
                            "filter": {
                                **expected,
                                "filterViewId": current["filterViewId"],
                            },
                            "fields": "title,range,sortSpecs,criteria",
                        }
                    }
                )
                updated += 1
        for duplicate in matches[1:]:
            duplicate_id = duplicate.get("filterViewId")
            if isinstance(duplicate_id, int):
                requests.append(
                    {"deleteFilterView": {"filterId": duplicate_id}}
                )
                deleted += 1

    if requests:
        sheets.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": requests},
        ).execute()
    return {
        "added": added,
        "updated": updated,
        "deleted": deleted,
        "count": len(expected_views),
    }


def _apply_managed_sheet_protections(
    sheets,
    *,
    spreadsheet_id: str,
    editor_email: str | None,
) -> list[str]:
    """Protect generated family tabs while leaving Search C1:E1 editable."""

    normalized_editor_email = str(editor_email or "").strip()
    if not normalized_editor_email or "@" not in normalized_editor_email:
        raise GoogleAccessError(
            "GOOGLE_SERVICE_ACCOUNT_EMAIL is required to protect generated "
            "Google Sheet tabs"
        )

    response = (
        sheets.spreadsheets()
        .get(
            spreadsheetId=spreadsheet_id,
            fields=(
                "sheets(properties(sheetId,title),"
                "protectedRanges(protectedRangeId,description,warningOnly,editors,"
                "range,unprotectedRanges))"
            ),
        )
        .execute()
    )
    sheet_states = [
        sheet
        for sheet in response.get("sheets", [])
        if isinstance(sheet, Mapping)
    ]
    managed_tabs = [
        sheet
        for sheet in sheet_states
        if isinstance(sheet.get("properties"), Mapping)
        and _is_managed_protection_tab(
            str(sheet["properties"].get("title") or "")
        )
        and "sheetId" in sheet["properties"]
    ]

    requests: list[dict[str, object]] = []
    protected_tab_titles: list[str] = []
    for sheet in managed_tabs:
        properties = sheet["properties"]
        sheet_id = int(properties["sheetId"])
        title = str(properties["title"])
        protected_ranges = sheet.get("protectedRanges", [])
        existing_ranges = protected_ranges if isinstance(protected_ranges, list) else []
        managed_ranges = [
            protected_range
            for protected_range in existing_ranges
            if isinstance(protected_range, Mapping)
            and str(protected_range.get("description") or "").startswith(
                MANAGED_PROTECTION_DESCRIPTION_PREFIX
            )
        ]
        current_managed = next(
            (
                protected_range
                for protected_range in existing_ranges
                if isinstance(protected_range, Mapping)
                if _managed_protection_is_current(
                    protected_range,
                    sheet_id=sheet_id,
                    title=title,
                    editor_email=normalized_editor_email,
                )
            ),
            None,
        )
        protected_tab_titles.append(title)
        incompatible_manual_sheet_protection = next(
            (
                protected_range
                for protected_range in existing_ranges
                if isinstance(protected_range, Mapping)
                and protected_range.get("range") == {"sheetId": sheet_id}
                and protected_range not in managed_ranges
                and not _managed_protection_is_current(
                    protected_range,
                    sheet_id=sheet_id,
                    title=title,
                    editor_email=normalized_editor_email,
                )
            ),
            None,
        )
        if incompatible_manual_sheet_protection is not None:
            raise GoogleAccessError(
                f"{title} has an incompatible manual whole-sheet protection; "
                "preserving it instead of replacing it"
            )
        for protected_range in managed_ranges:
            if protected_range is current_managed:
                continue
            protected_range_id = protected_range.get("protectedRangeId")
            if isinstance(protected_range_id, int):
                requests.append(
                    {
                        "deleteProtectedRange": {
                            "protectedRangeId": protected_range_id,
                        }
                    }
                )
        if current_managed is not None:
            continue
        protected_range: dict[str, object] = {
            "range": {"sheetId": sheet_id},
            "description": f"{MANAGED_PROTECTION_DESCRIPTION_PREFIX} {title}",
            "warningOnly": False,
            "editors": {
                "users": [normalized_editor_email],
                "domainUsersCanEdit": False,
            },
        }
        if title == "Search":
            protected_range["unprotectedRanges"] = [
                {
                    "sheetId": sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": 1,
                    "startColumnIndex": 2,
                    "endColumnIndex": 5,
                }
            ]
        requests.append(
            {"addProtectedRange": {"protectedRange": protected_range}}
        )

    if requests:
        sheets.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": requests},
        ).execute()
    return protected_tab_titles


def _managed_protection_is_current(
    protected_range: Mapping[str, object],
    *,
    sheet_id: int,
    title: str,
    editor_email: str,
) -> bool:
    if protected_range.get("range") != {"sheetId": sheet_id}:
        return False
    if protected_range.get("warningOnly") is True:
        return False
    editors = protected_range.get("editors")
    if not isinstance(editors, Mapping):
        return False
    users = editors.get("users")
    if not isinstance(users, list) or editor_email not in users:
        return False
    if editors.get("domainUsersCanEdit") is True:
        return False
    expected_unprotected = (
        [
            {
                "sheetId": sheet_id,
                "startRowIndex": 0,
                "endRowIndex": 1,
                "startColumnIndex": 2,
                "endColumnIndex": 5,
            }
        ]
        if title == "Search"
        else []
    )
    actual_unprotected = protected_range.get("unprotectedRanges") or []
    return actual_unprotected == expected_unprotected


def _is_managed_protection_tab(title: str) -> bool:
    return (
        title in {"Search", "Aktuell", "Insider Activity"}
        or ISSUE_TAB_TITLE_RE.fullmatch(title) is not None
    )


def _fetch_sheet_ids_by_title(sheets, *, spreadsheet_id: str) -> dict[str, int]:
    return {
        str(properties.get("title")): int(properties["sheetId"])
        for properties in _fetch_sheet_properties(sheets, spreadsheet_id=spreadsheet_id)
        if properties.get("title") and "sheetId" in properties
    }


def _fetch_sheet_row_counts_by_title(sheets, *, spreadsheet_id: str) -> dict[str, int]:
    response = (
        sheets.spreadsheets()
        .get(
            spreadsheetId=spreadsheet_id,
            fields="sheets.properties(sheetId,title,gridProperties.rowCount)",
        )
        .execute()
    )
    result: dict[str, int] = {}
    for sheet in response.get("sheets", []):
        if not isinstance(sheet, Mapping):
            continue
        properties = sheet.get("properties", {})
        if not isinstance(properties, Mapping):
            continue
        title = str(properties.get("title") or "").strip()
        grid_properties = properties.get("gridProperties", {})
        if not title or not isinstance(grid_properties, Mapping):
            continue
        row_count = grid_properties.get("rowCount")
        if isinstance(row_count, int) and row_count > 0:
            result[title] = row_count
    return result


def _normalize_sheet_row_values(values: list[object], *, width: int) -> list[str]:
    row = [str(value) if value is not None else "" for value in values[:width]]
    if len(row) < width:
        row.extend("" for _ in range(width - len(row)))
    return row


def _sanitize_stock_sheet_row(
    row: list[str],
    *,
    spec: GoogleSheetTabSpec,
    sheet_ids_by_title: Mapping[str, int] | None = None,
) -> list[str]:
    values = list(row)
    for header in (
        "Target",
        "Stop",
        "Current price",
    ):
        index = _header_index(spec, header)
        if index is not None:
            values[index] = _sheet_price_currency_only(values[index])
    dividend_yield_index = _header_index(spec, "Dividend Yield")
    if dividend_yield_index is not None:
        values[dividend_yield_index] = _sheet_unsigned_percent_only(
            values[dividend_yield_index]
        )
    for header in ("P/S Ratio 26e", "P/E Ratio 26e"):
        index = _header_index(spec, header)
        if index is not None:
            values[index] = _sheet_ratio_only(values[index])
    insider_index = _header_index(spec, "Insider Activity")
    if insider_index is not None and not values[insider_index] and sheet_ids_by_title:
        sheet_id = sheet_ids_by_title.get("Insider Activity")
        if sheet_id is not None and (
            _row_value_by_header(values, spec, "WKN")
            or _row_value_by_header(values, spec, "Company")
        ):
            values[insider_index] = f'=HYPERLINK("#gid={sheet_id}","Insiders")'
    return values


def _sheet_price_currency_only(value: str) -> str:
    if not value:
        return ""
    normalized = value.replace("€", "EUR").replace("$", "USD")
    match = SHEET_MONEY_WITH_CURRENCY_RE.search(normalized)
    if match is None:
        return ""
    prefix_currency, prefix_amount, suffix_amount, suffix_currency = match.groups()
    amount = prefix_amount or suffix_amount
    currency = prefix_currency or suffix_currency
    return f"{amount} {currency}"


def _sheet_unsigned_percent_only(value: str) -> str:
    normalized = " ".join((value or "").split())
    return normalized if SHEET_UNSIGNED_PERCENT_VALUE_RE.match(normalized) else ""


def _sheet_ratio_only(value: str) -> str:
    normalized = " ".join((value or "").split())
    return normalized if SHEET_RATIO_VALUE_RE.match(normalized) else ""


def _is_header_row(row: list[str], *, spec: GoogleSheetTabSpec) -> bool:
    return tuple(row[: len(spec.headers)]) == spec.headers


def _refinement_row_values(
    raw_row: Mapping[str, object],
    *,
    spec: GoogleSheetTabSpec,
) -> list[str]:
    values = [str(raw_row.get(header) or "") for header in spec.headers]
    _validate_sheet_row_width(spec.title, values, width=len(spec.headers))
    return values


def _refinement_page_sort_key(row: list[str]) -> tuple[int, str]:
    try:
        return int(row[0]), row[0]
    except (TypeError, ValueError):
        return 10**9, row[0] if row else ""


def _preserve_refinement_reviewer_notes(
    rows: list[list[str]],
    existing_rows: list[list[str]],
    *,
    spec: GoogleSheetTabSpec,
) -> list[list[str]]:
    page_index = _header_index(spec, "Page_number")
    notes_index = _header_index(spec, "reviewer_notes")
    if page_index is None or notes_index is None:
        return rows
    existing_notes_by_page = {
        row[page_index].strip(): row[notes_index].strip()
        for row in existing_rows
        if page_index < len(row) and notes_index < len(row) and row[notes_index].strip()
    }
    merged_rows: list[list[str]] = []
    for row in rows:
        merged = list(row)
        page = merged[page_index].strip()
        if not merged[notes_index].strip() and page in existing_notes_by_page:
            merged[notes_index] = existing_notes_by_page[page]
        merged_rows.append(merged)
    return merged_rows


def _count_non_empty_reviewer_notes(
    rows: list[list[str]],
    *,
    spec: GoogleSheetTabSpec,
) -> int:
    notes_index = _header_index(spec, "reviewer_notes")
    if notes_index is None:
        return 0
    return sum(1 for row in rows if notes_index < len(row) and row[notes_index].strip())


def _merge_stock_sheet_rows(
    rows: list[list[str]],
    *,
    spec: GoogleSheetTabSpec,
) -> list[list[str]]:
    grouped: dict[str, list[str]] = {}
    order: list[str] = []
    for row in rows:
        key = _stock_sheet_identity_key(row, spec=spec)
        if key not in grouped:
            grouped[key] = row
            order.append(key)
            continue
        grouped[key] = _merge_stock_sheet_row(grouped[key], row, spec=spec)
    return [grouped[key] for key in order]


def _stock_sheet_identity_key(row: list[str], *, spec: GoogleSheetTabSpec) -> str:
    wkn = _row_value_by_header(row, spec, "WKN")
    if wkn:
        return f"wkn:{wkn.casefold()}"
    company = _row_value_by_header(row, spec, "Company")
    return f"name:{re.sub(r'[^a-z0-9]+', '', company.casefold())}"


def _merge_stock_sheet_row(
    existing: list[str],
    incoming: list[str],
    *,
    spec: GoogleSheetTabSpec,
) -> list[str]:
    values = list(existing)
    latest_wins_headers = {
        "Target",
        "Stop",
        "Current price",
        "Market Cap",
        "Dividend Yield",
        "Performance since Recommendation",
        "Next Report",
        "Report type",
        "P/S Ratio 26e",
        "P/E Ratio 26e",
        "Chance",
        "Risk",
        "Insider Activity",
        "Enrichment status",
        "Import date",
    }
    fill_only_headers = {
        "Company",
        "WKN",
    }
    for header in latest_wins_headers:
        _copy_stock_sheet_value(values, incoming, spec, header, overwrite=True)
    for header in fill_only_headers:
        _copy_stock_sheet_value(values, incoming, spec, header, overwrite=False)

    recommendation_index = _header_index(spec, "Recommendation")
    if recommendation_index is not None and incoming[recommendation_index]:
        values[recommendation_index] = incoming[recommendation_index]
        held_since_index = _header_index(spec, "Held since")
        if held_since_index is not None:
            values[held_since_index] = incoming[held_since_index]

    source_index = _header_index(spec, "Issue:Page")
    if source_index is not None:
        values[source_index] = _join_unique_sheet_values(
            (values[source_index], incoming[source_index]),
            separator=" | ",
        )

    return values


def _copy_stock_sheet_value(
    values: list[str],
    incoming: list[str],
    spec: GoogleSheetTabSpec,
    header: str,
    *,
    overwrite: bool,
) -> None:
    index = _header_index(spec, header)
    if index is None or not incoming[index]:
        return
    if overwrite or not values[index]:
        values[index] = incoming[index]


def _row_value_by_header(row: list[str], spec: GoogleSheetTabSpec, header: str) -> str:
    index = _header_index(spec, header)
    if index is None or index >= len(row):
        return ""
    return row[index].strip()


def _header_index(spec: GoogleSheetTabSpec, header: str) -> int | None:
    for index, candidate in enumerate(spec.headers):
        if candidate == header:
            return index
    return None


def _looks_like_richer_sheet_recommendation(candidate: str, current: str) -> bool:
    return (
        bool(re.search(r"\d{2}\.\d{2}\.\d{2,4}", candidate)),
        len(candidate),
    ) > (
        bool(re.search(r"\d{2}\.\d{2}\.\d{2,4}", current)),
        len(current),
    )


def _join_unique_sheet_values(values: tuple[str, ...], *, separator: str) -> str:
    result: list[str] = []
    for value in values:
        for part in value.split(separator):
            stripped = part.strip()
            if stripped and stripped not in result:
                result.append(stripped)
    return separator.join(result)


def _validate_sheet_row_width(tab: str, values: list[object], *, width: int) -> None:
    actual_width = len(values)
    if actual_width != width:
        raise GoogleAccessError(
            f"workbook plan row for {tab} must contain {width} values, got {actual_width}"
        )


def _row_has_issue_id(
    row: list[object],
    spec: GoogleSheetTabSpec,
    *,
    issue_id: str,
) -> bool:
    source_index = _issue_source_column_index(spec)
    if source_index is None or source_index >= len(row):
        return False
    source_value = str(row[source_index] or "").strip()
    return any(
        part.strip() == issue_id or part.strip().startswith(f"{issue_id}:")
        for part in source_value.split("|")
    )


def _issue_source_column_index(spec: GoogleSheetTabSpec) -> int | None:
    for index, header in enumerate(spec.headers):
        normalized = header.strip().lower()
        if normalized in {"issue", "issue:page"}:
            return index
    return None


def _quote_sheet_title(title: str) -> str:
    escaped_title = title.replace("'", "''")
    return f"'{escaped_title}'"


def _column_letter(column_number: int) -> str:
    if column_number < 1:
        raise GoogleAccessError("column_number must be positive")

    letters = ""
    current = column_number
    while current:
        current, remainder = divmod(current - 1, 26)
        letters = f"{chr(65 + remainder)}{letters}"
    return letters


def _google_service_factories(config: GoogleAccessConfig):
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ModuleNotFoundError as error:
        raise GoogleAccessError(
            "Google API dependencies are not installed. Run `pip install -e .` in a virtualenv."
        ) from error

    credentials = service_account.Credentials.from_service_account_file(
        str(config.credentials_path),
        scopes=[GOOGLE_DRIVE_READONLY_SCOPE, GOOGLE_SHEETS_SCOPE],
    )

    return (
        lambda: build("drive", "v3", credentials=credentials, cache_discovery=False),
        lambda: build("sheets", "v4", credentials=credentials, cache_discovery=False),
    )


def _service_account_email_from_credentials(credentials_path: Path) -> str:
    try:
        payload = json.loads(credentials_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise GoogleAccessError(
            "GOOGLE_APPLICATION_CREDENTIALS must be a readable service-account "
            "JSON file"
        ) from error
    client_email = (
        str(payload.get("client_email") or "").strip()
        if isinstance(payload, Mapping)
        else ""
    )
    if not client_email or "@" not in client_email:
        raise GoogleAccessError(
            "GOOGLE_SERVICE_ACCOUNT_EMAIL is required when the credentials "
            "file does not contain client_email"
        )
    return client_email


def _required_value(env: Mapping[str, str], key: str) -> str:
    value = str(env.get(key) or "").strip()
    if not value:
        raise GoogleAccessError(f"{key} is required")
    return value


def _validate_google_id(name: str, value: str) -> None:
    if not GOOGLE_ID_RE.match(value):
        raise GoogleAccessError(f"{name} must look like a Google Drive/Sheets id")


def _drive_file_metadata_from_payload(payload: Mapping[str, object]) -> DrivePdfMetadata:
    drive_file_id = _required_payload_string(payload, "id")
    name = _required_payload_string(payload, "name")
    mime_type = _required_payload_string(payload, "mimeType")
    size_value = payload.get("size")
    size_bytes = int(size_value) if size_value not in (None, "") else None

    return DrivePdfMetadata(
        drive_file_id=drive_file_id,
        name=name,
        mime_type=mime_type,
        size_bytes=size_bytes,
        md5_checksum=_optional_payload_string(payload.get("md5Checksum")),
        created_time=_optional_payload_string(payload.get("createdTime")),
        modified_time=_optional_payload_string(payload.get("modifiedTime")),
        web_view_link=_optional_payload_string(payload.get("webViewLink")),
    )


def _required_payload_string(payload: Mapping[str, object], key: str) -> str:
    value = _optional_payload_string(payload.get(key))
    if value is None:
        raise GoogleAccessError(f"Drive file metadata is missing {key}")
    return value


def _optional_payload_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
