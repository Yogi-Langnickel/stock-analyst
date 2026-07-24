import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from stock_analyst.cli import run_google_drive_pdfs_command
from stock_analyst.google_access import (
    ACTIVE_GOOGLE_SHEET_TABS,
    AKTUELL_DERIVATIVE_HEADERS,
    DEFAULT_SHEET_TABS,
    GoogleAccessError,
    MANAGED_PROTECTION_DESCRIPTION_PREFIX,
    _apply_managed_sheet_protections,
    _auto_resize_issue_review_tab_columns,
    _build_aktuell_table_format_requests,
    _build_issue_search_index_rows,
    _build_issue_search_results_formula,
    _build_reviewer_action_format_requests,
    _build_search_format_requests,
    _fetch_sheet_ids_by_title,
    _reorder_issue_review_tabs_newest_first,
    bootstrap_google_sheet,
    build_drive_pdf_metadata_result,
    clear_google_sheet_data_rows,
    list_drive_pdf_metadata,
    load_env_file,
    load_google_access_config,
    refresh_google_sheet_search,
    run_google_access_smoke,
    write_refinement_plan_to_google_sheet,
    write_workbook_plan_to_google_sheet,
    write_drive_pdf_metadata_manifest,
)

TEST_SERVICE_ACCOUNT_CREDENTIALS = (
    '{"client_email":"stock-analyst@example.iam.gserviceaccount.com"}'
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
        sheets = self.payload.get("sheets", [])
        for request in kwargs.get("body", {}).get("requests", []):
            if "addSheet" in request:
                properties = dict(request["addSheet"].get("properties", {}))
                if "sheetId" not in properties:
                    properties["sheetId"] = max(
                        (
                            int(item.get("properties", {}).get("sheetId", 0))
                            for item in sheets
                        ),
                        default=0,
                    ) + 1
                sheets.append({"properties": properties})
            if "deleteSheet" in request:
                sheet_id = request["deleteSheet"]["sheetId"]
                sheets[:] = [
                    item
                    for item in sheets
                    if item.get("properties", {}).get("sheetId") != sheet_id
                ]
            if "updateSheetProperties" in request:
                update = request["updateSheetProperties"]["properties"]
                sheet_id = update["sheetId"]
                sheet_index = next(
                    index
                    for index, item in enumerate(sheets)
                    if item["properties"].get("sheetId") == sheet_id
                )
                sheet = sheets.pop(sheet_index)
                sheet["properties"].update(update)
                sheets.insert(min(int(update.get("index", sheet_index)), len(sheets)), sheet)
        return _FakeExecute({"updated": True})

    def values(self):
        return self.values_resource


class _FakeValues:
    def __init__(self):
        self.batch_update_requests = []
        self.batch_get_requests = []
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

    def batchGet(self, **kwargs):
        self.batch_get_requests.append(kwargs)
        return _FakeExecute(
            {
                "valueRanges": [
                    {
                        "range": range_name,
                        "values": self.values_by_range.get(range_name, []),
                    }
                    for range_name in kwargs.get("ranges", [])
                ]
            }
        )

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
    def test_managed_protections_cover_existing_and_future_review_tabs(self) -> None:
        sheets = _FakeSheets(
            {
                "spreadsheetId": "test-spreadsheet",
                "sheets": [
                    {
                        "properties": {"sheetId": 10, "title": "Search"},
                        "protectedRanges": [
                            {
                                "protectedRangeId": 91,
                                "description": (
                                    f"{MANAGED_PROTECTION_DESCRIPTION_PREFIX} Search"
                                ),
                            },
                            {
                                "protectedRangeId": 92,
                                "description": "Family-owned manual protection",
                            },
                        ],
                    },
                    {"properties": {"sheetId": 20, "title": "Aktuell"}},
                    {"properties": {"sheetId": 30, "title": "DA_2026_30"}},
                    {"properties": {"sheetId": 40, "title": "Notes"}},
                ],
            }
        )

        protected_tabs = _apply_managed_sheet_protections(
            sheets,
            spreadsheet_id="test-spreadsheet",
            editor_email="stock-analyst@example.iam.gserviceaccount.com",
        )

        self.assertEqual(protected_tabs, ["Search", "Aktuell", "DA_2026_30"])
        requests = sheets.spreadsheets_resource.batch_update_requests[-1]["body"][
            "requests"
        ]
        self.assertIn(
            {"deleteProtectedRange": {"protectedRangeId": 91}},
            requests,
        )
        self.assertNotIn(
            {"deleteProtectedRange": {"protectedRangeId": 92}},
            requests,
        )
        added = [
            request["addProtectedRange"]["protectedRange"]
            for request in requests
            if "addProtectedRange" in request
        ]
        self.assertEqual(
            [item["range"]["sheetId"] for item in added],
            [10, 20, 30],
        )
        self.assertEqual(
            added[0]["unprotectedRanges"],
            [
                {
                    "sheetId": 10,
                    "startRowIndex": 0,
                    "endRowIndex": 1,
                    "startColumnIndex": 2,
                    "endColumnIndex": 5,
                }
            ],
        )
        self.assertNotIn("unprotectedRanges", added[1])
        self.assertNotIn("unprotectedRanges", added[2])
        for protected_range in added:
            self.assertFalse(protected_range["warningOnly"])
            self.assertEqual(
                protected_range["editors"],
                {
                    "users": [
                        "stock-analyst@example.iam.gserviceaccount.com"
                    ],
                    "domainUsersCanEdit": False,
                },
            )

    def test_active_google_sheet_tabs_keep_search_and_aktuell_only(self) -> None:
        self.assertEqual(
            [spec.title for spec in ACTIVE_GOOGLE_SHEET_TABS],
            ["Search", "Aktuell"],
        )
        self.assertIn("Stocks", [spec.title for spec in DEFAULT_SHEET_TABS])
        self.assertIn("Derivative Tips", [spec.title for spec in DEFAULT_SHEET_TABS])

    def test_issue_search_index_preserves_full_rows_newest_issue_first_without_aktuell(self) -> None:
        stock_header = list(_headers_for("Aktuell"))
        stock_row = ["" for _ in stock_header]
        stock_row[stock_header.index("WKN")] = "A0TEST"
        stock_row[stock_header.index("Company")] = "Example AG"
        stock_row[stock_header.index("Action")] = "Buy"
        stock_row[stock_header.index("Source")] = "2026-W30:12"
        stock_row[stock_header.index("Review status")] = "approved"
        derivative_header = list(AKTUELL_DERIVATIVE_HEADERS)
        derivative_row = ["" for _ in derivative_header]
        derivative_row[derivative_header.index("WKN")] = "D0TEST"
        derivative_row[derivative_header.index("Derivative")] = "Example Call"
        derivative_row[derivative_header.index("Action")] = "Hold"
        derivative_row[derivative_header.index("Issue:Page")] = "2026-W30:18"
        derivative_row[derivative_header.index("Review status")] = "needs_review"
        older_stock_row = list(stock_row)
        older_stock_row[stock_header.index("Action")] = "Hold"
        older_stock_row[stock_header.index("Source")] = "2026-W29:10"

        rows = _build_issue_search_index_rows(
            issue_tab_values_by_title={
                "Aktuell": [stock_header, stock_row],
                "DA_2026_29": [stock_header, older_stock_row],
                "DA_2026_30": [
                    stock_header,
                    stock_row,
                    [],
                    [],
                    ["Derivatives"],
                    derivative_header,
                    derivative_row,
                ],
            },
            sheet_ids_by_title={
                "Aktuell": 20,
                "DA_2026_29": 29,
                "DA_2026_30": 30,
            },
        )

        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0][:4], [
            "Stock",
            202630,
            12,
            "a0test example ag",
        ])
        self.assertEqual(rows[0][4:20], stock_row)
        self.assertEqual(rows[0][20], "")
        self.assertEqual(rows[1][:4], [
            "Derivative",
            202630,
            18,
            "d0test example call",
        ])
        self.assertEqual(rows[1][4:], derivative_row)
        self.assertEqual(rows[2][1:3], [202629, 10])
        self.assertEqual(rows[2][4:20], older_stock_row)
        self.assertNotIn("Aktuell", str(rows))

    def test_issue_search_formula_stacks_full_reviewer_schemas_sorted_descending(self) -> None:
        formula = _build_issue_search_results_formula()

        self.assertIn("$C$1", formula)
        self.assertNotIn("$B$1", formula)
        self.assertIn('$S$2:$S="Stock"', formula)
        self.assertIn('$S$2:$S="Derivative"', formula)
        self.assertIn("$W$2:$AM", formula)
        self.assertIn("SORT(", formula)
        self.assertIn(",1,FALSE,2,TRUE)", formula)
        self.assertIn('"Source","WKN","Company","Action"', formula)
        self.assertIn('"Source","WKN","Derivative","Action"', formula)
        self.assertIn("CHOOSECOLS(stockSorted,16,3,4,5", formula)
        self.assertIn("CHOOSECOLS(derivativeSorted,17,3,4,5", formula)
        self.assertIn('{"Stocks"', formula)
        self.assertIn('{"Derivatives"', formula)
        self.assertIn('"Price at Print"', formula)
        self.assertIn('"Magazine Current Price"', formula)
        self.assertIn('"Reviewer note"', formula)
        self.assertIn("ARRAYFORMULA(ISNUMBER(SEARCH(", formula)
        self.assertNotIn("Aktuell", formula)

    def test_search_formats_match_reviewer_headers_and_action_colours(self) -> None:
        requests = _build_search_format_requests(
            sheet_id=42,
            existing_rule_count=2,
        )

        self.assertEqual(
            [request["deleteConditionalFormatRule"]["index"] for request in requests[:2]],
            [1, 0],
        )
        add_rules = [
            request["addConditionalFormatRule"]["rule"]
            for request in requests
            if "addConditionalFormatRule" in request
        ]
        formulas = [
            rule["booleanRule"]["condition"]["values"][0]["userEnteredValue"]
            for rule in add_rules
        ]
        self.assertIn('=OR($A4="Stocks",$A4="Derivatives")', formulas)
        self.assertIn(
            '=AND($A4="Source",$B4="WKN",$C4="Company",$D4="Action")',
            formulas,
        )
        self.assertIn(
            '=AND($A4="Source",$B4="WKN",$C4="Derivative",$D4="Action")',
            formulas,
        )
        self.assertIn('=$D4="Buy"', formulas)
        self.assertIn('=$D4="Hold"', formulas)
        self.assertIn('=$D4="Sell"', formulas)
        self.assertFalse(any("Wait" in formula for formula in formulas))
        for rule in add_rules:
            data_range = rule["ranges"][0]
            self.assertEqual(data_range["startRowIndex"], 3)
            self.assertEqual(data_range["startColumnIndex"], 0)
            self.assertEqual(data_range["endColumnIndex"], 17)

    def test_search_refresh_indexes_existing_issue_tabs_without_reexporting_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            credentials_path = Path(temp_dir) / "service-account.json"
            credentials_path.write_text(TEST_SERVICE_ACCOUNT_CREDENTIALS, encoding="utf-8")
            config = load_google_access_config(
                env={
                    "GOOGLE_DRIVE_FOLDER_ID": "synthetic-drive-folder-id-0001",
                    "GOOGLE_SHEETS_SPREADSHEET_ID": "synthetic-spreadsheet-id-0001",
                    "GOOGLE_APPLICATION_CREDENTIALS": str(credentials_path),
                }
            )
            sheets = _FakeSheets(
                {
                    "spreadsheetId": config.sheets_spreadsheet_id,
                    "sheets": [
                        {"properties": {"sheetId": 10, "title": "Search"}},
                        {"properties": {"sheetId": 20, "title": "Aktuell"}},
                        {"properties": {"sheetId": 30, "title": "DA_2026_30"}},
                    ],
                }
            )
            stock_header = list(_headers_for("Aktuell"))
            stock_row = ["" for _ in stock_header]
            stock_row[0:3] = ["A0TEST", "Example AG", "Buy"]
            stock_row[stock_header.index("Source")] = "2026-W30:12"
            sheets.spreadsheets_resource.values_resource.values_by_range[
                "'DA_2026_30'!A:Q"
            ] = [stock_header, stock_row]
            sheets.spreadsheets_resource.values_resource.values_by_range[
                "'Search'!B1:C1"
            ] = [["Legacy query", ""]]

            result = refresh_google_sheet_search(
                config,
                sheets_service_factory=lambda: sheets,
            )

        self.assertEqual(result["searchIndexedRows"], 1)
        self.assertEqual(
            result["protectedTabs"],
            ["Search", "Aktuell", "DA_2026_30"],
        )
        user_entered_batches = [
            request["body"]["data"]
            for request in sheets.spreadsheets_resource.values_resource.batch_update_requests
            if request["body"].get("valueInputOption") == "USER_ENTERED"
        ]
        search_batch = next(
            batch
            for batch in user_entered_batches
            if any(item["range"] == "'Search'!A4" for item in batch)
        )
        self.assertIn(
            {
                "range": "'Search'!C1",
                "values": [["Legacy query"]],
            },
            search_batch,
        )
        self.assertTrue(
            any(
                request["range"] == "'Search'!B1"
                for request in sheets.spreadsheets_resource.values_resource.clear_requests
            )
        )
        raw_batches = [
            request["body"]["data"]
            for request in sheets.spreadsheets_resource.values_resource.batch_update_requests
            if request["body"].get("valueInputOption") == "RAW"
        ]
        self.assertTrue(
            any(
                item["range"] == "'Search'!S2:AM2"
                for batch in raw_batches
                for item in batch
            )
        )
        self.assertFalse(
            any(
                item["range"].startswith("'DA_2026_30'!")
                for batch in user_entered_batches
                for item in batch
            )
        )
        search_properties_request = next(
            request["updateSheetProperties"]
            for batch in sheets.spreadsheets_resource.batch_update_requests
            for request in batch["body"]["requests"]
            if "updateSheetProperties" in request
            and request["updateSheetProperties"]["properties"].get("sheetId") == 10
        )
        self.assertEqual(
            search_properties_request["properties"]["gridProperties"][
                "frozenRowCount"
            ],
            0,
        )
        search_structure_requests = next(
            batch["body"]["requests"]
            for batch in sheets.spreadsheets_resource.batch_update_requests
            if any("mergeCells" in request for request in batch["body"]["requests"])
        )
        input_range = {
            "sheetId": 10,
            "startRowIndex": 0,
            "endRowIndex": 1,
            "startColumnIndex": 2,
            "endColumnIndex": 5,
        }
        self.assertIn(
            {"unmergeCells": {"range": input_range}},
            search_structure_requests,
        )
        self.assertIn(
            {
                "mergeCells": {
                    "range": input_range,
                    "mergeType": "MERGE_ALL",
                }
            },
            search_structure_requests,
        )
        input_format = next(
            request["repeatCell"]
            for request in search_structure_requests
            if "repeatCell" in request
            and request["repeatCell"]["range"] == input_range
        )
        self.assertEqual(
            input_format["cell"]["note"],
            "Enter a company name or WKN.",
        )

    def test_aktuell_table_format_uses_colored_stacked_section_headers(self) -> None:
        requests = _build_aktuell_table_format_requests(
            sheet_id=42,
            stock_header_row=1,
            derivative_label_row=5,
            derivative_header_row=6,
        )

        self.assertEqual(len(requests), 4)
        self.assertEqual(
            requests[1]["repeatCell"]["range"],
            {
                "sheetId": 42,
                "startRowIndex": 0,
                "endRowIndex": 1,
                "startColumnIndex": 0,
                "endColumnIndex": 16,
            },
        )
        self.assertEqual(requests[0]["repeatCell"]["range"]["startRowIndex"], 1)
        self.assertEqual(requests[2]["repeatCell"]["range"]["startRowIndex"], 4)
        self.assertEqual(requests[3]["repeatCell"]["range"]["startRowIndex"], 5)
        body_reset = requests[0]["repeatCell"]
        self.assertEqual(
            body_reset["fields"],
            "userEnteredFormat.backgroundColor,"
            "userEnteredFormat.horizontalAlignment,"
            "userEnteredFormat.textFormat.bold,"
            "userEnteredFormat.textFormat.foregroundColor",
        )
        self.assertEqual(
            body_reset["cell"]["userEnteredFormat"]["textFormat"]["foregroundColor"],
            {"red": 0.0, "green": 0.0, "blue": 0.0},
        )
        self.assertFalse(body_reset["cell"]["userEnteredFormat"]["textFormat"]["bold"])
        self.assertEqual(body_reset["cell"]["userEnteredFormat"]["horizontalAlignment"], "LEFT")
        self.assertNotIn("endRowIndex", body_reset["range"])
        self.assertTrue(requests[1]["repeatCell"]["cell"]["userEnteredFormat"]["textFormat"]["bold"])

    def test_reviewer_action_formats_use_each_stacked_table_action_column(self) -> None:
        requests = _build_reviewer_action_format_requests(
            (
                {"sheetId": 42, "title": "Aktuell", "conditionalFormats": []},
                {"sheetId": 43, "title": "DA_2026_30", "conditionalFormats": []},
            )
        )

        add_requests = [
            request["addConditionalFormatRule"]
            for request in requests
            if "addConditionalFormatRule" in request
        ]
        self.assertEqual(len(add_requests), 12)
        self.assertFalse(
            any(
                "Wait" in rule["rule"]["booleanRule"]["condition"]["values"][0]["userEnteredValue"]
                for rule in add_requests
            )
        )
        expected_by_sheet = {
            42: (
                ('=$C2="Buy"', 16, {"red": 0.85, "green": 0.94, "blue": 0.85}),
                ('=$C2="Hold"', 16, {"red": 1.0, "green": 0.95, "blue": 0.75}),
                ('=$C2="Sell"', 16, {"red": 0.98, "green": 0.84, "blue": 0.84}),
                ('=$C2="Buy"', 17, {"red": 0.85, "green": 0.94, "blue": 0.85}),
                ('=$C2="Hold"', 17, {"red": 1.0, "green": 0.95, "blue": 0.75}),
                ('=$C2="Sell"', 17, {"red": 0.98, "green": 0.84, "blue": 0.84}),
            ),
            43: (
                ('=$C2="Buy"', 16, {"red": 0.85, "green": 0.94, "blue": 0.85}),
                ('=$C2="Hold"', 16, {"red": 1.0, "green": 0.95, "blue": 0.75}),
                ('=$C2="Sell"', 16, {"red": 0.98, "green": 0.84, "blue": 0.84}),
                ('=$C2="Buy"', 17, {"red": 0.85, "green": 0.94, "blue": 0.85}),
                ('=$C2="Hold"', 17, {"red": 1.0, "green": 0.95, "blue": 0.75}),
                ('=$C2="Sell"', 17, {"red": 0.98, "green": 0.84, "blue": 0.84}),
            ),
        }
        actual_by_sheet: dict[int, set[tuple[object, object, object]]] = {}
        for request in add_requests:
            rule = request["rule"]
            data_range = rule["ranges"][0]
            formula = rule["booleanRule"]["condition"]["values"][0]["userEnteredValue"]
            color = rule["booleanRule"]["format"]["backgroundColor"]
            self.assertEqual(data_range["startRowIndex"], 1)
            self.assertEqual(data_range["startColumnIndex"], 0)
            self.assertNotIn("endRowIndex", data_range)
            actual_by_sheet.setdefault(data_range["sheetId"], set()).add(
                (formula, data_range["endColumnIndex"], tuple(sorted(color.items())))
            )
        self.assertEqual(
            actual_by_sheet,
            {
                sheet_id: {
                    (formula, end_column, tuple(sorted(color.items())))
                    for formula, end_column, color in expected
                }
                for sheet_id, expected in expected_by_sheet.items()
            },
        )

    def test_reviewer_action_formats_replace_only_owned_rules_descending(self) -> None:
        owned_stock = {
            "ranges": [{"sheetId": 42, "startRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": 16}],
            "booleanRule": {
                "condition": {"type": "CUSTOM_FORMULA", "values": [{"userEnteredValue": '=$C2="Buy"'}]}
            },
        }
        unrelated = {
            "ranges": [{"sheetId": 42, "startRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": 16}],
            "booleanRule": {
                "condition": {"type": "CUSTOM_FORMULA", "values": [{"userEnteredValue": "=LEN(A2)>0"}]}
            },
        }
        owned_derivative = {
            "ranges": [{"sheetId": 42, "startRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": 17}],
            "booleanRule": {
                "condition": {"type": "CUSTOM_FORMULA", "values": [{"userEnteredValue": '=$A2="Sell"'}]}
            },
        }

        requests = _build_reviewer_action_format_requests(
            ({"sheetId": 42, "title": "Aktuell", "conditionalFormats": [unrelated, owned_stock, owned_derivative]},)
        )

        self.assertEqual(
            [request["deleteConditionalFormatRule"] for request in requests if "deleteConditionalFormatRule" in request],
            [{"sheetId": 42, "index": 2}, {"sheetId": 42, "index": 1}],
        )
        self.assertEqual(
            len([request for request in requests if "addConditionalFormatRule" in request]),
            6,
        )

    def test_issue_recommendation_tables_leave_at_most_two_blank_rows_between_sections(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            credentials_path = Path(temp_dir) / "service-account.json"
            credentials_path.write_text(TEST_SERVICE_ACCOUNT_CREDENTIALS, encoding="utf-8")
            config = load_google_access_config(
                env={
                    "GOOGLE_DRIVE_FOLDER_ID": "synthetic-drive-folder-id-0001",
                    "GOOGLE_SHEETS_SPREADSHEET_ID": "synthetic-spreadsheet-id-0001",
                    "GOOGLE_APPLICATION_CREDENTIALS": str(credentials_path),
                }
            )
            sheets = _FakeSheets(
                {
                    "spreadsheetId": config.sheets_spreadsheet_id,
                    "sheets": [
                        {"properties": {"sheetId": index + 1, "title": spec.title}}
                        for index, spec in enumerate(DEFAULT_SHEET_TABS)
                    ],
                }
            )
            stock_values = ["" for _ in _headers_for("Aktuell")]
            stock_values[0:3] = ["Example WKN", "Example Stock", "Buy"]
            derivative_values = ["" for _ in AKTUELL_DERIVATIVE_HEADERS]
            derivative_values[0:3] = ["DERIV1", "Example Call", "Buy"]

            write_workbook_plan_to_google_sheet(
                config,
                {
                    "issueId": "2026-W30",
                    "rows": [
                        {
                            "tab": "Aktuell",
                            "rowKind": "latest_issue_stock_buy_sell_recommendation",
                            "values": stock_values,
                        },
                        {
                            "tab": "Aktuell",
                            "rowKind": "latest_issue_derivative_buy_sell_recommendation",
                            "values": derivative_values,
                        },
                    ],
                },
                sheets_service_factory=lambda: sheets,
                allow_draft_rows=True,
            )

        raw_data = next(
            request["body"]["data"]
            for request in sheets.spreadsheets_resource.values_resource.batch_update_requests
            if request["body"].get("valueInputOption") == "RAW"
        )
        stock_header = next(
            item for item in raw_data if item["range"] == "'Aktuell'!A1:P1"
        )
        derivative_label = next(
            item for item in raw_data if item["range"] == "'Aktuell'!A5:Q5"
        )
        derivative_header = next(
            item for item in raw_data if item["range"] == "'Aktuell'!A6:Q6"
        )
        self.assertEqual(stock_header["values"], [list(_headers_for("Aktuell"))])
        self.assertEqual(derivative_label["values"], [["Derivatives", *([""] * 16)]])
        self.assertEqual(derivative_header["values"][0][:3], ["WKN", "Derivative", "Action"])
        self.assertEqual(derivative_header["values"][0][14], "Issue:Page")
        self.assertTrue(
            any(item["range"] == "'DA_2026_30'!A1:P1" for item in raw_data)
        )
        self.assertTrue(
            any(item["range"] == "'DA_2026_30'!A5:Q5" for item in raw_data)
        )
        self.assertFalse(
            any(item["range"] in {"'Aktuell'!A1", "'Aktuell'!A2", "'Aktuell'!A3"}
                for item in raw_data)
        )

    def test_google_sheet_export_resyncs_existing_reviewer_grid_and_trims_tail(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            credentials_path = Path(temp_dir) / "service-account.json"
            credentials_path.write_text(TEST_SERVICE_ACCOUNT_CREDENTIALS, encoding="utf-8")
            config = load_google_access_config(
                env={
                    "GOOGLE_DRIVE_FOLDER_ID": "synthetic-drive-folder-id-0001",
                    "GOOGLE_SHEETS_SPREADSHEET_ID": "synthetic-spreadsheet-id-0001",
                    "GOOGLE_APPLICATION_CREDENTIALS": str(credentials_path),
                }
            )
            sheets = _FakeSheets(
                {
                    "spreadsheetId": config.sheets_spreadsheet_id,
                    "sheets": [
                        {
                            "properties": {
                                "sheetId": index + 1,
                                "title": spec.title,
                                "gridProperties": {
                                    "frozenRowCount": 4,
                                    "frozenColumnCount": 4,
                                    "rowCount": 1000,
                                },
                            }
                        }
                        for index, spec in enumerate(DEFAULT_SHEET_TABS)
                    ]
                    + [
                        {
                            "properties": {
                                "sheetId": 99,
                                "title": "DA_2026_30",
                                "gridProperties": {
                                    "frozenRowCount": 4,
                                    "frozenColumnCount": 4,
                                    "rowCount": 1000,
                                },
                            }
                        }
                    ],
                }
            )
            stock_values = ["" for _ in _headers_for("Aktuell")]
            stock_values[0:3] = ["Example WKN", "Example Stock", "Buy"]
            derivative_values = ["" for _ in AKTUELL_DERIVATIVE_HEADERS]
            derivative_values[0:3] = ["DERIV1", "Example Call", "Buy"]

            result = write_workbook_plan_to_google_sheet(
                config,
                {
                    "issueId": "2026-W30",
                    "rows": [
                        {
                            "tab": "Aktuell",
                            "rowKind": "latest_issue_stock_buy_sell_recommendation",
                            "values": stock_values,
                        },
                        {
                            "tab": "Aktuell",
                            "rowKind": "latest_issue_derivative_buy_sell_recommendation",
                            "values": derivative_values,
                        },
                    ],
                },
                sheets_service_factory=lambda: sheets,
                allow_draft_rows=True,
            )

        properties_by_title = {
            item["properties"]["title"]: item["properties"]
            for item in sheets.spreadsheets_resource.payload["sheets"]
        }
        for title in ("Aktuell", "DA_2026_30"):
            grid = properties_by_title[title]["gridProperties"]
            self.assertEqual(grid["frozenRowCount"], 1)
            self.assertEqual(grid["frozenColumnCount"], 3)
            self.assertEqual(grid["rowCount"], 8)
        self.assertEqual(result["reviewerGridTabsSynced"], ["DA_2026_30", "Aktuell"])

    def test_google_sheet_export_expands_compact_reviewer_grid_before_larger_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            credentials_path = Path(temp_dir) / "service-account.json"
            credentials_path.write_text(TEST_SERVICE_ACCOUNT_CREDENTIALS, encoding="utf-8")
            config = load_google_access_config(
                env={
                    "GOOGLE_DRIVE_FOLDER_ID": "synthetic-drive-folder-id-0001",
                    "GOOGLE_SHEETS_SPREADSHEET_ID": "synthetic-spreadsheet-id-0001",
                    "GOOGLE_APPLICATION_CREDENTIALS": str(credentials_path),
                }
            )
            sheets = _FakeSheets(
                {
                    "spreadsheetId": config.sheets_spreadsheet_id,
                    "sheets": [
                        {
                            "properties": {
                                "sheetId": index + 1,
                                "title": spec.title,
                                "gridProperties": {
                                    "frozenRowCount": 1,
                                    "frozenColumnCount": 3,
                                    "rowCount": 8,
                                },
                            }
                        }
                        for index, spec in enumerate(DEFAULT_SHEET_TABS)
                    ]
                    + [
                        {
                            "properties": {
                                "sheetId": 99,
                                "title": "DA_2026_30",
                                "gridProperties": {
                                    "frozenRowCount": 1,
                                    "frozenColumnCount": 3,
                                    "rowCount": 8,
                                },
                            }
                        }
                    ],
                }
            )
            rows = []
            for index in range(4):
                values = ["" for _ in _headers_for("Aktuell")]
                values[0:3] = ["Buy", f"2026-W30:{index + 1}", f"Stock {index + 1}"]
                rows.append(
                    {
                        "tab": "Aktuell",
                        "rowKind": "latest_issue_stock_buy_sell_recommendation",
                        "values": values,
                    }
                )
            derivative_values = ["" for _ in AKTUELL_DERIVATIVE_HEADERS]
            derivative_values[0:3] = ["DERIV1", "Example Call", "Buy"]
            rows.append(
                {
                    "tab": "Aktuell",
                    "rowKind": "latest_issue_derivative_buy_sell_recommendation",
                    "values": derivative_values,
                }
            )

            result = write_workbook_plan_to_google_sheet(
                config,
                {"issueId": "2026-W30", "rows": rows},
                sheets_service_factory=lambda: sheets,
                allow_draft_rows=True,
            )

        capacity_requests = [
            request["updateSheetProperties"]
            for batch in sheets.spreadsheets_resource.batch_update_requests
            for request in batch["body"].get("requests", [])
            if request.get("updateSheetProperties", {}).get("fields")
            == "gridProperties.rowCount"
        ]
        self.assertEqual(len(capacity_requests), 2)
        self.assertTrue(
            all(
                request["properties"]["gridProperties"]["rowCount"] == 11
                for request in capacity_requests
            )
        )
        self.assertEqual(result["reviewerGridTabsExpanded"], ["DA_2026_30", "Aktuell"])
        self.assertIn("'DA_2026_30'!A11:AI", result["staleRangesCleared"])
        self.assertIn("'Aktuell'!A11:AI", result["staleRangesCleared"])
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

    def test_google_sheet_export_creates_issue_tab_and_keeps_aktuell_on_newest_issue(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            credentials_path = Path(temp_dir) / "service-account.json"
            credentials_path.write_text(TEST_SERVICE_ACCOUNT_CREDENTIALS, encoding="utf-8")
            config = load_google_access_config(
                env={
                    "GOOGLE_DRIVE_FOLDER_ID": "synthetic-drive-folder-id-0001",
                    "GOOGLE_SHEETS_SPREADSHEET_ID": "synthetic-spreadsheet-id-0001",
                    "GOOGLE_APPLICATION_CREDENTIALS": str(credentials_path),
                }
            )
            sheets = _FakeSheets(
                {
                    "spreadsheetId": config.sheets_spreadsheet_id,
                    "sheets": [
                        {"properties": {"sheetId": index + 1, "title": spec.title}}
                        for index, spec in enumerate(DEFAULT_SHEET_TABS)
                    ],
                }
            )
            aktuell_values = ["" for _ in _headers_for("Aktuell")]
            aktuell_values[0:7] = [
                "EXM123",
                "Example Company",
                "Buy",
                "111,11 EUR",
                "140,00 EUR",
                "95,00 EUR",
                "",
            ]
            latest_plan = {
                "issueId": "2026-W25",
                "rows": [
                    {
                        "tab": "Aktuell",
                        "rowKind": "latest_issue_stock_buy_sell_recommendation",
                        "values": aktuell_values,
                    }
                ],
            }

            latest_result = write_workbook_plan_to_google_sheet(
                config,
                latest_plan,
                sheets_service_factory=lambda: sheets,
                allow_draft_rows=True,
            )
            sheets.spreadsheets_resource.values_resource.values_by_range[
                "'DA_2026_25'!A:Q"
            ] = [list(_headers_for("Aktuell")), aktuell_values]

            earlier_plan = {**latest_plan, "issueId": "2026-W24"}
            earlier_result = write_workbook_plan_to_google_sheet(
                config,
                earlier_plan,
                sheets_service_factory=lambda: sheets,
                allow_draft_rows=True,
            )

        self.assertEqual(latest_result["issueTab"], "DA_2026_25")
        self.assertTrue(latest_result["aktuellUpdated"])
        self.assertEqual(
            latest_result["protectedTabs"],
            ["Search", "Aktuell", "DA_2026_25"],
        )
        self.assertIn("'DA_2026_25'!A3:Q4", latest_result["staleRangesCleared"])
        self.assertNotIn("'DA_2026_25'!A2:Q4", latest_result["staleRangesCleared"])
        self.assertEqual(earlier_result["issueTab"], "DA_2026_24")
        self.assertFalse(earlier_result["aktuellUpdated"])
        self.assertEqual(
            earlier_result["protectedTabs"],
            ["Search", "Aktuell", "DA_2026_25", "DA_2026_24"],
        )
        titles = [item["properties"]["title"] for item in sheets.spreadsheets_resource.payload["sheets"]]
        self.assertIn("DA_2026_25", titles)
        self.assertIn("DA_2026_24", titles)

        raw_batches = [
            request["body"]["data"]
            for request in sheets.spreadsheets_resource.values_resource.batch_update_requests
            if request["body"].get("valueInputOption") == "RAW"
        ]
        issue_raw_batches = [
            batch
            for batch in raw_batches
            if any(item["range"].startswith("'DA_") for item in batch)
        ]
        self.assertTrue(any(item["range"] == "'DA_2026_25'!A2:P2" for item in issue_raw_batches[0]))
        self.assertTrue(any(item["range"] == "'Aktuell'!A2:P2" for item in issue_raw_batches[0]))
        self.assertTrue(any(item["range"] == "'DA_2026_24'!A2:P2" for item in issue_raw_batches[1]))
        self.assertFalse(any(item["range"] == "'Aktuell'!A2:P2" for item in issue_raw_batches[1]))

        search_batches = [
            request["body"]["data"]
            for request in sheets.spreadsheets_resource.values_resource.batch_update_requests
            if request["body"].get("valueInputOption") == "USER_ENTERED"
            and any(item["range"] == "'Search'!A4" for item in request["body"]["data"])
        ]
        self.assertEqual(earlier_result["searchIndexedRows"], 2)
        search_data = search_batches[-1]
        search_formula = next(item for item in search_data if item["range"] == "'Search'!A4")
        search_index = next(
            item
            for batch in raw_batches
            for item in batch
            if item["range"] == "'Search'!S2:AM3"
        )
        self.assertNotIn("Aktuell", search_formula["values"][0][0])
        self.assertEqual(
            [row[1] for row in search_index["values"]],
            [202625, 202624],
        )
        self.assertEqual(search_index["values"][0][4:20], aktuell_values)

    def test_issue_review_tabs_reorder_newest_first_and_auto_resize_all_columns(self) -> None:
        sheets = _FakeSheets(
            {
                "spreadsheetId": "test-spreadsheet",
                "sheets": [
                    {"properties": {"sheetId": 10, "title": "Navigation Dashboard"}},
                    {"properties": {"sheetId": 20, "title": "Aktuell"}},
                    {"properties": {"sheetId": 30, "title": "Stocks"}},
                    {"properties": {"sheetId": 40, "title": "DA_2026_28"}},
                    {"properties": {"sheetId": 50, "title": "DA_2026_30"}},
                    {"properties": {"sheetId": 60, "title": "DA_2026_29"}},
                ],
            }
        )

        reordered = _reorder_issue_review_tabs_newest_first(
            sheets,
            spreadsheet_id="test-spreadsheet",
        )
        sheet_ids = _fetch_sheet_ids_by_title(sheets, spreadsheet_id="test-spreadsheet")
        resized = _auto_resize_issue_review_tab_columns(
            sheets,
            spreadsheet_id="test-spreadsheet",
            sheet_ids_by_title=sheet_ids,
        )

        titles = [
            item["properties"]["title"]
            for item in sheets.spreadsheets_resource.payload["sheets"]
        ]
        self.assertEqual(titles[:3], ["Navigation Dashboard", "Aktuell", "Stocks"])
        self.assertEqual(titles[3:], ["DA_2026_30", "DA_2026_29", "DA_2026_28"])
        self.assertEqual(reordered, ["DA_2026_30", "DA_2026_29", "DA_2026_28"])
        self.assertEqual(resized, ["Aktuell", "DA_2026_30", "DA_2026_29", "DA_2026_28"])

        resize_requests = [
            request["autoResizeDimensions"]["dimensions"]
            for batch in sheets.spreadsheets_resource.batch_update_requests
            for request in batch["body"].get("requests", [])
            if "autoResizeDimensions" in request
        ]
        self.assertEqual(
            resize_requests,
            [
                {"sheetId": 20, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 17},
                {"sheetId": 50, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 17},
                {"sheetId": 60, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 17},
                {"sheetId": 40, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 17},
            ],
        )

    def test_load_env_file_parses_quoted_google_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_file = Path(temp_dir) / ".env.google"
            env_file.write_text(
                '\n'.join(
                    (
                        'GOOGLE_SERVICE_ACCOUNT_EMAIL="stock-analyst@example.iam.gserviceaccount.com"',
                        'GOOGLE_DRIVE_FOLDER_ID="synthetic-drive-folder-id-0001"',
                    )
                ),
                encoding="utf-8",
            )

            values = load_env_file(env_file)

        self.assertEqual(
            values["GOOGLE_SERVICE_ACCOUNT_EMAIL"],
            "stock-analyst@example.iam.gserviceaccount.com",
        )
        self.assertEqual(values["GOOGLE_DRIVE_FOLDER_ID"], "synthetic-drive-folder-id-0001")

    def test_config_requires_existing_credentials_and_google_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            credentials_path = Path(temp_dir) / "service-account.json"
            credentials_path.write_text(TEST_SERVICE_ACCOUNT_CREDENTIALS, encoding="utf-8")

            config = load_google_access_config(
                env={
                    "GOOGLE_DRIVE_FOLDER_ID": "synthetic-drive-folder-id-0001",
                    "GOOGLE_SHEETS_SPREADSHEET_ID": "synthetic-spreadsheet-id-0001",
                    "GOOGLE_APPLICATION_CREDENTIALS": str(credentials_path),
                }
            )

        self.assertEqual(config.drive_folder_id, "synthetic-drive-folder-id-0001")
        self.assertEqual(config.service_account_email, "stock-analyst@example.iam.gserviceaccount.com")
        self.assertNotEqual(
            config.to_public_dict()["serviceAccountEmail"],
            "stock-analyst@example.iam.gserviceaccount.com",
        )

    def test_config_rejects_missing_credentials_file(self) -> None:
        with self.assertRaisesRegex(GoogleAccessError, "GOOGLE_APPLICATION_CREDENTIALS does not exist"):
            load_google_access_config(
                env={
                    "GOOGLE_DRIVE_FOLDER_ID": "synthetic-drive-folder-id-0001",
                    "GOOGLE_SHEETS_SPREADSHEET_ID": "synthetic-spreadsheet-id-0001",
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
                    "GOOGLE_DRIVE_FOLDER_ID": "synthetic-drive-folder-id-0001",
                    "GOOGLE_SHEETS_SPREADSHEET_ID": "synthetic-spreadsheet-id-0001",
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
            credentials_path.write_text(TEST_SERVICE_ACCOUNT_CREDENTIALS, encoding="utf-8")
            config = load_google_access_config(
                env={
                    "GOOGLE_DRIVE_FOLDER_ID": "synthetic-drive-folder-id-0001",
                    "GOOGLE_SHEETS_SPREADSHEET_ID": "synthetic-spreadsheet-id-0001",
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
            credentials_path.write_text(TEST_SERVICE_ACCOUNT_CREDENTIALS, encoding="utf-8")
            config = load_google_access_config(
                env={
                    "GOOGLE_DRIVE_FOLDER_ID": "synthetic-drive-folder-id-0001",
                    "GOOGLE_SHEETS_SPREADSHEET_ID": "synthetic-spreadsheet-id-0001",
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
            credentials_path.write_text(TEST_SERVICE_ACCOUNT_CREDENTIALS, encoding="utf-8")
            config = load_google_access_config(
                env={
                    "GOOGLE_DRIVE_FOLDER_ID": "synthetic-drive-folder-id-0001",
                    "GOOGLE_SHEETS_SPREADSHEET_ID": "synthetic-spreadsheet-id-0001",
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
            credentials_path.write_text(TEST_SERVICE_ACCOUNT_CREDENTIALS, encoding="utf-8")
            config = load_google_access_config(
                env={
                    "GOOGLE_DRIVE_FOLDER_ID": "synthetic-drive-folder-id-0001",
                    "GOOGLE_SHEETS_SPREADSHEET_ID": "synthetic-spreadsheet-id-0001",
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
        self.assertIn("Search", result["createdTabs"])
        self.assertIn("Aktuell", result["createdTabs"])
        self.assertNotIn("Derivative Tips", result["createdTabs"])
        self.assertEqual(result["headerRowsWritten"], len(result["tabs"]))
        batch_body = sheets.spreadsheets_resource.batch_update_requests[0]["body"]
        self.assertIn(
            {"addSheet": {"properties": {"title": "Search"}}},
            batch_body["requests"],
        )
        self.assertIn(
            {"addSheet": {"properties": {"title": "Aktuell"}}},
            batch_body["requests"],
        )
        values_body = sheets.spreadsheets_resource.values_resource.batch_update_requests[0]["body"]
        self.assertEqual(values_body["valueInputOption"], "USER_ENTERED")
        self.assertIn(
            {
                "range": "'Search'!A1:A1",
                "values": [["Search company or WKN"]],
            },
            values_body["data"],
        )
        self.assertIn(
            {
                "range": "'Search'!A2",
                "values": [[
                    "Searches issue tabs only. Aktuell is excluded to avoid duplicate current-issue results."
                ]],
            },
            values_body["data"],
        )
        self.assertNotIn("'Stocks'!A1:T1", str(values_body["data"]))
        search_tab = next(tab for tab in result["tabs"] if tab["title"] == "Search")
        self.assertEqual(search_tab["headerRow"], 1)
        self.assertEqual(search_tab["frozenRows"], 0)
        self.assertEqual(search_tab["frozenColumns"], 0)
        self.assertEqual(search_tab["tableStartsAt"], "A1")
        self.assertEqual(search_tab["parserStatus"], "layout_only")
        self.assertIn(
            "Source is the first result column for both stock and derivative matches.",
            search_tab["layoutNotes"],
        )
        self.assertEqual(search_tab["metadataCells"][0]["cell"], "A2")
        tab_status = {tab["title"]: tab["parserStatus"] for tab in result["tabs"]}
        self.assertEqual(set(tab_status), {"Search", "Aktuell"})
        self.assertEqual(tab_status["Search"], "layout_only")
        self.assertEqual(tab_status["Aktuell"], "parser_backed")
        headers_by_tab = {tab["title"]: tab["headers"] for tab in result["tabs"]}
        self.assertEqual(headers_by_tab["Search"], ["Search company or WKN"])
        self.assertEqual(headers_by_tab["Aktuell"][0], "WKN")
        self.assertEqual(headers_by_tab["Aktuell"][3], "Price at Print")
        for tab in result["tabs"]:
            if tab["title"] == "Search":
                self.assertEqual(tab["frozenRows"], 0)
            else:
                self.assertGreaterEqual(tab["frozenRows"], 1)
            self.assertIn("layoutNotes", tab)
            self.assertTrue(tab["tableStartsAt"])

    def test_google_sheet_bootstrap_renames_latest_issue_to_aktuell_without_data_loss(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            credentials_path = Path(temp_dir) / "service-account.json"
            credentials_path.write_text(TEST_SERVICE_ACCOUNT_CREDENTIALS, encoding="utf-8")
            config = load_google_access_config(
                env={
                    "GOOGLE_DRIVE_FOLDER_ID": "synthetic-drive-folder-id-0001",
                    "GOOGLE_SHEETS_SPREADSHEET_ID": "synthetic-spreadsheet-id-0001",
                    "GOOGLE_APPLICATION_CREDENTIALS": str(credentials_path),
                }
            )
            sheets = _FakeSheets(
                {
                    "spreadsheetId": config.sheets_spreadsheet_id,
                    "sheets": [
                        {"properties": {"sheetId": 10, "title": "Navigation Dashboard"}},
                        {"properties": {"sheetId": 20, "title": "Latest Issue"}},
                        {"properties": {"sheetId": 30, "title": "Stocks"}},
                    ],
                }
            )

            result = bootstrap_google_sheet(config, sheets_service_factory=lambda: sheets)

        self.assertNotIn("Aktuell", result["createdTabs"])
        self.assertEqual(result["renamedTabs"], [{"from": "Latest Issue", "to": "Aktuell"}])
        rename_request = sheets.spreadsheets_resource.batch_update_requests[0]["body"]["requests"][0]
        self.assertEqual(
            rename_request,
            {
                "updateSheetProperties": {
                    "properties": {"sheetId": 20, "title": "Aktuell", "index": 1},
                    "fields": "title,index",
                }
            },
        )
        self.assertEqual(
            [item["properties"]["title"] for item in sheets.spreadsheets_resource.payload["sheets"]],
            ["Search", "Aktuell"],
        )

    def test_google_sheet_bootstrap_moves_aktuell_to_first_when_search_is_not_requested(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            credentials_path = Path(temp_dir) / "service-account.json"
            credentials_path.write_text(TEST_SERVICE_ACCOUNT_CREDENTIALS, encoding="utf-8")
            config = load_google_access_config(
                env={
                    "GOOGLE_DRIVE_FOLDER_ID": "synthetic-drive-folder-id-0001",
                    "GOOGLE_SHEETS_SPREADSHEET_ID": "synthetic-spreadsheet-id-0001",
                    "GOOGLE_APPLICATION_CREDENTIALS": str(credentials_path),
                }
            )
            sheets = _FakeSheets(
                {
                    "spreadsheetId": config.sheets_spreadsheet_id,
                    "sheets": [
                        {"properties": {"sheetId": 10, "title": "Navigation Dashboard"}},
                        {"properties": {"sheetId": 20, "title": "Stocks"}},
                        {"properties": {"sheetId": 30, "title": "Aktuell"}},
                    ],
                }
            )

            bootstrap_google_sheet(
                config,
                sheets_service_factory=lambda: sheets,
                tab_specs=(),
                write_headers=False,
                prune_extra_tabs=False,
            )

        self.assertEqual(
            sheets.spreadsheets_resource.batch_update_requests[0]["body"]["requests"],
            [
                        {
                            "updateSheetProperties": {
                                "properties": {"sheetId": 30, "index": 0},
                                "fields": "index",
                            }
                }
            ],
        )
        self.assertEqual(
            [item["properties"]["title"] for item in sheets.spreadsheets_resource.payload["sheets"]],
            ["Aktuell", "Navigation Dashboard", "Stocks"],
        )

    def test_google_sheet_bootstrap_can_skip_header_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            credentials_path = Path(temp_dir) / "service-account.json"
            credentials_path.write_text(TEST_SERVICE_ACCOUNT_CREDENTIALS, encoding="utf-8")
            config = load_google_access_config(
                env={
                    "GOOGLE_DRIVE_FOLDER_ID": "synthetic-drive-folder-id-0001",
                    "GOOGLE_SHEETS_SPREADSHEET_ID": "synthetic-spreadsheet-id-0001",
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
            credentials_path.write_text(TEST_SERVICE_ACCOUNT_CREDENTIALS, encoding="utf-8")
            config = load_google_access_config(
                env={
                    "GOOGLE_DRIVE_FOLDER_ID": "synthetic-drive-folder-id-0001",
                    "GOOGLE_SHEETS_SPREADSHEET_ID": "synthetic-spreadsheet-id-0001",
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
        self.assertEqual(result["deletedTabCount"], 3)
        self.assertIn({"sheetId": 10}, delete_requests)
        self.assertIn({"sheetId": 20}, delete_requests)
        self.assertIn({"sheetId": 40}, delete_requests)
        self.assertNotIn({"sheetId": 30}, delete_requests)

    def test_google_sheet_bootstrap_replaces_generated_conditional_format_rules(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            credentials_path = Path(temp_dir) / "service-account.json"
            credentials_path.write_text(TEST_SERVICE_ACCOUNT_CREDENTIALS, encoding="utf-8")
            config = load_google_access_config(
                env={
                    "GOOGLE_DRIVE_FOLDER_ID": "synthetic-drive-folder-id-0001",
                    "GOOGLE_SHEETS_SPREADSHEET_ID": "synthetic-spreadsheet-id-0001",
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
                tab_specs=DEFAULT_SHEET_TABS,
                write_headers=False,
            )

        delete_requests = [
            request["deleteConditionalFormatRule"]
            for batch in sheets.spreadsheets_resource.batch_update_requests
            for request in batch["body"]["requests"]
            if "deleteConditionalFormatRule" in request
        ]
        add_requests = [
            request["addConditionalFormatRule"]
            for batch in sheets.spreadsheets_resource.batch_update_requests
            for request in batch["body"]["requests"]
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
            credentials_path.write_text(TEST_SERVICE_ACCOUNT_CREDENTIALS, encoding="utf-8")
            config = load_google_access_config(
                env={
                    "GOOGLE_DRIVE_FOLDER_ID": "synthetic-drive-folder-id-0001",
                    "GOOGLE_SHEETS_SPREADSHEET_ID": "synthetic-spreadsheet-id-0001",
                    "GOOGLE_APPLICATION_CREDENTIALS": str(credentials_path),
                }
            )
            sheets = _FakeSheets(
                {
                    "spreadsheetId": config.sheets_spreadsheet_id,
                    "sheets": [{"properties": {"sheetId": 30, "title": "Stocks"}}],
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
        self.assertNotIn("'Stocks'!A2:T", clear_ranges)
        self.assertIn("'Aktuell'!A2:P", clear_ranges)
        self.assertNotIn("'Search'!A2:A", clear_ranges)
        self.assertGreater(len(values_resource.batch_update_requests), 0)

    def test_google_sheet_export_omits_retired_canonical_tabs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            credentials_path = Path(temp_dir) / "service-account.json"
            credentials_path.write_text(TEST_SERVICE_ACCOUNT_CREDENTIALS, encoding="utf-8")
            config = load_google_access_config(
                env={
                    "GOOGLE_DRIVE_FOLDER_ID": "synthetic-drive-folder-id-0001",
                    "GOOGLE_SHEETS_SPREADSHEET_ID": "synthetic-spreadsheet-id-0001",
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
        data_ranges = next(
            request["body"]["data"]
            for request in values_resource.batch_update_requests
            if request["body"].get("valueInputOption") == "RAW"
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["enrichmentProviderCalls"], 0)
        self.assertEqual(result["exportMode"], "private_draft_review_export")
        self.assertFalse(result["familyVisibleSafe"])
        self.assertTrue(result["privateDraftReviewOnly"])
        self.assertEqual(result["rowsWritten"], 0)
        self.assertEqual(result["rowsOmittedFromCleanSheet"], 2)
        self.assertNotIn("Stocks", result["clearedTabs"])
        self.assertNotIn("Dividend Focus", result["clearedTabs"])
        self.assertFalse(any(item["range"].startswith("'Stocks'!") for item in data_ranges))
        self.assertFalse(any(item["range"].startswith("'Dividend Focus'!") for item in data_ranges))

    def test_google_sheet_export_writes_before_clearing_stale_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            credentials_path = Path(temp_dir) / "service-account.json"
            credentials_path.write_text(TEST_SERVICE_ACCOUNT_CREDENTIALS, encoding="utf-8")
            config = load_google_access_config(
                env={
                    "GOOGLE_DRIVE_FOLDER_ID": "synthetic-drive-folder-id-0001",
                    "GOOGLE_SHEETS_SPREADSHEET_ID": "synthetic-spreadsheet-id-0001",
                    "GOOGLE_APPLICATION_CREDENTIALS": str(credentials_path),
                }
            )
            sheets = _FakeSheets(
                {
                    "spreadsheetId": config.sheets_spreadsheet_id,
                    "sheets": [{"properties": {"sheetId": 30, "title": "Stocks"}}],
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

            with self.assertRaisesRegex(
                GoogleAccessError,
                "workbook row export failed during writing workbook values",
            ):
                write_workbook_plan_to_google_sheet(
                    config,
                    workbook_plan,
                    sheets_service_factory=lambda: sheets,
                    allow_draft_rows=True,
                )

        self.assertEqual(values_resource.clear_requests, [])

    def test_google_sheet_export_does_not_recreate_stocks_tab_for_follow_up_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            credentials_path = Path(temp_dir) / "service-account.json"
            credentials_path.write_text(TEST_SERVICE_ACCOUNT_CREDENTIALS, encoding="utf-8")
            config = load_google_access_config(
                env={
                    "GOOGLE_DRIVE_FOLDER_ID": "synthetic-drive-folder-id-0001",
                    "GOOGLE_SHEETS_SPREADSHEET_ID": "synthetic-spreadsheet-id-0001",
                    "GOOGLE_APPLICATION_CREDENTIALS": str(credentials_path),
                }
            )
            sheets = _FakeSheets(
                {
                    "spreadsheetId": config.sheets_spreadsheet_id,
                    "sheets": [{"properties": {"sheetId": 30, "title": "Stocks"}}],
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

        self.assertTrue(result["ok"])
        self.assertEqual(result["rowsWritten"], 0)
        self.assertEqual(result["rowsOmittedFromCleanSheet"], 1)
        self.assertNotIn(
            "Stocks",
            [
                item["properties"]["title"]
                for item in sheets.spreadsheets_resource.payload["sheets"]
            ],
        )

    def test_google_sheet_export_rejects_short_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            credentials_path = Path(temp_dir) / "service-account.json"
            credentials_path.write_text(TEST_SERVICE_ACCOUNT_CREDENTIALS, encoding="utf-8")
            config = load_google_access_config(
                env={
                    "GOOGLE_DRIVE_FOLDER_ID": "synthetic-drive-folder-id-0001",
                    "GOOGLE_SHEETS_SPREADSHEET_ID": "synthetic-spreadsheet-id-0001",
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
            credentials_path.write_text(TEST_SERVICE_ACCOUNT_CREDENTIALS, encoding="utf-8")
            config = load_google_access_config(
                env={
                    "GOOGLE_DRIVE_FOLDER_ID": "synthetic-drive-folder-id-0001",
                    "GOOGLE_SHEETS_SPREADSHEET_ID": "synthetic-spreadsheet-id-0001",
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
            credentials_path.write_text(TEST_SERVICE_ACCOUNT_CREDENTIALS, encoding="utf-8")
            config = load_google_access_config(
                env={
                    "GOOGLE_DRIVE_FOLDER_ID": "synthetic-drive-folder-id-0001",
                    "GOOGLE_SHEETS_SPREADSHEET_ID": "synthetic-spreadsheet-id-0001",
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
            credentials_path.write_text(TEST_SERVICE_ACCOUNT_CREDENTIALS, encoding="utf-8")
            config = load_google_access_config(
                env={
                    "GOOGLE_DRIVE_FOLDER_ID": "synthetic-drive-folder-id-0001",
                    "GOOGLE_SHEETS_SPREADSHEET_ID": "synthetic-spreadsheet-id-0001",
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
        self.assertEqual(result["rowsWritten"], 0)
        self.assertEqual(result["rowsOmittedFromCleanSheet"], 1)
        self.assertNotEqual(result["spreadsheetId"], config.sheets_spreadsheet_id)
        self.assertNotIn(config.sheets_spreadsheet_id, str(result))

    def test_google_sheet_export_rejects_invalid_approval_evidence_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            credentials_path = Path(temp_dir) / "service-account.json"
            credentials_path.write_text(TEST_SERVICE_ACCOUNT_CREDENTIALS, encoding="utf-8")
            config = load_google_access_config(
                env={
                    "GOOGLE_DRIVE_FOLDER_ID": "synthetic-drive-folder-id-0001",
                    "GOOGLE_SHEETS_SPREADSHEET_ID": "synthetic-spreadsheet-id-0001",
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
            credentials_path.write_text(TEST_SERVICE_ACCOUNT_CREDENTIALS, encoding="utf-8")
            config = load_google_access_config(
                env={
                    "GOOGLE_DRIVE_FOLDER_ID": "synthetic-drive-folder-id-0001",
                    "GOOGLE_SHEETS_SPREADSHEET_ID": "synthetic-spreadsheet-id-0001",
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
            credentials_path.write_text(TEST_SERVICE_ACCOUNT_CREDENTIALS, encoding="utf-8")
            config = load_google_access_config(
                env={
                    "GOOGLE_DRIVE_FOLDER_ID": "synthetic-drive-folder-id-0001",
                    "GOOGLE_SHEETS_SPREADSHEET_ID": "synthetic-spreadsheet-id-0001",
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
