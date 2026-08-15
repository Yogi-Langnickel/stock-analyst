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

## 2026-07-23 Clean Workbook Search Review

### Iteration 1: Product And Accessibility Reviewer

Findings:

- Required: place the input above results rather than to their right so it
  remains visible on narrow screens.
- Initial direction: use a compact reference view. This was superseded after
  reviewer feedback that comparing Search with issue tabs is easier when both
  expose the same columns and values.
- Required: keep stock and derivative results vertically stacked and show an
  explicit no-match state for each section.
- Medium: auto-resizing an empty formula result can collapse useful columns.

Revisions applied:

- `Search!B1` is the highlighted input, with results beginning at `A4`.
- Results now reproduce all 16 stock columns and all 17 derivative columns.
- Stock and derivative matches are stacked in one spill formula.
- Visible result columns use stable reviewer-oriented widths; generated index
  columns `S:AM` are hidden.

### Iteration 2: Privacy And Export-Reliability Reviewer

Findings:

- Required: exclude `Aktuell` from the index because its latest-issue rows are
  duplicates of the corresponding issue tab.
- Required: delete only known generated inactive tabs; preserve manual tabs and
  every `DA_YYYY_NN` issue tab.
- Required: remove retired tabs from normal bootstrap/export ownership so a
  later import cannot recreate them.
- Required: rebuild search from live issue-tab rows and preserve source links;
  do not call enrichment or copy article text.
- Live verification initially found that Sheets treated the `LET` search match
  expression as a scalar. The index and exact-WKN diagnostic were correct, but
  the result filters returned no rows.

Revisions applied:

- Normal Google bootstrap owns `Search`, `Aktuell`, and cumulative
  `Insider Activity`, while issue tabs remain generated history.
- Known retired generated tabs are pruned; unknown/manual tabs are untouched.
- The search index reads issue reviewer rows plus deduplicated insider rows and
  preserves their displayed values in three stacked sections.
- Local canonical schemas remain available for extraction validation, but their
  rows are reported as omitted from the clean Google Sheet.
- The result formula now wraps its match expression in `ARRAYFORMULA`; a
  reversible live WKN lookup returned the expected row without a formula error,
  and the input cell was restored afterward.
- Full-row results are explicitly sorted by issue descending and source-row
  order, with the same stock/derivative headers and action colors as issue tabs.

### 2026-W33 Extraction And Insider Migration Review

Extraction-fidelity review found no remaining issues after synthetic regressions
recovered single-space recommendation rows and USD Quick-Check rows. The private
candidate manifest reconciled 84 unique candidates across 28 visually inspected
pages with zero exceptions.

The Sheets/SEC migration review required four fixes before live use:

- migrate the legacy Insider Activity ledger before the issue bootstrap can
  rewrite its header or shrink its grid;
- preserve prior magazine-backed candidates in the private symbol-map universe
  so incremental SEC refreshes are not limited to the latest issue;
- report failed or request-budget-exhausted SEC runs as `partial`;
- replace only stale Stock Analyst-managed protections while preserving manual
  protections and the editable `Search!C1:E1` exception.

All four findings received focused regressions. SEC hyperlinks remain on company
cells in the dedicated 12-column Insider Activity ledger; Search mirrors the
displayed insider values but does not promise a separate source column.

### Iteration 3: Reviewer Data-Fidelity Review

Findings:

- Required: Search must expose the original issue-row values, not a second
  condensed projection that can drift from reviewer tabs.
- Required: stock and derivative schemas must remain distinct even though they
  share the first three columns.
- Required: matching rows must be ordered newest issue first, with original row
  order retained within each issue.
- Required: hidden index writes must use raw input so formula-like reviewer text
  is not reinterpreted.

Revisions applied:

- The hidden index stores four routing fields followed by all 17 possible
  reviewer values; stock rows retain their 16 values plus one structural blank.
- Visible Stocks and Derivatives sections use the exact corresponding headers.
- Formula sorting uses issue descending and numeric source-row ascending.
- Index writes use `RAW`; only the visible result formula uses `USER_ENTERED`.

### Iteration 4: Reviewer Presentation And Mobile Review

Findings:

- Required: keep the search input above the tables while restoring the full
  reviewer width requested by the user.
- Required: reuse stock/derivative header colors and row-level Buy/Hold/Sell
  colors; explicit `Wait` remains neutral.
- Required: expose all result columns `A:Q` and move generated index data out of
  the visible reviewer area.
- Live gate: verify full headers, exact row values, issue ordering, column
  visibility, and conditional-format rules after refresh.

Revisions applied:

- Search stays in `B1`; results begin at `A4`.
- Visible columns `A:Q` use stable reviewer-oriented widths.
- Generated routing/index columns moved to hidden `S:AM`.
- Search owns and refreshes its section, header, and action conditional-format
  rules without altering issue-tab formatting.
- Reversible live verification confirmed exact stock and derivative headers,
  exact returned values, issue-descending/source-row ordering, visible `A:Q`,
  hidden `R:AM`, valid widths, six owned conditional-format rules, and matching
  action colors; the search input was restored afterward.

### Follow-up: Source-First Chronology

- Search moves each row's existing stock `Source` or derivative `Issue:Page`
  value to a single leading `Source` column.
- The hidden index uses a numeric `YYYYNN` issue key and source-page number so
  sorting treats the issue label as a date indicator: newest issue first, then
  ascending page.
- Results continue at row 4.

### Follow-up: Search Input Placement

- Search no longer freezes any rows.
- The input moves from `B1` to a merged `C1:E1` field, while results continue
  at row 4.

## 2026-07-25 Managed Family-Sheet Protection Review

### Iteration 1: Family Usability And Accidental-Edit Review

Findings:

- Required: the family search user must be able to change only the merged
  `Search!C1:E1` query field.
- Required: generated formulas, hidden search-index columns, `Aktuell`, and all
  issue-history tabs must reject accidental edits.
- Required: existing issue tabs must be covered without manual per-tab work,
  and newly exported issue tabs must receive the same protection.

Revisions applied:

- Search refresh and workbook export now protect `Search`, `Aktuell`, and every
  title matching `DA_YYYY_NN`.
- The Search protection is sheet-wide with only `C1:E1` listed as an
  unprotected range; the other managed tabs are fully protected.
- Protection reconciliation runs after generated values, formatting, grid
  sizing, and search-index updates have completed.

### Iteration 2: Export Reliability And Ownership Review

Findings:

- Required: protection must not lock the exporter out of future refreshes.
- Required: repeat exports must be idempotent and must not accumulate managed
  protections.
- Required: user-created protections outside the exporter contract must remain
  untouched.
- Required: protection ownership must come from configured private credentials,
  without printing or hard-coding the live service-account address.

Revisions applied:

- The configured service-account email is the explicit managed-range editor;
  when the environment value is absent it is read locally from the credentials
  file's `client_email`.
- Each run deletes only protections carrying the Stock Analyst managed
  description prefix, then recreates the exact current protection set.
- Unrelated manual protections are preserved.
- Focused tests cover existing issue tabs, the Search exception, managed-only
  replacement, and protection results returned by refresh and export.
