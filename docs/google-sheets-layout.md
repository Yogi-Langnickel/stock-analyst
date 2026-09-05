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

1. `Search`
   Visible workbook entrypoint. Enter a company name or WKN in the merged
   `C1:E1` input field. No Search rows are frozen. Matching
   stock and derivative references are shown in vertically stacked sections
   using the full reviewer values and action colors from the issue tabs.
   Insider matches use the same full-row Acquired/Disposed colors as the
   dedicated ledger.
   `Source` is the first visible column for both sections (using the stock
   `Source` or derivative `Issue:Page` value). Matches are ordered by numeric
   issue year/week descending and source page ascending. The generated index
   reads only `DA_YYYY_NN` issue tabs; `Aktuell` is deliberately excluded so the
   current issue is not returned twice.

2. `Aktuell` (Latest)
   Quick-review tab generated from the current workbook-export plan. It shows
   only source-linked explicit publisher Buy, Sell, Hold, and Wait actions from
   the latest imported issue. Separate Stocks and Derivatives tables use their own
   headers; stock rows retain dividend yield, KUV, and KGV when printed.
   Derivative rows omit `Chance` and `Risk`. Reviewer-facing update timestamps
   are labeled `Import date`.
   Crypto and ETF rows appear only when the issue contains an actionable
   recommendation. It is a triage view and is not part of the search index.

3. `DA_YYYY_NN` issue reviewer tabs
   Every scanned issue receives its own reviewer tab, named from the source
   filename convention without the `.pdf` extension (for example,
   `DA_2026_25`). The layout and review status are the same as `Aktuell`.
   `Aktuell` is refreshed only when the imported issue is the newest available
   issue tab; importing an older issue leaves the current latest view intact.
   Issue tabs are physically ordered newest first.

The previous hidden generated tabs (`Navigation Dashboard`, `Stocks`,
`Derivative Tips`, `Dividend Focus`, `AKTIONAER Depot`, `Extraction Audit`,
`Depot Transactions`) are retired from the live Google
Sheet and deleted by bootstrap. Their local workbook-plan schemas remain
available for extraction and validation, but Google export intentionally omits
those rows instead of recreating duplicate live tables.

`Insider Activity` is now an active cumulative SEC Form 4 ledger. It is
refreshed after issue export when `SEC_USER_AGENT` is configured, deduplicates
by filing transaction, and contributes a third Search result section below
Derivatives. Its visible schema is limited to 12 reviewer columns: company,
WKN, ticker, insider, relationship, shares owned after the transaction,
transaction date, simplified transaction, direction, shares, USD price, and
transaction value. Company cells link to the source SEC filing, while acquired
rows are green and disposed rows are red. Only non-derivative SEC stock
purchases and sales are retained; awards, gifts, conversions, exercises,
payments, derivative-security transactions, and other transaction types are
excluded. The native filter is kept on the exact 12-column data range after
each write without dropping the reviewer's criteria or sort state. Managed
filter views for all trades, purchases, and sales let family reviewers select a
personal view while the underlying ledger remains protected. User-created
custom filter views are left untouched. Two compact rows merged across the
frozen `A:C` pane above the ledger explain the workflow in English and German.
The instructions and row-3 header remain frozen while scrolling.

## Tab Layout Matrix

The bootstrap metadata exposes a concrete layout plan for review. Search refresh
and workbook export also reconcile managed sheet protections after all generated
values and formatting have been written:

- `Search` is protected except for the merged `C1:E1` input field.
- `Aktuell` and every existing `DA_YYYY_NN` issue tab are fully protected.
- New issue tabs are included automatically during the export that creates them.
- The configured service account remains an allowed protection editor so later
  refreshes can update generated values. Spreadsheet owners retain owner access.
- Existing whole-sheet protections are preserved; protection is added only to
  managed tabs that do not already have it.

<!-- markdownlint-disable MD013 -->
| Tab | Parser status | Freeze | Table start | Metadata / top area | Notes |
| --- | --- | --- | --- | --- | --- |
| `Search` | `layout_only` | 0 rows, 0 cols | `A1` | Search label in `A1`, merged user input in `C1:E1`, scope note in `A2`, results from `A4` | Searches company/WKN across issue tabs and company/WKN/ticker/insider across Insider Activity. Results appear as Stocks, Derivatives, then Insider Activity. Generated index columns `U:AQ` are hidden; `Aktuell` is excluded. |
| `Aktuell` | `parser_backed` | 1 row, 3 cols | `A1` | Stock headers, then two intentional spacer rows and a separate Derivatives table | Current issue explicit publisher Buy, Sell, Hold, and Wait actions only. The derivative table starts `WKN`, `Derivative`, `Action`; its `Issue:Page` provenance is kept near the review fields at the tail. Stock rows retain source dividend yield, KUV, and KGV; derivative rows use underlying, strike/KO, leverage, and runtime columns. |
| `Insider Activity` | `parser_backed` | 3 rows, 3 cols | `A3` | Bilingual filter-view instructions in rows 1-2; cumulative SEC Form 4 transaction ledger from row 3 | Exactly 12 visible columns in the requested order. Weekly imports merge by stable SEC source identity; company hyperlinks retain source provenance. Acquired rows are green and disposed rows red. |
| `DA_YYYY_NN` | `parser_backed` | 1 row, 3 cols | `A1` | Same compact stacked tables as `Aktuell` | One source-linked review tab per scanned issue. Uses the PDF stem convention, such as `DA_2026_25`; preserved for archive review while `Aktuell` remains the latest issue. |
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
latest magazine recommendation, `Issue:Page`, price, target, stop, split
`Chance` and `Risk` ratings, dividend yield/trend, quick-check signal, chart-check fields,
performance since recommendation, 52-week range, one-year/five-year
performance, next report date, enrichment status, and review status. Keep
current-issue comments on `Aktuell`.

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
  identity. Keep latest recommendation and `Issue:Page` fields current, while
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
bootstraps `Search`, `Aktuell`, and `Insider Activity`, writes the issue-specific
reviewer tab, refreshes issue and insider Search data, and calls SEC Form 4 only
when `SEC_USER_AGENT` is configured. Other provider calls remain disabled.
Rows belonging to retired canonical live tabs are reported as omitted rather
than recreating those tabs. The write result labels this boundary explicitly: default
writes return `exportMode=approved_family_export`, `familyVisibleSafe=true`,
and `privateDraftReviewOnly=false`; draft reviewer writes return
`exportMode=private_draft_review_export`, `familyVisibleSafe=false`, and
`privateDraftReviewOnly=true`.

Use `scripts/stock-analyst google-sheets-refresh-search --env-file .env` to
apply the clean live-tab structure and rebuild `Search` from existing issue
tabs without re-exporting magazine rows.

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
"printed in `Issue:Page`". No row from section inventory, statistics, or
quick-check extraction should become family-visible without manual review.
