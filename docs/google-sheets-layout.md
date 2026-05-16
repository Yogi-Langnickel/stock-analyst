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
- Commodities
- Options
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
   or selling.

3. `Commodities`
   Commodity-related recommendations, article bullets, price/context snapshots,
   and commodity-specific enrichment.

4. `Options`
   Option and derivative recommendations with underlying, base value, strike or
   base price, Omega/Hebel, runtime, target, stop, and risk flags.

5. `Forex`
   Currency-pair recommendations and macro/currency-specific context.

6. `Example Portfolios`
   Publisher model portfolio snapshots, transactions, stops, and changes.

7. `Review Queue`
   Draft-only reviewer workspace. This should stay reviewer-only.

8. `Reviewed Magazine Mentions`
   Main approved stock-centric export. One row per reviewed instrument mention
   with issue/page, printed name, identifiers, recommendation, price, target,
   stop, reviewer, and approved timestamp.

9. `Recommendation Cards`
   Structured extraction of labelled magazine card fields. Link rows back to
   `Reviewed Magazine Mentions` through stable source IDs.

10. `Derivative Tips`
   Dedicated derivative table. Include underlying, derivative WKN/ISIN, type,
   base price, strike/cap, leverage/Omega, runtime, chance/risk, target, stop,
   recommendation, and source page.

11. `AKTIONAER Depot`
   Dedicated magazine model-depot snapshot. One row per issue/position. Treat
   this as publisher portfolio context, not direct app advice.

12. `Depot Transactions`
   Dedicated ledger for `Durchgefuehrte Transaktionen`. One row per issue and
   transaction, including explicit no-transaction weeks.

13. `Chart Check`
   Dedicated page/table export for chart-check items. Link rows back to stock
   rows when WKNs match.

14. `Stock Quickcheck`
   Dedicated normalized quick-check table. Attach the final reviewed
   quick-check signal to the matching stock row, but keep the full table here.

15. `Statistics Context`
   Dedicated context tab for market, index, sector, and stock-statistics data.
   Do not create recommendation rows from statistics alone.

16. `Dividend Focus`
    Dedicated dividend section for multi-date, multi-period, or table-based
    dividend data. Simple labelled card values can also be embedded in the
    stock/recommendation-card row.

17. `Extraction Audit`
    Internal audit tab for skipped pages, low-priority back matter, OCR-needed
    pages, parser warnings, and row-level review notes.

## Asset-Class Enrichment

Each major dashboard tab may have a small specialized enrichment area updated
daily from approved sources:

- Stocks: insider buying/selling, major index context, and reviewed company
  news/context.
- Commodities: spot/futures context, macro notes, and related ETF/equity links.
- Options: underlying movement, runtime proximity, leverage/Omega, and
  instrument-specific risk warnings.
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

- stock recommendation cards to `Recommendation Cards`
- derivative cards to `Derivative Tips`
- dividend strategy rows to `Dividend Focus`
- section-inventory routing hints to `Extraction Audit`

The command does not call Google Sheets and does not write export files. Planned
rows are draft reviewer infrastructure only: `exportable=false`,
`requiresManualReview=true`, and `approvedRows=0`.

## Reviewer Rule

Approved exports should use neutral wording such as "magazine says" or
"printed in issue/page". No row from section inventory, statistics, or
quick-check extraction should become family-visible without manual review.
