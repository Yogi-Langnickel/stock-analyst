# Stock Analyst Agent Memory

Status: active
Created: 2026-05-15
Last compacted: 2026-06-06

## Current Truth

- Stock Analyst is a private family tool for turning family-owned Der Aktionaer
  PDFs into reviewed, source-linked digest rows.
- Source PDFs, extracted text, review notes, spreadsheet IDs, Drive file IDs,
  credentials, and exports are private and must not be committed.
- Local PDF intake can validate one PDF or a folder, copy PDFs into ignored
  private storage, record metadata-only JSONL manifests, and dedupe by
  checksum.
- The local private corpus is present under ignored `data/private/issues/`
  through latest issue `DA_2026_25.pdf`. Corpus availability is no longer a
  blocker; use metadata-only `corpus-status` to verify counts, latest issue,
  malformed filenames, and filename gaps without reading PDF contents. A
  `local_corpus_files_available` status means only matching local files are
  present; it does not imply extraction success, workbook readiness,
  recommendation coverage, market-data readiness, exportability, or
  family-visible readiness.
- Extraction is local-first. PyMuPDF and Tesseract are optional local adapters;
  tests use deterministic no-network stubs. Low-text pages become local OCR
  work items, not remote uploads.
- Visual/OCR commands may report artifact paths, statuses, dimensions, hashes,
  counts, and failure reasons only. They must not print OCR text or source PDF
  text in JSON or logs.
- Remote OCR planning has a 900-page monthly budget guard. Provider adapters
  must block or require manual approval above that budget before making Google
  Vision calls.
- Manual review remains mandatory before family-visible digest rows or exports.
  Parser rows stay `needs_review`, non-exportable, and marked
  manual-review-required until reviewed.
- Normal scan policy skips the first five `Inhalt`/front-matter pages and cuts
  remote/OCR planning after the first detected `Statistik` body section. Local
  workbook export still scans non-front-matter embedded text across the whole
  issue so later explicit sections are not dropped.
- Workbook/export routing, row identity, active tabs, Aktuell
  Recommendations, market-data provider metadata, and no-extra-key enrichment
  candidates live in `docs/memory/workbook-and-enrichment.md`.
- Active Google Sheet tabs are `Search`, `Aktuell`, and newest-first
  `DA_YYYY_NN` issue tabs. The former generated summary/dashboard tabs are
  retired from the live workbook and pruned by bootstrap.
- `Aktuell` is generated quick-review triage for explicit publisher Buy, Sell,
  Hold, and Wait actions in the current workbook-export plan only. It is
  excluded from `Search` so the latest issue is not duplicated.
- The merged `Search!C1:E1` field matches company names and WKNs against issue
  tabs only. Search has no frozen rows. Stock and
  derivative results are stacked vertically with their full reviewer values and
  action colors. `Source` is column A for both sections. Results sort by numeric
  issue year/week descending and source page ascending.
- Search refresh and workbook export protect `Search`, `Aktuell`, and all
  `DA_YYYY_NN` tabs after generated writes finish. Only merged `Search!C1:E1`
  remains editable; the service account is retained as a protection editor.
- Market-data enrichment is disabled by default. Provider metadata/config
  scaffolding exists for Stooq CSV, Alpha Vantage, Twelve Data, Finnhub, FMP,
  OpenFIGI, ECB FX, SEC companyfacts, SEC EDGAR Form 4, GLEIF LEI, and
  Bundesbank SDMX, but live adapters are not implemented. `market-data-plan`
  does not implicitly select FMP for manual symbols; dry-run provider planning
  requires explicit provider config.
- OpenFIGI, ECB FX, SEC companyfacts, SEC Form 4, GLEIF LEI, and Bundesbank
  SDMX have no-network dry-run descriptors for identifier mapping, issuer
  identity, EUR FX/macro display context, fundamentals, and insider planning.
  They remain live-adapter-disabled until cache/throttle/fair-access review is
  complete.
- Remaining corpus work is parser/review coverage against local private issues,
  not PDF availability. Do not ask for a new PDF handoff unless a specific
  issue is absent from `corpus-status`.
- Use `corpus-refinement-summary` for aggregate parser-training coverage across
  local issues; it must stay source-text-free and does not imply review,
  approval, exportability, or family-visible readiness.
- Use service account first for future private Drive/Sheets automation unless
  per-user Google identity becomes a product requirement.
- Dev Google Drive/Sheets access is configured through ignored local
  environment values and a private service-account credentials file; see
  `unblockme.md` for variable names and smoke commands. Never place live
  account addresses or Drive/Sheets identifiers in tracked documentation.
- Target Drive workflow: dad drops each weekly PDF into the shared Drive folder
  between Wednesday and Thursday; a future EventBridge/Lambda preprocessor may
  check hourly for new files and record lightweight metadata, while heavy
  OCR/parsing/review remains local-first.
- Target workbook name is `Der Aktionär Summaries`; keep the live workbook
  trimmed to data-backed tabs until parsers emit real rows for broader
  asset-class dashboards.

## Commands

- `scripts/stock-analyst which-python`: show the interpreter selected by the
  wrapper. It prefers `.venv/bin/python`, then `python3.13`, then `python3`.
- `scripts/stock-analyst compile`: compile `src` and `tests`.
- `scripts/stock-analyst test`: run the unittest suite.
- `scripts/stock-analyst workbook-export-plan ./data/private/issues/DA_2026_03.pdf`
- `scripts/stock-analyst market-symbol-map-template --workbook-plan-file ./data/private/workbook-plan.json --output ./data/private/market-symbol-map.csv`
- `scripts/stock-analyst market-data-plan --env-file .env --workbook-plan-file ./data/private/workbook-plan.json --symbol-map-file ./data/private/market-symbol-map.csv`
- `scripts/stock-analyst workbook-approval-template ./data/private/workbook-plan.json --output ./data/private/review/approvals.csv`: create the private reviewer approval CSV with exact row hashes.
- `scripts/stock-analyst workbook-approval-audit ./data/private/workbook-plan.json --approval-csv ./data/private/review/approvals.csv --output ./data/private/reviewed-workbook-plan.json`: apply reviewer approval state without printing row content.
- `scripts/stock-analyst google-sheets-export-plan ./data/private/reviewed-workbook-plan.json --env-file .env`:
  write approved rows with `exportMode=approved_family_export`; add
  `--allow-draft-rows` only for private reviewer workbook triage, which returns
  `exportMode=private_draft_review_export` and `familyVisibleSafe=false`.
- `scripts/stock-analyst ocr-fixture-plan --pdf ./data/private/issues/DA_2026_03.pdf --artifact-dir ./data/private/visual-ocr`
- `PYTHONPYCACHEPREFIX=.pycache python3 -m compileall src tests`
- `PYTHONPATH=src python3 -m unittest discover tests`
- `PYTHONPATH=src python3 -m stock_analyst.cli corpus-status ./data/private/issues`
  and `scripts/stock-analyst corpus-status ./data/private/issues`: report
  local filename metadata only (`DA_YYYY_NN.pdf` count/latest/gaps/malformed
  names); no PDF reads, OCR, extraction, workbook planning, providers, or
  network calls.
- `PYTHONPATH=src python3 -m stock_analyst.cli corpus-refinement-summary ./data/private/issues --limit 1`:
  aggregate local refinement coverage without page titles, source text, page
  rows, reviewer notes, providers, or network calls.
- `PYTHONPATH=src python3 -m stock_analyst.cli process-pdf --dry-run ./data/private/issue.pdf`
- `PYTHONPATH=src python3 -m stock_analyst.cli import-pdf-folder --dry-run ./data/private/issues`
- `PYTHONPATH=src python3 -m stock_analyst.cli extraction-quality-report ./data/uploads/uploads.jsonl`
- `PYTHONPATH=src python3 -m stock_analyst.cli review-queue ./data/uploads/uploads.jsonl`
- `PYTHONPATH=src python3 -m stock_analyst.cli visual-ocr-review ./data/private/issues/DA_2026_03.pdf --pages 22,62-63`
- `PYTHONPATH=src python3 -m stock_analyst.cli recommendation-cards ./data/private/issues/DA_2026_03.pdf`
- `PYTHONPATH=src python3 -m stock_analyst.cli section-inventory ./data/private/issues/DA_2026_03.pdf`
- `PYTHONPATH=src python3 -m stock_analyst.cli dividend-strategy ./data/private/issues/DA_2026_03.pdf`
- `PYTHONPATH=src python3 -m stock_analyst.cli workbook-export-plan ./data/private/issues/DA_2026_03.pdf`
- `PYTHONPATH=src python3 -m stock_analyst.cli google-access-smoke --env-file .env`
  reports only redacted Drive/Sheets identifiers and tab counts; stdout must not
  include service-account email, folder names, spreadsheet titles, or tab names.
- `PYTHONPATH=src python3 -m stock_analyst.cli google-drive-pdfs --env-file .env`
  lists redacted Drive metadata; raw Drive-ID manifests require
  `--include-private-identifiers` and a private output path, and command stdout
  must stay redacted even after writing the private manifest.
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
- `docs/memory/workbook-and-enrichment.md` for workbook, Sheets, and enrichment
  rules.
- `docs/implementation-plan.md` for milestone details.
- `docs/free-market-data-options.md` before changing enrichment behavior.
- `docs/google-sheets-layout.md` before changing export destinations.
- `docs/ocr-options.md` before enabling local or remote OCR.
- `unblockme.md` before configuring Drive/Sheets, enabling live providers, or
  asking for user PDF handoff.
