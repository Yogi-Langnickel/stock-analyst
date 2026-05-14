# Stock Analyst Implementation Plan

Status: active draft  
Created: 2026-05-14  
Revised after persona review: 2026-05-14

## Goal

Build a private family application that turns family-owned Der Aktionaer PDF
issues into reviewed, source-linked digests of recommendations, market context,
and instrument details.

The first release must be usable by a late-70s non-technical uploader without
developer help and readable by family members as a source-linked magazine
digest, not as investment advice.

Standard user-facing disclaimer:

> This summarizes magazine content for private family reading. It is not
> personal financial advice, a recommendation, or a suitability assessment.

## Scope

In scope:

- PDF upload for a non-technical family uploader.
- Source PDF retention in a private Google Drive folder or local private storage
  during early development.
- Embedded text extraction, OCR fallback, table extraction, and image text
  extraction when image text refers to financial instruments.
- Structured extraction of stock, ETF, fund, derivative, commodity, crypto,
  forex, and other instrument mentions.
- Manual review before publication or spreadsheet export.
- German source summaries and optional English translations.
- Optional public news/company enrichment after the PDF extraction path works.
  Scrapling may be used only for permitted public pages where APIs/RSS are not
  adequate.

Out of scope for the first release:

- Public sharing outside the family.
- Autonomous financial advice.
- Paywall bypass or scraping protected magazine content from the web.
- Broker integration or trading.
- Automatic publication without reviewer approval.

## Architecture

Recommended initial shape:

- Web/API: Python FastAPI service with a simple accessible intake UI from the
  first PDF-intake milestone.
- Processing: Python pipeline modules for PDF, OCR, layout, extraction,
  normalization, summarization, review gating, and export.
- Storage: SQLite locally, with a migration path to Postgres if hosted later.
- Files: private local `data/` during prototype; Google Drive adapter for source
  PDFs once OAuth/service-account policy is finalized.
- Exports: Google Sheets API with idempotent row IDs.
- Enrichment: RSS/API first. Scrapling only as a controlled, allowlisted
  enrichment adapter for company/news context.

Do not defer the frontend decision past PDF intake. Build and test the first
intake UI alongside upload validation so accessibility and recovery behavior are
verified before extraction complexity grows.

## Data Boundary Gate

Before M1 implementation, confirm these boundaries in code and docs:

- Source PDFs and full extracted text stay in private local or private Drive
  storage.
- Family-facing views show summaries and issue/page references, not full
  article-length excerpts.
- Reviewer-only quotes are minimal and source-linked.
- No PDF, extracted article text, prompt logs, OCR images, or full scraped news
  pages are exported to Google Sheets.
- Retention and deletion behavior is explicit before family beta.

## Local-First Boundary

M1-M4 must run fully offline after dependencies are installed. PDF intake,
embedded text extraction, OCR fallback, table detection, structured extraction,
review gating, and local reports must not require Google Drive, Google Sheets,
LLM providers, Scrapling, hosted OCR, or enrichment services.

External services are adapters behind explicit configuration flags. Tests must
be able to force `external_services=disabled`.

## Model And OCR Data Boundary

- Prefer local OCR first.
- Do not send full PDFs to any LLM provider.
- Do not call remote OCR or LLM providers until provider data-use, retention,
  logging, and deletion controls are documented and approved.
- Send only minimized, source-linked chunks when a provider is enabled.
- Disable provider prompt/output logging where possible.
- Store hashes and source references separately from provider prompts.

## Data Model

Start with these records:

- `source_pdf`: id, original filename, checksum, storage provider, storage id,
  issue date, uploader id, status, created at.
- `pdf_page`: id, source pdf id, page number, embedded text status, OCR status,
  text hash.
- `text_block`: id, page id, block type, text, bounding box, confidence.
- `article`: id, source pdf id, title, section, page range, language,
  extraction confidence.
- `instrument_mention`: id, article id, printed name, normalized name, ticker,
  exchange, ISIN, WKN, type, confidence.
- `recommendation`: id, mention id, recommendation type, current price,
  currency, stop loss, target, take profit, horizon, thesis, risks, confidence.
- `digest`: id, source pdf id, language, status, reviewer id, approved at.
- `sheet_export`: id, digest id, spreadsheet id, exported row count, status,
  exported at.
- `news_context`: id, mention id, source URL, source name, retrieved at,
  summary, relevance score.
- `user_preference`: user id, preferred language, font size, digest density,
  email or print preference.
- `upload_event`: source pdf id, event type, user-facing message, created at.
- `reader_view`: digest id, visibility status, published summary, last updated
  at.
- `audit_event`: actor, role, action, object type/id, before/after hash, source
  issue/page when relevant, export destination, timestamp, request id.
- `access_grant`: actor, target user, role, scope, status, granted at, revoked
  at.

## Confidence And Review Policy

Store both component confidence and final row confidence. Component confidence
includes:

- extraction quality
- OCR quality
- identifier validation
- normalization match quality
- recommendation parsing quality
- source reference completeness

Rows are exportable only when:

- reviewer status is `approved`
- source reference includes issue, page, and block or manual reference
- no required financial field was inferred without source support

Confidence never replaces review. It only controls queue priority and warnings.

## State Machine

Minimum states:

- `source_pdf`: uploaded, duplicate, processing, needs_review, reviewed,
  rejected, archived, delete_requested, deleted.
- `pdf_page`: pending, extracted, ocr_needed, ocr_complete, extraction_failed,
  needs_review.
- `recommendation`: draft, needs_review, approved, rejected,
  reprocess_requested.
- `digest`: draft, reviewer_ready, approved, published, unpublished, archived.
- `sheet_export`: pending, dry_run, exported, export_failed, superseded.

Acceptance:

- Invalid transitions are rejected in tests.
- No row can move from extracted/draft directly to exported.
- Only reviewer/admin roles can approve, publish, or export.

## Step-By-Step Implementation

### 1. Project Bootstrap

1. Create repo scaffold, instructions, README, `.gitignore`, `.env.example`,
   Python package, pipeline skeleton, and tests.
1. Add a compile check and a minimal pipeline test suite.
1. Keep sample PDFs out of Git. Use ignored local `data/fixtures/private/`.

Acceptance:

- `python3 -m compileall src tests` passes.
- Repo has clear no-secrets and no-PDF commit rules.

### 2. Local PDF Intake

1. Add a local upload directory under ignored `data/uploads`.
1. Calculate SHA-256 checksum for each PDF.
1. Reject non-PDF uploads by extension and magic bytes.
1. Record filename, checksum, upload time, and draft processing status.
1. Add a basic uploader UI with large controls, keyboard access, visible focus
   states, and plain progress states.

Acceptance:

- Uploader can upload with one primary action: "Choose PDF" and "Upload issue".
- A non-technical user can upload a PDF without seeing technical terms.
- Body text is at least 18px, touch targets are at least 44px, focus states are
  visible, and contrast is high.
- Upload progress uses plain states: "Uploading", "Checking file", "Ready for
  review", and "Needs help".
- Duplicate and invalid files explain what happened and what to do next.
- Closing or refreshing the page does not lose a completed upload.
- Final confirmation says the file is private and who can see it.
- Duplicate uploads are detected by checksum.
- Non-PDF files fail with a clear message.

### 3. PDF Text And Layout Extraction

1. Extract embedded text with page numbers.
1. Extract table candidates and bounding boxes.
1. Detect low-text pages needing OCR.
1. Run OCR only where embedded text is missing or poor.
1. Store page text and block coordinates separately from generated summaries.
1. Preserve extraction source, reading-order index, confidence components, and
   failure reason when extraction is incomplete.
1. Handle magazine-specific layout: multi-column reading order, title/subtitle
   boundaries, sidebars, captions, table continuation, chart labels, duplicated
   header/footer furniture, and image text near instrument names.
1. Bound image OCR with cheap prefilters: region size, nearby keywords, caption
   proximity, chart/table detection, and per-page OCR budget.

Acceptance:

- Every extracted text block has page reference metadata.
- OCR is not run unnecessarily on pages with good embedded text.
- Failed OCR marks the page `needs_review` rather than blocking the whole issue.
- Reading order and source block IDs are available for reviewer inspection.

### 4. Financial Entity Extraction

1. Define a strict JSON schema for instrument mentions and recommendations.
1. Extract printed names, tickers, ISINs, WKNs, price strings, currencies,
   recommendation verbs, stop losses, targets, horizons, thesis, and risks.
1. Preserve original printed values next to normalized values.
1. Normalize German company names to exchange candidates without overwriting
   the printed name.
1. Mark rows missing ticker/ISIN/WKN as `needs_review`.

Acceptance:

- No missing value is invented.
- Each row has issue, page, and source block references.
- Low-confidence rows cannot reach approved export state automatically.

### 5. Digest Generation

1. Generate concise German summaries from extracted facts.
1. Generate optional English summaries from the reviewed German facts.
1. Create two digest formats: reviewer detail view and family reader view.
1. Family view starts with issue date, magazine source, short summary, and
   reviewed status.
1. Include market overview, watchlist changes, high-risk instruments, repeated
   recommendations, and rows needing review.
1. Use neutral language: "the magazine says" rather than app advice language.
1. Show risk level, source page, and "not financial advice" copy near
   recommendation sections.
1. Avoid dense tables as the default reader experience; use expandable detail
   rows.

Acceptance:

- Digest language is understandable to family users.
- Output does not look like personalized financial advice.
- Every recommendation row links back to source page.

### 6. Manual Review UI

1. Add reviewer queue grouped by issue and confidence.
1. Support approve, edit, reject, and request reprocess actions.
1. Show the source page number and extracted quote/block next to each row.
1. Require reviewer approval before family visibility or Sheets export.
1. Add audit fields for reviewer, decision, and timestamp.

Acceptance:

- Draft rows are invisible to family readers.
- Reviewer can correct identifiers and recommendations before export.
- Reprocessing shows a diff against prior reviewed rows.

### 7. Google Drive And Sheets

1. Store source PDFs in a private Drive folder when configured.
1. Export approved rows to a shared family Google Sheet for review and analysis.
1. Use stable row IDs so re-export updates rows instead of duplicating them.
1. Create tabs:
   - `Reviewed Magazine Mentions`
   - `Market Overview`
   - `Issue Index`
   - `Extraction Audit`
1. Support dry-run mode, retry with backoff, schema version checks, partial
   export recovery, and idempotent upsert by stable row ID.
1. Decide OAuth vs service account before implementation based on family
   sharing, least-privilege scopes, revocation simplicity, and whether the app
   runs only on a trusted local machine.

Acceptance:

- Family-shared exports include approved rows only.
- Re-export is idempotent.
- Drive and Sheet IDs are configuration, not committed values.
- Google Sheets is reviewer/export infrastructure, not the primary family
  reader UI.
- A simple family digest page and optional print-friendly view exist before
  family beta.
- Sheets export preserves reviewer/audit detail; reader view hides extraction
  noise.
- Reviewer-only `Needs Review` export is disabled by default and requires
  separate reviewer-only credentials and audit.
- No raw extracted article text is exported.

### 8. News And Company Enrichment

1. Add an allowlist of permitted public news/company sources.
1. Prefer official APIs and RSS feeds.
1. Add Scrapling only for public pages where API/RSS coverage is insufficient.
1. Cache normalized metadata/snippets only; do not store full page bodies.
1. Store source URL, retrieval time, source name, and short summary.
1. Show enrichment separately from magazine facts.
1. Review robots.txt and source terms before enabling each source.

Acceptance:

- Enrichment is clearly labeled as external context.
- No paywall, CAPTCHA, login, stealth, or proxy bypass is used.
- Source URLs are retained for reviewer inspection.
- Source allowlist, rate limit, and owner are documented.

### 9. Family Access

1. Add low-friction family authentication, such as invite links or simple
   email-based login.
1. Restrict uploader, reviewer, and reader actions by role.
1. Keep Drive links private and avoid public PDF URLs.
1. Add session timeout and basic audit logging.
1. Warn before session timeout and preserve in-progress upload or review state.
1. Add an "Ask reviewer for help" action on upload failures.

Acceptance:

- Family readers see approved digests only.
- Upload/review/export actions are auditable.
- No source PDFs are publicly linkable.
- Reader role never exposes source PDFs unless explicitly allowed.

Minimum auth, roles, and audit must exist before enabling Drive/Sheets export.

### 10. Quality And Regression Gates

1. Build private fixture tests from manually selected pages.
1. Test German decimals, umlauts, ISIN/WKN formats, multi-currency prices, and
   table extraction.
1. Add extraction golden files with redacted/minimal snippets, not full
   copyrighted articles.
1. Use three fixture classes:
   - public synthetic PDFs committed to Git for CI
   - redacted minimal snippets committed only when they contain no copyrighted
     article text
   - private real-magazine fixtures stored under ignored
     `data/fixtures/private/`
1. Add local private fixture manifests with checksum, issue/page coverage,
   expected rows, known extraction risks, and reviewer initials.
1. Add tests for manual review gating and export idempotency.
1. Add accessibility checks for keyboard navigation, focus order, contrast, text
   scaling, and mobile/tablet layout.
1. Add persona task tests: upload a PDF, recover from wrong file type, find the
   latest approved digest, and understand whether a recommendation is
   magazine-sourced.
1. Add family-reader comprehension review before beta.

Acceptance:

- Extraction changes must pass fixture tests.
- Failures produce actionable row/page diagnostics.
- Test data does not expose full magazine content.
- Users can identify source, date, recommendation, and "not advice" status
  without explanation.
- CI passes with synthetic/redacted fixtures only.

## Cost And Reliability Controls

Track per-issue counts for:

- pages processed
- OCR pages
- image OCR regions
- LLM/provider calls
- enrichment fetches
- retries
- failures
- estimated cost

Default development mode must avoid paid/provider calls. Remote OCR, LLM
extraction, enrichment, Drive upload, and Sheets export require explicit config
and visible dry-run output first.

## Milestones

1. `M0` Scaffold and plan: repo, docs, skeleton pipeline, compile check.
1. `M1` Local PDF intake: accessible uploader UI, upload, checksum, status
   tracking, no external calls.
1. `M2` Text/layout extraction: embedded text, OCR fallback, page references.
1. `M3` Structured extraction: instrument/recommendation JSON and review flags.
1. `M4` Manual review: status transitions, approve/edit/reject UI, audit, and
   family-hidden drafts.
1. `M4a` Family reader digest: approved-only web view, print-friendly view,
   source links, and no-advice framing.
1. `M5` Google export: minimum roles/audit, Drive storage, and approved-only
   Sheets export.
1. `M6` Enrichment: API/RSS/Scrapling-backed public context.
1. `M7` Family access: auth, roles, audit, accessibility checks, reader
   comprehension checks, and first trusted family beta.

## Immediate Next Tasks

1. Wire a local SQLite schema and repository layer.
1. Define extraction schemas, confidence fields, status transitions, and
   fixture manifest format.
1. Implement checksum and upload validation.
1. Add a CLI command for `process-pdf --dry-run <file>`.
1. Add the first private fixture outside Git and record expected extraction rows.
1. Extend the accessible intake UI into a working local upload page.
