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

No dependencies are installed by default in this scaffold.

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

Inventory important magazine sections and table surfaces, including dividend
strategy tables, derivative overview tables, AKTIONAER depot snapshots,
transaction tables, chart-check pages, quick-check tables, statistics, and
low-priority back matter:

```sh
PYTHONPATH=src python3 -m stock_analyst.cli section-inventory ./data/private/issues/DA_2026_03.pdf
```

The manifest records only local metadata such as checksum, guessed issue date,
private storage filename, and processing status. Source PDFs and extracted text
remain in ignored private storage and must not be committed.

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

## Documentation

- [Implementation plan](docs/implementation-plan.md)
- [Free market data options](docs/free-market-data-options.md)
- [Google Sheets layout](docs/google-sheets-layout.md)
- [OCR options](docs/ocr-options.md)
- [Persona review and revisions](docs/persona-review.md)
- [Security and privacy](docs/security-and-privacy.md)
- [Unblock steps](unblockme.md)
