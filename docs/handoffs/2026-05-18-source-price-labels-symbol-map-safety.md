# 2026-05-18 Source Price Labels And Symbol Map Safety

## Slice

Tightened workbook price provenance after the stock price/as-of split by making
source-tab price labels explicit and blocking unsafe enrichment candidate
planning from source-specific tabs.

## Completed Work

- Renamed source-tab printed price headers to `Magazine` labels in active tabs:
  `Derivative Tips`, `AKTIONAER Depot`, `Depot Transactions`, `Chart Check`,
  `Stock Quickcheck`, and `Dividend Focus`.
- Also renamed inactive traceability headers in `Reviewed Magazine Mentions`
  and `Recommendation Cards` from current-price wording to `Magazine Price`.
- Replaced stale positional `WORKBOOK_INSTRUMENT_TABS` enrichment planning with
  header-derived `Stocks` candidate locations only.
- Source-specific tabs such as `Dividend Focus` and `Derivative Tips` are now
  ignored by market symbol-map template generation and enrichment candidate
  planning until their provider-symbol semantics are deliberately designed.
- Added exact-width validation for `Stocks` enrichment candidate rows and for
  Google workbook-plan write rows, so stale short rows fail instead of being
  padded or truncated.

## Validation

- `PYTHONPATH=src python3 -m unittest tests.test_market_data tests.test_google_access`
  passed.
- `scripts/stock-analyst test` passed.
- `scripts/stock-analyst compile` passed.
- No enrichment provider calls were made.
- No Google writes were made.

## Residual Risks

- This slice intentionally limits enrichment candidates to `Stocks`. Dividend
  focus rows that do not surface into `Stocks` will not produce provider-symbol
  lookup rows yet.
- Dedicated derivative enrichment still needs a separate design because
  derivative WKNs, underlyings, and provider symbols are not interchangeable.

## Next Slice

- Consider adding workbook schema validation earlier in local export-plan
  construction so row-width drift is caught before Google export planning.
