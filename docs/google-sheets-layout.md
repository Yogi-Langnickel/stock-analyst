# Google Sheets Layout

Status: active proposal  
Created: 2026-05-16

The Google Sheet is reviewer/export infrastructure, not the primary family
reading UI. It should preserve source references and review state while keeping
family-facing output limited to approved rows.

## Presentation Direction

Target workbook name: `Der Aktionär Summaries`.

The active workbook is currently trimmed to parser-backed, data-bearing tabs
only. Older planned tabs such as `Navigation Dashboard`, `ETF`, `Commodities`,
`Options`, `Crypto`, `Forex`, `Example Portfolios`, `Review Queue`,
`Reviewed Magazine Mentions`, `Recommendation Cards`, and `Statistics Context`
are intentionally pruned from Google Sheets until they have real emitted data.
Bootstrap pruning is limited to tabs known to this project so manual user tabs
are preserved.

There is no separate `Options` tab for now. Calls, puts, discount calls, turbo
long/short products, certificates, and derivative overview rows all use
`Derivative Tips`.

## Active Tabs

1. `Stocks`
   Canonical equity row per WKN/normalized company. Stock recommendation cards,
   `Aktien im Quick-Check`, and `Chart-Check` rows all surface here, with
   duplicate mentions consolidated and non-empty fields merged. The stock table
   header starts on row 3 with `Company`, `WKN`, `Current Price*`,
   `Magazine Price`, `Magazine Price As Of`, `Price at Recommendation`,
   `Dividend Yield`, `Market Cap`, `Chance/Risk`, `P/S Ratio 26e`,
   `P/E Ratio 26e`, `Target`, `Stop`, `Performance since Recommendation`,
   `52w High`, `52w Low`, `1Y Performance`, `5Y Performance`,
   `Next Report`, `Recommendation`, `Comment`, `issue`, `page`, and
   `date updated`. `Current Price*` stays blank until a future enrichment job
   writes a provider-backed value.

2. `Derivative Tips`
   Unified detailed options/derivatives table. Issue and page are trailing
   provenance columns. New derivative recommendations use printed magazine
   values in `Magazine Entry Price` and `Magazine Current Price`; enrichment
   must not overwrite those source fields.

3. `Dividend Focus`
   Dedicated dividend section for table-based dividend data, including dividend
   yield, ex/cum date, next pay date, and payouts per year. Issue/page are
   trailing provenance columns.

4. `AKTIONAER Depot`
   Dedicated magazine model-depot snapshot. One row per issue/position. This
   is publisher portfolio context, not direct app advice. Performance cells are
   conditionally formatted green for positive values and red for negative
   values.

5. `Depot Transactions`
   Dedicated ledger for `Durchgefuehrte Transaktionen`. One row per issue and
   transaction, including explicit no-transaction weeks. Performance cells use
   the same positive/negative conditional formatting as the depot tab.

6. `Chart Check`
   Dedicated traceability export for chart-check source rows, including the
   parsed table fields for magazine price, magazine recommendation price,
   target, stop, 52-week range, performance, dividend yield, and next report
   date. Parsed fields also surface into the matching `Stocks` row by
   WKN/normalized company while remaining `needs_review`.

7. `Stock Quickcheck`
   Dedicated normalized quick-check table with printed magazine price labels.
   Parsed rows also update the matching `Stocks` row by WKN/normalized company.

8. `Extraction Audit`
   Internal audit tab for skipped pages, low-priority back matter, OCR-needed
   pages, parser warnings, and row-level review notes.

## Tab Layout Matrix

The bootstrap metadata now exposes a concrete layout plan for review. It does
not yet apply formatting such as widths, filters, colors, or protected ranges to
the live Sheet; those should be added only after this layout is accepted.

<!-- markdownlint-disable MD013 -->
| Tab | Parser status | Freeze | Table start | Metadata / top area | Notes |
| --- | --- | --- | --- | --- | --- |
| `Stocks` | `parser_backed` | 3 rows, 2 cols | `A3` | Header row only | Canonical stock rows consolidated by WKN/name across recommendation cards, Quick Check, and Chart Check. `Current Price*` is reserved for provider-backed enrichment and remains blank in local magazine-only plans; `Magazine Price` and `Magazine Price As Of` preserve the latest printed source price; `Price at Recommendation` preserves the printed recommendation price where available; includes market cap, P/S ratio, P/E ratio, Chance/Risk, dividend yield, chart fields, and comments where available; `date updated` is the last row field. |
| `Derivative Tips` | `parser_backed` | 1 row, 2 cols | `A1` | Header row | Unified detailed options/derivatives table. Printed source prices use `Magazine Entry Price` and `Magazine Current Price`; source ID stays in row metadata; visible provenance is trailing issue/page columns. |
| `AKTIONAER Depot` | `parser_backed` | 1 row, 2 cols | `A1` | Header row | One row per issue/position for the publisher model-depot snapshot; printed source prices use `Magazine Buy Price` and `Magazine Current Price`; performance cells are green for positive values and red for negative values. |
| `Depot Transactions` | `parser_backed` | 1 row, 2 cols | `A1` | Header row | One row per issue/transaction, including explicit no-transaction weeks; printed source transaction prices use `Magazine Transaction Price`; performance cells use positive/negative conditional formatting. |
| `Chart Check` | `parser_backed` | 1 row, 3 cols | `A1` | Header row | Keep full chart-check traceability here, including `Magazine Price` and `Magazine Price at Recommendation`, while also merging parsed stock fields into `Stocks`. |
| `Stock Quickcheck` | `parser_backed` | 1 row, 3 cols | `A1` | Header row | Keep full quick-check table here with split `Magazine Price`, `Magazine Price at Recommendation`, target, and stop fields; also surface each row in `Stocks`. |
| `Dividend Focus` | `parser_backed` | 1 row, 3 cols | `A1` | Header row | Multi-period dividend context including `Magazine Price`, ex/cum date, pay date, and payout frequency; concise decision fields may surface in `Stocks`. |
| `Extraction Audit` | `parser_backed` | 1 row, 3 cols | `A1` | Header row | First stop for parser warnings and planned-tab surfaces before row emitters exist. |
<!-- markdownlint-enable MD013 -->

## Future Asset-Class Enrichment

Once asset-class dashboard tabs are reintroduced, each major dashboard tab may
have a small specialized enrichment area updated daily from approved sources:

- Stocks: insider buying/selling, major index context, and reviewed company
  news/context.
- ETF: holdings, distribution/yield, expense-ratio context, issuer/family, and
  benchmark/index exposure.
- Commodities: spot/futures context, macro notes, and related ETF/equity links.
- Options: underlying movement, runtime proximity, leverage/Omega, and
  instrument-specific risk warnings.
- Crypto: current price, exchange/liquidity notes, market-cap/risk context, and
  regulatory/news context.
- Forex: currency-pair context, macro calendar notes, and central-bank context.
- Example Portfolios: position changes, transactions, current stops, and
  publisher performance context.

Enrichment must remain context only. It cannot change magazine-extracted
recommendations, targets, stops, WKNs, prices, or recommendation status without
manual review.

## Currency Display

Preserve every magazine-source price in its printed currency. Do not overwrite
`Magazine Price`, `Price at Recommendation`, `Target`, `Stop`, derivative
strike/base values, or publisher portfolio values during currency conversion.

Add a display-currency control to the dashboard layer once daily enrichment is
active:

- Allowed display currencies for now: `EUR`, `USD`, `AUD`.
- Default display currency: `EUR`.
- The toggle should affect derived display columns/cards only, not source
  fields.
- FX rates should be sourced from the daily enrichment pipeline, cached with
  provider/date metadata, and refreshed no more than once per day.
- Converted values should carry `fx rate date`, `source currency`, and
  `display currency` metadata so stale conversions are visible.

Until the enrichment pipeline writes FX rates, keep converted display fields
blank rather than estimating rates manually.

## Embed With Stock Rows

Embed concise reviewed fields that help one stock/instrument row stand alone:
latest magazine recommendation, source issue/page, price, target, stop,
risk/chance dots, dividend yield/trend, quick-check signal, chart-check fields,
performance since recommendation, 52-week range, one-year/five-year
performance, next report date, comment, and review status.

## Keep In Dedicated Tabs

Use dedicated tabs for many-to-one, event-based, or structurally different
content: derivative overview tables, model-depot positions, model-depot
transactions, chart-check sections, quick-check tables, statistics, extraction
audit, and multi-period dividend tables.

## Page Mapping Review

Yes: reviewing each magazine page and defining which data goes where is useful.
Treat it as a parser training/review manifest, not as manual data entry. For
each page or page range, capture:

- source pages and section title
- extraction priority
- destination tab
- row identity rule
- fields to extract
- fields to ignore
- confidence/review notes

This page map should live in versioned docs or a small YAML fixture once the
shape stabilizes. The human review goal is to define routing and field rules;
the parser should still populate rows automatically.

## Row Identity And Update Rules

Once an instrument exists in the workbook, later issue imports should update
the existing instrument row rather than append a duplicate, unless the source
represents a genuinely distinct instrument or event.

Default identity rules:

- Stocks: update by WKN when present; otherwise by reviewed normalized company
  identity. Keep latest recommendation/source issue/page fields current, while
  preserving source history separately once a history tab exists.
- ETF, Commodities, Crypto, and Forex: update by primary identifier or reviewed
  normalized instrument key. Do not append duplicates for repeated mentions.
- Dividend Focus: keep the table/event rows because dividend rows can be
  period-specific, but surface the most appropriate current yield back onto the
  matching instrument row.
- AKTIONAER Depot: keep one snapshot row per issue/position. This is a
  publisher portfolio history, not the canonical instrument row.
- Depot Transactions: append transaction events. Explicit no-transaction weeks
  remain issue-specific evidence.
- Derivative Tips: update only when it is the same derivative/security, normally
  the same WKN/ISIN. A new call or put for the same underlying is a new row when
  the derivative WKN/ISIN differs, even if the underlying stock is the same.

For options and derivatives, the underlying alone is not a stable row identity.
Use derivative WKN/ISIN first, then reviewed product terms only when the WKN is
missing.

## Current Section Keys

The local `section-inventory` command emits stable section keys and suggested
tabs:

<!-- markdownlint-disable MD013 -->
| Section key | Suggested tab | Purpose |
| --- | --- | --- |
| `dividend_strategy` | `Dividend Focus` | Dividend tables such as pages 18-19. |
| `derivative_tips_overview` | `Derivative Tips` | Derivative overview pages such as 62-63. |
| `aktionaer_depot_positions` | `AKTIONAER Depot` | Model-depot position snapshot. |
| `aktionaer_depot_transactions` | `Depot Transactions` | Transaction ledger/no-transaction weeks. |
| `chart_check` | `Chart Check` | Parser-backed Chart-Check stocks and technical context. |
| `quick_check` | `Stock Quickcheck` | Parser-backed publisher quick-check evaluations. |
| `statistics_context` | `Extraction Audit` | Context-only statistics tables until a parser-backed statistics tab is reintroduced. |
| `low_priority_back_matter` | `Extraction Audit` | Back matter after statistics. |
<!-- markdownlint-enable MD013 -->

## Local Export Plan

The local `workbook-export-plan` command builds a JSON dry run of planned row
DTOs for the workbook tabs. It currently routes:

- stock recommendation cards to `Stocks`
- chart-check stock rows to `Stocks` and `Chart Check`
- quick-check stock rows to `Stocks` and `Stock Quickcheck`
- derivative cards to `Derivative Tips`
- derivative overview table rows to `Derivative Tips`
- dividend strategy rows to `Dividend Focus`
- AKTIONAER depot rows to `AKTIONAER Depot`
- depot transaction/no-transaction rows to `Depot Transactions`
- section-inventory routing hints to `Extraction Audit`

`Recommendation Cards` is retained as a future traceability idea, but the
current active workbook does not keep that tab. Parsed stock cards route to
`Stocks`, and parsed derivative cards route to `Derivative Tips`.

The command does not call Google Sheets and does not write export files. Planned
rows are draft reviewer infrastructure only: `exportable=false`,
`requiresManualReview=true`, and `approvedRows=0`.

Workbook export-plan construction validates every planned row against the active
tab schemas before JSON serialization. Rows that target inactive tabs or have a
stale width fail locally instead of being padded, truncated, or handed to a
Google write path.

The `google-sheets-export-plan` command writes those draft reviewer rows into
the configured Google Sheet. It bootstraps headers first, replaces existing rows
for the same issue in affected tabs by default, preserves rows from other
issues, and makes no enrichment provider calls.

Broad index, statistics, or constituent-table context must not fan out into
individual `Stocks` rows. Parsed Quick Check and Chart Check rows are explicit
stock mentions and should create/update `Stocks` rows, while the dedicated
`Stock Quickcheck` and `Chart Check` tabs remain detailed traceability views.

## Reviewer Rule

Approved exports should use neutral wording such as "magazine says" or
"printed in issue/page". No row from section inventory, statistics, or
quick-check extraction should become family-visible without manual review.
