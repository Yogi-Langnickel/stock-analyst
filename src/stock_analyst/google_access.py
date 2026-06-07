"""Google Drive/Sheets access configuration and metadata-only helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import os
import re


GOOGLE_DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
GOOGLE_SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"

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


DATA_BACKED_TAB_TITLES = {
    "Navigation Dashboard",
    "Latest Issue Recommendations",
    "Stocks",
    "Derivative Tips",
    "AKTIONAER Depot",
    "Depot Transactions",
    "Insider Activity",
    "Dividend Focus",
    "Extraction Audit",
}


NAVIGATION_DASHBOARD_CELLS: tuple[tuple[str, str], ...] = (
    ("A1", "Der Aktionär Summaries"),
    ("A2", "Navigation Dashboard"),
    ("A3", "Draft reviewer workbook. Verify issue/page/source fields before family-facing export."),
    ("A6", "Core review"),
    ("B6", "__sheet_link__:Latest Issue Recommendations"),
    ("C6", "Current import recommendations for quick reviewer triage."),
    ("D6", "Start here after each issue import."),
    ("E6", "=COUNTA('Latest Issue Recommendations'!A2:A)"),
    ("F6", "parser-backed; review required"),
    ("G6", "Source-linked magazine rows only; not investment advice."),
    ("A7", "Core review"),
    ("B7", "__sheet_link__:Stocks"),
    ("C7", "Canonical equity rows merged from recommendation cards, Quick Check, and Chart Check."),
    ("D7", "Review stock identity and current source fields."),
    ("E7", "=COUNTA('Stocks'!A2:A)"),
    ("F7", "parser-backed; review required"),
    ("G7", "Price, target, stop, yield, and ratio columns are shape-sanitized."),
    ("A8", "Core review"),
    ("B8", "__sheet_link__:Dividend Focus"),
    ("C8", "Dividend table rows and multi-period dividend context."),
    ("D8", "Validate yield/date/price fields."),
    ("E8", "=COUNTA('Dividend Focus'!A2:A)"),
    ("F8", "parser-backed; review required"),
    ("G8", "Dividend yield is source context, not a guaranteed future payout."),
    ("A9", "Core review"),
    ("B9", "__sheet_link__:Derivative Tips"),
    ("C9", "Calls, puts, certificates, and derivative overview rows."),
    ("D9", "Check derivative WKN/product terms."),
    ("E9", "=COUNTA('Derivative Tips'!A2:A)"),
    ("F9", "parser-backed; review required"),
    ("G9", "Highest risk surface; do not group rows by underlying alone."),
    ("A10", "Publisher portfolio"),
    ("B10", "__sheet_link__:AKTIONAER Depot"),
    ("C10", "Publisher model-depot position snapshots."),
    ("D10", "Treat as source context, not advice."),
    ("E10", "=COUNTA('AKTIONAER Depot'!A2:A)"),
    ("F10", "parser-backed; review required"),
    ("G10", "This is the publisher's model portfolio, not a household portfolio."),
    ("A11", "Publisher portfolio"),
    ("B11", "__sheet_link__:Depot Transactions"),
    ("C11", "Publisher transaction and no-transaction ledger."),
    ("D11", "Check event history."),
    ("E11", "=COUNTA('Depot Transactions'!A2:A)"),
    ("F11", "parser-backed; review required"),
    ("G11", "Use for source history and transaction evidence."),
    ("A12", "Source detail"),
    ("B12", "__sheet_link__:Insider Activity"),
    ("C12", "SEC Form 4 insider activity rows and stock-level signal context."),
    ("D12", "Review filing links and transaction classification."),
    ("E12", "=COUNTA('Insider Activity'!A2:A)"),
    ("F12", "planned; review required"),
    ("G12", "Signals are context only and must link to source filings."),
    ("A13", "QA"),
    ("B13", "__sheet_link__:Extraction Audit"),
    ("C13", "Parser warnings, skipped sections, OCR-needed pages, and review notes."),
    ("D13", "Fix blockers before relying on rows."),
    ("E13", "=COUNTA('Extraction Audit'!A2:A)"),
    ("F13", "parser-backed; internal"),
    ("G13", "Check this tab after each import."),
)


DEFAULT_SHEET_TABS: tuple[GoogleSheetTabSpec, ...] = (
    GoogleSheetTabSpec(
        "Navigation Dashboard",
        ("Area", "Open", "What this tab is for", "Reviewer action", "Row count", "Status", "Notes"),
        "Low-clutter entrypoint for active workbook tabs.",
        header_row=5,
        metadata_cells=NAVIGATION_DASHBOARD_CELLS,
        frozen_rows=5,
        frozen_columns=2,
        table_starts_at="A5",
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
        "Latest Issue Recommendations",
        (
            "Issue",
            "Page",
            "Company",
            "WKN",
            "Recommendation",
            "Magazine Current Price",
            "Target",
            "Stop",
            "Chance/Risk",
            "Dividend Yield",
            "Next Report",
            "Comment",
            "Source tab",
            "Review status",
            "date updated",
        ),
        "Current issue recommendation rows for quick reviewer triage.",
        header_row=1,
        frozen_rows=1,
        frozen_columns=3,
        table_starts_at="A1",
        layout_notes=(
            "Generated from the current workbook-export plan only.",
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
            "Chance/Risk",
            "Insider Activity",
            "Comment",
            "issue",
            "page",
            "date updated",
        ),
        "Equity dashboard and reviewed stock mentions.",
        header_row=1,
        frozen_rows=1,
        frozen_columns=2,
        table_starts_at="A1",
        layout_notes=(
            "Only explicit stock mentions become rows; do not fan out index constituents.",
            "Quick-check and chart-check stock rows also surface here with split source fields.",
            "Current price preserves printed Akt. Kurs as amount and currency until reviewed enrichment refreshes it.",
            "Target, Stop, and Current price must contain only amount and currency.",
            "Next Report stores only the date; Report type stores the event label.",
            "Recommendation stores the current action/status; Held since stores the source issue for holds.",
            "Insider Activity is reserved for SEC Form 4 signal links from the dedicated tab.",
            "Row-level date updated is the last field and advances on enrichment or newer mention.",
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
            "date updated",
        ),
        "ETF recommendations and fund-specific context.",
        frozen_rows=2,
        frozen_columns=2,
        table_starts_at="A2",
        layout_notes=(
            "Reserve row 1 for fund family, holdings, fee, and distribution context.",
            "Rows remain review-gated until ETF parser/export is implemented.",
            "Row-level date updated is the last field.",
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
            "date updated",
        ),
        "Commodity recommendations and context.",
        frozen_rows=2,
        frozen_columns=1,
        table_starts_at="A2",
        layout_notes=(
            "Reserve row 1 for commodity spot/futures context.",
            "Rows remain review-gated until commodity parser/export is implemented.",
            "Row-level date updated is the last field.",
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
            "date updated",
        ),
        "Option and derivative recommendations.",
        frozen_rows=2,
        frozen_columns=1,
        table_starts_at="A2",
        layout_notes=(
            "Reserve row 1 for option risk notes and stale-data warnings.",
            "Detailed option and derivative rows emit to Derivative Tips to avoid split review queues.",
            "Row-level date updated is the last field.",
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
            "date updated",
        ),
        "Crypto recommendations and digital-asset context.",
        frozen_rows=2,
        frozen_columns=1,
        table_starts_at="A2",
        layout_notes=(
            "Reserve row 1 for exchange, liquidity, and risk context.",
            "Rows remain review-gated until crypto parser/export is implemented.",
            "Row-level date updated is the last field.",
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
            "date updated",
        ),
        "Currency-pair recommendations and macro context.",
        frozen_rows=2,
        frozen_columns=1,
        table_starts_at="A2",
        layout_notes=(
            "Reserve row 1 for macro/calendar context.",
            "Rows remain review-gated until forex parser/export is implemented.",
            "Row-level date updated is the last field.",
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
            "Issue",
            "Page",
            "date updated",
        ),
        "Derivative overview tables and option cards.",
        frozen_columns=2,
        layout_notes=(
            "Parser-backed for derivative recommendation cards and the Derivate-Tipps im Rueckblick table.",
            "Derivative Source IDs stay in row metadata; issue/page are visible provenance.",
            "Row-level date updated is the last field.",
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
            "Issue",
            "Page",
            "date updated",
        ),
        "Publisher model-depot position snapshots.",
        frozen_columns=2,
        layout_notes=(
            "Parser-backed for the weekly publisher model-depot snapshot.",
            "Use one row per issue/position once parser-backed.",
            "Row-level date updated is the last field.",
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
            "Issue",
            "Page",
            "date updated",
        ),
        "Publisher model-depot transaction ledger.",
        frozen_columns=2,
        layout_notes=(
            "Parser-backed for explicit no-transaction weeks and future transaction rows.",
            "Include explicit no-transaction weeks once parser-backed.",
            "Row-level date updated is the last field.",
        ),
        parser_status="parser_backed",
    ),
    GoogleSheetTabSpec(
        "Insider Activity",
        (
            "Company",
            "WKN",
            "Ticker",
            "CIK",
            "Insider",
            "Relationship",
            "Transaction date",
            "Transaction code",
            "Direction",
            "Shares",
            "Price",
            "Transaction value",
            "Shares owned after",
            "Filing date",
            "SEC filing URL",
            "Signal",
            "Review status",
            "Issue",
            "Page",
            "date updated",
        ),
        "SEC Form 4 insider activity context for reviewed stock rows.",
        frozen_columns=3,
        layout_notes=(
            "Planned parser-backed destination for SEC EDGAR Form 4 enrichment rows.",
            "Rows remain review-gated and must retain direct SEC filing URLs.",
            "Stock-level Insider Activity indicators should summarize only reviewed rows from this tab.",
        ),
        parser_status="planned",
    ),
    GoogleSheetTabSpec(
        "Statistics Context",
        ("Issue", "Page", "Context type", "Name", "Value", "Period", "Source note", "Review status"),
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
            "Issue",
            "Page",
            "date updated",
        ),
        "Dividend section and multi-period dividend data.",
        frozen_columns=3,
        layout_notes=(
            "Parser-backed for dividend strategy table rows today.",
            "Keep multi-period dividend context here and concise dividend decision data in Stocks.",
            "Row-level date updated is the last field.",
        ),
        parser_status="parser_backed",
    ),
    GoogleSheetTabSpec(
        "Extraction Audit",
        ("Run ID", "Issue", "Page", "Section", "Severity", "Message", "Action", "Created at"),
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
    "Stock Quickcheck",
}
GENERATED_SHEET_TAB_TITLES = {
    spec.title for spec in ALL_SHEET_TABS
} | RETIRED_GENERATED_SHEET_TAB_TITLES


DEFAULT_SHEET_TABS = tuple(
    spec for spec in DEFAULT_SHEET_TABS if spec.title in DATA_BACKED_TAB_TITLES
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
    service_account_email = merged.get("GOOGLE_SERVICE_ACCOUNT_EMAIL") or None

    _validate_google_id("GOOGLE_DRIVE_FOLDER_ID", drive_folder_id)
    _validate_google_id("GOOGLE_SHEETS_SPREADSHEET_ID", spreadsheet_id)
    if not credentials_path.exists():
        raise GoogleAccessError(
            f"GOOGLE_APPLICATION_CREDENTIALS does not exist: {credentials_path}"
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
    tab_specs: tuple[GoogleSheetTabSpec, ...] = DEFAULT_SHEET_TABS,
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
        format_requests = _build_conditional_format_requests(tab_specs, sheet_properties)
        if format_requests:
            sheets.spreadsheets().batchUpdate(
                spreadsheetId=config.sheets_spreadsheet_id,
                body={"requests": list(format_requests)},
            ).execute()
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
        "deletedTabCount": len(delete_sheet_ids),
        "headerRowsWritten": len(tab_specs) if write_headers else 0,
        "preHeaderRangesCleared": list(pre_header_clear_ranges)
        if "pre_header_clear_ranges" in locals()
        else [],
        "formatRulesWritten": len(format_requests) if "format_requests" in locals() else 0,
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
    tab_specs: tuple[GoogleSheetTabSpec, ...] = DEFAULT_SHEET_TABS,
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

    if sheets_service_factory is None:
        _drive_service_factory, sheets_service_factory = _google_service_factories(config)

    issue_id = str(workbook_plan.get("issueId") or "").strip()
    raw_rows = workbook_plan.get("rows")
    if not issue_id:
        raise GoogleAccessError("workbook plan is missing issueId")
    if not isinstance(raw_rows, list):
        raise GoogleAccessError("workbook plan is missing rows list")
    if not allow_draft_rows:
        _require_family_export_approval_audit(workbook_plan, raw_rows)

    specs_by_title = {spec.title: spec for spec in tab_specs}
    rows_by_tab: dict[str, list[list[str]]] = {}
    skipped_count = 0
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
        _validate_sheet_row_width(tab, values, width=len(spec.headers))
        normalized_values = _normalize_sheet_row_values(values, width=len(spec.headers))
        if tab == "Stocks":
            normalized_values = _sanitize_stock_sheet_row(normalized_values, spec=spec)
        rows_by_tab.setdefault(tab, []).append(normalized_values)

    sheets = sheets_service_factory()
    bootstrap_result = bootstrap_google_sheet(
        config,
        sheets_service_factory=sheets_service_factory,
        tab_specs=tab_specs,
        write_headers=True,
    )
    sheet_ids_by_title = _fetch_sheet_ids_by_title(
        sheets,
        spreadsheet_id=config.sheets_spreadsheet_id,
    )
    try:
        write_ranges: list[dict[str, object]] = []
        post_write_clear_ranges: list[str] = []
        cleared_tabs: list[str] = []
        restored_existing_count = 0
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
            if tab == "Latest Issue Recommendations" and replace_issue:
                kept_rows = []
            elif replace_issue:
                kept_rows = [
                    _normalize_sheet_row_values(row, width=len(spec.headers))
                    for row in existing_rows
                    if _row_issue_id(row, spec) != issue_id
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

        if write_ranges:
            sheets.spreadsheets().values().batchUpdate(
                spreadsheetId=config.sheets_spreadsheet_id,
                body={
                    "valueInputOption": "RAW",
                    "data": write_ranges,
                },
            ).execute()
        for range_name in post_write_clear_ranges:
            sheets.spreadsheets().values().clear(
                spreadsheetId=config.sheets_spreadsheet_id,
                range=range_name,
                body={},
            ).execute()
    except Exception as error:
        raise GoogleAccessError(
            "Google Sheets workbook row export failed. Verify network access, "
            "API enablement, service-account sheet sharing, and configured spreadsheet ID."
        ) from error

    written_count = sum(len(rows) for rows in rows_by_tab.values())
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
        "tabsWritten": sorted(rows_by_tab),
        "rowsWritten": written_count,
        "rowsSkipped": skipped_count,
        "clearedTabs": sorted(cleared_tabs),
        "staleRangesCleared": post_write_clear_ranges,
        "restoredExistingRows": restored_existing_count,
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

    if approval_audit.get("approvalSource") != "private_reviewer_csv":
        raise GoogleAccessError(
            "family-visible workbook export requires private reviewer CSV approval provenance"
        )
    if approval_audit.get("staleApprovalDetected") is not False:
        raise GoogleAccessError(
            "family-visible workbook export cannot use stale or unchecked approval hashes"
        )
    if approval_audit.get("hashMismatchRows") not in (0, None):
        raise GoogleAccessError(
            "family-visible workbook export cannot include approval hash mismatches"
        )
    if approval_audit.get("invalidEvidenceRows") not in (0, None):
        raise GoogleAccessError(
            "family-visible workbook export cannot include invalid approval evidence"
        )
    if approval_audit.get("rowCount") != len(raw_rows):
        raise GoogleAccessError(
            "family-visible workbook export approval audit row count does not match rows"
        )

    approved_row_count = sum(
        1 for row in raw_rows if isinstance(row, Mapping) and _is_approved_export_row(row)
    )
    if approval_audit.get("approvedRows") != approved_row_count:
        raise GoogleAccessError(
            "family-visible workbook export approved row count does not match approval audit"
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
) -> list[list[object]]:
    response = (
        sheets.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=range_name)
        .execute()
    )
    values = response.get("values", [])
    return values if isinstance(values, list) else []


def _fetch_sheet_ids_by_title(sheets, *, spreadsheet_id: str) -> dict[str, int]:
    response = (
        sheets.spreadsheets()
        .get(spreadsheetId=spreadsheet_id, fields="sheets.properties(sheetId,title)")
        .execute()
    )
    return {
        str(properties.get("title")): int(properties["sheetId"])
        for properties in (
            sheet.get("properties", {})
            for sheet in response.get("sheets", [])
            if isinstance(sheet, Mapping)
        )
        if properties.get("title") and "sheetId" in properties
    }


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
        "Chance/Risk",
        "Insider Activity",
        "date updated",
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

    comment_index = _header_index(spec, "Comment")
    if comment_index is not None:
        values[comment_index] = _join_unique_sheet_values(
            (values[comment_index], incoming[comment_index]),
            separator=" | ",
        )

    issue_index = _header_index(spec, "issue")
    if issue_index is not None:
        values[issue_index] = _join_unique_sheet_values(
            (values[issue_index], incoming[issue_index]),
            separator=", ",
        )

    page_index = _header_index(spec, "page")
    if page_index is not None:
        values[page_index] = _join_unique_sheet_values(
            (values[page_index], incoming[page_index]),
            separator=", ",
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


def _row_issue_id(row: list[object], spec: GoogleSheetTabSpec) -> str:
    issue_index = _issue_column_index(spec)
    if issue_index is None or issue_index >= len(row):
        return ""
    return str(row[issue_index] or "").strip()


def _issue_column_index(spec: GoogleSheetTabSpec) -> int | None:
    for index, header in enumerate(spec.headers):
        if header.strip().lower() == "issue":
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
