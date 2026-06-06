# Workbook And Enrichment Memory

Status: active
Created: 2026-06-06

## Workbook Export

- A local embedded-text recommendation-card extractor captures printed company
  name, instrument type, WKN, current price, target, stop, chance/risk dots,
  market cap, recommendation status, performance, issue/date, dividend
  yield/trend, P/S and P/E ratios, next report date, and derivative fields.
  It is draft-only and emits `needs_review`.
- The local section inventory command flags dividend strategy tables,
  derivative overview tables, AKTIONAER depot positions, depot transactions,
  chart-check pages, quick-check tables, statistics context, and low-priority
  back matter with suggested Google Sheet destinations.
- `Aktien im Quick-Check` rows are parser-backed into `Stocks` as
  previous-recommendation rows with split current price, price at
  recommendation, target, stop, and comment fields. The separate
  `Stock Quickcheck` tab is inactive.
- `Chart-Check` pages are parser-backed into `Stocks` with publisher bullet
  summary and parsed table fields. `Akt. Kurs` is current price; `Empf.- Kurs`
  is price at recommendation. The separate `Chart Check` tab is inactive.
- A workbook export plan can route recommendation cards, derivative cards,
  derivative overview rows, dividend strategy rows, AKTIONAER depot positions,
  depot transaction/no-transaction rows, and audit hints into Google Sheet row
  DTOs without writing to Sheets.
- Dividend strategy rows preserve otherwise complete high-yield entries when
  optional market-cap or P/E cells are dash-like missing values; those cells
  normalize to blank workbook cells.
- Dividend OCR line normalization can split collapsed OCR table lines into the
  existing row-major and continuation parser shapes. Rows touched by the helper
  carry `ocr_line_normalized` and still remain `needs_review`.
- Derivative overview rows apply retrospective metrics only when base-row count
  and retrospective-row count match exactly. On mismatch, keep base rows and
  leave retrospective metric fields blank.
- Planned rows must target an active workbook tab and exactly match that tab's
  configured width before JSON serialization or Google write paths can pad or
  truncate them.

## Active Tabs And Identity

- Active workbook tabs are the layout-only `Navigation Dashboard` plus
  `Latest Issue Recommendations`, `Stocks`, `Derivative Tips`,
  `AKTIONAER Depot`, `Depot Transactions`, `Dividend Focus`,
  `Insider Activity`, and `Extraction Audit`.
- `Latest Issue Recommendations` is generated for the current workbook-export
  plan. It duplicates selected stock fields for triage only; canonical merged
  equity state remains in `Stocks`.
- Google Sheets export replaces `Latest Issue Recommendations` on each
  same-issue export so the tab stays focused on the latest plan.
- Google Sheets row replacement writes the new combined ranges before clearing
  stale trailing rows. Do not reintroduce clear-before-write behavior; a failed
  write must leave existing rows intact.
- Google Sheets export results must distinguish approved-family writes from
  private draft-review writes. Default exports return
  `exportMode=approved_family_export` and `familyVisibleSafe=true`; explicit
  `--allow-draft-rows` writes return `exportMode=private_draft_review_export`
  and `familyVisibleSafe=false`.
- Reviewer approval import is private and hash-bound. Generate
  `workbook-approval-template`, have the reviewer mark rows in the private CSV,
  then apply it with `workbook-approval-audit` to produce a private reviewed
  workbook plan. Approvals require reviewer, reviewed timestamp, source block,
  and exact `row_values_sha256`; stale hash mismatches keep rows non-exportable.
- `Navigation Dashboard` is a static reviewer cockpit. Do not emit workbook
  rows to it, do not trigger enrichment from it, and preserve its body rows
  during generated data clears.
- Stocks update by WKN when present, falling back to normalized company name.
  Later magazine mentions update existing instrument rows rather than append
  duplicates, and merge issue/page provenance.
- Derivatives update only when the derivative/security is the same, normally
  by derivative WKN/ISIN. A new call or put for the same underlying is a new
  row when derivative WKN/ISIN differs.
- Depot snapshots and transactions remain issue/event-specific history rows.
- Stock rows use English labels. German source fields map to `Dividend Yield`,
  `P/S Ratio 26e`, `P/E Ratio 26e`, `Market Cap`, `Chance/Risk`, and
  `recommendation_status=no_buy` for `Kein Kauf`.
- In `Stocks`, `Current price` preserves printed `Akt. Kurs` amount and
  currency until reviewed enrichment refreshes it. `Target`, `Stop`, and
  ratio/yield columns are shape-sanitized so nearby notes cannot shift into
  financial value columns.
- Source-specific tabs use printed-price labels such as `Magazine Price`,
  `Magazine Current Price`, and `Magazine Price at Recommendation` so they are
  not mistaken for live provider-backed prices.
- Future currency display should preserve printed source prices and add derived
  display fields for `EUR`, `USD`, and `AUD` with FX date/source metadata.
- A page-by-page extraction map should guide parser training and review. It is
  not manual data entry.

## Enrichment

- Market-data enrichment is disabled by default.
- Stooq CSV parsing exists only as fixture-driven enrichment and cannot
  overwrite magazine source values.
- Provider symbols must currently be derived from exact-width `Stocks` rows,
  using a private `source_id,wkn,name,symbol` map. Source-specific tabs such as
  `Dividend Focus` and `Derivative Tips` are not enrichment candidates until
  their provider-symbol semantics are deliberately designed.
- Arbitrary watchlist symbols are not an approved live-enrichment source.
- Provider metadata/config scaffolding exists for disabled, Stooq CSV, Alpha
  Vantage, Twelve Data, Finnhub, FMP, OpenFIGI, ECB FX, SEC companyfacts, SEC
  EDGAR Form 4, GLEIF LEI, and Bundesbank SDMX.
- Cache request metadata plus provider dry-run request plans can be built
  deterministically for known providers without exposing credential-like
  parameters, reading secrets, or making network calls.
- Dry-run planning reads a local provider/day budget ledger so prior same-day
  usage counts against the hard cap.
- FMP planning defaults to a 235 calls/day hard limit, treats local cache hits
  as budget-free, and carries a 512MB/month bandwidth note.
- OpenFIGI, ECB FX, SEC companyfacts, SEC Form 4, GLEIF LEI, and Bundesbank
  SDMX have provider-specific dry-run descriptors for identifier mapping,
  issuer identity, EUR FX/macro display context, company facts, submissions,
  and Form 4 XML planning. They still make no network calls.
- SEC planning defaults to a conservative 100 calls/day local cap and still
  requires `SEC_USER_AGENT` before any future live access.
- Structured cache records can persist provider response payloads with
  credential-free metadata, freshness fields, source URL hashes, and terms
  review fields. Raw provider URLs and API keys must not be stored; response
  payload keys containing credential markers such as `apiKey`, `token`,
  `secret`, `authorization`, or `password` are rejected recursively before a
  cache file is written.
- SEC EDGAR Form 4 is the preferred planned insider-activity enrichment source
  for US-listed stocks already present in `Stocks`. It requires an identifying
  `SEC_USER_AGENT`, ticker-to-CIK mapping, submissions/Form 4 XML parsing,
  source filing URLs, conservative caching, and explicit not-covered handling
  for non-US or unresolved companies.
- Finviz is comparison/reference only, not the automated insider source of
  record.
