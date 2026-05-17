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
- Configured Google Drive folders can be listed for PDF metadata only. The
  Drive listing does not download PDFs or inspect PDF content, and optional
  JSONL manifests must stay in ignored private storage because they include
  Drive file identifiers and filenames.
- A local embedded-text recommendation-card extractor exists for labelled card
  rows. It captures printed name, instrument type, WKN, current price, target,
  stop, chance/risk dots, market cap, new/follow-up status, performance since
  recommendation, recommended issue/date, dividend yield/trend, KUV/KGV, next
  report date, and derivative fields such as underlying price, base price,
  Omega/Hebel, and runtime. It is draft-only and emits `needs_review`.
- A local section inventory command exists for high-value magazine tables and
  sections. It flags dividend strategy tables, derivative overview tables,
  AKTIONAER depot positions, depot transactions, chart-check pages,
  quick-check tables, statistics context, and low-priority back matter with
  suggested Google Sheet destinations.
- A local workbook export-plan command can route draft recommendation cards,
  derivative cards, dividend strategy rows, and section-inventory audit hints
  into Google Sheet tab row DTOs without writing to Sheets. Every planned row
  remains `needs_review`, non-exportable, and marked manual-review-required.
- Stocks dry-run rows must populate row-level `date updated` from an explicit
  import/issue date when available, otherwise from the command's current UTC
  date. Section inventories, index context, statistics, quick-check tables, and
  broad constituent lists must not fan out into `Stocks`; only explicitly
  mentioned stock rows go there.
- Market data enrichment is disabled by default. Stooq CSV parsing exists only
  as fixture-driven enrichment and cannot overwrite magazine source values.
  Provider metadata/config scaffolding exists for disabled, Stooq CSV, Alpha
  Vantage, Twelve Data, FMP, and SEC companyfacts, but live adapters are not
  implemented. Cache request metadata and FMP dry-run request plans can be
  built deterministically for known providers without creating files, exposing
  credential-like parameters, reading secrets, or making network calls. FMP
  planning defaults to a 235 calls/day hard limit, treats local cache hits as
  budget-free, and carries a 512MB/month bandwidth note.
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
- Target workbook name is `Der Aktionär Summaries`; start with a `Navigation
  Dashboard` plus asset-class dashboard tabs for Stocks, Commodities, Options,
  Forex, and Example Portfolios, with specialized daily enrichment areas per
  asset class.

## Commands

- `scripts/stock-analyst which-python`: show the interpreter selected by the
  wrapper. It prefers `.venv/bin/python`, then `python3.13`, then `python3`.
- `scripts/stock-analyst compile`: compile `src` and `tests` through the
  selected interpreter.
- `scripts/stock-analyst test`: run the unittest suite through the selected
  interpreter.
- `scripts/stock-analyst workbook-export-plan ./data/private/issues/DA_2026_03.pdf`:
  run the local workbook plan through the venv-aware wrapper.
- `scripts/stock-analyst market-data-plan --env-file .env --symbol AAPL`:
  dry-run FMP enrichment planning with local env-file config and no network.
- `PYTHONPYCACHEPREFIX=.pycache python3 -m compileall src tests`
- `PYTHONPATH=src python3 -m unittest discover tests`
- `PYTHONPATH=src python3 -m stock_analyst.cli process-pdf --dry-run ./data/private/issue.pdf`
- `PYTHONPATH=src python3 -m stock_analyst.cli import-pdf-folder --dry-run ./data/private/issues`
- `PYTHONPATH=src python3 -m stock_analyst.cli extraction-quality-report ./data/uploads/uploads.jsonl`
- `PYTHONPATH=src python3 -m stock_analyst.cli review-queue ./data/uploads/uploads.jsonl`
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
