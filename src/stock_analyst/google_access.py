"""Google Drive/Sheets access configuration and metadata-only helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import os
import re
from typing import Mapping


GOOGLE_DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
GOOGLE_SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"

GOOGLE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{10,}$")


class GoogleAccessError(ValueError):
    """Raised when Google Drive/Sheets access is not configured correctly."""


@dataclass(frozen=True)
class GoogleAccessConfig:
    drive_folder_id: str
    sheets_spreadsheet_id: str
    credentials_path: Path
    service_account_email: str | None = None

    def to_public_dict(self) -> dict[str, object]:
        return {
            "driveFolderId": self.drive_folder_id,
            "sheetsSpreadsheetId": self.sheets_spreadsheet_id,
            "credentialsPath": str(self.credentials_path),
            "serviceAccountEmail": self.service_account_email,
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
        return f"drive_{self.drive_file_id[:16]}"

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "sourcePdfId": self.source_pdf_id,
            "driveFileId": self.drive_file_id,
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
            result["webViewLink"] = self.web_view_link
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


DEFAULT_SHEET_TABS: tuple[GoogleSheetTabSpec, ...] = (
    GoogleSheetTabSpec(
        "Navigation Dashboard",
        ("Area", "Tab", "Purpose", "Status"),
        "Low-clutter entrypoint for the workbook.",
        layout_notes=(
            "Use spreadsheet-native links to major workbook areas.",
            "Keep only high-level status and navigation here.",
        ),
        parser_status="layout_only",
    ),
    GoogleSheetTabSpec(
        "Stocks",
        (
            "Company",
            "WKN",
            "Current Price*",
            "Price at Recommendation",
            "Dividend Yield",
            "Chance/Risk",
            "P/S Ratio 26e",
            "P/E Ratio 26e",
            "Target",
            "Stop",
            "Recommendation",
            "issue",
            "page",
            "date updated",
        ),
        "Equity dashboard and reviewed stock mentions.",
        header_row=3,
        frozen_rows=3,
        frozen_columns=2,
        table_starts_at="A3",
        layout_notes=(
            "Only explicit stock mentions become rows; do not fan out index constituents.",
            "Current Price* is daily enrichment; Price at Recommendation is the magazine source value.",
            "Row-level date updated is the last field and advances on enrichment or newer mention.",
        ),
        parser_status="parser_backed",
    ),
    GoogleSheetTabSpec(
        "ETF",
        (
            "ETF",
            "WKN",
            "Current Price*",
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
            "Current Price*",
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
            "Current Price*",
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
            "Current price",
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
            "Current price",
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
            "Issue",
            "Page",
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
            "Entry price",
            "Current price",
            "Performance",
            "Target",
            "Stop",
            "Recommendation",
            "Review status",
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
            "Issue",
            "Page",
            "Instrument",
            "WKN",
            "Quantity",
            "Buy date",
            "Buy price",
            "Current price",
            "Value",
            "Performance since buy",
            "Stop",
            "Review status",
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
            "Issue",
            "Page",
            "Action",
            "Instrument",
            "WKN",
            "Quantity",
            "Transaction date",
            "Price",
            "Performance since buy",
            "Review status",
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
        "Chart Check",
        ("Issue", "Page", "Instrument", "WKN", "Signal", "Trend", "Support", "Resistance", "Review status"),
        "Chart-check section extraction.",
        frozen_columns=3,
        layout_notes=(
            "Currently audit-hinted, not row-emitted.",
            "Attach reviewed chart signals back to matching stock rows by WKN.",
        ),
        parser_status="audit_hint",
    ),
    GoogleSheetTabSpec(
        "Stock Quickcheck",
        ("Issue", "Page", "Instrument", "WKN", "Evaluation", "Signal", "Comment", "Review status"),
        "Normalized quick-check table rows.",
        frozen_columns=3,
        layout_notes=(
            "Currently audit-hinted, not row-emitted.",
            "Keep full publisher quick-check table here; surface only reviewed summary in Stocks.",
        ),
        parser_status="audit_hint",
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
            "Issue",
            "Page",
            "Instrument",
            "WKN",
            "Payout count",
            "Yield",
            "Period",
            "Ex date",
            "Review status",
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
            .get(fileId=config.drive_folder_id, fields="id,name,mimeType", supportsAllDrives=True)
            .execute()
        )
        spreadsheet = (
            sheets.spreadsheets()
            .get(
                spreadsheetId=config.sheets_spreadsheet_id,
                fields="spreadsheetId,properties.title,sheets.properties.title",
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
        "serviceAccountEmail": config.service_account_email,
        "drive": {
            "folderId": folder.get("id"),
            "folderName": folder.get("name"),
            "mimeType": folder.get("mimeType"),
        },
        "sheets": {
            "spreadsheetId": spreadsheet.get("spreadsheetId"),
            "title": spreadsheet.get("properties", {}).get("title"),
            "tabs": [
                sheet.get("properties", {}).get("title")
                for sheet in spreadsheet.get("sheets", [])
                if sheet.get("properties", {}).get("title")
            ],
        },
    }


def bootstrap_google_sheet(
    config: GoogleAccessConfig,
    *,
    sheets_service_factory=None,
    tab_specs: tuple[GoogleSheetTabSpec, ...] = DEFAULT_SHEET_TABS,
    write_headers: bool = True,
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
                fields="spreadsheetId,properties.title,sheets.properties.title",
            )
            .execute()
        )
        existing_titles = tuple(
            sheet.get("properties", {}).get("title")
            for sheet in spreadsheet.get("sheets", [])
            if sheet.get("properties", {}).get("title")
        )
        missing_titles = tuple(
            spec.title for spec in tab_specs if spec.title not in set(existing_titles)
        )

        if missing_titles:
            sheets.spreadsheets().batchUpdate(
                spreadsheetId=config.sheets_spreadsheet_id,
                body={
                    "requests": [
                        {"addSheet": {"properties": {"title": title}}}
                        for title in missing_titles
                    ]
                },
            ).execute()

        header_ranges = _build_sheet_header_ranges(tab_specs) if write_headers else ()
        if header_ranges:
            sheets.spreadsheets().values().batchUpdate(
                spreadsheetId=config.sheets_spreadsheet_id,
                body={
                    "valueInputOption": "RAW",
                    "data": list(header_ranges),
                },
            ).execute()
    except Exception as error:
        raise GoogleAccessError(
            "Google Sheets bootstrap failed. Verify network access, API enablement, "
            "service-account sheet sharing, and configured spreadsheet ID."
        ) from error

    return {
        "ok": True,
        "externalServicesEnabled": True,
        "spreadsheetId": config.sheets_spreadsheet_id,
        "existingTabs": list(existing_titles),
        "createdTabs": list(missing_titles),
        "headerRowsWritten": len(tab_specs) if write_headers else 0,
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
        "spreadsheetId": config.sheets_spreadsheet_id,
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
) -> dict[str, object]:
    """Write reviewer-gated workbook-plan rows to configured Google Sheet.

    This only writes rows already produced by local magazine extraction. It does
    not call enrichment providers and does not mark rows as approved.
    """

    if sheets_service_factory is None:
        _drive_service_factory, sheets_service_factory = _google_service_factories(config)

    issue_id = str(workbook_plan.get("issueId") or "").strip()
    raw_rows = workbook_plan.get("rows")
    if not issue_id:
        raise GoogleAccessError("workbook plan is missing issueId")
    if not isinstance(raw_rows, list):
        raise GoogleAccessError("workbook plan is missing rows list")

    specs_by_title = {spec.title: spec for spec in tab_specs}
    rows_by_tab: dict[str, list[list[str]]] = {}
    skipped_count = 0
    for raw_row in raw_rows:
        if not isinstance(raw_row, Mapping):
            skipped_count += 1
            continue
        tab = str(raw_row.get("tab") or "").strip()
        spec = specs_by_title.get(tab)
        values = raw_row.get("values")
        if spec is None or not isinstance(values, list):
            skipped_count += 1
            continue
        normalized_values = _normalize_sheet_row_values(values, width=len(spec.headers))
        rows_by_tab.setdefault(tab, []).append(normalized_values)

    sheets = sheets_service_factory()
    bootstrap_result = bootstrap_google_sheet(
        config,
        sheets_service_factory=sheets_service_factory,
        tab_specs=tab_specs,
        write_headers=True,
    )
    try:
        write_ranges: list[dict[str, object]] = []
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
            kept_rows = (
                [
                    _normalize_sheet_row_values(row, width=len(spec.headers))
                    for row in existing_rows
                    if _row_issue_id(row, spec) != issue_id
                ]
                if replace_issue
                else [
                    _normalize_sheet_row_values(row, width=len(spec.headers))
                    for row in existing_rows
                ]
            )
            restored_existing_count += len(kept_rows)
            combined_rows = kept_rows + new_rows
            if replace_issue:
                sheets.spreadsheets().values().clear(
                    spreadsheetId=config.sheets_spreadsheet_id,
                    range=body_range,
                    body={},
                ).execute()
                cleared_tabs.append(tab)
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
        "spreadsheetId": config.sheets_spreadsheet_id,
        "issueId": issue_id,
        "replaceIssue": replace_issue,
        "tabsWritten": sorted(rows_by_tab),
        "rowsWritten": written_count,
        "rowsSkipped": skipped_count,
        "clearedTabs": sorted(cleared_tabs),
        "restoredExistingRows": restored_existing_count,
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
) -> dict[str, object]:
    files = list_drive_pdf_metadata(
        config,
        drive_service_factory=drive_service_factory,
        page_size=page_size,
    )
    return {
        "ok": True,
        "externalServicesEnabled": True,
        "driveFolderId": config.drive_folder_id,
        "listedAt": datetime.now(timezone.utc).isoformat(),
        "fileCount": len(files),
        "files": [file.to_dict() for file in files],
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
) -> tuple[dict[str, object], ...]:
    metadata_ranges = tuple(
        {
            "range": f"{_quote_sheet_title(spec.title)}!{cell}",
            "values": [[value]],
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


def _build_sheet_body_clear_ranges(
    tab_specs: tuple[GoogleSheetTabSpec, ...],
) -> tuple[str, ...]:
    return tuple(
        (
            f"{_quote_sheet_title(spec.title)}!A{spec.header_row + 1}:"
            f"{_column_letter(len(spec.headers))}"
        )
        for spec in tab_specs
    )


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


def _normalize_sheet_row_values(values: list[object], *, width: int) -> list[str]:
    row = [str(value) if value is not None else "" for value in values[:width]]
    if len(row) < width:
        row.extend("" for _ in range(width - len(row)))
    return row


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
