# TSI Local Reviewer Integration v1

Status: implementation plan, 2026-10-25

Delivery mode: `integrate_develop`, authorized by the current bounded user goal
and the standing develop-delivery instruction. No workbook writes, external OCR,
inbox access, SEC refresh, family publication, deployment or master promotion.

## Sequence and ownership

1. Named TSI developer inventories the private corpus and establishes a
   content-addressed, source-neutral registry and versioned observation contract.
1. Obtain architecture/privacy review of this plan before parser implementation.
1. Write synthetic regressions before extraction and review-identity logic.
1. Implement a dedicated modern TSI USA PDF adapter; inventory every page and
   retain unsupported source identities and unresolved candidate regions.
1. A separately assigned developer adds local PNG/JPEG OCR and private HTML
   preview against the contract below; original sources remain untouched.
1. Reconcile supported private PDF pages visually, including candidate counts,
   rows and unresolved exceptions. Demonstrate stable repeated imports.
1. Complete two independent persona review iterations on stable baselines,
   resolve required feedback, run compilation, the full suite, bundled tests and
   diff checks, then commit and deliver verified `origin/develop`.

## Private artifact contract

`registry.json` is versioned and contains documents keyed by complete SHA-256.
Each document retains `document_id`, `sha256`, `aliases`, `media_type`,
`original_publication`, `product`, `publication_date`, `ingested_at`,
`extraction_status`, `pages`, `observations`, and `exceptions`.

Each page inventories its number, dimensions, extraction method, layout status,
candidate count, observation IDs and unresolved exception IDs. All pages are
visited, including opening and historical pages; no DA week/skip policy applies.
Coverage distinguishes parsed, exception, unsupported and no-candidate pages.

Observations have separate `observation_id` and nullable `instrument_id`,
`record_type` (`recommendation`, `ranking`, `portfolio_snapshot`, `transaction`,
`commentary`), `publication_date`, `as_of_date`, `transaction_effective_date`,
`ingested_at`, `strategy`, `universe`, printed identity/value fields and raw
source text. `evidence` binds document hash, page, bounding box, extraction method
and source text hash. Unknown/conflicting facts retain unresolved reasons.
Every observation has `review_status=needs_review`, `exportable=false`,
`manual_review_required=true`; no approval is synthesized. A canonical review
hash covers exact values, type, identity, all dates, publication/product,
strategy/universe, full document hash, page/region, extraction method and parser
version; only review bookkeeping is excluded. Changed evidence cannot reuse a
previous decision.

The screenshot module accepts a local PNG/JPEG path and optional crop region and
returns document/page metadata, OCR regions and explicit unavailable/uncertain
statuses. Original images are retained locally by hash. Possible PDF overlaps
are review links, never merges. The preview module accepts the registry and
writes escaped, self-contained local HTML with typed tables, source previews,
historical-date labels, coverage and exceptions. Neither module logs source
text. Outputs are constrained to ignored private storage. Image validation
requires matching extension/magic plus successful decoding and valid dimensions.
Regions retain coordinates relative to the full original and crop origin. HTML
loads no remote assets. Exact module APIs will be agreed with their owner before
wiring.

## Parsing boundaries

Modern TSI USA is supported only after document/header and layout recognition.
Older USA/Premium, transaction notices and Aktienreports keep their real
publication/product identities and visibly unsupported pages. Table membership
never implies Buy, publisher portfolios never imply personal holdings, and
snapshot disappearance never implies a sale. Printed derivative identity is
distinct from its underlying. Unsupported or ambiguous candidates become
explicit exceptions with evidence rather than invented facts.

## Validation

Use synthetic fixtures for all committed tests. Private source artifacts stay
under ignored `data/private/tsi-review-v1/`; originals under `data/private/tsi/`
are read-only. Recount unique hashes/pages/duplicates/images, reconcile all
supported candidates visually, verify no duplicate observations after repeated
imports and preserve separation of dates, products, strategies and universes.
The private visual reconciliation manifest binds each supported candidate's
document hash, page and region to record IDs or unresolved exception IDs;
candidate totals alone do not prove completeness.
Run `PYTHONPYCACHEPREFIX=.pycache python3 -m compileall src tests`,
`PYTHONPATH=src python3 -m unittest discover tests`, bundled weekly-skill tests,
and `git diff --check`. Existing DA behavior remains covered by its full suite.
