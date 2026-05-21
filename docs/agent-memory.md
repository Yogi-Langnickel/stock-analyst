# Stock Analyst Agent Memory

Status: active
Created: 2026-05-15

## Current Truth

- Stock Analyst is a private family tool for turning family-owned Der Aktionaer
  PDFs into reviewed, source-linked digest rows.
- Source PDFs, extracted text, review notes, spreadsheet IDs, and exports are
  private and must not be committed.
- Local PDF intake can validate one PDF or a folder of PDFs, copy them into
  ignored private storage, record a JSONL manifest with source ID, checksum,
  issue date guess, and processing status, and detect duplicates by checksum.
- Local text extraction is scaffolded behind an injected adapter. PyMuPDF is an
  optional local adapter; tests use deterministic no-network stubs and low-text
  pages are marked for future OCR instead of sending PDFs externally.
- Imported PDF manifests can be summarized with a local extraction quality
  report that emits draft-readiness, missing-file, extraction-failure, and
  OCR-needed counts without exposing extracted page text.
- Imported PDF manifests can also produce a local review queue with
  draft-review, restore-missing-file, local-OCR, and rerun-extraction actions.
  The queue is metadata-only and does not expose extracted page text.
- Local visual/OCR review can render selected PDF pages into ignored private
  storage and optionally run local Tesseract. The command reports artifact
  paths, statuses, hashes, and counts, but not OCR text; missing local tools
  degrade to dependency/status output with no remote OCR or enrichment.
- Local OCR fixture planning is metadata-only through `ocr-fixture-plan`.
  Default `DA_2026_03` fixture coverage includes pages 18-19, 22, 37, 61-63,
  66, and 78-89 with intended targets and expected section labels. If private
  artifacts exist, the command reports paths/statuses/hashes/counts only and
  rejects fixture manifests containing text-bearing keys. The same output now
  includes `artifactReviewPlanning`, which summarizes available/missing render
  and OCR artifact pages and emits exact local `visual-ocr-review` commands for
  creating missing private artifacts.
- Configured Google Drive folders can be listed for PDF metadata only. The
  Drive listing does not download PDFs or inspect PDF content, and optional
  JSONL manifests must stay in ignored private storage because they include
  Drive file identifiers and filenames.
- A local embedded-text recommendation-card extractor exists for labelled card
  rows. It captures printed name, instrument type, WKN, current price, target,
  stop, chance/risk dots, market cap, new/follow-up status, performance since
  recommendation, recommended issue/date, dividend yield/trend, P/S and P/E
  ratios, next report date, and derivative fields such as underlying price,
  base price, Omega/Hebel, and runtime. It is draft-only and emits
  `needs_review`.
- A local section inventory command exists for high-value magazine tables and
  sections. It flags dividend strategy tables, derivative overview tables,
  AKTIONAER depot positions, depot transactions, chart-check pages,
  quick-check tables, statistics context, and low-priority back matter with
  suggested Google Sheet destinations.
- Normal OCR/cost-control scan policy skips the first five
  `Inhalt`/front-matter pages and cuts remote/OCR planning after the first
  detected `Statistik` body section. Keep the `Statistik` page itself as
  context; back matter after it is excluded unless a manual override is
  introduced later. Repeated page-corner/running header labels such as `Inhalt`
  or `Statistik` are not section markers by themselves. Local workbook export
  still scans non-front-matter embedded text across the whole issue so
  later explicit sections such as Chart Check, Quick Check, and depot tables
  are not dropped.
- Remote OCR planning has a 900-page monthly budget guard. Provider adapters
  must block or require manual approval above that budget before making Google
  Vision calls.
- `Aktien im Quick-Check` rows are parser-backed into `Stock Quickcheck` and
  also surface in `Stocks` as previous-recommendation stock rows with split
  current price, price at recommendation, target, stop, and comment fields.
- `Chart-Check` pages are parser-backed into `Chart Check` as explicit
  instrument/WKN rows with the publisher bullet summary and parsed table fields
  such as price, target, stop, 52-week range, performance, dividend yield, and
  next report date. They also surface into `Stocks` by WKN/normalized company,
  remain `needs_review`, and must not invent missing values.
- A local workbook export-plan command can route draft recommendation cards,
  derivative cards, derivative overview rows, dividend strategy rows, AKTIONAER
  depot positions, depot transaction/no-transaction rows, and section-inventory
  audit hints into Google Sheet tab row DTOs without writing to Sheets. Every
  planned row remains `needs_review`, non-exportable, and marked
  manual-review-required.
- Dividend strategy rows preserve otherwise complete high-yield table entries
  when optional market-cap or P/E cells are printed as dash-like missing values;
  those cells normalize to blank workbook cells rather than dropping the row.
- Dividend OCR line normalization can split collapsed OCR table lines into the
  existing strict row-major and continuation parser shapes. Rows touched by
  that helper carry `ocr_line_normalized` in `extractionNotes` and still remain
  `needs_review`.
- Derivative overview rows apply retrospective entry/current/performance/
  target/stop/recommendation metrics only when the parsed base-row count and
  retrospective-row count match exactly. On mismatch, keep the base rows and
  leave retrospective metric fields blank instead of applying metrics by
  position.
- Instrument dry-run rows must populate row-level `date updated` as the last
  field. Stocks initialize it from an explicit import/issue date when
  available, otherwise from the command's current UTC date. Section inventories,
  index context, statistics, and broad constituent lists must not fan out into
  `Stocks`; parsed quick-check, chart-check, and other explicitly mentioned
  stock rows go there.
- Active workbook tabs are pruned to the layout-only `Navigation Dashboard`
  plus data-backed surfaces: `Stocks`, `Derivative Tips`, `AKTIONAER Depot`,
  `Depot Transactions`, `Chart Check`, `Stock Quickcheck`, `Dividend Focus`,
  and `Extraction Audit`. Planned tabs are removed from the live workbook until
  they have real emitted rows; pruning is limited to project-known generated
  tabs so manual user tabs survive.
- `Navigation Dashboard` is a static reviewer cockpit only. Do not emit
  workbook rows to it, do not trigger enrichment from it, and preserve its body
  rows during generated data clears. Its row-count cells are spreadsheet
  formulas over active tab data ranges only.
- Workbook identity rule: once a stock exists, later magazine mentions update
  the existing instrument row rather than append duplicates. Options and
  derivatives all live in `Derivative Tips` for now and are different: update
  only the same derivative/security, normally by derivative WKN/ISIN; a new
  call or put for the same underlying is a new row when the derivative WKN/ISIN
  differs. Depot snapshots and transactions remain issue/event-specific history
  rows.
- Google Sheets export now also applies the `Stocks` identity rule against
  existing sheet rows across prior issues by WKN, falling back to normalized
  company name when WKN is missing. It merges issue/page provenance rather than
  appending duplicate stock rows.
- Stock rows use English sheet labels. `Dividendenrendite` maps to
  `Dividend Yield`, `KUV 26e` maps to `P/S Ratio 26e`, `KGV 26e` maps to
  `P/E Ratio 26e`, `Marktkap.` / `Marktkapitalisierung` maps to `Market Cap`,
  and the printed chance/risk dot ratings map to `Chance/Risk`. `Kein Kauf`
  maps to `recommendation_status=no_buy`.
- In `Stocks`, `Current Price*` is reserved for provider-backed enrichment and
  stays blank in local magazine-only workbook plans. Printed source values go
  to `Magazine Price` with `Magazine Price As Of`; `Price at Recommendation`
  remains the printed recommendation price when available.
- Source-specific review tabs use printed-price labels such as
  `Magazine Price`, `Magazine Current Price`, and
  `Magazine Price at Recommendation` so they are not mistaken for live
  provider-backed prices.
- Local workbook export-plan construction now requires each planned row to
  target an active workbook tab and exactly match that tab's configured width;
  stale short rows fail before JSON serialization or any Google write path can
  pad or truncate them.
- Future currency display should preserve printed source prices and add a
  dashboard/display toggle for `EUR`, `USD`, and `AUD`. Converted values must
  be derived enrichment fields with FX date/source metadata, not replacements
  for magazine values.
- A page-by-page extraction map would help define which pages/sections populate
  which tabs and fields. Treat it as parser training/review guidance, not
  manual data entry.
- `Refinement` tab writes must preserve reviewer-owned columns for existing
  page rows: section, page title, useful-info, suggested destination, and
  reviewer notes. Regeneration may update parser hints/reasons/date metadata,
  but must not wipe completed manual review fields.
- 2026-05-21 full-issue `Refinement` review confirmed that page labels are
  issue-specific training signals, not page-number rules. General recognition
  rules: compact ad-marker pages, cover/editorial/front matter, books,
  impressum/last-page, social-media filler, generic crypto/forex/commodity/ETF
  surfaces, and index-only pages are normally not useful extraction rows unless
  a focused parser later owns them; explicit section markers such as
  title-story, news, statistics, Dax/Wall-Street/Rohstoff checks, chart-check,
  and quick-check should beat generic financial keywords. Generic stock/title
  story/derivative pages need stronger extraction signals before marking
  `useful_info=yes`.
- Local visual review is available through `scripts/stock-analyst
  visual-ocr-review`. It renders selected pages to ignored private PNG
  artifacts using PyMuPDF and can optionally run local Tesseract OCR. Command
  output must stay privacy-safe: paths, dimensions, hashes, counts, statuses,
  and failure reasons only; no OCR text in JSON output. On 2026-05-18 local
  Tesseract 5.5.2 with `deu` and `eng` language data extracted OCR text for
  `DA_2026_03` pages 18-19, 22, 37, 61-63, and 66 into ignored private
  artifacts.
- Market data enrichment is disabled by default. Stooq CSV parsing exists only
  as fixture-driven enrichment and cannot overwrite magazine source values.
- Live enrichment must wait until magazine extraction has populated workbook
  rows. Provider symbols must currently be derived from exact-width `Stocks`
  rows only, using a private `source_id,wkn,name,symbol` map; source-specific
  tabs such as `Dividend Focus` and `Derivative Tips` are not enrichment
  candidate sources until their provider-symbol semantics are deliberately
  designed. Arbitrary watchlist symbols are not an approved live-enrichment
  source.
  Provider metadata/config scaffolding exists for disabled, Stooq CSV, Alpha
  Vantage, Twelve Data, FMP, and SEC companyfacts, but live adapters are not
  implemented. Cache request metadata and FMP dry-run request plans can be
  built deterministically for known providers without exposing credential-like
  parameters, reading secrets, or making network calls. Dry-run planning reads a
  local provider/day budget ledger so prior same-day usage counts against the
  hard cap. FMP planning defaults to a 235 calls/day hard limit, treats local
  cache hits as budget-free, and carries a 512MB/month bandwidth note.
  Structured cache records can persist provider response payloads with
  credential-free metadata, freshness fields, source URL hashes, and terms
  review fields; raw provider URLs and API keys must not be stored.
- SEC EDGAR Form 4 is the preferred planned insider-activity enrichment source
  for US-listed stocks already present in `Stocks`. It requires an identifying
  `SEC_USER_AGENT`, ticker-to-CIK mapping, SEC submissions/Form 4 XML parsing,
  source filing URLs, conservative caching, and explicit not-covered handling
  for non-US or unresolved companies. Finviz is comparison/reference only, not
  the automated source of record.
- Manual review remains mandatory before family-visible digest rows or exports.
- Next real-corpus unblock is user-provided private PDFs from the last two years
  in ignored local `data/private/issues/` or a private Drive folder. Local
  folder handoff is fastest because current commands do not need Drive/Sheets.
- Use service account first for future private Drive/Sheets automation unless
  per-user Google identity becomes a product requirement.
- Dev Google Drive/Sheets IDs are configured for the service account
  `stock-analyst@stock-analyst-496512.iam.gserviceaccount.com`; see
  `unblockme.md` for the non-secret folder/sheet IDs and smoke command.
- Target Drive workflow: dad drops each weekly PDF into the shared Drive folder
  between Wednesday and Thursday; a future EventBridge/Lambda preprocessor may
  check hourly on those days for new files and record lightweight metadata, while
  heavy OCR/parsing/review remains local-first.
- Target workbook name is `Der Aktionär Summaries`; keep the live workbook
  trimmed to data-backed tabs until the parser emits real rows for broader
  asset-class dashboards.

## Commands

- `scripts/stock-analyst which-python`: show the interpreter selected by the
  wrapper. It prefers `.venv/bin/python`, then `python3.13`, then `python3`.
- `scripts/stock-analyst compile`: compile `src` and `tests` through the
  selected interpreter.
- `scripts/stock-analyst test`: run the unittest suite through the selected
  interpreter.
- `scripts/stock-analyst workbook-export-plan ./data/private/issues/DA_2026_03.pdf`:
  run the local workbook plan through the venv-aware wrapper.
- `scripts/stock-analyst market-data-plan --env-file .env --workbook-plan-file
  ./data/private/workbook-plan.json --symbol-map-file
  ./data/private/market-symbol-map.csv`: dry-run provider enrichment planning
  from magazine-backed workbook rows with local env-file config and no network.
- `scripts/stock-analyst market-symbol-map-template --workbook-plan-file
  ./data/private/workbook-plan.json --output
  ./data/private/market-symbol-map.csv`: refresh the private mapping workfile
  from magazine rows without provider calls; existing symbols are preserved.
- `scripts/stock-analyst google-sheets-export-plan
  ./data/private/workbook-plan.json --env-file .env`: write reviewer-gated
  workbook-plan rows to Google Sheets, replacing rows for the same issue in
  affected tabs by default and making no enrichment provider calls.
- `PYTHONPYCACHEPREFIX=.pycache python3 -m compileall src tests`
- `PYTHONPATH=src python3 -m unittest discover tests`
- `PYTHONPATH=src python3 -m stock_analyst.cli process-pdf --dry-run ./data/private/issue.pdf`
- `PYTHONPATH=src python3 -m stock_analyst.cli import-pdf-folder --dry-run ./data/private/issues`
- `PYTHONPATH=src python3 -m stock_analyst.cli extraction-quality-report ./data/uploads/uploads.jsonl`
- `PYTHONPATH=src python3 -m stock_analyst.cli review-queue ./data/uploads/uploads.jsonl`
- `PYTHONPATH=src python3 -m stock_analyst.cli visual-ocr-review ./data/private/issues/DA_2026_03.pdf --pages 22,62-63`
- `PYTHONPATH=src python3 -m stock_analyst.cli visual-ocr-review ./data/private/issues/DA_2026_03.pdf --page 22 --ocr --write-ocr-text`
- `PYTHONPATH=src python3 -m stock_analyst.cli ocr-fixture-plan --pdf ./data/private/issues/DA_2026_03.pdf --artifact-dir ./data/private/visual-ocr`
- `scripts/stock-analyst ocr-fixture-plan --pdf ./data/private/issues/DA_2026_03.pdf --artifact-dir ./data/private/visual-ocr`
- `PYTHONPATH=src python3 -m stock_analyst.cli recommendation-cards ./data/private/issues/DA_2026_03.pdf`
- `PYTHONPATH=src python3 -m stock_analyst.cli section-inventory ./data/private/issues/DA_2026_03.pdf`
- `PYTHONPATH=src python3 -m stock_analyst.cli dividend-strategy ./data/private/issues/DA_2026_03.pdf`
- `PYTHONPATH=src python3 -m stock_analyst.cli workbook-export-plan ./data/private/issues/DA_2026_03.pdf`
- `PYTHONPATH=src python3 -m stock_analyst.cli google-access-smoke --env-file .env`
- `PYTHONPATH=src python3 -m stock_analyst.cli google-drive-pdfs --env-file .env`
- `PYTHONPATH=src python3 -m stock_analyst.cli google-drive-pdfs --env-file .env --manifest ./data/private/drive-pdf-metadata.jsonl`
- `PYTHONPATH=src python3 -m stock_analyst.cli google-sheets-bootstrap --env-file .env`

## Performance And Context Notes

- Preserve checksum dedupe before expensive OCR or enrichment.
- Run embedded-text recommendation-card extraction before OCR; queue OCR only
  for low-text pages or missing fields that matter to review.
- Keep OCR/PDF extraction and provider enrichment as separate queues so provider
  latency cannot block PDF review.
- Cache future market-data responses under ignored `data/market-cache` before
  enabling live providers.
- Do not run provider calls in tests; use deterministic fixtures.
- Use `.contextignore` to keep private PDFs, exports, caches, and generated
  artifacts out of broad agent context loads.

## Read Next

- `AGENTS.md` for hard privacy/source rules.
- `docs/implementation-plan.md` for milestone details.
- `docs/free-market-data-options.md` before changing enrichment behavior.
- `docs/google-sheets-layout.md` before changing export destinations.
- `docs/ocr-options.md` before enabling local or remote OCR.
- `unblockme.md` before configuring Drive/Sheets, enabling live providers, or
  asking for user PDF handoff.
