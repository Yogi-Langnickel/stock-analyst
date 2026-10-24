"""Read-only, aggregate-only verification of the private reviewer workbook.

This checks delivery against a retained extraction plan and the live workbook.
It does not establish source completeness, reviewer approval, or SEC cache replay.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from stock_analyst import google_access as ga


GOOGLE_SHEETS_READONLY_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"


def _readonly_sheets_service(config: ga.GoogleAccessConfig):
    # Verification never needs Drive access or a token with Sheets write scope.
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    credentials = service_account.Credentials.from_service_account_file(
        str(config.credentials_path), scopes=[GOOGLE_SHEETS_READONLY_SCOPE]
    )
    return build("sheets", "v4", credentials=credentials, cache_discovery=False)


def _canonical_grid(rows: Sequence[Sequence[object]]) -> list[list[str]]:
    """Ignore omitted trailing empty cells/rows, but retain all actual values."""

    result: list[list[str]] = []
    for row in rows:
        values = ["" if value is None else str(value) for value in row]
        while values and values[-1] == "":
            values.pop()
        result.append(values)
    while result and not result[-1]:
        result.pop()
    return result


def _expected_issue_grid(workbook_plan: Mapping[str, object]) -> list[list[object]]:
    ga.preflight_workbook_plan_google_sheet_export(workbook_plan, allow_draft_rows=True)
    spec = next(spec for spec in ga.ACTIVE_GOOGLE_SHEET_TABS if spec.title == "Aktuell")
    stock_rows: list[list[str]] = []
    derivative_rows: list[list[str]] = []
    for row in workbook_plan["rows"]:
        if not isinstance(row, Mapping) or row.get("tab") != "Aktuell":
            continue
        values = row.get("values")
        if not isinstance(values, list):
            continue
        row_kind = str(row.get("rowKind") or "")
        if "derivative" in row_kind and len(values) == len(ga.LEGACY_AKTUELL_DERIVATIVE_HEADERS):
            normalized = ga._project_legacy_aktuell_derivative_values(values)
        else:
            width = len(ga.AKTUELL_DERIVATIVE_HEADERS) if "derivative" in row_kind else len(spec.headers)
            normalized = ga._normalize_sheet_row_values(values, width=width)
        (stock_rows if "stock" in row_kind else derivative_rows).append(normalized)
    ranges: list[dict[str, object]] = []
    ga._append_issue_recommendation_table_write_ranges(
        ranges, tab_title="Aktuell", spec=spec,
        stock_rows=stock_rows, derivative_rows=derivative_rows,
    )
    expected: list[list[object]] = []
    for item in ranges:
        match = re.search(r"!A(\d+)", str(item["range"]))
        if match is None:
            raise ValueError("unsupported projection range")
        start = int(match.group(1)) - 1
        for offset, row in enumerate(item["values"]):
            while len(expected) <= start + offset:
                expected.append([])
            expected[start + offset] = row
    return expected


def _read_ranges(api, *, spreadsheet_id: str, ranges: Sequence[str], render: str):
    if not ranges:
        return []
    response = api.values().batchGet(
        spreadsheetId=spreadsheet_id, ranges=list(ranges),
        majorDimension="ROWS", valueRenderOption=render,
    ).execute()
    value_ranges = response.get("valueRanges")
    if not isinstance(value_ranges, list) or len(value_ranges) != len(ranges):
        raise ValueError("incomplete value read")
    rows_by_range = []
    for item in value_ranges:
        rows = item.get("values", [])
        if not isinstance(rows, list) or any(not isinstance(row, list) for row in rows):
            raise ValueError("invalid value read")
        rows_by_range.append(rows)
    return rows_by_range


def _input_range(sheet_id: int) -> dict[str, int]:
    return {
        "sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1,
        "startColumnIndex": 2, "endColumnIndex": 5,
    }


def _visible_columns(sheet: Mapping[str, object], count: int) -> bool:
    for grid in sheet.get("data", []):
        start = grid.get("startColumn", 0)
        for offset, column in enumerate(grid.get("columnMetadata", [])):
            if start + offset < count and column.get("hiddenByUser") is True:
                return False
    return True


def _search_input_editable(sheet: Mapping[str, object]) -> bool:
    sheet_id = sheet["properties"]["sheetId"]
    expected = _input_range(sheet_id)
    # A second manual protection can accidentally cover the otherwise exempt
    # field. Whole-sheet protections must all exempt exactly this field.
    has_whole_sheet = False
    for protection in sheet.get("protectedRanges", []):
        if protection.get("warningOnly") is True:
            continue
        protected = protection.get("range", {})
        if protected == {"sheetId": sheet_id}:
            has_whole_sheet = True
            if protection.get("unprotectedRanges") != [expected]:
                return False
        elif (
            protected.get("sheetId") == sheet_id
            and protected.get("startRowIndex", 0) < 1
            and protected.get("endRowIndex", 1) > 0
            and protected.get("startColumnIndex", 0) < 5
            and protected.get("endColumnIndex", 5) > 2
        ):
            return False
    return has_whole_sheet


def _ledger_presentation_checks(sheet, values, *, data_rows: int) -> dict[str, bool]:
    sheet_id = sheet["properties"]["sheetId"]
    rules = sheet.get("conditionalFormats", [])
    expected_formulas = {f'=$I4="{direction}"' for direction, _color in ga.INSIDER_DIRECTION_FORMATS}
    matched_rules = {}
    first_formulas = []
    for index, rule in enumerate(rules):
        condition = rule.get("booleanRule", {}).get("condition", {})
        formulas = [item.get("userEnteredValue") for item in condition.get("values", [])]
        if index < 2:
            first_formulas.extend(formulas)
        for formula in formulas:
            if formula in expected_formulas:
                # Sheets applies the first matching background format. Historic
                # equivalent rules below it do not change the visible ledger.
                # Validate that effective rule rather than counting duplicates
                # or allowing a later correct rule to mask a broken first one.
                matched_rules.setdefault(formula, rule)
    directions_correct = set(matched_rules) == expected_formulas
    for direction, expected_color in ga.INSIDER_DIRECTION_FORMATS:
        rule = matched_rules.get(f'=$I4="{direction}"', {})
        boolean = rule.get("booleanRule", {})
        color = boolean.get("format", {}).get("backgroundColor", {})
        ranges = rule.get("ranges", [])
        directions_correct = directions_correct and (
            boolean.get("condition", {}).get("type") == "CUSTOM_FORMULA"
            and all(abs(color.get(channel, 0) - value) <= 1 / 255 for channel, value in expected_color.items())
            and bool(ranges)
            and all(
                item.get("sheetId") == sheet_id
                and item.get("startRowIndex", 0) == 3
                and item.get("startColumnIndex", 0) == 0
                and item.get("endColumnIndex") == 12
                and item.get("endRowIndex", data_rows + 3) >= data_rows + 3
                for item in ranges
            )
        )
    actual_views = {
        view.get("title"): view for view in sheet.get("filterViews", [])
        if view.get("title") in ga.MANAGED_INSIDER_FILTER_VIEW_TITLES
    }
    expected_views = ga._managed_insider_filter_view_specs(sheet_id=sheet_id, data_row_count=data_rows)
    return {
        "ledgerBannerValuesCorrect": all(
            len(values) > index and values[index] == [value]
            for index, (_cell, value) in enumerate(ga.INSIDER_ACTIVITY_INSTRUCTIONS)
        ),
        "ledgerBannerMergesCorrect": all({
            "sheetId": sheet_id, "startRowIndex": index, "endRowIndex": index + 1,
            "startColumnIndex": 0, "endColumnIndex": 3,
        } in sheet.get("merges", []) for index in (0, 1)),
        "ledgerDirectionRulesCorrect": directions_correct,
        "ledgerDirectionRulesHighestPriority": len(first_formulas) == 2 and set(first_formulas) == expected_formulas,
        "ledgerManagedFilterViewsCorrect": len(actual_views) == len(expected_views) and all(
            all(actual_views.get(view["title"], {}).get(key, {}) == view.get(key, {}) for key in ("range", "criteria", "sortSpecs"))
            for view in expected_views
        ),
    }


def verify_google_sheet_workbook(
    config: ga.GoogleAccessConfig,
    workbook_plan: Mapping[str, object],
    *,
    expected_ledger_rows: int | None = None,
    sheets_service_factory=None,
) -> dict[str, object]:
    """Return redacted delivery checks using only metadata and values GETs.

    The plan is the private reviewer draft used for the import. All its Aktuell
    rows are expected; approved-family export subsets are outside this command.
    Batch reads avoid one request per historic issue. Any failed/incomplete read
    fails closed without returning provider messages or private values.
    """

    result: dict[str, object] = {
        "ok": False, "status": "incomplete", "readOnly": True,
        "rowContentReturned": False, "privateIdentifiersReturned": False,
        "sourceCompletenessVerified": False, "approvalVerified": False,
        "secReplayVerified": False, "manualStatePreservationVerified": False,
    }
    try:
        if expected_ledger_rows is not None and (
            isinstance(expected_ledger_rows, bool)
            or not isinstance(expected_ledger_rows, int)
            or expected_ledger_rows < 0
        ):
            raise ValueError("invalid expected row count")
        expected = _expected_issue_grid(workbook_plan)
        selected_title = ga._issue_tab_title(str(workbook_plan["issueId"]))
    except Exception:
        result["reason"] = "invalid_verification_input"
        return result

    try:
        api = (sheets_service_factory() if sheets_service_factory else _readonly_sheets_service(config)).spreadsheets()
        metadata = api.get(
            spreadsheetId=config.sheets_spreadsheet_id,
            includeGridData=True,
            fields="sheets(properties,protectedRanges,merges,basicFilter,filterViews,conditionalFormats,data(startColumn,columnMetadata(hiddenByUser)))",
        ).execute()
        sheets = metadata.get("sheets", [])
        by_title = {sheet["properties"]["title"]: sheet for sheet in sheets}
        ids = {title: sheet["properties"]["sheetId"] for title, sheet in by_title.items()}
        issue_titles = ga._issue_tab_titles_newest_first(ids)
        checks: dict[str, bool] = {
            "requiredTabsPresent": all(title in by_title for title in ("Search", "Aktuell", "Insider Activity", selected_title)),
        }
        result["checks"] = checks
        if not checks["requiredTabsPresent"]:
            return result
        managed_titles = ["Search", "Aktuell", "Insider Activity", *issue_titles]
        checks["requiredReviewerTabsVisible"] = all(
            by_title[title]["properties"].get("hidden", False) is False
            for title in managed_titles
        )
        ordered_titles = [sheet["properties"]["title"] for sheet in sorted(sheets, key=lambda sheet: sheet["properties"].get("index", 0))]
        checks["managedTabOrderCorrect"] = [title for title in ordered_titles if title in managed_titles] == managed_titles
        reviewer_sheets = [by_title[title] for title in {selected_title, "Aktuell"}]
        checks["reviewerGridCorrect"] = all(
            sheet["properties"].get("gridProperties", {}).get("columnCount") == 16
            and sheet["properties"].get("gridProperties", {}).get("frozenRowCount") == 1
            and sheet["properties"].get("gridProperties", {}).get("frozenColumnCount") == 3
            for sheet in reviewer_sheets
        )
        checks["reviewerColumnsVisible"] = all(_visible_columns(sheet, 16) for sheet in reviewer_sheets)

        # FORMULA is required both for exact literal projection and filing-link
        # proof; FORMATTED_VALUE matches the Search producer's source reads.
        formula_titles = list(dict.fromkeys((selected_title, "Aktuell", issue_titles[0])))
        formula_ranges = [f"{ga._quote_sheet_title(title)}!A:P" for title in formula_titles]
        formula_ranges.extend(("'Insider Activity'!A:L", "'Search'!A4"))
        formula_values = _read_ranges(api, spreadsheet_id=config.sheets_spreadsheet_id, ranges=formula_ranges, render="FORMULA")
        literal_by_title = dict(zip(formula_titles, formula_values))
        ledger_formulas, search_formula = formula_values[-2:]
        source_ranges = [f"{ga._quote_sheet_title(title)}!A:P" for title in issue_titles]
        source_ranges.extend(("'Insider Activity'!A:L", "'Search'!U:AQ"))
        source_values = _read_ranges(api, spreadsheet_id=config.sheets_spreadsheet_id, ranges=source_ranges, render="FORMATTED_VALUE")
        source_by_title = dict(zip(issue_titles, source_values))
        ledger_values, actual_index = source_values[-2:]
        selected_is_latest = selected_title == issue_titles[0]
        checks["issuePlanLiteralProjectionCorrect"] = _canonical_grid(literal_by_title[selected_title]) == _canonical_grid(expected)
        checks["aktuellMatchesLatestIssue"] = _canonical_grid(literal_by_title["Aktuell"]) == _canonical_grid(literal_by_title[issue_titles[0]])
        if selected_is_latest:
            checks["aktuellPlanLiteralProjectionCorrect"] = _canonical_grid(literal_by_title["Aktuell"]) == _canonical_grid(expected)

        expected_index = [list(ga.SEARCH_INDEX_HEADERS), *ga._build_issue_search_index_rows(
            issue_tab_values_by_title=source_by_title, sheet_ids_by_title=ids,
            insider_activity_values=ledger_values,
        )]
        checks["searchIndexCoversAllIssueAndLedgerRows"] = _canonical_grid(actual_index) == _canonical_grid(expected_index)
        checks["searchFormulaCurrent"] = search_formula == [[ga._build_issue_search_results_formula()]]
        search = by_title["Search"]
        checks["searchInputEditableOnly"] = _search_input_editable(search)
        checks["searchInputMerged"] = _input_range(ids["Search"]) in search.get("merges", [])
        checks["searchHasNoFrozenRows"] = search["properties"].get("gridProperties", {}).get("frozenRowCount", 0) == 0

        ledger_spec = next(spec for spec in ga.ACTIVE_GOOGLE_SHEET_TABS if spec.title == "Insider Activity")
        header_index = ga.INSIDER_ACTIVITY_HEADER_ROW - 1
        checks["ledgerHeadersCorrect"] = len(ledger_formulas) > header_index and ledger_formulas[header_index] == list(ledger_spec.headers)
        rows = _canonical_grid(ledger_formulas[header_index + 1:])
        hyperlinks = [ga._parse_insider_company_formula(row[0]) if row else ("", "") for row in rows]
        hyperlink_count = sum(bool(company and url.startswith("https://www.sec.gov/Archives/")) for company, url in hyperlinks)
        checks["ledgerAllRowsHaveFilingLinks"] = hyperlink_count == len(rows)
        checks["ledgerFilingLinksUnique"] = len({url for _company, url in hyperlinks}) == len(rows)
        rendered_ledger = [
            [ga._parse_insider_company_formula(str(row[0]))[0], *row[1:]] if row else []
            for row in ledger_formulas
        ]
        checks["ledgerLiteralAndRenderedValuesMatch"] = _canonical_grid(rendered_ledger) == _canonical_grid(ledger_values)
        checks["ledgerFormattedAndFormulaRowCountsMatch"] = len(_canonical_grid(ledger_values[header_index + 1:])) == len(rows)
        # SEC transaction code and acquired/disposed direction are independent
        # source fields; unusual combinations must retain their source values.
        checks["ledgerTransactionLabelsCorrect"] = all(
            len(row) >= 9 and row[7] in {"purchase", "sale"}
            and row[8] in {"Acquired", "Disposed"} for row in rows
        )
        ledger_sheet = by_title["Insider Activity"]
        ledger_id = ids["Insider Activity"]
        expected_filter = {
            "sheetId": ledger_id, "startRowIndex": header_index,
            "endRowIndex": header_index + len(rows) + 1,
            "startColumnIndex": 0, "endColumnIndex": len(ledger_spec.headers),
        }
        checks["ledgerFilterCoversAllRows"] = ledger_sheet.get("basicFilter", {}).get("range") == expected_filter
        grid = ledger_sheet["properties"].get("gridProperties", {})
        checks["ledgerGridCorrect"] = grid.get("columnCount") == 12 and grid.get("frozenRowCount") == 3 and grid.get("frozenColumnCount") == 3
        checks["ledgerColumnsVisible"] = _visible_columns(ledger_sheet, 12)
        checks.update(_ledger_presentation_checks(ledger_sheet, ledger_formulas, data_rows=len(rows)))
        if expected_ledger_rows is not None:
            checks["ledgerExpectedRowCountMatches"] = len(rows) == expected_ledger_rows

        editor_email = config.service_account_email or ga._service_account_email_from_credentials(config.credentials_path)
        checks["allManagedTabsProtected"] = all(any(
            ga._managed_protection_is_current(protection, sheet_id=ids[title], title=title, editor_email=editor_email)
            for protection in by_title[title].get("protectedRanges", [])
        ) for title in managed_titles)
        result["counts"] = {
            "issueTabs": len(issue_titles),
            "currentActions": sum(1 for row in workbook_plan["rows"] if isinstance(row, Mapping) and row.get("tab") == "Aktuell" and isinstance(row.get("values"), list)),
            "ledgerRows": len(rows), "ledgerHyperlinks": hyperlink_count,
            "searchExpectedRows": len(expected_index) - 1,
            "searchActualRows": max(0, len(_canonical_grid(actual_index)) - 1),
        }
        result["selectedIssueIsLatest"] = selected_is_latest
        result["ledgerExpectedRowCountProvided"] = expected_ledger_rows is not None
        result["ok"] = all(checks.values())
        result["status"] = "verified" if result["ok"] else "incomplete"
    except Exception:
        # Provider errors can echo IDs, URLs and private cell values. They are
        # deliberately excluded from stdout and exception text.
        result["ok"] = False
        result["status"] = "incomplete"
        result["reason"] = "verification_read_failed"
    return result
