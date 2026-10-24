"""Provider-free delivery verification, including deliberate live-state damage."""

import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from stock_analyst import cli, google_access as ga
from stock_analyst.workbook_verification import verify_google_sheet_workbook


def _fixture():
    stock_headers = list(next(spec.headers for spec in ga.ACTIVE_GOOGLE_SHEET_TABS if spec.title == "Aktuell"))
    stock = [""] * len(stock_headers)
    for header, value in {
        "WKN": "SYN001", "Company": "SYNTHETIC PRIVATE COMPANY", "Action": "Buy",
        "Source": "2026-W44:12", "Review status": "needs_review",
    }.items():
        stock[stock_headers.index(header)] = value
    plan = {"issueId": "2026-W44", "rows": [{"tab": "Aktuell", "rowKind": "stock_recommendation", "values": stock}]}
    # Explicit stacked-table layout, independent of the verifier projection.
    issue = [stock_headers, stock, [], [], ["Derivatives"], list(ga.AKTUELL_DERIVATIVE_HEADERS)]
    old = copy.deepcopy(issue)
    old[1][stock_headers.index("Source")] = "2026-W43:9"
    ledger_headers = list(next(spec.headers for spec in ga.ACTIVE_GOOGLE_SHEET_TABS if spec.title == "Insider Activity"))
    insider = ["SYNTHETIC PRIVATE COMPANY", "SYN001", "SYN", "SYNTHETIC PRIVATE PERSON", "Director", "120", "2026-10-23", "purchase", "Acquired", "20", "2.00", "40.00"]
    ledger = [[value] for _cell, value in ga.INSIDER_ACTIVITY_INSTRUCTIONS] + [ledger_headers, insider]
    ledger_formulas = copy.deepcopy(ledger)
    ledger_formulas[3][0] = '=HYPERLINK("https://www.sec.gov/Archives/edgar/data/1/filing.xml#transaction-1","SYNTHETIC PRIVATE COMPANY")'
    titles = ["Search", "Aktuell", "Insider Activity", "DA_2026_44", "DA_2026_43"]
    sheets = []
    ids = {title: index + 1 for index, title in enumerate(titles)}
    for index, title in enumerate(titles):
        sheet_id = ids[title]
        grid = {"rowCount": 100, "columnCount": 16, "frozenRowCount": 1, "frozenColumnCount": 3}
        if title == "Search":
            grid.update(columnCount=43, frozenRowCount=0, frozenColumnCount=0)
        if title == "Insider Activity":
            grid.update(columnCount=12, frozenRowCount=3)
        protection = {
            "range": {"sheetId": sheet_id}, "warningOnly": False,
            "editors": {"users": ["synthetic@example.test"]},
        }
        sheet = {"properties": {"title": title, "sheetId": sheet_id, "index": index, "gridProperties": grid}, "protectedRanges": [protection]}
        if title == "Search":
            input_range = {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1, "startColumnIndex": 2, "endColumnIndex": 5}
            protection["unprotectedRanges"] = [input_range]
            sheet["merges"] = [input_range]
        if title == "Insider Activity":
            filter_range = {"sheetId": sheet_id, "startRowIndex": 2, "endRowIndex": 4, "startColumnIndex": 0, "endColumnIndex": 12}
            sheet["basicFilter"] = {"range": filter_range}
            sheet["merges"] = [{"sheetId": sheet_id, "startRowIndex": row, "endRowIndex": row + 1, "startColumnIndex": 0, "endColumnIndex": 3} for row in (0, 1)]
            sheet["filterViews"] = list(ga._managed_insider_filter_view_specs(sheet_id=sheet_id, data_row_count=1))
            sheet["conditionalFormats"] = [{
                "ranges": [{"sheetId": sheet_id, "startRowIndex": 3, "endRowIndex": 100, "startColumnIndex": 0, "endColumnIndex": 12}],
                "booleanRule": {"condition": {"type": "CUSTOM_FORMULA", "values": [{"userEnteredValue": f'=$I4="{direction}"'}]}, "format": {"backgroundColor": color}},
            } for direction, color in ga.INSIDER_DIRECTION_FORMATS]
        sheets.append(sheet)
    source = {"DA_2026_44": issue, "DA_2026_43": old}
    index = [list(ga.SEARCH_INDEX_HEADERS), *ga._build_issue_search_index_rows(issue_tab_values_by_title=source, sheet_ids_by_title=ids, insider_activity_values=ledger)]
    formatted = {f"'{title}'!A:P": rows for title, rows in source.items()}
    formatted.update({"'Insider Activity'!A:L": ledger, "'Search'!U:AQ": index})
    formula = {f"'{title}'!A:P": rows for title, rows in {**source, "Aktuell": issue}.items()}
    formula.update({"'Insider Activity'!A:L": ledger_formulas, "'Search'!A4": [[ga._build_issue_search_results_formula()]]})
    return plan, {"sheets": sheets}, formatted, formula


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        return copy.deepcopy(self.payload)


class _ReadOnlySheets:
    """No mutation methods exist: any attempted write fails the test."""

    def __init__(self, metadata, formatted, formula):
        self.metadata = metadata
        self.formatted = formatted
        self.formula = formula
        self.reads = []

    def spreadsheets(self):
        return self

    def values(self):
        return self

    def get(self, **request):
        self.reads.append(("get", request))
        return _Response(self.metadata)

    def batchGet(self, **request):
        self.reads.append(("batchGet", request))
        data = self.formula if request["valueRenderOption"] == "FORMULA" else self.formatted
        return _Response({"valueRanges": [{"values": data[range_name]} for range_name in request["ranges"]]})


class WorkbookVerificationTests(unittest.TestCase):
    def setUp(self):
        self.plan, self.metadata, self.formatted, self.formula = _fixture()
        self.config = ga.GoogleAccessConfig("synthetic-drive-id", "SYNTHETIC-PRIVATE-SHEET-ID", Path("synthetic-credentials"), "synthetic@example.test")
        self.api = _ReadOnlySheets(self.metadata, self.formatted, self.formula)

    def verify(self, **kwargs):
        return verify_google_sheet_workbook(self.config, self.plan, sheets_service_factory=lambda: self.api, **kwargs)

    def test_exact_publication_with_rendered_company_search_and_formula_link(self):
        result = self.verify(expected_ledger_rows=1)
        self.assertEqual(result["status"], "verified", result)
        self.assertEqual(result["counts"]["ledgerHyperlinks"], 1)
        self.assertEqual(result["counts"]["searchExpectedRows"], 3)
        self.assertEqual(len(self.api.reads), 3)
        self.assertFalse(result["secReplayVerified"])
        self.assertFalse(result["sourceCompletenessVerified"])
        self.assertFalse(result["approvalVerified"])
        self.assertFalse(result["manualStatePreservationVerified"])
        output = json.dumps(result)
        for private in ("PRIVATE", "2026-W44", "DA_2026_44", "synthetic@example.test", "filing.xml"):
            self.assertNotIn(private, output)

    def test_missing_or_duplicate_search_rows_fail(self):
        pristine = copy.deepcopy(self.formatted["'Search'!U:AQ"])
        for damaged in (pristine[:-1], pristine + [pristine[1]]):
            with self.subTest(rows=len(damaged)):
                self.formatted["'Search'!U:AQ"] = damaged
                result = self.verify()
                self.assertFalse(result["ok"])
                self.assertFalse(result["checks"]["searchIndexCoversAllIssueAndLedgerRows"])

    def test_stale_issue_tail_or_changed_literal_fails(self):
        for damaged in (self.formula["'DA_2026_44'!A:P"] + [["STALE PRIVATE VALUE"]], [["PRIVATE INCORRECT HEADER"]]):
            with self.subTest(rows=len(damaged)):
                self.formula["'DA_2026_44'!A:P"] = damaged
                result = self.verify()
                self.assertFalse(result["checks"]["issuePlanLiteralProjectionCorrect"])
                self.assertNotIn("PRIVATE", json.dumps(result))

    def test_historic_issue_does_not_require_aktuell_to_equal_older_plan(self):
        self.plan["issueId"] = "2026-W43"
        self.plan["rows"][0]["values"][13] = "2026-W43:9"
        # Fixture shares the selected source and Aktuell list; isolate the
        # latest values from the independently retained older plan.
        self.formula["'DA_2026_44'!A:P"] = copy.deepcopy(self.formula["'DA_2026_44'!A:P"])
        self.formula["'DA_2026_44'!A:P"][1][13] = "2026-W44:12"
        self.formula["'Aktuell'!A:P"] = self.formula["'DA_2026_44'!A:P"]
        self.formatted["'DA_2026_44'!A:P"] = self.formula["'DA_2026_44'!A:P"]
        result = self.verify()
        self.assertTrue(result["ok"], result)
        self.assertFalse(result["selectedIssueIsLatest"])
        self.assertNotIn("aktuellPlanLiteralProjectionCorrect", result["checks"])

    def test_aktuell_duplication_in_search_fails_even_if_rows_are_valid(self):
        self.formatted["'Search'!U:AQ"].append(copy.deepcopy(self.formatted["'Search'!U:AQ"][1]))
        self.assertFalse(self.verify()["checks"]["searchIndexCoversAllIssueAndLedgerRows"])

    def test_broken_search_formula_and_blocked_query_field_fail(self):
        self.formula["'Search'!A4"] = [["#REF!"]]
        search = self.metadata["sheets"][0]
        search["protectedRanges"].append({"range": {"sheetId": 1, "startColumnIndex": 2}})
        result = self.verify()
        self.assertFalse(result["checks"]["searchFormulaCurrent"])
        self.assertFalse(result["checks"]["searchInputEditableOnly"])

    def test_absent_link_wrong_count_and_weakened_protection_fail(self):
        self.formula["'Insider Activity'!A:L"][3][0] = "SYNTHETIC PRIVATE COMPANY"
        self.metadata["sheets"][3]["protectedRanges"][0]["warningOnly"] = True
        result = self.verify(expected_ledger_rows=2)
        self.assertFalse(result["checks"]["ledgerAllRowsHaveFilingLinks"])
        self.assertFalse(result["checks"]["ledgerExpectedRowCountMatches"])
        self.assertFalse(result["checks"]["allManagedTabsProtected"])

    def test_ledger_layout_damage_is_reported(self):
        ledger = self.metadata["sheets"][2]
        ledger["conditionalFormats"][0]["booleanRule"]["format"]["backgroundColor"] = {"red": 0, "green": 0, "blue": 0}
        ledger["filterViews"][1]["range"]["endRowIndex"] = 3
        ledger["merges"] = []
        result = self.verify()
        self.assertFalse(result["ok"])
        for check in ("ledgerDirectionRulesCorrect", "ledgerManagedFilterViewsCorrect", "ledgerBannerMergesCorrect"):
            self.assertFalse(result["checks"][check])

    def test_equivalent_lower_priority_direction_rules_do_not_block_verification(self):
        ledger = self.metadata["sheets"][2]
        ledger["conditionalFormats"] = [copy.deepcopy(rule) for _ in range(54) for rule in ledger["conditionalFormats"]]
        result = self.verify()
        self.assertTrue(result["checks"]["ledgerDirectionRulesCorrect"])
        self.assertTrue(result["checks"]["ledgerDirectionRulesHighestPriority"])
        self.assertTrue(result["ok"], result)

    def test_effective_direction_format_cannot_be_masked_by_later_correct_rule(self):
        ledger = self.metadata["sheets"][2]
        ledger["conditionalFormats"] = [copy.deepcopy(rule) for _ in range(2) for rule in ledger["conditionalFormats"]]
        ledger["conditionalFormats"][0]["booleanRule"]["format"]["backgroundColor"] = {"red": 0, "green": 0, "blue": 0}
        result = self.verify()
        self.assertFalse(result["checks"]["ledgerDirectionRulesCorrect"])
        self.assertFalse(result["ok"])

    def test_lower_priority_direction_format_does_not_override_effective_rule(self):
        ledger = self.metadata["sheets"][2]
        ledger["conditionalFormats"] = [copy.deepcopy(rule) for _ in range(2) for rule in ledger["conditionalFormats"]]
        ledger["conditionalFormats"][2]["booleanRule"]["format"]["backgroundColor"] = {"red": 0, "green": 0, "blue": 0}
        result = self.verify()
        self.assertTrue(result["checks"]["ledgerDirectionRulesCorrect"])
        self.assertTrue(result["ok"], result)

    def test_every_required_reviewer_tab_must_be_visible(self):
        for sheet in self.metadata["sheets"]:
            with self.subTest(tab=sheet["properties"]["title"]):
                sheet["properties"]["hidden"] = True
                result = self.verify()
                self.assertFalse(result["checks"]["requiredReviewerTabsVisible"])
                self.assertFalse(result["ok"])
                sheet["properties"]["hidden"] = False

    def test_hidden_ledger_column_blocks_review(self):
        self.metadata["sheets"][2]["data"] = [{"startColumn": 3, "columnMetadata": [{"hiddenByUser": True}]}]
        result = self.verify()
        self.assertFalse(result["checks"]["ledgerColumnsVisible"])
        self.assertFalse(result["ok"])

    def test_code_and_direction_are_independent_source_values(self):
        self.formula["'Insider Activity'!A:L"][3][8] = "Disposed"
        self.formatted["'Insider Activity'!A:L"][3][8] = "Disposed"
        self.formatted["'Search'!U:AQ"][-1][12] = "Disposed"
        result = self.verify()
        self.assertTrue(result["checks"]["ledgerTransactionLabelsCorrect"])
        self.assertTrue(result["ok"], result)

    def test_same_count_changed_ledger_between_read_renders_fails(self):
        self.formatted["'Insider Activity'!A:L"][3][3] = "SYNTHETIC DIFFERENT PRIVATE PERSON"
        result = self.verify()
        self.assertFalse(result["checks"]["ledgerLiteralAndRenderedValuesMatch"])
        self.assertFalse(result["ok"])

    def test_reviewer_hidden_column_and_misordered_issues_fail(self):
        self.metadata["sheets"][1]["data"] = [{"startColumn": 1, "columnMetadata": [{"hiddenByUser": True}]}]
        self.metadata["sheets"][3]["properties"]["index"] = 5
        result = self.verify()
        self.assertFalse(result["checks"]["reviewerColumnsVisible"])
        self.assertFalse(result["checks"]["managedTabOrderCorrect"])

    def test_missing_tab_and_partial_get_fail_closed(self):
        self.metadata["sheets"].pop(2)
        self.assertFalse(self.verify()["checks"]["requiredTabsPresent"])
        self.metadata["sheets"].insert(2, _fixture()[1]["sheets"][2])
        self.api.batchGet = lambda **request: _Response({"valueRanges": []})
        result = self.verify()
        self.assertEqual(result["reason"], "verification_read_failed")
        self.assertFalse(result["ok"])

    def test_private_provider_and_input_errors_are_redacted(self):
        self.api.get = Mock(side_effect=RuntimeError("PRIVATE SHEET-ID company insider secret"))
        result = self.verify()
        self.assertNotIn("PRIVATE", json.dumps(result))
        self.assertEqual(result["status"], "incomplete")
        self.plan["issueId"] = "PRIVATE-INVALID-ID"
        result = self.verify()
        self.assertEqual(result["reason"], "invalid_verification_input")
        self.assertNotIn("PRIVATE", json.dumps(result))

    def test_readonly_client_requests_only_readonly_scope(self):
        from stock_analyst.workbook_verification import _readonly_sheets_service, GOOGLE_SHEETS_READONLY_SCOPE

        credentials = Mock()
        service_account = SimpleNamespace(Credentials=SimpleNamespace(from_service_account_file=credentials))
        discovery = SimpleNamespace(build=Mock())
        with patch.dict("sys.modules", {
            "google": SimpleNamespace(oauth2=SimpleNamespace(service_account=service_account)),
            "google.oauth2": SimpleNamespace(service_account=service_account),
            "google.oauth2.service_account": service_account,
            "googleapiclient": SimpleNamespace(discovery=discovery),
            "googleapiclient.discovery": discovery,
        }):
            _readonly_sheets_service(self.config)
        self.assertEqual(credentials.call_args.kwargs["scopes"], [GOOGLE_SHEETS_READONLY_SCOPE])

    def test_cli_incomplete_returns_nonzero_and_never_echoes_private_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "PRIVATE-MISSING-PLAN.json"
            output = io.StringIO()
            with redirect_stdout(output):
                code = cli.main(["google-sheets-verify-plan", str(missing)])
        self.assertEqual(code, 1)
        self.assertNotIn("PRIVATE", output.getvalue())
        self.assertEqual(json.loads(output.getvalue())["status"], "incomplete")


if __name__ == "__main__":
    unittest.main()
