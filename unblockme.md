# Stock Analyst Unblock Notes

Status: local implementation can continue; real-corpus validation needs user
PDF handoff
Created: 2026-05-15
Last updated: 2026-05-16

Local development can continue on scoped branches. These items block
Drive/Sheets integration, real Der Aktionaer extraction validation, and family
beta only.

## Current Priority

Stock Analyst is higher priority than eToro Dashboard, Money-maker-3000, and
Chuck Norris until the PDF intake, extraction, review, and private export path
has enough real-corpus evidence to continue confidently.

## Git Flow

- `origin` is configured at `https://github.com/Yogi-Langnickel/stock-analyst.git`.
- `develop` tracks `origin/develop` and remains the integration branch.
- Use scoped feature branches from `develop` for new PR/review work.
- Take clear implementation slices through reviewed merge into `develop`.
- `master` is release/promotion only. The assistant may prepare a promotion
  request when `develop` is a good checkpoint, but must not merge into
  `master` without explicit user approval.

## Fastest Unblock Path

The fastest path is local-first:

1. Put the last two years of PDFs into an ignored local folder:
   `data/private/issues/`.
2. Keep original filenames if useful, but prefer future filenames like
   `YYYY-MM-DD_der-aktionaer_<issue-or-special>.pdf`.
3. Tell the assistant the local folder path only. Do not paste PDF content,
   screenshots, article text, Drive links with public access, or credentials in
   chat.
4. The assistant can then run:

```sh
PYTHONPATH=src python3 -m stock_analyst.cli import-pdf-folder \
  --dry-run data/private/issues

PYTHONPATH=src python3 -m stock_analyst.cli import-pdf-folder \
  --recursive data/private/issues

PYTHONPATH=src python3 -m stock_analyst.cli extraction-quality-report \
  data/uploads/uploads.jsonl

PYTHONPATH=src python3 -m stock_analyst.cli review-queue \
  data/uploads/uploads.jsonl
```

This does not call Google Drive, Google Sheets, market data, OCR, LLM, or any
network provider. It validates PDFs, copies accepted files into ignored private
storage, deduplicates by checksum, and reports embedded-text quality.

## Google Drive Folder Setup

Google Drive is useful as the private source archive, but it is not required to
continue local extraction work. If you create it now, use this structure:

```text
Stock Analyst - Private Source PDFs - Dev/
  source-pdfs/
    2024/
    2025/
    2026/
  fixture-expectations/
  exports/
  archive/
```

Recommended sharing while implementation is local-first:

1. Keep the top folder private to the family account.
2. Do not create public links.
3. Upload the original PDFs into `source-pdfs/<year>/`.
4. Keep `fixture-expectations/` for small manually written expected extraction
   notes, not copied article text.
5. Keep `exports/` for future approved-row Sheets/CSV exports only.

When the Drive adapter is ready, use a service account first unless per-user
Google identity becomes important. Service account tradeoff:

- Good: stable backend/local automation, simple revocation by unsharing the
  folder, no per-family-member OAuth flow at the start.
- Cost: no direct per-user Google audit identity; app audit records must track
  uploader/reviewer separately.

Drive adapter setup steps when requested:

1. Create or reuse a Google Cloud project for Stock Analyst.
2. Enable Google Drive API and Google Sheets API.
3. Create a service account.
4. Download its JSON key to a private local path outside Git.
5. Share the Drive folder with the service-account email.
6. Give Viewer access if the app only reads uploaded PDFs; give Editor access
   only if the app will upload/archive files or write status artifacts.
7. Put these values in local `.env`, never in chat or Git:
   - `GOOGLE_DRIVE_FOLDER_ID`
   - `GOOGLE_SHEETS_SPREADSHEET_ID`
   - `GOOGLE_APPLICATION_CREDENTIALS`

## Google Sheet Setup

Create a dedicated dev sheet only when we start approved-row export work.

Recommended name: `Stock Analyst Review Export - Dev`.

Create these tabs:

- `Reviewed Magazine Mentions`
- `Needs Review`
- `Market Overview`
- `Issue Index`
- `Extraction Audit`
- `Private Fixture Expectations`

Rules:

- Only approved rows should go to family-facing tabs.
- `Needs Review` remains reviewer-only and disabled by default in exports.
- Do not paste full article text into the sheet.
- Use issue date, page, article title, printed instrument name, ticker/ISIN/WKN
  if printed, recommendation type, price/target/stop-loss as printed, and a
  short note for expected extraction rows.
- Share the sheet with the service-account email as Editor when export work
  begins.

## Fixture Expectations Needed From User

To make real extraction tests useful, pick 5 to 10 representative PDFs from the
last two years:

1. One normal recent issue with mostly selectable text.
2. One issue with tables or recommendation boxes.
3. One issue with derivatives/options/certificates.
4. One issue with image-heavy pages or chart labels.
5. One issue where German decimals, umlauts, or multi-currency values matter.
6. One scanned or low-text issue if any exist.

For each selected PDF, add a small expectation row in the dev sheet or a local
ignored note file with:

- issue date
- page number
- article title or section
- printed instrument/company name
- ticker, ISIN, or WKN if printed
- recommendation type exactly as printed
- current price, target/take-profit, and stop-loss exactly as printed
- one short reviewer note about why the page is representative

Do not copy long article passages. Minimal expected fields are enough.

## Decisions Still Needed Before Later Milestones

These are not blockers for local PDF intake and embedded-text extraction, but
they block Drive/Sheets/family beta:

1. Retention: confirm whether source PDFs are kept indefinitely in private
   Drive, archived after review, or deleted after a set period.
2. Access: confirm who can upload, who can review, and who can read approved
   family digests.
3. OCR: approve local Tesseract OCR installation/use before image-heavy PDFs
   are processed. Remote OCR remains disabled unless separately approved.
4. LLM extraction: approve provider, data-use boundary, prompt logging policy,
   and cost ceiling before any remote LLM sees minimized chunks.
5. Google integration: confirm service account first versus per-user OAuth.
   Recommendation: service account first for private family archive/export.
6. Family beta: confirm disclaimer text and that manual review is mandatory
   before any digest becomes family-visible.

## Market Data Providers

- Live provider fetching remains disabled by default.
- Before enabling Stooq, Alpha Vantage, Twelve Data, or SEC adapters, confirm
  terms, rate limits, user-agent/cache requirements, and whether the app is
  local-only or hosted.
- Ticker/ISIN/WKN normalization is not implemented yet, so market data lookup
  must initially use explicit reviewer-provided ticker symbols.

Market data does not block the next PDF work. Keep it disabled until the
magazine extraction and review path is useful on real PDFs.

## Cost Notes

- Local intake, embedded-text extraction, and local review queues: no provider
  cost.
- Google Drive/Sheets APIs: no direct API cost for the expected dev volume, but
  Drive storage counts against the Google account quota.
- Service account: no direct cost.
- Local Tesseract OCR: no provider cost, but may require local installation.
- Remote OCR or LLM extraction: not approved and should remain disabled until a
  separate cost/data-use decision exists.
