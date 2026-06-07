import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from stock_analyst.cli import run_google_drive_pdfs_command
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


def _headers_for(tab: str) -> tuple[str, ...]:
    for spec in DEFAULT_SHEET_TABS:
        if spec.title == tab:
            return spec.headers
    raise AssertionError(f"unknown tab: {tab}")


def _stock_value(row: list[str], header: str) -> str:
    return row[_headers_for("Stocks").index(header)]


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
        self.fail_batch_update = False
        self.fail_batch_update_after = 0

    def batchUpdate(self, **kwargs):
        self.batch_update_requests.append(kwargs)
        if self.fail_batch_update and len(self.batch_update_requests) > self.fail_batch_update_after:
            raise RuntimeError("simulated batch update failure")
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
    def _stock_sheet_row(
        self,
        *,
        company: str = "Banco Sabadell",
        wkn: str = "A0MRD4",
        recommendation: str = "",
        held_since: str = "",
        comment: str = "",
        issue: str = "2026-W03",
        page: str = "22",
        date_updated: str = "2026-05-17",
        target: str = "",
        stop: str = "",
        current_price: str = "",
        dividend_yield: str = "",
    ) -> list[str]:
        row = ["" for _ in _headers_for("Stocks")]
        row[0] = company
        row[1] = wkn
        row[2] = target
        row[3] = stop
        row[4] = current_price
        row[6] = dividend_yield
        row[7] = recommendation
        row[8] = held_since
        headers = _headers_for("Stocks")
        if comment:
            row[headers.index("Enrichment status")] = comment
        row[headers.index("Issue:Page")] = f"{issue}:{page}" if issue and page else issue or page
        row[headers.index("date updated")] = date_updated
        return row

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
        self.assertNotEqual(
            config.to_public_dict()["serviceAccountEmail"],
            "stock-analyst@example.iam.gserviceaccount.com",
        )

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
        self.assertNotEqual(result["drive"]["folderId"], config.drive_folder_id)
        self.assertNotEqual(result["sheets"]["spreadsheetId"], config.sheets_spreadsheet_id)
        self.assertNotEqual(result["serviceAccountEmail"], config.service_account_email)
        self.assertEqual(result["sheets"]["tabCount"], 2)
        self.assertNotIn("secret", str(result))
        self.assertNotIn("stock-analyst@example.iam.gserviceaccount.com", str(result))
        self.assertNotIn("Der Aktionär Issues", str(result))
        self.assertNotIn("Der Aktionär Summaries", str(result))
        self.assertNotIn("Navigation Dashboard", str(result))
        self.assertNotIn("Stocks", str(result))
        self.assertNotIn(config.drive_folder_id, str(result))
        self.assertNotIn(config.sheets_spreadsheet_id, str(result))

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
        self.assertEqual(len(files[0].source_pdf_id), len("drive_") + 16)
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
        self.assertNotIn("1DrivePdfFileAlpha", lines[0])
        self.assertIn('"stage": "drive_metadata_imported"', lines[0])
        self.assertIn('"status": "pending_local_download"', lines[0])
        self.assertNotIn("private_key", lines[0])

    def test_drive_pdf_metadata_can_include_private_ids_for_private_manifest(self) -> None:
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
            result = build_drive_pdf_metadata_result(
                config,
                drive_service_factory=lambda: _FakeDrive(
                    {
                        "files": [
                            {
                                "id": "1DrivePdfFileAlpha",
                                "name": "DA_2026_05.pdf",
                                "mimeType": "application/pdf",
                                "webViewLink": "https://drive.google.com/file/d/private",
                            }
                        ]
                    }
                ),
                include_private_identifiers=True,
            )

        self.assertEqual(result["driveFolderId"], config.drive_folder_id)
        self.assertEqual(result["files"][0]["driveFileId"], "1DrivePdfFileAlpha")
        self.assertEqual(result["files"][0]["webViewLink"], "https://drive.google.com/file/d/private")

    def test_drive_pdf_cli_manifest_stays_redacted_without_private_flag(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = Path(temp_dir) / "drive" / "pdf-metadata.jsonl"
            fake_config = object()
            redacted_result = {
                "ok": True,
                "files": [{"sourcePdfId": "drive_redacted"}],
            }

            with (
                patch("stock_analyst.cli.load_google_access_config", return_value=fake_config),
                patch(
                    "stock_analyst.cli.build_drive_pdf_metadata_result",
                    return_value=redacted_result,
                ) as build_result,
                patch("stock_analyst.cli.write_drive_pdf_metadata_manifest") as write_manifest,
            ):
                result = run_google_drive_pdfs_command(manifest=manifest)

        self.assertEqual(result["manifestPath"], str(manifest))
        build_result.assert_called_once_with(
            fake_config,
            page_size=100,
            include_private_identifiers=False,
        )
        write_manifest.assert_called_once_with(redacted_result, manifest)

    def test_drive_pdf_cli_requires_private_path_for_raw_identifier_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = Path(temp_dir) / "drive" / "pdf-metadata.jsonl"

            with (
                patch("stock_analyst.cli.load_google_access_config", return_value=object()),
                patch(
                    "stock_analyst.cli.build_drive_pdf_metadata_result",
                    return_value={
                        "ok": True,
                        "files": [{"driveFileId": "1DrivePdfFileAlpha"}],
                    },
                ) as build_result,
                patch("stock_analyst.cli.write_drive_pdf_metadata_manifest") as write_manifest,
            ):
                with self.assertRaisesRegex(ValueError, "private path"):
                    run_google_drive_pdfs_command(
                        manifest=manifest,
                        include_private_identifiers=True,
                    )

        build_result.assert_not_called()
        write_manifest.assert_not_called()

    def test_drive_pdf_cli_requires_manifest_for_raw_identifier_stdout_safety(self) -> None:
        with (
            patch("stock_analyst.cli.load_google_access_config", return_value=object()) as load_config,
            patch("stock_analyst.cli.build_drive_pdf_metadata_result") as build_result,
            patch("stock_analyst.cli.write_drive_pdf_metadata_manifest") as write_manifest,
        ):
            with self.assertRaisesRegex(ValueError, "private manifest path"):
                run_google_drive_pdfs_command(include_private_identifiers=True)

        load_config.assert_not_called()
        build_result.assert_not_called()
        write_manifest.assert_not_called()

    def test_drive_pdf_cli_allows_raw_identifier_manifest_under_private_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = Path(temp_dir) / "data" / "private" / "drive" / "pdf-metadata.jsonl"
            private_result = {
                "ok": True,
                "driveFolderId": "1PrivateDriveFolder",
                "files": [
                    {
                        "driveFileId": "1DrivePdfFileAlpha",
                        "webViewLink": "https://drive.google.com/file/d/private",
                    }
                ],
            }

            with (
                patch("stock_analyst.cli.load_google_access_config", return_value=object()),
                patch(
                    "stock_analyst.cli.build_drive_pdf_metadata_result",
                    return_value=private_result,
                ),
                patch("stock_analyst.cli.write_drive_pdf_metadata_manifest") as write_manifest,
            ):
                result = run_google_drive_pdfs_command(
                    manifest=manifest,
                    include_private_identifiers=True,
                )

        self.assertEqual(result["manifestPath"], str(manifest))
        self.assertTrue(result["privateIdentifiersWritten"])
        self.assertNotIn("1PrivateDriveFolder", str(result))
        self.assertNotIn("1DrivePdfFileAlpha", str(result))
        self.assertNotIn("https://drive.google.com/file/d/private", str(result))
        self.assertIn("redacted:", str(result))
        write_manifest.assert_called_once_with(private_result, manifest)

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
                        {"properties": {"sheetId": 10, "title": "Navigation Dashboard"}},
                        {"properties": {"sheetId": 20, "title": "Stocks"}},
                    ],
                }
            )

            result = bootstrap_google_sheet(config, sheets_service_factory=lambda: sheets)

        self.assertTrue(result["ok"])
        self.assertNotEqual(result["spreadsheetId"], config.sheets_spreadsheet_id)
        self.assertNotIn(config.sheets_spreadsheet_id, str(result))
        self.assertIn("Derivative Tips", result["createdTabs"])
        self.assertIn("Dividend Focus", result["createdTabs"])
        self.assertIn("Latest Issue", result["createdTabs"])
        self.assertIn("Insider Activity", result["createdTabs"])
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
                "values": [["Latest Issue"]],
            },
            values_body["data"],
        )
        self.assertIn(
            {
                "range": "'Navigation Dashboard'!E6",
                "values": [["=COUNTA('Latest Issue'!A2:A)"]],
            },
            values_body["data"],
        )
        self.assertIn(
            {
                "range": "'Navigation Dashboard'!F12",
                "values": [["planned; review required"]],
            },
            values_body["data"],
        )
        self.assertNotIn({"range": "'Stocks'!A1", "values": [["date updated"]]}, values_body["data"])
        self.assertNotIn({"range": "'Stocks'!B1", "values": [[""]]}, values_body["data"])
        self.assertNotIn(
            "'Stocks'!A1:T1",
            [request["range"] for request in sheets.spreadsheets_resource.values_resource.clear_requests],
        )
        self.assertIn(
            {
                "range": "'Stocks'!A1:T1",
                "values": [[
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
                    "date updated",
                ]],
            },
            values_body["data"],
        )
        stock_tab = next(tab for tab in result["tabs"] if tab["title"] == "Stocks")
        self.assertEqual(stock_tab["headerRow"], 1)
        self.assertEqual(stock_tab["frozenRows"], 1)
        self.assertEqual(stock_tab["frozenColumns"], 2)
        self.assertEqual(stock_tab["tableStartsAt"], "A1")
        self.assertEqual(stock_tab["parserStatus"], "parser_backed")
        self.assertIn(
            "Only explicit stock mentions become rows; do not fan out index constituents.",
            stock_tab["layoutNotes"],
        )
        self.assertIn(
            "Quick-check and chart-check stock rows also surface here with atomic source refs.",
            stock_tab["layoutNotes"],
        )
        self.assertEqual(stock_tab["metadataCells"], [])
        tab_status = {tab["title"]: tab["parserStatus"] for tab in result["tabs"]}
        self.assertNotIn("ETF", tab_status)
        self.assertNotIn("Options", tab_status)
        self.assertNotIn("Crypto", tab_status)
        self.assertEqual(tab_status["Derivative Tips"], "parser_backed")
        self.assertEqual(tab_status["Latest Issue"], "parser_backed")
        self.assertEqual(tab_status["Dividend Focus"], "parser_backed")
        self.assertEqual(tab_status["Extraction Audit"], "parser_backed")
        self.assertEqual(tab_status["AKTIONAER Depot"], "parser_backed")
        self.assertEqual(tab_status["Depot Transactions"], "parser_backed")
        self.assertNotIn("Chart Check", tab_status)
        self.assertNotIn("Stock Quickcheck", tab_status)
        self.assertNotIn("Refinement", tab_status)
        self.assertEqual(tab_status["Insider Activity"], "planned")
        self.assertEqual(tab_status["Navigation Dashboard"], "layout_only")
        navigation_tab = next(tab for tab in result["tabs"] if tab["title"] == "Navigation Dashboard")
        self.assertEqual(navigation_tab["headerRow"], 5)
        self.assertEqual(navigation_tab["frozenRows"], 5)
        self.assertEqual(navigation_tab["frozenColumns"], 2)
        self.assertEqual(navigation_tab["tableStartsAt"], "A5")
        headers_by_tab = {tab["title"]: tab["headers"] for tab in result["tabs"]}
        self.assertEqual(headers_by_tab["Latest Issue"][0], "Issue:Page")
        self.assertEqual(headers_by_tab["Latest Issue"][4], "Magazine Current Price")
        self.assertEqual(headers_by_tab["Derivative Tips"][10], "Magazine Entry Price")
        self.assertEqual(headers_by_tab["Derivative Tips"][11], "Magazine Current Price")
        self.assertEqual(headers_by_tab["AKTIONAER Depot"][3], "Buy date")
        self.assertEqual(headers_by_tab["AKTIONAER Depot"][4], "Sale date")
        self.assertEqual(headers_by_tab["AKTIONAER Depot"][5], "Magazine Buy Price")
        self.assertEqual(headers_by_tab["AKTIONAER Depot"][6], "Magazine Current Price")
        self.assertEqual(headers_by_tab["Depot Transactions"][5], "Magazine Transaction Price")
        self.assertEqual(headers_by_tab["Stocks"][10], "Next Report")
        self.assertEqual(headers_by_tab["Stocks"][11], "Report type")
        self.assertEqual(headers_by_tab["Stocks"][16], "Insider Activity")
        self.assertEqual(headers_by_tab["Insider Activity"][14], "SEC filing URL")
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
        self.assertNotEqual(result["spreadsheetId"], config.sheets_spreadsheet_id)
        self.assertNotIn(config.sheets_spreadsheet_id, str(result))
        self.assertEqual(result["clearedTabCount"], len(result["clearedRanges"]))
        self.assertNotIn("'Stocks'!A1:T1", clear_ranges)
        self.assertIn("'Stocks'!A2:T", clear_ranges)
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
            sheets.spreadsheets_resource.values_resource.values_by_range["'Stocks'!A2:T"] = [
                self._stock_sheet_row(
                    company="Old Same Issue",
                    wkn="OLD",
                    current_price="1 EUR",
                    issue="2026-W03",
                    page="1",
                    date_updated="2026-05-17",
                ),
                self._stock_sheet_row(
                    company="Keep Different Issue",
                    wkn="KEEP",
                    target="€3,33",
                    current_price="$8.82",
                    dividend_yield="2026-05-27",
                    stop="!",
                    issue="2026-W02",
                    page="1",
                    date_updated="2026-05-10",
                ),
                self._stock_sheet_row(
                    target="3,50 EUR",
                    current_price="$2.90",
                    dividend_yield="16,0 %",
                    recommendation="hold",
                    held_since="02/2026",
                    comment="Previous comment",
                    issue="2026-W02",
                    page="20",
                    date_updated="2026-05-10",
                ),
            ]
            workbook_plan = {
                "issueId": "2026-W03",
                "rows": [
                    {
                        "tab": "Stocks",
                        "values": self._stock_sheet_row(
                            target="4,30 EUR",
                            stop="2,70 EUR",
                            current_price="3,33 EUR",
                            dividend_yield="18,6 %",
                            recommendation="new_recommendation",
                            issue="2026-W03",
                            page="22",
                            date_updated="2026-05-17",
                        ),
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
                            "2026-W03:18",
                            "2026-05-17",
                        ],
                    },
                ],
            }

            result = write_workbook_plan_to_google_sheet(
                config,
                workbook_plan,
                sheets_service_factory=lambda: sheets,
                allow_draft_rows=True,
            )

        values_resource = sheets.spreadsheets_resource.values_resource
        data_ranges = values_resource.batch_update_requests[-1]["body"]["data"]
        stocks_write = next(item for item in data_ranges if item["range"] == "'Stocks'!A2:T3")

        self.assertTrue(result["ok"])
        self.assertEqual(result["enrichmentProviderCalls"], 0)
        self.assertEqual(result["exportMode"], "private_draft_review_export")
        self.assertFalse(result["familyVisibleSafe"])
        self.assertTrue(result["privateDraftReviewOnly"])
        self.assertEqual(result["rowsWritten"], 2)
        self.assertIn("Stocks", result["clearedTabs"])
        self.assertIn("Dividend Focus", result["clearedTabs"])
        self.assertEqual(stocks_write["values"][0][0], "Keep Different Issue")
        self.assertEqual(stocks_write["values"][1][0], "Banco Sabadell")
        self.assertEqual(_stock_value(stocks_write["values"][0], "Dividend Yield"), "")
        self.assertEqual(_stock_value(stocks_write["values"][0], "Target"), "3,33 EUR")
        self.assertEqual(_stock_value(stocks_write["values"][0], "Stop"), "")
        self.assertEqual(_stock_value(stocks_write["values"][0], "Current price"), "8.82 USD")
        self.assertEqual(_stock_value(stocks_write["values"][1], "Target"), "4,30 EUR")
        self.assertEqual(_stock_value(stocks_write["values"][1], "Stop"), "2,70 EUR")
        self.assertEqual(_stock_value(stocks_write["values"][1], "Current price"), "3,33 EUR")
        self.assertEqual(_stock_value(stocks_write["values"][1], "Dividend Yield"), "18,6 %")
        self.assertEqual(_stock_value(stocks_write["values"][1], "Recommendation"), "new_recommendation")
        self.assertEqual(_stock_value(stocks_write["values"][1], "Held since"), "")
        self.assertEqual(
            _stock_value(stocks_write["values"][1], "Issue:Page"),
            "2026-W02:20 | 2026-W03:22",
        )
        self.assertIn("'Stocks'!A4:T4", [request["range"] for request in values_resource.clear_requests])
        self.assertIn("'Stocks'!A4:T4", result["staleRangesCleared"])

    def test_google_sheet_export_writes_before_clearing_stale_rows(self) -> None:
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
            values_resource = sheets.spreadsheets_resource.values_resource
            values_resource.values_by_range["'Stocks'!A2:T"] = [
                self._stock_sheet_row(company="Old Same Issue", issue="2026-W03"),
                self._stock_sheet_row(company="Keep Different Issue", issue="2026-W02"),
            ]
            values_resource.fail_batch_update = True
            values_resource.fail_batch_update_after = 1
            workbook_plan = {
                "issueId": "2026-W03",
                "rows": [
                    {
                        "tab": "Stocks",
                        "values": self._stock_sheet_row(issue="2026-W03"),
                    }
                ],
            }

            with self.assertRaisesRegex(GoogleAccessError, "workbook row export failed"):
                write_workbook_plan_to_google_sheet(
                    config,
                    workbook_plan,
                    sheets_service_factory=lambda: sheets,
                    allow_draft_rows=True,
                )

        self.assertEqual(values_resource.clear_requests, [])

    def test_google_sheet_export_uses_latest_stock_recommendation_and_held_since(self) -> None:
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
            sheets.spreadsheets_resource.values_resource.values_by_range["'Stocks'!A2:T"] = [
                self._stock_sheet_row(
                    recommendation="new_recommendation",
                    issue="2026-W02",
                    page="20",
                    date_updated="2026-05-10",
                )
            ]
            workbook_plan = {
                "issueId": "2026-W03",
                "rows": [
                    {
                        "tab": "Stocks",
                        "values": self._stock_sheet_row(
                            recommendation="hold",
                            held_since="02/2026",
                            comment="Follow-up coverage.",
                        ),
                    }
                ],
            }

            result = write_workbook_plan_to_google_sheet(
                config,
                workbook_plan,
                sheets_service_factory=lambda: sheets,
                allow_draft_rows=True,
            )

        values_resource = sheets.spreadsheets_resource.values_resource
        data_ranges = values_resource.batch_update_requests[-1]["body"]["data"]
        stocks_write = next(item for item in data_ranges if item["range"] == "'Stocks'!A2:T2")

        self.assertTrue(result["ok"])
        self.assertEqual(_stock_value(stocks_write["values"][0], "Recommendation"), "hold")
        self.assertEqual(_stock_value(stocks_write["values"][0], "Held since"), "02/2026")
        self.assertEqual(
            _stock_value(stocks_write["values"][0], "Issue:Page"),
            "2026-W02:20 | 2026-W03:22",
        )

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

            with self.assertRaisesRegex(GoogleAccessError, "Stocks.*20 values.*got 11"):
                write_workbook_plan_to_google_sheet(
                    config,
                    workbook_plan,
                    sheets_service_factory=lambda: sheets,
                    allow_draft_rows=True,
                )

    def test_google_sheet_export_skips_draft_rows_by_default(self) -> None:
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
                        "reviewStatus": "needs_review",
                        "exportable": False,
                        "requiresManualReview": True,
                        "values": self._stock_sheet_row(),
                    }
                ],
            }

            with self.assertRaisesRegex(GoogleAccessError, "workbook-approval-audit provenance"):
                write_workbook_plan_to_google_sheet(
                    config,
                    workbook_plan,
                    sheets_service_factory=lambda: sheets,
                )

        self.assertEqual(sheets.spreadsheets_resource.values_resource.clear_requests, [])

    def test_google_sheet_export_rejects_forged_approved_rows_without_audit(self) -> None:
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
                        "reviewStatus": "approved",
                        "exportable": True,
                        "requiresManualReview": False,
                        "reviewedBy": "reviewer@example.test",
                        "reviewedAt": "2026-06-06T10:00:00+00:00",
                        "sourceBlock": "reviewed_card_page_22",
                        "values": self._stock_sheet_row(),
                    }
                ],
            }

            with self.assertRaisesRegex(GoogleAccessError, "workbook-approval-audit provenance"):
                write_workbook_plan_to_google_sheet(
                    config,
                    workbook_plan,
                    sheets_service_factory=lambda: sheets,
                )

        self.assertEqual(sheets.spreadsheets_resource.values_resource.batch_update_requests, [])

    def test_google_sheet_export_writes_audit_approved_rows_by_default(self) -> None:
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
                "approvalAudit": {
                    "approvalSource": "private_reviewer_csv",
                    "rowCount": 1,
                    "approvedRows": 1,
                    "hashMismatchRows": 0,
                    "staleApprovalDetected": False,
                },
                "rows": [
                    {
                        "tab": "Stocks",
                        "reviewStatus": "approved",
                        "exportable": True,
                        "requiresManualReview": False,
                        "reviewedBy": "reviewer@example.test",
                        "reviewedAt": "2026-06-06T10:00:00+00:00",
                        "sourceBlock": "reviewed_card_page_22",
                        "values": self._stock_sheet_row(),
                    }
                ],
            }

            result = write_workbook_plan_to_google_sheet(
                config,
                workbook_plan,
                sheets_service_factory=lambda: sheets,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["exportMode"], "approved_family_export")
        self.assertTrue(result["familyVisibleSafe"])
        self.assertFalse(result["privateDraftReviewOnly"])
        self.assertEqual(result["rowsWritten"], 1)
        self.assertNotEqual(result["spreadsheetId"], config.sheets_spreadsheet_id)
        self.assertNotIn(config.sheets_spreadsheet_id, str(result))

    def test_google_sheet_export_rejects_invalid_approval_evidence_audit(self) -> None:
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
                "approvalAudit": {
                    "approvalSource": "private_reviewer_csv",
                    "rowCount": 1,
                    "approvedRows": 1,
                    "hashMismatchRows": 0,
                    "invalidEvidenceRows": 1,
                    "staleApprovalDetected": False,
                },
                "rows": [
                    {
                        "tab": "Stocks",
                        "reviewStatus": "approved",
                        "exportable": True,
                        "requiresManualReview": False,
                        "reviewedBy": "reviewer@example.test",
                        "reviewedAt": "2026-06-06T10:00:00+00:00",
                        "sourceBlock": "reviewed_card_page_22",
                        "values": self._stock_sheet_row(),
                    }
                ],
            }

            with self.assertRaisesRegex(GoogleAccessError, "invalid approval evidence"):
                write_workbook_plan_to_google_sheet(
                    config,
                    workbook_plan,
                    sheets_service_factory=lambda: sheets,
                )

        self.assertEqual(sheets.spreadsheets_resource.values_resource.batch_update_requests, [])

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
                allow_draft_rows=True,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["rowsWritten"], 0)
        self.assertEqual(result["rowsSkipped"], 1)
        self.assertNotIn("Navigation Dashboard", result["tabsWritten"])

    def test_google_sheet_refinement_export_writes_page_map_and_preserves_notes(self) -> None:
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
                    "Dividenden",
                    "Old title",
                    "yes",
                    "Dividend Focus",
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
        self.assertNotEqual(result["spreadsheetId"], config.sheets_spreadsheet_id)
        self.assertNotIn(config.sheets_spreadsheet_id, str(result))
        self.assertEqual(result["tabWritten"], "Refinement")
        self.assertEqual(result["rowsWritten"], 2)
        self.assertEqual(result["reviewerNotesPreserved"], 1)
        self.assertEqual(data["range"], "'Refinement'!A4:J5")
        self.assertEqual(data["values"][0][0], "1")
        self.assertEqual(data["values"][1][0], "18")
        self.assertEqual(data["values"][1][7], "Keep this page")
        self.assertIn("'Refinement'!A4:J", [request["range"] for request in values_resource.clear_requests])


if __name__ == "__main__":
    unittest.main()
