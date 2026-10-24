# TSI local review v1 evidence

## Pre-code architecture and privacy review

The read-only design/privacy reviewer approved implementation plan
`docs/plans/tsi-local-review-v1.md`, SHA-256
`a74f011338ac2f5ab77ba92a5e0a5b9372afcc718c466d600623d17429667af5`,
before implementation. Required acceptance points were full-hash alias retention,
recomputed exact semantic/provenance review fingerprints, stable first ingestion
timestamps, private output enforcement, escaped offline HTML and explicit image
context/OCR uncertainty. The implementation follows those boundaries.

## Source and synthetic validation

The source inventory was independently rechecked at 36 PDFs / 24 unique hashes /
12 duplicate copies / 462 pages, all with embedded text; no screenshot files were
present. Three source reviewers divided all nine modern issues and visually
inspected all 153 pages. Private images and source reconciliation stay ignored.
The remaining 309 legacy/special-report pages retain unsupported status and
their original publication/product identities.

Source review identified concrete format differences, addressed before the
implementation review baseline: portfolio tables with/without stop columns;
transaction tables with/without stop columns; derivative expiry dates beginning
before the original column boundary; printed page-header date conflicts;
competing maturity evidence; allocation sidebar geometry; and visual-only
ranking/category markers. Each unresolved source fact remains flagged.

Focused synthetic tests were written and observed failing before extraction,
registry, review-fingerprint and preview-overwrite implementation changes.
Synthetic local image OCR and offline headless-browser preview checks passed.
No real screenshot extraction fidelity is claimed.

## Implementation review iterations

Iteration 1: pending stable feature commit and independent domain/QA review.

Iteration 2: pending required-fix resolution and independent re-review.

The primary assistant owns final source mapping, replay verification, remote
SHA publication evidence and the separate governance closeout review. This
document does not claim develop integration before those gates pass.
