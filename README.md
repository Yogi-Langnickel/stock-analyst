# Stock Analyst

Private family tool for processing Der Aktionaer PDF issues into reviewed,
source-linked digests of magazine mentions, market context, and instrument
details.

This summarizes magazine content for private family reading. It is not personal
financial advice, a recommendation, or a suitability assessment.

## Current Status

Initialized planning and scaffold. The current local-first prototype can
validate and store PDFs, record checksum/issue-date manifest metadata, detect
duplicates, scaffold local text extraction status, and keep all rows draft-only
until manual review.

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

The manifest records only local metadata such as checksum, guessed issue date,
private storage filename, and processing status. Source PDFs and extracted text
remain in ignored private storage and must not be committed.

Future dependency setup should use a virtual environment:

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
```

## Documentation

- [Implementation plan](docs/implementation-plan.md)
- [Free market data options](docs/free-market-data-options.md)
- [Persona review and revisions](docs/persona-review.md)
- [Security and privacy](docs/security-and-privacy.md)
