# 2026-05-18 Price As-Of Semantics

## Slice

Separated magazine-source stock prices from the future enrichment current-price
slot in the `Stocks` workbook tab.

## Completed Work

- Added `Magazine Price` and `Magazine Price As Of` columns after
  `Current Price*` in the `Stocks` tab schema.
- Kept `Current Price*` blank for local magazine-only stock rows from
  recommendation cards, Quick Check summaries, and Chart Check summaries.
- Routed printed source prices into `Magazine Price`; kept
  `Price at Recommendation` for printed recommendation prices where available.
- Updated stock-row consolidation indexes so latest magazine price/as-of,
  targets, stops, chart fields, comments, issue, page, and date fields still
  merge correctly after the schema expansion.
- Updated Google bootstrap/clear/export tests and workbook row tests for the
  24-column stock schema.
- Updated `docs/google-sheets-layout.md` and `docs/agent-memory.md` with the
  new stock price contract.

## Validation

- `scripts/stock-analyst test` passed.
- `scripts/stock-analyst compile` passed.
- No enrichment provider calls were made.
- No Google writes were made.

## Residual Risks

- The slice only changes the active `Stocks` dashboard semantics. Dedicated
  traceability tabs such as `Chart Check`, `Stock Quickcheck`, `Dividend Focus`,
  `Derivative Tips`, and `AKTIONAER Depot` still use their printed source
  price labels because they are source-specific review surfaces.
- `Magazine Price As Of` currently uses the stock row update date already
  resolved by workbook export, preferring explicit import/issue dates where
  available. If a future parser captures a more precise source table date, that
  should replace this value.

## Next Slice

- Add workbook schema validation so planned rows must exactly match tab widths
  before any Google export-plan write path accepts them.
- When enrichment writes `Current Price*`, include provider/date metadata or an
  adjacent enrichment as-of field before enabling family-visible use.
