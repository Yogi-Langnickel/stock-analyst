# Persona Review

Status: active  
Created: 2026-05-14

This file records specialist review feedback and plan revisions for Stock
Analyst.

## Personas To Consult

- Product and accessibility reviewer for the late-70s non-technical uploader.
- Security and privacy reviewer for family-only documents and Google access.
- Legal/content-use reviewer for private summaries and copyrighted PDFs.
- Financial compliance reviewer for recommendation wording and no-advice copy.
- Data extraction/OCR reviewer for PDF, tables, image text, and confidence.
- Architecture and operations reviewer for local-first, Drive/Sheets, and cost.
- QA reviewer for fixture strategy and regression gates.

## Product UX And Accessibility Feedback

Findings:

- High: uploader UI cannot wait until after the extraction pipeline. The upload
  flow defines whether the product works for a late-70s non-technical uploader.
- High: uploader acceptance criteria need explicit accessibility details:
  minimum text size, contrast, keyboard access, touch targets, focus states,
  recovery messages, and support path.
- High: family-reader UX needs a purpose-built digest view with source,
  confidence, magazine-sourced framing, risk labels, and no-advice copy.
- Medium: Google Sheets is useful reviewer/export infrastructure, but should not
  be the primary family reader experience.
- Medium: failure states need plain-language recovery for wrong file type,
  duplicate upload, failed OCR, slow processing, page refresh, and re-upload.
- Medium: family auth must be low-friction and preserve in-progress work.
- Medium: quality gates need accessibility and comprehension checks.

## Revisions Applied

- Goal now requires first release usability for a late-70s non-technical
  uploader and source-linked family digest readability.
- Architecture now requires the accessible intake UI alongside PDF intake rather
  than after pipeline stabilization.
- Data model now includes `user_preference`, `upload_event`, and `reader_view`.
- Local PDF intake acceptance now includes 18px body text, 44px touch targets,
  visible focus states, high contrast, plain status labels, duplicate/invalid
  recovery, refresh resilience, and privacy confirmation.
- Digest generation now includes reviewer detail and family reader views.
- Google Sheets is explicitly reviewer/export infrastructure, not the primary
  family reader UI.
- Family access now prefers low-friction invite or email login and timeout
  warnings.
- Quality gates now include accessibility and family-reader comprehension checks.

## Data Extraction, QA, And Operations Feedback

Findings:

- High: confidence is required but was not operationally defined.
- High: magazine PDF extraction needs explicit handling for multi-column
  reading order, article boundaries, captions, sidebars, table continuation,
  chart labels, and page furniture.
- High: fixture strategy needs classes that protect copyrighted/private data
  while still letting CI run.
- Medium: image text extraction needs prefilters and per-page OCR budget.
- Medium: M1-M4 need an explicit offline/local-first boundary.
- Medium: Drive/Sheets needs dry-run, retry, idempotency, schema versioning, and
  partial export recovery.
- Medium: OCR/LLM/enrichment cost and reliability controls need counters and
  explicit no-provider default mode.
- Medium: review is mandatory but needed explicit status transitions.

Revisions applied:

- Added `Data Boundary Gate`, `Local-First Boundary`, and `Model And OCR Data
  Boundary`.
- Added confidence component policy and export conditions.
- Added explicit state machine for source PDFs, pages, recommendations, digests,
  and sheet exports.
- Expanded magazine-specific extraction requirements.
- Added three-class fixture strategy and private fixture manifests.
- Added cost/reliability counters and no-paid-provider default mode.
- Added Google adapter dry-run, retry/backoff, schema, and partial export
  requirements.

## Security, Legal, And Financial Compliance Feedback

Findings:

- High: family-shared Google Sheets must not export unapproved or copyrighted
  review rows.
- High: LLM/OCR vendor exposure needs provider approval, retention/logging
  controls, and local OCR first.
- High: copyrighted PDF handling needs excerpt limits and no full article
  display/export.
- High: user-facing language should not make the app sound like it approves
  investment recommendations.
- Medium: Google access model needs narrow scopes, revocation, and protected
  ranges.
- Medium: audit controls need modeled events.
- Medium: Scrapling policy needs robots/terms review and no full-page cache.
- Medium: minimal auth/roles should come before Drive/Sheets export.

Revisions applied:

- Renamed user-facing spreadsheet tab to `Reviewed Magazine Mentions`.
- Added standard no-advice disclaimer to README, plan, and security guidance.
- Changed family-shared Sheets export to approved-only and no raw extracted
  article text.
- Added reviewer-only `Needs Review` export as disabled-by-default and requiring
  separate credentials/audit.
- Added `audit_event` and `access_grant` data records.
- Added Google scope, credential rotation, and revocation guidance.
- Added Scrapling robots/terms/rate-limit/source-owner requirements.
- Moved minimum auth, roles, and audit before Google export.
