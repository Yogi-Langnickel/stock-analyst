# Google Sheets Layout

Status: active proposal  
Created: 2026-05-16

The Google Sheet is reviewer/export infrastructure, not the primary family
reading UI. It should preserve source references and review state while keeping
family-facing output limited to approved rows.

## Presentation Direction

Target workbook name: `Der Aktionär Summaries`.

Use a first tab named `Navigation Dashboard` as the low-clutter entrypoint. It
can show large visual links or button-like cells for the main areas:

- Stocks
- ETF
- Commodities
- Options
- Crypto
- Forex
- Example Portfolios

Prefer spreadsheet-native links and protected ranges before Apps Script buttons.
This keeps service-account writes simpler and avoids extra script authorization
until a richer UI is justified.

The dashboard tabs should prevent overload by separating asset classes, while
still allowing additional specialized tabs where the extraction shape demands
it. A future council review should decide the exact split once several real
issues have been extracted and the repeated sections are clearer.

## Recommended Tabs

1. `Navigation Dashboard`
   Entry tab with links to major asset-class dashboards and status summaries.

2. `Stocks`
   Dashboard-style view for equity recommendations, major indexes such as DAX
   and Dow Jones, small trend charts, key article bullets, reviewed
   recommendation state, and stock-specific enrichment such as insider buying
   or selling. The stock table header starts on row 3 with `Company`, `WKN`,
   `Current Price*`, `Price at Recommendation`, `Dividends`, `Target`, `Stop`,
   `Recommendation`, `issue`, `page`, and `date updated`. The row-level
   `date updated` value is required as the last field: weekly imports
   initialize it from the import/issue date when available, otherwise from the
   command's current UTC date, and later reviewed enrichment or newer issue
   mentions update it.

3. `ETF`
   ETF-related recommendations and fund context such as holdings, distributions,
   fees, issuer/family, index exposure, WKN, and ETF-specific enrichment. The
   row-level `date updated` field is the last field.

4. `Commodities`
   Commodity-related recommendations, article bullets, price/context snapshots,
   and commodity-specific enrichment. The row-level `date updated` field is the
   last field.

5. `Options`
   Option and derivative recommendations with underlying, base value, strike or
   base price, Omega/Hebel, runtime, target, stop, and risk flags. The row-level
   `date updated` field is the last field.

6. `Crypto`
   Crypto recommendations and digital-asset context such as exchange/liquidity,
   sector/theme, risk flags, and daily enrichment. The row-level `date updated`
   field is the last field.

7. `Forex`
   Currency-pair recommendations and macro/currency-specific context. The
   row-level `date updated` field is the last field.

8. `Example Portfolios`
   Publisher model portfolio snapshots, transactions, stops, and changes.

9. `Review Queue`
   Draft-only reviewer workspace. This should stay reviewer-only.

10. `Reviewed Magazine Mentions`
   Main approved stock-centric export. One row per reviewed instrument mention
   with issue/page, printed name, identifiers, recommendation, price, target,
   stop, reviewer, and approved timestamp.

11. `Recommendation Cards`
   Structured extraction of labelled magazine card fields. Link rows back to
   `Reviewed Magazine Mentions` through stable source IDs.

12. `Derivative Tips`
   Dedicated derivative table. Include underlying, derivative WKN/ISIN, type,
   base price, strike/cap, leverage/Omega, runtime, chance/risk, target, stop,
   recommendation, and source page.

13. `AKTIONAER Depot`
   Dedicated magazine model-depot snapshot. One row per issue/position. Treat
   this as publisher portfolio context, not direct app advice.

14. `Depot Transactions`
   Dedicated ledger for `Durchgefuehrte Transaktionen`. One row per issue and
   transaction, including explicit no-transaction weeks.

15. `Chart Check`
   Dedicated page/table export for chart-check items. Link rows back to stock
   rows when WKNs match.

16. `Stock Quickcheck`
   Dedicated normalized quick-check table. Attach the final reviewed
   quick-check signal to the matching stock row, but keep the full table here.

17. `Statistics Context`
   Dedicated context tab for market, index, sector, and stock-statistics data.
   Do not create recommendation rows from statistics alone.

18. `Dividend Focus`
    Dedicated dividend section for multi-date, multi-period, or table-based
    dividend data. Simple labelled card values can also be embedded in the
    stock/recommendation-card row.

19. `Extraction Audit`
    Internal audit tab for skipped pages, low-priority back matter, OCR-needed
    pages, parser warnings, and row-level review notes.

## Tab Layout Matrix

The bootstrap metadata now exposes a concrete layout plan for review. It does
not yet apply formatting such as widths, filters, colors, or protected ranges to
the live Sheet; those should be added only after this layout is accepted.

<!-- markdownlint-disable MD013 -->
| Tab | Parser status | Freeze | Table start | Metadata / top area | Notes |
| --- | --- | --- | --- | --- | --- |
| `Navigation Dashboard` | `layout_only` | 1 row, 0 cols | `A1` | Workbook links and processing status | Spreadsheet-native links to the main tabs, last issue processed, parser-backed/planned legend. |
| `Stocks` | `parser_backed` | 3 rows, 2 cols | `A3` | Header row only | Explicit stock mentions only. `Current Price*` comes from daily enrichment; `Price at Recommendation` is the printed magazine value; `date updated` is the last row field. |
| `ETF` | `planned` | 2 rows, 2 cols | `A2` | Row 1 fund context | Fund holdings, fee, WKN, distribution/yield, and index-exposure context once parser-backed; `date updated` is the last row field. |
| `Commodities` | `planned` | 2 rows, 1 col | `A2` | Row 1 commodity context | Spot/futures context, macro note, related instruments; `date updated` is the last row field. |
| `Options` | `planned` | 2 rows, 1 col | `A2` | Row 1 risk/stale-data notes | Dashboard for option summaries; detailed derivative cards currently emit to `Derivative Tips`; `date updated` is the last row field. |
| `Crypto` | `planned` | 2 rows, 1 col | `A2` | Row 1 digital-asset context | Crypto recommendations, exchange/liquidity context, and digital-asset risk notes; `date updated` is the last row field. |
| `Forex` | `planned` | 2 rows, 1 col | `A2` | Row 1 macro/calendar context | Currency-pair recommendations and central-bank context once parser-backed; `date updated` is the last row field. |
| `Example Portfolios` | `planned` | 2 rows, 2 cols | `A2` | Row 1 publisher portfolio status | Publisher model portfolio context only, not direct app advice. |
| `Review Queue` | `planned` | 1 row, 1 col | `A1` | Header row | Reviewer-only triage; no family-facing export should read directly from this tab. |
| `Reviewed Magazine Mentions` | `planned` | 1 row, 1 col | `A1` | Header row | Approved source-linked rows only after manual review. |
| `Recommendation Cards` | `planned` | 1 row, 1 col | `A1` | Header row | Raw labelled card traceability; stock/derivative cards currently route to `Stocks` or `Derivative Tips`. |
| `Derivative Tips` | `parser_backed` | 1 row, 3 cols | `A1` | Header row | Option/card rows with WKN, base value, base price, Omega/Hebel, runtime, target, stop. |
| `AKTIONAER Depot` | `audit_hint` | 1 row, 3 cols | `A1` | Header row | Section inventory detects this surface; dedicated row emitter is not implemented yet. |
| `Depot Transactions` | `audit_hint` | 1 row, 3 cols | `A1` | Header row | Section inventory detects transaction tables and no-transaction weeks; dedicated row emitter is not implemented yet. |
| `Chart Check` | `audit_hint` | 1 row, 3 cols | `A1` | Header row | Section inventory detects pages; reviewed signals should later link back to stock WKNs. |
| `Stock Quickcheck` | `audit_hint` | 1 row, 3 cols | `A1` | Header row | Keep full quick-check table here; surface only reviewed summary in `Stocks`. |
| `Statistics Context` | `audit_hint` | 1 row, 3 cols | `A1` | Header row | Context only. It must never create recommendation rows by itself. |
| `Dividend Focus` | `parser_backed` | 1 row, 3 cols | `A1` | Header row | Multi-period dividend context; concise decision fields may surface in `Stocks`. |
| `Extraction Audit` | `parser_backed` | 1 row, 3 cols | `A1` | Header row | First stop for parser warnings and planned-tab surfaces before row emitters exist. |
<!-- markdownlint-enable MD013 -->

## Asset-Class Enrichment

Each major dashboard tab may have a small specialized enrichment area updated
daily from approved sources:

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

## Embed With Stock Rows

Embed concise reviewed fields that help one stock/instrument row stand alone:
latest magazine recommendation, source issue/page, price, target, stop,
risk/chance dots, dividend yield/trend, quick-check signal, chart-check summary,
and review status.

## Keep In Dedicated Tabs

Use dedicated tabs for many-to-one, event-based, or structurally different
content: derivative overview tables, model-depot positions, model-depot
transactions, chart-check sections, quick-check tables, statistics, extraction
audit, and multi-period dividend tables.

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
| `chart_check` | `Chart Check` | Chart-check stocks and technical context. |
| `quick_check` | `Stock Quickcheck` | Publisher quick-check evaluations. |
| `statistics_context` | `Statistics Context` | Context-only statistics tables. |
| `low_priority_back_matter` | `Extraction Audit` | Back matter after statistics. |
<!-- markdownlint-enable MD013 -->

## Local Export Plan

The local `workbook-export-plan` command builds a JSON dry run of planned row
DTOs for the workbook tabs. It currently routes:

- stock recommendation cards to `Stocks`
- derivative cards to `Derivative Tips`
- dividend strategy rows to `Dividend Focus`
- section-inventory routing hints to `Extraction Audit`

`Recommendation Cards` is retained as a planned traceability tab, but the
current workbook export plan does not populate it directly. Parsed stock cards
route to `Stocks`, and parsed derivative cards route to `Derivative Tips`.

The command does not call Google Sheets and does not write export files. Planned
rows are draft reviewer infrastructure only: `exportable=false`,
`requiresManualReview=true`, and `approvedRows=0`.

Broad index, statistics, quick-check, chart-check, or constituent-table context
must not fan out into individual `Stocks` rows. Only explicitly mentioned stock
recommendation cards or reviewed explicit stock mentions may create rows in the
`Stocks` tab.

## Reviewer Rule

Approved exports should use neutral wording such as "magazine says" or
"printed in issue/page". No row from section inventory, statistics, or
quick-check extraction should become family-visible without manual review.
