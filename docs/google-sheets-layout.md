# Google Sheets Layout

Status: active proposal  
Created: 2026-05-16

The Google Sheet is reviewer/export infrastructure, not the primary family
reading UI. It should preserve source references and review state while keeping
family-facing output limited to approved rows.

## Presentation Direction

Target workbook name: `Der Aktionär Summaries`.

The active workbook is currently trimmed to the navigation dashboard plus
parser-backed, data-bearing tabs. Older planned tabs such as `ETF`,
`Commodities`, `Options`, `Crypto`, `Forex`, `Example Portfolios`,
`Review Queue`, `Reviewed Magazine Mentions`, `Recommendation Cards`, and
`Statistics Context` are intentionally pruned from Google Sheets until they
have real emitted data. Bootstrap pruning is limited to tabs known to this
project so manual user tabs are preserved.

There is no separate `Options` tab for now. Calls, puts, discount calls, turbo
long/short products, certificates, and derivative overview rows all use
`Derivative Tips`.

## Active Tabs

1. `Navigation Dashboard`
   Low-clutter cockpit for the active workbook tabs. It groups the current tabs
   into core instruments, derivatives, income, publisher portfolio, source
   detail, and review control so the workbook has a stable entrypoint without
   duplicating detailed financial rows.

2. `Latest Issue Recommendations`
   Quick-review tab generated from the current workbook-export plan. It shows
   selected source-linked stock recommendation fields for the latest imported
   issue only. It is a triage view; canonical merged equity state remains in
   `Stocks`.

3. `Stocks`
   Canonical equity row per WKN/normalized company. Stock recommendation cards,
   `Aktien im Quick-Check`, and `Chart-Check` rows all surface here, with
   duplicate mentions consolidated and non-empty fields merged. The stock table
   header starts on row 1 with `Company`, `WKN`, `Target`, `Stop`,
   `Current price`, `Market Cap`, `Dividend Yield`, `Recommendation`,
   `Held since`, `Performance since Recommendation`, `Next Report`,
   `Report type`, `P/S Ratio 26e`, `P/E Ratio 26e`, `Chance/Risk`,
   `Insider Activity`, `Comment`, `issue`, `page`, and `date updated`.
   `Next Report` is date-only; report labels such as quarterly or year-end
   results live in `Report type`. `Current price` preserves the printed
   `Akt. Kurs` value as amount and currency until reviewed enrichment refreshes
   it.

4. `Derivative Tips`
   Unified detailed options/derivatives table. Issue and page are trailing
   provenance columns. New derivative recommendations use printed magazine
   values in `Magazine Entry Price` and `Magazine Current Price`; enrichment
   must not overwrite those source fields.

5. `Dividend Focus`
   Dedicated dividend section for table-based dividend data, including dividend
   yield, ex/cum date, next pay date, and payouts per year. Issue/page are
   trailing provenance columns.

6. `AKTIONAER Depot`
   Dedicated magazine model-depot snapshot. One row per issue/position. This
   is publisher portfolio context, not direct app advice. Performance cells are
   conditionally formatted green for positive values and red for negative
   values.

7. `Depot Transactions`
   Dedicated ledger for `Durchgefuehrte Transaktionen`. One row per issue and
   transaction, including explicit no-transaction weeks. Performance cells use
   the same positive/negative conditional formatting as the depot tab.

8. `Insider Activity`
   Dedicated review destination for future SEC EDGAR Form 4 insider activity
   rows. Stock rows can link to a reviewed buy/sell indicator from this tab.

9. `Extraction Audit`
   Internal audit tab for skipped pages, low-priority back matter, OCR-needed
   pages, parser warnings, and row-level review notes.

## Tab Layout Matrix

The bootstrap metadata now exposes a concrete layout plan for review. It does
not yet apply formatting such as widths, filters, colors, or protected ranges to
the live Sheet; those should be added only after this layout is accepted.

<!-- markdownlint-disable MD013 -->
| Tab | Parser status | Freeze | Table start | Metadata / top area | Notes |
| --- | --- | --- | --- | --- | --- |
| `Navigation Dashboard` | `layout_only` | 5 rows, 2 cols | `A5` | Workbook title, static navigation rows, and row-count formulas | Entry dashboard based on the active tabs. Keep rows concise, source-neutral, and review-oriented; data clears preserve this layout. Row counts are spreadsheet formulas over active tab data ranges and do not trigger enrichment. |
| `Latest Issue Recommendations` | `parser_backed` | 1 row, 3 cols | `A1` | Header row only | Current import triage rows copied from generated `Stocks` rows. This tab is replaced for each workbook export and must not become the canonical stock record. |
| `Stocks` | `parser_backed` | 1 row, 2 cols | `A1` | Header row only | Canonical stock rows consolidated by WKN/name across recommendation cards, Quick Check, and Chart Check. `Current price`, `Target`, and `Stop` contain only amount and currency; `Dividend Yield` accepts only unsigned yield percentages; `P/S Ratio 26e` and `P/E Ratio 26e` accept only plain ratio values; `Next Report` is date-only; `Report type` stores the event label; `Recommendation` stores action/status such as `hold`, `new_recommendation`, `no_buy`, or `verkauft`; `Held since` stores the issue only for holds; `Insider Activity` links to the dedicated insider transaction tab. |
| `Derivative Tips` | `parser_backed` | 1 row, 2 cols | `A1` | Header row | Unified detailed options/derivatives table. Printed source prices use `Magazine Entry Price` and `Magazine Current Price`; source ID stays in row metadata; visible provenance is trailing issue/page columns. |
| `AKTIONAER Depot` | `parser_backed` | 1 row, 2 cols | `A1` | Header row | One row per issue/position for the publisher model-depot snapshot; printed source prices use `Magazine Buy Price` and `Magazine Current Price`; performance cells are green for positive values and red for negative values. |
| `Depot Transactions` | `parser_backed` | 1 row, 2 cols | `A1` | Header row | One row per issue/transaction, including explicit no-transaction weeks; printed source transaction prices use `Magazine Transaction Price`; performance cells use positive/negative conditional formatting. |
| `Dividend Focus` | `parser_backed` | 1 row, 3 cols | `A1` | Header row | Multi-period dividend context including `Magazine Price`, ex/cum date, pay date, and payout frequency; concise decision fields may surface in `Stocks`. |
| `Insider Activity` | `planned` | 1 row, 3 cols | `A1` | Header row | Planned SEC Form 4 source rows with direct filing links; stock-row indicators should summarize only reviewed rows from this tab. |
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
`Current price`, `Target`, `Stop`, derivative strike/base values, or publisher
portfolio values during currency conversion.

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
| `chart_check` | `Stocks` | Parser-backed Chart-Check stocks and technical context. |
| `quick_check` | `Stocks` | Parser-backed publisher quick-check evaluations. |
| `statistics_context` | `Extraction Audit` | Context-only statistics tables until a parser-backed statistics tab is reintroduced. |
| `low_priority_back_matter` | `Extraction Audit` | Back matter after statistics. |
<!-- markdownlint-enable MD013 -->

## Local Export Plan

The local `workbook-export-plan` command builds a JSON dry run of planned row
DTOs for the workbook tabs. It currently routes:

- stock recommendation cards to `Stocks`
- chart-check stock rows to `Stocks`
- quick-check stock rows to `Stocks`
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

The `google-sheets-export-plan` command writes approved rows into the configured
Google Sheet only when the workbook plan carries `workbook-approval-audit`
provenance from a private reviewer CSV with exact row-hash matches. It fails
closed instead of trusting caller-controlled `approved` flags. It writes draft
rows only when `--allow-draft-rows` is supplied for the private reviewer workbook. It
bootstraps headers first, replaces existing rows for the same issue in affected
tabs by default, preserves rows from other issues, and makes no enrichment
provider calls. The write result labels this boundary explicitly: default
writes return `exportMode=approved_family_export`, `familyVisibleSafe=true`,
and `privateDraftReviewOnly=false`; draft reviewer writes return
`exportMode=private_draft_review_export`, `familyVisibleSafe=false`, and
`privateDraftReviewOnly=true`.

Approved-family export must consume a reviewed workbook plan created by
`workbook-approval-audit`, not the raw parser draft. The approval workflow is
local/private: `workbook-approval-template` writes a CSV with `source_id` and
`row_values_sha256`; the reviewer fills approval fields; `workbook-approval-audit`
applies only exact row-hash matches and returns counts without row content.

Broad index, statistics, or constituent-table context must not fan out into
individual `Stocks` rows. Parsed Quick Check and Chart Check rows are explicit
stock mentions and should create/update `Stocks` rows; the separate Quickcheck
and Chart Check tabs are intentionally inactive because those rows already
surface on `Stocks`.

## Reviewer Rule

Approved exports should use neutral wording such as "magazine says" or
"printed in issue/page". No row from section inventory, statistics, or
quick-check extraction should become family-visible without manual review.
