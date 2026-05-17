# Stock Analyst

Private family tool for processing Der Aktionaer PDF issues into reviewed,
source-linked digests of magazine mentions, market context, and instrument
details.

This summarizes magazine content for private family reading. It is not personal
financial advice, a recommendation, or a suitability assessment.

## Current Status

Initialized planning and scaffold. The current local-first prototype can
validate and store PDFs, record checksum/issue-date manifest metadata, detect
duplicates, scaffold local text extraction status, report embedded-text quality
for imported PDFs, extract draft recommendation-card rows from embedded text,
inventory high-value magazine table/section surfaces, and keep all rows
draft-only until manual review.

## Intended Users

- Non-technical family uploader.
- Reviewer who approves or edits extracted rows.
- Family readers who see only approved digest content.

## Core Flow

1. Upload one or more PDFs.
1. Extract text, tables, image text, page references, and instrument mentions.
1. Generate draft recommendation rows.
1. Reviewer approves, edits, or rejects rows.
1. Approved rows appear in the family digest and can export to Google Sheets.

## Local Development

Use the local wrapper so commands run through `.venv/bin/python` when the
virtual environment exists. This avoids relying on interactive shell activation:

```sh
scripts/stock-analyst which-python
scripts/stock-analyst compile
scripts/stock-analyst test
```

The raw commands remain:

```sh
PYTHONPYCACHEPREFIX=.pycache python3 -m compileall src tests
PYTHONPATH=src python3 -m unittest discover tests
```

Dry-run a local PDF intake without copying, OCR, extraction, external calls, or
export:

```sh
PYTHONPATH=src python3 -m stock_analyst.cli process-pdf --dry-run ./data/private/issue.pdf
```

Store a validated PDF into ignored private local upload storage:

```sh
PYTHONPATH=src python3 -m stock_analyst.cli process-pdf ./data/private/issue.pdf
```

Validate a local folder of PDFs without copying anything:

```sh
PYTHONPATH=src python3 -m stock_analyst.cli import-pdf-folder --dry-run ./data/private/issues
```

Import a local folder of PDFs into ignored private upload storage:

```sh
PYTHONPATH=src python3 -m stock_analyst.cli import-pdf-folder --recursive ./data/private/issues
```

Review local embedded-text extraction quality for imported PDFs without Drive,
Sheets, market data, OCR, LLM, or network calls:

```sh
PYTHONPATH=src python3 -m stock_analyst.cli extraction-quality-report ./data/uploads/uploads.jsonl
```

Generate a local review queue from the same manifest, including draft-review and
reprocess-needed actions:

```sh
PYTHONPATH=src python3 -m stock_analyst.cli review-queue ./data/uploads/uploads.jsonl
```

Extract draft recommendation cards from a private local PDF. This uses embedded
PDF text only, does not call OCR, Drive, Sheets, market data, or LLM providers,
and marks rows as `needs_review`:

```sh
PYTHONPATH=src python3 -m stock_analyst.cli recommendation-cards ./data/private/issues/DA_2026_03.pdf
```

With the wrapper:

```sh
scripts/stock-analyst recommendation-cards ./data/private/issues/DA_2026_03.pdf
scripts/stock-analyst workbook-export-plan ./data/private/issues/DA_2026_03.pdf
```

`workbook-export-plan` is still a dry run. Instrument rows include a row-level
`date updated` value as the last field. Stock rows initialize it from the
import/issue date when available, or from the command's current UTC date. Broad
index or constituent-table context is kept as review/audit context and does not
create stock rows unless a stock is explicitly mentioned as a recommendation
row.

Render pages for private visual review and optional local OCR:

```sh
scripts/stock-analyst visual-ocr-review ./data/private/issues/DA_2026_03.pdf --pages 22,62-63 --render
scripts/stock-analyst visual-ocr-review ./data/private/issues/DA_2026_03.pdf --page 22 --ocr --write-ocr-text
```

The command writes rendered page PNGs, and optionally OCR text, under ignored
private storage. Its JSON output contains file paths, sizes, hashes, and status
metadata only; it does not print OCR text or call remote OCR providers.

Inventory important magazine sections and table surfaces, including dividend
strategy tables, derivative overview tables, AKTIONAER depot snapshots,
transaction tables, chart-check pages, quick-check tables, statistics, and
low-priority back matter:

```sh
PYTHONPATH=src python3 -m stock_analyst.cli section-inventory ./data/private/issues/DA_2026_03.pdf
```

Check Google Drive/Sheets access after the service account JSON is stored in an
ignored private path and a local env file points at the configured folder/sheet:

```sh
PYTHONPATH=src python3 -m stock_analyst.cli google-access-smoke --env-file .env
```

This reads only Drive folder metadata and spreadsheet/tab names. It does not
copy PDFs, write rows, run extraction, or expose the service-account private
key.

List PDF metadata in the configured Drive folder without downloading source
PDFs:

```sh
PYTHONPATH=src python3 -m stock_analyst.cli google-drive-pdfs --env-file .env
```

Optionally write a metadata-only JSONL manifest to ignored private storage:

```sh
PYTHONPATH=src python3 -m stock_analyst.cli google-drive-pdfs --env-file .env --manifest ./data/private/drive-pdf-metadata.jsonl
```

Treat this output as private because it includes Drive file identifiers and
filenames. It does not contain PDF text, credentials, or downloaded PDF bytes.

Create any missing workbook tabs from `docs/google-sheets-layout.md` and write
stable header rows without exporting private PDF content:

```sh
PYTHONPATH=src python3 -m stock_analyst.cli google-sheets-bootstrap --env-file .env
```

Use `--skip-headers` if you only want to create missing tabs and preserve
existing first-row labels.

Write reviewer-gated workbook-plan rows into the configured Google Sheet:

```sh
scripts/stock-analyst google-sheets-export-plan ./data/private/workbook-plan.json --env-file .env
```

By default this replaces existing rows for the same issue in the affected tabs,
preserves rows from other issues, and makes no enrichment provider calls.

The manifest records only local metadata such as checksum, guessed issue date,
private storage filename, and processing status. Source PDFs and extracted text
remain in ignored private storage and must not be committed.

Plan local provider enrichment requests without making network calls. This uses
the hard local budget from `.env`. For the real workflow, derive candidates
from magazine-backed workbook rows and a private provider-symbol map:

```sh
scripts/stock-analyst workbook-export-plan ./data/private/issues/DA_2026_03.pdf > ./data/private/workbook-plan.json
scripts/stock-analyst market-symbol-map-template --workbook-plan-file ./data/private/workbook-plan.json --output ./data/private/market-symbol-map.csv
scripts/stock-analyst market-data-plan --env-file .env --workbook-plan-file ./data/private/workbook-plan.json --symbol-map-file ./data/private/market-symbol-map.csv
```

Do not use enrichment provider API calls before magazine rows have been
populated into the workbook flow. Manual `--symbol` and `--symbol-file` inputs
are development-only and are not an approved source for live enrichment.
`market-symbol-map-template` is safe to run repeatedly: it uses only local
workbook-plan data, preserves existing symbols in the private CSV, and adds new
magazine instruments with `needs_symbol_lookup`.

Run the local scheduled task manually. It imports new local PDFs, refreshes the
local extraction quality report, and only plans market-data enrichment when
`STOCK_ANALYST_WORKBOOK_PLAN_FILE` points at a magazine-backed workbook plan:

```sh
scripts/stock-analyst-local-run
```

Local PDF intake does not require Google Drive or Google Sheets credentials.
Those will only be needed later to sync source PDFs into a private Drive folder
or export approved, reviewed rows into a configured Sheet.

For the next real-corpus validation slice, put private PDFs in ignored local
`data/private/issues/` or a private Google Drive folder following
[unblockme.md](unblockme.md). A local folder is fastest because the current
pipeline can import and report extraction quality without any network provider.

Future dependency setup should use a virtual environment:

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
```

After setup, `scripts/stock-analyst ...` automatically uses `.venv/bin/python`;
manual activation is optional for interactive work.

## Documentation

- [Implementation plan](docs/implementation-plan.md)
- [Free market data options](docs/free-market-data-options.md)
- [Google Sheets layout](docs/google-sheets-layout.md)
- [Local scheduling](docs/local-scheduling.md)
- [OCR options](docs/ocr-options.md)
- [Persona review and revisions](docs/persona-review.md)
- [Security and privacy](docs/security-and-privacy.md)
- [Unblock steps](unblockme.md)
