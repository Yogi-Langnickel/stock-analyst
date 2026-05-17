import tempfile
import unittest
from pathlib import Path

from stock_analyst.google_access import (
    GoogleAccessError,
    bootstrap_google_sheet,
    build_drive_pdf_metadata_result,
    list_drive_pdf_metadata,
    load_env_file,
    load_google_access_config,
    run_google_access_smoke,
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

    def batchUpdate(self, **kwargs):
        self.batch_update_requests.append(kwargs)
        return _FakeExecute({"updated": True})


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
        self.assertIn("ETF", result["createdTabs"])
        self.assertIn("Options", result["createdTabs"])
        self.assertIn("Crypto", result["createdTabs"])
        self.assertEqual(result["headerRowsWritten"], len(result["tabs"]))
        batch_body = sheets.spreadsheets_resource.batch_update_requests[0]["body"]
        self.assertIn({"addSheet": {"properties": {"title": "ETF"}}}, batch_body["requests"])
        self.assertIn({"addSheet": {"properties": {"title": "Options"}}}, batch_body["requests"])
        self.assertIn({"addSheet": {"properties": {"title": "Crypto"}}}, batch_body["requests"])
        values_body = sheets.spreadsheets_resource.values_resource.batch_update_requests[0]["body"]
        self.assertEqual(values_body["valueInputOption"], "RAW")
        self.assertIn(
            {
                "range": "'Navigation Dashboard'!A1:D1",
                "values": [["Area", "Tab", "Purpose", "Status"]],
            },
            values_body["data"],
        )
        self.assertNotIn({"range": "'Stocks'!A1", "values": [["date updated"]]}, values_body["data"])
        self.assertNotIn({"range": "'Stocks'!B1", "values": [[""]]}, values_body["data"])
        self.assertIn(
            {
                "range": "'Stocks'!A3:K3",
                "values": [[
                    "Company",
                    "WKN",
                    "Current Price*",
                    "Price at Recommendation",
                    "Dividends",
                    "Target",
                    "Stop",
                    "Recommendation",
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
        self.assertEqual(stock_tab["metadataCells"], [])
        tab_status = {tab["title"]: tab["parserStatus"] for tab in result["tabs"]}
        self.assertEqual(tab_status["ETF"], "planned")
        self.assertEqual(tab_status["Crypto"], "planned")
        self.assertEqual(tab_status["Derivative Tips"], "parser_backed")
        self.assertEqual(tab_status["Dividend Focus"], "parser_backed")
        self.assertEqual(tab_status["Extraction Audit"], "parser_backed")
        self.assertEqual(tab_status["AKTIONAER Depot"], "audit_hint")
        self.assertEqual(tab_status["Chart Check"], "audit_hint")
        self.assertEqual(tab_status["Navigation Dashboard"], "layout_only")
        for tab in result["tabs"]:
            self.assertGreaterEqual(tab["frozenRows"], 1)
            self.assertIn("layoutNotes", tab)
            self.assertTrue(tab["tableStartsAt"])

        instrument_tabs = {
            "Stocks",
            "ETF",
            "Commodities",
            "Options",
            "Crypto",
            "Forex",
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


if __name__ == "__main__":
    unittest.main()
