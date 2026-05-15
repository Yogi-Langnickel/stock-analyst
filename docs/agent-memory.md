# Stock Analyst Agent Memory

Status: active
Created: 2026-05-15

## Current Truth

- Stock Analyst is a private family tool for turning family-owned Der Aktionaer
  PDFs into reviewed, source-linked digest rows.
- Source PDFs, extracted text, review notes, spreadsheet IDs, and exports are
  private and must not be committed.
- Local PDF intake can validate PDFs, copy them into ignored private storage,
  record a JSONL manifest with source ID, checksum, issue date guess, and
  processing status, and detect duplicates by checksum.
- Local text extraction is scaffolded behind an injected adapter. PyMuPDF is an
  optional local adapter; tests use deterministic no-network stubs and low-text
  pages are marked for future OCR instead of sending PDFs externally.
- Market data enrichment is disabled by default. Stooq CSV parsing exists only
  as fixture-driven enrichment and cannot overwrite magazine source values.
  Provider metadata/config scaffolding exists for disabled, Stooq CSV, Alpha
  Vantage, Twelve Data, and SEC companyfacts, but live adapters are not
  implemented. Cache request metadata can be built deterministically for known
  providers without creating files, exposing credential-like parameters, or
  making network calls.
- Manual review remains mandatory before family-visible digest rows or exports.

## Commands

- `PYTHONPYCACHEPREFIX=.pycache python3 -m compileall src tests`
- `PYTHONPATH=src python3 -m unittest discover tests`
- `PYTHONPATH=src python3 -m stock_analyst.cli process-pdf --dry-run ./data/private/issue.pdf`

## Performance And Context Notes

- Preserve checksum dedupe before expensive OCR or enrichment.
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
- `unblockme.md` before configuring remotes or enabling live providers.
