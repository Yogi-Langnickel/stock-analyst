# 2026-05-18 Derivative Overview Alignment Guard

## Slice

Tightened derivative overview extraction so retrospective metrics are applied
only when the base table and retrospective table row counts align exactly.

## Completed Work

- `extract_derivative_overview_rows_from_page_lines` now keeps parsed base rows
  unchanged when the retrospective metrics row count is missing or extra.
- On count mismatch, entry price, current price, performance, target, stop, and
  recommendation remain blank instead of being applied positionally.
- Happy-path extraction still applies metrics when base-row and metrics-row
  counts match.
- Provider-symbol candidate behavior remains limited to exact-width `Stocks`
  rows; no derivative or source-specific tab candidates were added.

## Validation

- `PYTHONPATH=src python3 -m unittest tests.test_derivative_tables` passed.
- `scripts/stock-analyst test` passed.
- `scripts/stock-analyst compile` passed.
- No enrichment provider calls were made.
- No Google writes were made.

## Residual Risks

- The guard prevents positional misalignment, but it does not identify which
  specific retrospective row was skipped or duplicated. Those rows remain
  review-required and should be fixed by better OCR/table extraction later.
- Dedicated derivative enrichment still needs a separate provider-symbol design
  because derivative WKNs, underlyings, and provider symbols are not
  interchangeable.
