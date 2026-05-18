# 2026-05-18 Dividend OCR Line Normalization

## Slice

Added a safe local parser normalization slice for dividend strategy OCR text
where table rows arrive as one collapsed line instead of existing row-major
cells.

## Completed Work

- Added a pure dividend-line helper in `dividend_strategy.py` that expands
  recognizable OCR-collapsed base rows into the strict row-major parser shape.
- The same helper expands OCR-collapsed continuation rows into the existing
  month-first continuation parser shape.
- Kept parsing strict: the helper only expands lines whose month, WKN, price,
  optional numeric valuation cells, percentage yield, payout count, dates, and
  target/stop values already match local parser patterns.
- Normalized no-space OCR currency and percentage tokens to existing display
  style, for example `3,33€` to `3,33 EUR` and `18,6%` to `18,6 %`.
- Rows affected by the OCR line helper are tagged with
  `ocr_line_normalized` in `extractionNotes` and remain `needs_review`.
- Added synthetic OCR-shaped unit tests for inline base rows, continuation
  rows, single-digit day OCR dates, and deleted company-name spacing during
  continuation matching.

## Validation

- `PYTHONPATH=src python3 -m unittest tests.test_dividend_strategy`
- `PYTHONPATH=src python3 -m unittest tests.test_dividend_strategy tests.test_workbook_export`
- `scripts/stock-analyst test`
- `scripts/stock-analyst compile`
- Private local OCR artifact spot check printed only counts/status:
  `dividend_rows=11 complete_rows=11 tagged_rows=11`.

## Boundaries

- No enrichment API calls.
- No Google reads or writes.
- No changes to `market_data.py`, provider config, symbol-map behavior, or
  derivative/dividend provider-symbol design.
- No private OCR text was committed or printed in docs.

## Residual Risks

- The helper does not repair malformed OCR tokens that fail strict parser
  patterns, and it does not infer missing prices, targets, stops, WKNs, or
  percentages.
- Rows tagged `ocr_line_normalized` require manual review before any
  family-visible digest or export.
