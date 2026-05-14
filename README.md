# Stock Analyst

Private family tool for processing Der Aktionaer PDF issues into reviewed,
source-linked digests of magazine mentions, market context, and instrument
details.

This summarizes magazine content for private family reading. It is not personal
financial advice, a recommendation, or a suitability assessment.

## Current Status

Initialized planning and scaffold. The first implementation target is a
local-first prototype that can ingest a PDF, provide an accessible uploader,
extract page text with references, create draft article/table candidates, and
keep all rows draft-only until manual review.

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
python3 -m compileall src tests
```

Future dependency setup should use a virtual environment:

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
```

## Documentation

- [Implementation plan](docs/implementation-plan.md)
- [Persona review and revisions](docs/persona-review.md)
- [Security and privacy](docs/security-and-privacy.md)
