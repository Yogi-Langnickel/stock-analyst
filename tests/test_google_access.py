import tempfile
import unittest
from pathlib import Path

from stock_analyst.google_access import (
    DEFAULT_SHEET_TABS,
    GoogleAccessError,
    bootstrap_google_sheet,
    build_drive_pdf_metadata_result,
    clear_google_sheet_data_rows,
    list_drive_pdf_metadata,
    load_env_file,
    load_google_access_config,
    run_google_access_smoke,
    write_refinement_plan_to_google_sheet,
    write_workbook_plan_to_google_sheet,
    write_drive_pdf_metadata_manifest,
)


class _FakeExecute:
    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        return self.payload


class _FakeDriveFiles:
    def __init__(self, payload):
        self.payload = payload
        self.request = None
        self.list_requests = []

    def get(self, **kwargs):
        self.request = kwargs
        return _FakeExecute(self.payload)

    def list(self, **kwargs):
        self.list_requests.append(kwargs)
        page_token = kwargs.get("pageToken")
        if isinstance(self.payload, dict):
            return _FakeExecute(self.payload)
        if page_token:
            return _FakeExecute(self.payload[1])
        return _FakeExecute(self.payload[0])


class _FakeDrive:
    def __init__(self, payload):
        self.files_resource = _FakeDriveFiles(payload)

    def files(self):
        return self.files_resource


class _FakeSpreadsheets:
    def __init__(self, payload):
        self.payload = payload
        self.batch_update_requests = []
        self.values_resource = _FakeValues()

    def get(self, **_kwargs):
        return _FakeExecute(self.payload)

    def batchUpdate(self, **kwargs):
        self.batch_update_requests.append(kwargs)
        return _FakeExecute({"updated": True})

    def values(self):
        return self.values_resource


class _FakeValues:
    def __init__(self):
        self.batch_update_requests = []
        self.clear_requests = []
        self.get_requests = []
        self.values_by_range = {}

    def batchUpdate(self, **kwargs):
        self.batch_update_requests.append(kwargs)
        return _FakeExecute({"updated": True})

    def clear(self, **kwargs):
        self.clear_requests.append(kwargs)
        return _FakeExecute({"clearedRange": kwargs.get("range")})

    def get(self, **kwargs):
        self.get_requests.append(kwargs)
        return _FakeExecute({"values": self.values_by_range.get(kwargs.get("range"), [])})


class _FakeSheets:
    def __init__(self, payload):
        self.spreadsheets_resource = _FakeSpreadsheets(payload)

    def spreadsheets(self):
        return self.spreadsheets_resource


class GoogleAccessTest(unittest.TestCase):
    def test_load_env_file_parses_quoted_google_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_file = Path(temp_dir) / ".env.google"
            env_file.write_text(
                '\n'.join(
                    (
                        'GOOGLE_SERVICE_ACCOUNT_EMAIL="stock-analyst@example.iam.gserviceaccount.com"',
                        'GOOGLE_DRIVE_FOLDER_ID="1HqFI8-T1tXuyHedVx3U7D2AA0tHG53tb"',
                    )
                ),
                encoding="utf-8",
            )

            values = load_env_file(env_file)

        self.assertEqual(
            values["GOOGLE_SERVICE_ACCOUNT_EMAIL"],
            "stock-analyst@example.iam.gserviceaccount.com",
        )
        self.assertEqual(values["GOOGLE_DRIVE_FOLDER_ID"], "1HqFI8-T1tXuyHedVx3U7D2AA0tHG53tb")

    def test_config_requires_existing_credentials_and_google_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            credentials_path = Path(temp_dir) / "service-account.json"
            credentials_path.write_text("{}", encoding="utf-8")

            config = load_google_access_config(
                env={
                    "GOOGLE_SERVICE_ACCOUNT_EMAIL": "stock-analyst@example.iam.gserviceaccount.com",
                    "GOOGLE_DRIVE_FOLDER_ID": "1HqFI8-T1tXuyHedVx3U7D2AA0tHG53tb",
                    "GOOGLE_SHEETS_SPREADSHEET_ID": "1vE0YAMOoAP3SeFI6vXnzmSlGdaFRfBkQcoCYVMwz4UE",
                    "GOOGLE_APPLICATION_CREDENTIALS": str(credentials_path),
                }
            )

        self.assertEqual(config.drive_folder_id, "1HqFI8-T1tXuyHedVx3U7D2AA0tHG53tb")
        self.assertEqual(config.service_account_email, "stock-analyst@example.iam.gserviceaccount.com")

    def test_config_rejects_missing_credentials_file(self) -> None:
        with self.assertRaisesRegex(GoogleAccessError, "GOOGLE_APPLICATION_CREDENTIALS does not exist"):
            load_google_access_config(
                env={
                    "GOOGLE_DRIVE_FOLDER_ID": "1HqFI8-T1tXuyHedVx3U7D2AA0tHG53tb",
                    "GOOGLE_SHEETS_SPREADSHEET_ID": "1vE0YAMOoAP3SeFI6vXnzmSlGdaFRfBkQcoCYVMwz4UE",
                    "GOOGLE_APPLICATION_CREDENTIALS": "/missing/service-account.json",
                }
            )

    def test_smoke_result_is_metadata_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            credentials_path = Path(temp_dir) / "service-account.json"
            credentials_path.write_text('{"private_key":"secret"}', encoding="utf-8")
            config = load_google_access_config(
                env={
                    "GOOGLE_SERVICE_ACCOUNT_EMAIL": "stock-analyst@example.iam.gserviceaccount.com",
                    "GOOGLE_DRIVE_FOLDER_ID": "1HqFI8-T1tXuyHedVx3U7D2AA0tHG53tb",
                    "GOOGLE_SHEETS_SPREADSHEET_ID": "1vE0YAMOoAP3SeFI6vXnzmSlGdaFRfBkQcoCYVMwz4UE",
                    "GOOGLE_APPLICATION_CREDENTIALS": str(credentials_path),
                }
            )

            result = run_google_access_smoke(
                config,
                drive_service_factory=lambda: _FakeDrive(
                    {
                        "id": config.drive_folder_id,
                        "name": "Der Aktionär Issues",
                        "mimeType": "application/vnd.google-apps.folder",
                    }
                ),
                sheets_service_factory=lambda: _FakeSheets(
                    {
                        "spreadsheetId": config.sheets_spreadsheet_id,
                        "properties": {"title": "Der Aktionär Summaries"},
                        "sheets": [
                            {"properties": {"title": "Navigation Dashboard"}},
                            {"properties": {"title": "Stocks"}},
                        ],
                    }
                ),
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["drive"]["folderName"], "Der Aktionär Issues")
        self.assertEqual(result["sheets"]["title"], "Der Aktionär Summaries")
        self.assertNotIn("secret", str(result))

    def test_drive_pdf_metadata_listing_is_metadata_only_and_paginated(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            credentials_path = Path(temp_dir) / "service-account.json"
            credentials_path.write_text("{}", encoding="utf-8")
            config = load_google_access_config(
                env={
                    "GOOGLE_DRIVE_FOLDER_ID": "1HqFI8-T1tXuyHedVx3U7D2AA0tHG53tb",
                    "GOOGLE_SHEETS_SPREADSHEET_ID": "1vE0YAMOoAP3SeFI6vXnzmSlGdaFRfBkQcoCYVMwz4UE",
                    "GOOGLE_APPLICATION_CREDENTIALS": str(credentials_path),
                }
            )
            drive = _FakeDrive(
                [
                    {
                        "nextPageToken": "next",
                        "files": [
                            {
                                "id": "1DrivePdfFileAlpha",
                                "name": "DA_2026_05.pdf",
                                "mimeType": "application/pdf",
                                "md5Checksum": "abc123",
                                "size": "4096",
                                "createdTime": "2026-05-14T08:00:00Z",
                                "modifiedTime": "2026-05-15T08:00:00Z",
                                "webViewLink": "https://drive.google.com/file/d/private",
                            }
                        ],
                    },
                    {
                        "files": [
                            {
                                "id": "1DrivePdfFileBeta",
                                "name": "DA_2026_06.pdf",
                                "mimeType": "application/pdf",
                            }
                        ],
                    },
                ]
            )

            files = list_drive_pdf_metadata(
                config,
                drive_service_factory=lambda: drive,
                page_size=25,
            )

        self.assertEqual(len(files), 2)
        self.assertEqual(files[0].source_pdf_id, "drive_1DrivePdfFileAlp")
        self.assertEqual(files[0].size_bytes, 4096)
        self.assertEqual(files[1].name, "DA_2026_06.pdf")
        self.assertEqual(len(drive.files_resource.list_requests), 2)
        self.assertIn("mimeType = 'application/pdf'", drive.files_resource.list_requests[0]["q"])
        self.assertEqual(drive.files_resource.list_requests[0]["pageSize"], 25)

    def test_drive_pdf_metadata_result_can_write_private_jsonl_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            credentials_path = root / "service-account.json"
            credentials_path.write_text("{}", encoding="utf-8")
            config = load_google_access_config(
                env={
                    "GOOGLE_DRIVE_FOLDER_ID": "1HqFI8-T1tXuyHedVx3U7D2AA0tHG53tb",
                    "GOOGLE_SHEETS_SPREADSHEET_ID": "1vE0YAMOoAP3SeFI6vXnzmSlGdaFRfBkQcoCYVMwz4UE",
                    "GOOGLE_APPLICATION_CREDENTIALS": str(credentials_path),
                }
            )
            result = build_drive_pdf_metadata_result(
                config,
                drive_service_factory=lambda: _FakeDrive(
                    {
                        "files": [
                            {
                                "id": "1DrivePdfFileAlpha",
                                "name": "DA_2026_05.pdf",
                                "mimeType": "application/pdf",
                            }
                        ]
                    }
                ),
            )
            manifest_path = root / "drive" / "pdf-metadata.jsonl"

            written = write_drive_pdf_metadata_manifest(result, manifest_path)

            lines = written.read_text(encoding="utf-8").splitlines()

        self.assertEqual(written, manifest_path)
        self.assertEqual(len(lines), 1)
        self.assertIn('"stage": "drive_metadata_imported"', lines[0])
        self.assertIn('"status": "pending_local_download"', lines[0])
        self.assertNotIn("private_key", lines[0])

    def test_google_sheet_bootstrap_creates_missing_tabs_and_headers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            credentials_path = Path(temp_dir) / "service-account.json"
            credentials_path.write_text("{}", encoding="utf-8")
            config = load_google_access_config(
                env={
                    "GOOGLE_DRIVE_FOLDER_ID": "1HqFI8-T1tXuyHedVx3U7D2AA0tHG53tb",
                    "GOOGLE_SHEETS_SPREADSHEET_ID": "1vE0YAMOoAP3SeFI6vXnzmSlGdaFRfBkQcoCYVMwz4UE",
                    "GOOGLE_APPLICATION_CREDENTIALS": str(credentials_path),
                }
            )
            sheets = _FakeSheets(
                {
                    "spreadsheetId": config.sheets_spreadsheet_id,
                    "properties": {"title": "Der Aktionär Summaries"},
                    "sheets": [
                        {"properties": {"title": "Navigation Dashboard"}},
                        {"properties": {"title": "Stocks"}},
                    ],
                }
            )

            result = bootstrap_google_sheet(config, sheets_service_factory=lambda: sheets)

        self.assertTrue(result["ok"])
        self.assertIn("Derivative Tips", result["createdTabs"])
        self.assertIn("Dividend Focus", result["createdTabs"])
        self.assertIn("Chart Check", result["createdTabs"])
        self.assertEqual(result["headerRowsWritten"], len(result["tabs"]))
        batch_body = sheets.spreadsheets_resource.batch_update_requests[0]["body"]
        self.assertIn(
            {"addSheet": {"properties": {"title": "Derivative Tips"}}},
            batch_body["requests"],
        )
        self.assertIn(
            {"addSheet": {"properties": {"title": "Dividend Focus"}}},
            batch_body["requests"],
        )
        values_body = sheets.spreadsheets_resource.values_resource.batch_update_requests[0]["body"]
        self.assertEqual(values_body["valueInputOption"], "USER_ENTERED")
        self.assertIn(
            {
                "range": "'Navigation Dashboard'!A5:G5",
                "values": [[
                    "Area",
                    "Open",
                    "What this tab is for",
                    "Reviewer action",
                    "Row count",
                    "Status",
                    "Notes",
                ]],
            },
            values_body["data"],
        )
        self.assertIn(
            {
                "range": "'Navigation Dashboard'!A6",
                "values": [["Core review"]],
            },
            values_body["data"],
        )
        self.assertIn(
            {
                "range": "'Navigation Dashboard'!B6",
                "values": [["Stocks"]],
            },
            values_body["data"],
        )
        self.assertIn(
            {
                "range": "'Navigation Dashboard'!E6",
                "values": [["=COUNTA('Stocks'!A4:A)"]],
            },
            values_body["data"],
        )
        self.assertNotIn({"range": "'Stocks'!A1", "values": [["date updated"]]}, values_body["data"])
        self.assertNotIn({"range": "'Stocks'!B1", "values": [[""]]}, values_body["data"])
        self.assertIn(
            {
                "range": "'Stocks'!A3:X3",
                "values": [[
                    "Company",
                    "WKN",
                    "Current Price*",
                    "Magazine Price",
                    "Magazine Price As Of",
                    "Price at Recommendation",
                    "Dividend Yield",
                    "Market Cap",
                    "Chance/Risk",
                    "P/S Ratio 26e",
                    "P/E Ratio 26e",
                    "Target",
                    "Stop",
                    "Performance since Recommendation",
                    "52w High",
                    "52w Low",
                    "1Y Performance",
                    "5Y Performance",
                    "Next Report",
                    "Recommendation",
                    "Comment",
                    "issue",
                    "page",
                    "date updated",
                ]],
            },
            values_body["data"],
        )
        stock_tab = next(tab for tab in result["tabs"] if tab["title"] == "Stocks")
        self.assertEqual(stock_tab["headerRow"], 3)
        self.assertEqual(stock_tab["frozenRows"], 3)
        self.assertEqual(stock_tab["frozenColumns"], 2)
        self.assertEqual(stock_tab["tableStartsAt"], "A3")
        self.assertEqual(stock_tab["parserStatus"], "parser_backed")
        self.assertIn(
            "Only explicit stock mentions become rows; do not fan out index constituents.",
            stock_tab["layoutNotes"],
        )
        self.assertIn(
            "Quick-check and chart-check stock rows also surface here with split source fields.",
            stock_tab["layoutNotes"],
        )
        self.assertEqual(stock_tab["metadataCells"], [])
        tab_status = {tab["title"]: tab["parserStatus"] for tab in result["tabs"]}
        self.assertNotIn("ETF", tab_status)
        self.assertNotIn("Options", tab_status)
        self.assertNotIn("Crypto", tab_status)
        self.assertEqual(tab_status["Derivative Tips"], "parser_backed")
        self.assertEqual(tab_status["Dividend Focus"], "parser_backed")
        self.assertEqual(tab_status["Extraction Audit"], "parser_backed")
        self.assertEqual(tab_status["AKTIONAER Depot"], "parser_backed")
        self.assertEqual(tab_status["Depot Transactions"], "parser_backed")
        self.assertEqual(tab_status["Chart Check"], "parser_backed")
        self.assertEqual(tab_status["Stock Quickcheck"], "parser_backed")
        self.assertEqual(tab_status["Navigation Dashboard"], "layout_only")
        navigation_tab = next(tab for tab in result["tabs"] if tab["title"] == "Navigation Dashboard")
        self.assertEqual(navigation_tab["headerRow"], 5)
        self.assertEqual(navigation_tab["frozenRows"], 5)
        self.assertEqual(navigation_tab["frozenColumns"], 2)
        self.assertEqual(navigation_tab["tableStartsAt"], "A5")
        headers_by_tab = {tab["title"]: tab["headers"] for tab in result["tabs"]}
        self.assertEqual(headers_by_tab["Derivative Tips"][10], "Magazine Entry Price")
        self.assertEqual(headers_by_tab["Derivative Tips"][11], "Magazine Current Price")
        self.assertEqual(headers_by_tab["AKTIONAER Depot"][4], "Magazine Buy Price")
        self.assertEqual(headers_by_tab["AKTIONAER Depot"][5], "Magazine Current Price")
        self.assertEqual(headers_by_tab["Depot Transactions"][5], "Magazine Transaction Price")
        self.assertEqual(headers_by_tab["Chart Check"][6], "Magazine Price")
        self.assertEqual(headers_by_tab["Chart Check"][7], "Magazine Price at Recommendation")
        self.assertEqual(headers_by_tab["Stock Quickcheck"][4], "Magazine Price")
        self.assertEqual(
            headers_by_tab["Stock Quickcheck"][5],
            "Magazine Price at Recommendation",
        )
        self.assertEqual(headers_by_tab["Dividend Focus"][3], "Magazine Price")
        for tab in result["tabs"]:
            self.assertGreaterEqual(tab["frozenRows"], 1)
            self.assertIn("layoutNotes", tab)
            self.assertTrue(tab["tableStartsAt"])

        instrument_tabs = {
            "Stocks",
            "Derivative Tips",
            "Dividend Focus",
        }
        for tab in result["tabs"]:
            if tab["title"] in instrument_tabs:
                self.assertEqual(tab["headers"][-1], "date updated")

    def test_google_sheet_bootstrap_can_skip_header_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            credentials_path = Path(temp_dir) / "service-account.json"
            credentials_path.write_text("{}", encoding="utf-8")
            config = load_google_access_config(
                env={
                    "GOOGLE_DRIVE_FOLDER_ID": "1HqFI8-T1tXuyHedVx3U7D2AA0tHG53tb",
                    "GOOGLE_SHEETS_SPREADSHEET_ID": "1vE0YAMOoAP3SeFI6vXnzmSlGdaFRfBkQcoCYVMwz4UE",
                    "GOOGLE_APPLICATION_CREDENTIALS": str(credentials_path),
                }
            )
            sheets = _FakeSheets(
                {
                    "spreadsheetId": config.sheets_spreadsheet_id,
                    "sheets": [{"properties": {"title": "Navigation Dashboard"}}],
                }
            )

            result = bootstrap_google_sheet(
                config,
                sheets_service_factory=lambda: sheets,
                write_headers=False,
            )

        self.assertEqual(result["headerRowsWritten"], 0)
        self.assertEqual(sheets.spreadsheets_resource.values_resource.batch_update_requests, [])

    def test_google_sheet_bootstrap_prunes_only_generated_inactive_tabs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            credentials_path = Path(temp_dir) / "service-account.json"
            credentials_path.write_text("{}", encoding="utf-8")
            config = load_google_access_config(
                env={
                    "GOOGLE_DRIVE_FOLDER_ID": "1HqFI8-T1tXuyHedVx3U7D2AA0tHG53tb",
                    "GOOGLE_SHEETS_SPREADSHEET_ID": "1vE0YAMOoAP3SeFI6vXnzmSlGdaFRfBkQcoCYVMwz4UE",
                    "GOOGLE_APPLICATION_CREDENTIALS": str(credentials_path),
                }
            )
            sheets = _FakeSheets(
                {
                    "spreadsheetId": config.sheets_spreadsheet_id,
                    "sheets": [
                        {"properties": {"sheetId": 10, "title": "Navigation Dashboard"}},
                        {"properties": {"sheetId": 20, "title": "Options"}},
                        {"properties": {"sheetId": 30, "title": "Manual Review Notes"}},
                        {"properties": {"sheetId": 40, "title": "Stocks"}},
                    ],
                }
            )

            result = bootstrap_google_sheet(config, sheets_service_factory=lambda: sheets)

        batch_body = sheets.spreadsheets_resource.batch_update_requests[0]["body"]
        delete_requests = [
            request["deleteSheet"]
            for request in batch_body["requests"]
            if "deleteSheet" in request
        ]
        self.assertEqual(result["deletedTabCount"], 1)
        self.assertNotIn({"sheetId": 10}, delete_requests)
        self.assertIn({"sheetId": 20}, delete_requests)
        self.assertNotIn({"sheetId": 30}, delete_requests)

    def test_google_sheet_bootstrap_replaces_generated_conditional_format_rules(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            credentials_path = Path(temp_dir) / "service-account.json"
            credentials_path.write_text("{}", encoding="utf-8")
            config = load_google_access_config(
                env={
                    "GOOGLE_DRIVE_FOLDER_ID": "1HqFI8-T1tXuyHedVx3U7D2AA0tHG53tb",
                    "GOOGLE_SHEETS_SPREADSHEET_ID": "1vE0YAMOoAP3SeFI6vXnzmSlGdaFRfBkQcoCYVMwz4UE",
                    "GOOGLE_APPLICATION_CREDENTIALS": str(credentials_path),
                }
            )
            sheets = _FakeSheets(
                {
                    "spreadsheetId": config.sheets_spreadsheet_id,
                    "sheets": [
                        {
                            "properties": {"sheetId": index + 1, "title": spec.title},
                            "conditionalFormats": [{}]
                            if spec.title == "AKTIONAER Depot"
                            else [{}, {}]
                            if spec.title == "Depot Transactions"
                            else [],
                        }
                        for index, spec in enumerate(DEFAULT_SHEET_TABS)
                    ],
                }
            )

            result = bootstrap_google_sheet(
                config,
                sheets_service_factory=lambda: sheets,
                write_headers=False,
            )

        batch_body = sheets.spreadsheets_resource.batch_update_requests[0]["body"]
        delete_requests = [
            request["deleteConditionalFormatRule"]
            for request in batch_body["requests"]
            if "deleteConditionalFormatRule" in request
        ]
        add_requests = [
            request["addConditionalFormatRule"]
            for request in batch_body["requests"]
            if "addConditionalFormatRule" in request
        ]
        self.assertEqual(result["formatRulesWritten"], 7)
        self.assertEqual(len(delete_requests), 3)
        self.assertEqual(len(add_requests), 4)
        sheet_ids_by_title = {
            spec.title: index + 1
            for index, spec in enumerate(DEFAULT_SHEET_TABS)
        }
        self.assertIn(
            {"sheetId": sheet_ids_by_title["AKTIONAER Depot"], "index": 0},
            delete_requests,
        )
        self.assertIn(
            {"sheetId": sheet_ids_by_title["Depot Transactions"], "index": 1},
            delete_requests,
        )
        self.assertIn(
            {"sheetId": sheet_ids_by_title["Depot Transactions"], "index": 0},
            delete_requests,
        )

    def test_google_sheet_clear_data_rows_preserves_headers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            credentials_path = Path(temp_dir) / "service-account.json"
            credentials_path.write_text("{}", encoding="utf-8")
            config = load_google_access_config(
                env={
                    "GOOGLE_DRIVE_FOLDER_ID": "1HqFI8-T1tXuyHedVx3U7D2AA0tHG53tb",
                    "GOOGLE_SHEETS_SPREADSHEET_ID": "1vE0YAMOoAP3SeFI6vXnzmSlGdaFRfBkQcoCYVMwz4UE",
                    "GOOGLE_APPLICATION_CREDENTIALS": str(credentials_path),
                }
            )
            sheets = _FakeSheets(
                {
                    "spreadsheetId": config.sheets_spreadsheet_id,
                    "sheets": [{"properties": {"title": "Stocks"}}],
                }
            )

            result = clear_google_sheet_data_rows(
                config,
                sheets_service_factory=lambda: sheets,
            )

        values_resource = sheets.spreadsheets_resource.values_resource
        clear_ranges = [request["range"] for request in values_resource.clear_requests]

        self.assertTrue(result["ok"])
        self.assertTrue(result["headersRewritten"])
        self.assertEqual(result["clearedTabCount"], len(result["clearedRanges"]))
        self.assertIn("'Stocks'!A4:X", clear_ranges)
        self.assertNotIn("'Navigation Dashboard'!A5:E", clear_ranges)
        self.assertGreater(len(values_resource.batch_update_requests), 0)

    def test_google_sheet_export_writes_workbook_rows_and_replaces_same_issue(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            credentials_path = Path(temp_dir) / "service-account.json"
            credentials_path.write_text("{}", encoding="utf-8")
            config = load_google_access_config(
                env={
                    "GOOGLE_DRIVE_FOLDER_ID": "1HqFI8-T1tXuyHedVx3U7D2AA0tHG53tb",
                    "GOOGLE_SHEETS_SPREADSHEET_ID": "1vE0YAMOoAP3SeFI6vXnzmSlGdaFRfBkQcoCYVMwz4UE",
                    "GOOGLE_APPLICATION_CREDENTIALS": str(credentials_path),
                }
            )
            sheets = _FakeSheets(
                {
                    "spreadsheetId": config.sheets_spreadsheet_id,
                    "sheets": [
                        {"properties": {"title": "Stocks"}},
                        {"properties": {"title": "Dividend Focus"}},
                    ],
                }
            )
            sheets.spreadsheets_resource.values_resource.values_by_range[
                "'Stocks'!A4:X"
            ] = [
                [
                    "Old Same Issue",
                    "OLD",
                    "",
                    "1 EUR",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "2026-W03",
                    "1",
                    "2026-05-17",
                ],
                [
                    "Keep Different Issue",
                    "KEEP",
                    "",
                    "2 EUR",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "2026-W02",
                    "1",
                    "2026-05-10",
                ],
                [
                    "Banco Sabadell",
                    "A0MRD4",
                    "2,90 EUR",
                    "",
                    "",
                    "2,50 EUR",
                    "16,0 %",
                    "",
                    "",
                    "",
                    "",
                    "3,50 EUR",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "02/2026 07.01.26",
                    "Previous comment",
                    "2026-W02",
                    "20",
                    "2026-05-10",
                ],
            ]
            workbook_plan = {
                "issueId": "2026-W03",
                "rows": [
                    {
                        "tab": "Stocks",
                        "values": [
                            "Banco Sabadell",
                            "A0MRD4",
                            "",
                            "3,33 EUR",
                            "2026-05-17",
                            "3,33 EUR",
                            "18,6 %",
                            "",
                            "",
                            "",
                            "",
                            "4,30 EUR",
                            "2,70 EUR",
                            "",
                            "",
                            "",
                            "",
                            "",
                            "",
                            "new_recommendation",
                            "",
                            "2026-W03",
                            "22",
                            "2026-05-17",
                        ],
                    },
                    {
                        "tab": "Dividend Focus",
                        "values": [
                            "Banco Sabadell",
                            "A0MRD4",
                            "Maerz",
                            "3,33 EUR",
                            "",
                            "18,6 %",
                            "",
                            "",
                            "",
                            "",
                            "",
                            "",
                            "needs_review",
                            "2026-W03",
                            "18",
                            "2026-05-17",
                        ],
                    },
                ],
            }

            result = write_workbook_plan_to_google_sheet(
                config,
                workbook_plan,
                sheets_service_factory=lambda: sheets,
            )

        values_resource = sheets.spreadsheets_resource.values_resource
        data_ranges = values_resource.batch_update_requests[-1]["body"]["data"]
        stocks_write = next(item for item in data_ranges if item["range"] == "'Stocks'!A4:X5")

        self.assertTrue(result["ok"])
        self.assertEqual(result["enrichmentProviderCalls"], 0)
        self.assertEqual(result["rowsWritten"], 2)
        self.assertIn("Stocks", result["clearedTabs"])
        self.assertIn("Dividend Focus", result["clearedTabs"])
        self.assertEqual(stocks_write["values"][0][0], "Keep Different Issue")
        self.assertEqual(stocks_write["values"][1][0], "Banco Sabadell")
        self.assertEqual(stocks_write["values"][1][2], "2,90 EUR")
        self.assertEqual(stocks_write["values"][1][3], "3,33 EUR")
        self.assertEqual(stocks_write["values"][1][5], "3,33 EUR")
        self.assertEqual(stocks_write["values"][1][6], "18,6 %")
        self.assertEqual(stocks_write["values"][1][11], "4,30 EUR")
        self.assertIn("Previous comment", stocks_write["values"][1][20])
        self.assertEqual(stocks_write["values"][1][21], "2026-W02, 2026-W03")
        self.assertEqual(stocks_write["values"][1][22], "20, 22")
        self.assertIn("'Stocks'!A4:X", [request["range"] for request in values_resource.clear_requests])

    def test_google_sheet_export_rejects_short_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            credentials_path = Path(temp_dir) / "service-account.json"
            credentials_path.write_text("{}", encoding="utf-8")
            config = load_google_access_config(
                env={
                    "GOOGLE_DRIVE_FOLDER_ID": "1HqFI8-T1tXuyHedVx3U7D2AA0tHG53tb",
                    "GOOGLE_SHEETS_SPREADSHEET_ID": "1vE0YAMOoAP3SeFI6vXnzmSlGdaFRfBkQcoCYVMwz4UE",
                    "GOOGLE_APPLICATION_CREDENTIALS": str(credentials_path),
                }
            )
            sheets = _FakeSheets({"spreadsheetId": config.sheets_spreadsheet_id, "sheets": []})
            workbook_plan = {
                "issueId": "2026-W03",
                "rows": [
                    {
                        "tab": "Stocks",
                        "values": [
                            "Banco Sabadell",
                            "A0MRD4",
                            "",
                            "3,33 EUR",
                            "",
                            "4,30 EUR",
                            "2,70 EUR",
                            "new_recommendation",
                            "2026-W03",
                            "22",
                            "2026-05-17",
                        ],
                    }
                ],
            }

            with self.assertRaisesRegex(GoogleAccessError, "Stocks.*24 values.*got 11"):
                write_workbook_plan_to_google_sheet(
                    config,
                    workbook_plan,
                    sheets_service_factory=lambda: sheets,
                )

    def test_google_sheet_export_skips_layout_only_dashboard_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            credentials_path = Path(temp_dir) / "service-account.json"
            credentials_path.write_text("{}", encoding="utf-8")
            config = load_google_access_config(
                env={
                    "GOOGLE_DRIVE_FOLDER_ID": "1HqFI8-T1tXuyHedVx3U7D2AA0tHG53tb",
                    "GOOGLE_SHEETS_SPREADSHEET_ID": "1vE0YAMOoAP3SeFI6vXnzmSlGdaFRfBkQcoCYVMwz4UE",
                    "GOOGLE_APPLICATION_CREDENTIALS": str(credentials_path),
                }
            )
            sheets = _FakeSheets({"spreadsheetId": config.sheets_spreadsheet_id, "sheets": []})
            workbook_plan = {
                "issueId": "2026-W03",
                "rows": [
                    {
                        "tab": "Navigation Dashboard",
                        "values": ["" for _ in range(7)],
                    }
                ],
            }

            result = write_workbook_plan_to_google_sheet(
                config,
                workbook_plan,
                sheets_service_factory=lambda: sheets,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["rowsWritten"], 0)
        self.assertEqual(result["rowsSkipped"], 1)
        self.assertNotIn("Navigation Dashboard", result["tabsWritten"])

    def test_google_sheet_refinement_export_preserves_reviewer_owned_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            credentials_path = Path(temp_dir) / "service-account.json"
            credentials_path.write_text("{}", encoding="utf-8")
            config = load_google_access_config(
                env={
                    "GOOGLE_DRIVE_FOLDER_ID": "1HqFI8-T1tXuyHedVx3U7D2AA0tHG53tb",
                    "GOOGLE_SHEETS_SPREADSHEET_ID": "1vE0YAMOoAP3SeFI6vXnzmSlGdaFRfBkQcoCYVMwz4UE",
                    "GOOGLE_APPLICATION_CREDENTIALS": str(credentials_path),
                }
            )
            sheets = _FakeSheets(
                {
                    "spreadsheetId": config.sheets_spreadsheet_id,
                    "sheets": [{"properties": {"title": "Refinement"}}],
                }
            )
            sheets.spreadsheets_resource.values_resource.values_by_range["'Refinement'!A4:J"] = [
                [
                    "18",
                    "Titelstory",
                    "Reviewed title",
                    "no",
                    "",
                    "",
                    "",
                    "Keep this page",
                    "2026-W03",
                    "2026-05-19",
                ]
            ]
            refinement_plan = {
                "issueId": "2026-W03",
                "rows": [
                    {
                        "Page_number": "18",
                        "section": "Dividenden",
                        "page_titel": "Dividendenstrategie",
                        "useful_info": "yes",
                        "suggested_destination": "Dividend Focus",
                        "parser_hint": "section_inventory:dividend_strategy",
                        "reason": "Dividend table with payout timing.",
                        "reviewer_notes": "",
                        "issue": "2026-W03",
                        "date_updated": "2026-05-20",
                    },
                    {
                        "Page_number": "1",
                        "section": "Inhalt/front-matter",
                        "page_titel": "Inhalt",
                        "useful_info": "no",
                        "suggested_destination": "review",
                        "parser_hint": "ignore_or_manual_review",
                        "reason": "Early front matter.",
                        "reviewer_notes": "",
                        "issue": "2026-W03",
                        "date_updated": "2026-05-20",
                    },
                ],
            }

            result = write_refinement_plan_to_google_sheet(
                config,
                refinement_plan,
                sheets_service_factory=lambda: sheets,
            )

        values_resource = sheets.spreadsheets_resource.values_resource
        data = values_resource.batch_update_requests[-1]["body"]["data"][0]

        self.assertTrue(result["ok"])
        self.assertEqual(result["tabWritten"], "Refinement")
        self.assertEqual(result["rowsWritten"], 2)
        self.assertEqual(result["reviewerNotesPreserved"], 1)
        self.assertEqual(result["reviewerFieldsPreserved"], 1)
        self.assertEqual(data["range"], "'Refinement'!A4:J5")
        self.assertEqual(data["values"][0][0], "1")
        self.assertEqual(data["values"][1][0], "18")
        self.assertEqual(data["values"][1][1], "Titelstory")
        self.assertEqual(data["values"][1][2], "Reviewed title")
        self.assertEqual(data["values"][1][3], "no")
        self.assertEqual(data["values"][1][4], "")
        self.assertEqual(data["values"][1][7], "Keep this page")
        self.assertIn("'Refinement'!A4:J", [request["range"] for request in values_resource.clear_requests])


if __name__ == "__main__":
    unittest.main()
