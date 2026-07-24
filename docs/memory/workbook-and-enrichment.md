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
- Paired value/action tables are discovered from their layout headers rather
  than fixed page numbers. Emit rows only when the nearest preceding or
  co-located value table and action table have equal row counts and names in
  the same order.
  Missing, empty, count-mismatched, or name-mismatched candidates must emit a
  metadata-only `paired_action_table_candidate_exception` blocker in
  `Extraction Audit`; never silently discard them or include source text in the
  exception.
- Page-level `Top-Tipp` and `Verkaufssignal` wording must not set the action on
  unrelated cards. Use the signal only when it occurs inside that card's parsed
  block, or when the page contains exactly one card candidate. Established
  derivative source literals `Dabei-bleiben` and `Ausgestoppt` map to reviewer
  actions `Hold` and `Sell`.

## Active Tabs And Identity

- Active Google Sheet tabs are the layout-only `Search`, `Aktuell`, and
  newest-first `DA_YYYY_NN` issue tabs. Hidden generated summary/dashboard tabs
  are retired and bootstrap deletes them instead of recreating them.
- `Aktuell` is generated for the current workbook-export plan. It contains
  only source-linked explicit publisher Buy, Sell, Hold, and Wait actions and
  is excluded from the search index to avoid duplicating the latest issue.
- The merged `Search!C1:E1` field matches a company name or WKN against issue
  tabs only. Search has no frozen rows. Stock and
  derivative results use the same full columns and values as their issue-tab
  tables, remain vertically stacked, and sort by issue descending; generated
  index columns `S:AM` remain hidden.
- Search refresh and workbook export reconcile managed protections after all
  generated writes. `Search` is protected except for `C1:E1`; `Aktuell` and
  every existing or newly created `DA_YYYY_NN` tab are fully protected. The
  service account remains an allowed editor, and unrelated manual protections
  are preserved.
- Google Sheets export replaces `Aktuell` on each
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
  The approval application boundary enforces the same evidence rule for final
  `approved` and `rejected` decisions even when called directly in code, not
  only when loading CSV rows.
- Local workbook-plan schemas may still emit canonical `Stocks`, derivatives,
  dividend, depot, insider, and audit rows for extraction and validation.
  Google export omits those retired live-tab rows.
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
- Corpus refinement summaries aggregate section, destination, and parser-hint
  counts across local issues only. They must not include page titles, extracted
  source text, page rows, reviewer notes, or approval/export decisions.

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
