# 2026-05-18 Workbook Plan Schema Validation

## Slice

Moved workbook schema validation into local export-plan construction so stale
or inactive-tab rows fail before JSON serialization, Google export planning, or
any Sheets write path.

## Completed Work

- Added `WorkbookExportPlanError` and plan-level validation in
  `WorkbookExportPlan.__post_init__`.
- Enforced that planned rows target active workbook tabs from
  `DEFAULT_SHEET_TABS`.
- Enforced exact row width against the configured tab headers during local plan
  construction.
- Added targeted workbook export tests for stale `Stocks` rows and inactive
  `Recommendation Cards` rows.
- Updated workbook layout docs and agent memory with the local validation
  contract.

## Validation

- `scripts/stock-analyst test tests.test_workbook_export` passed.
- `scripts/stock-analyst test` passed.
- `scripts/stock-analyst compile` passed.
- No enrichment provider calls were made.
- No Google writes were made.

## Residual Risks

- Validation intentionally rejects inactive workbook tabs. If a future parser
  reintroduces a traceability tab such as `Recommendation Cards`, that tab must
  be restored to the active tab set with explicit headers before rows can emit.
- Google write validation still independently checks workbook-plan row widths
  as a defense-in-depth gate for plans produced by older code.

## Next Slice

- Derivative/dividend-specific enrichment provider-symbol design remains open.
- Derivative overview alignment guard remains open.
- Dividend OCR line normalizer remains open.
