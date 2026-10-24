# TSI Google Sheets presentation preview

Status: planned, 2026-10-25

The user explicitly requested a `TSI` tab and a concrete presentation of the
irregular, variable-format TSI evidence. This authorizes one private draft
presentation in the known configured reviewer workbook. It does not authorize
financial approvals, family publication or changes to Search/Aktuell results.
Reusable implementation targets reviewed `origin/develop`; the primary owns
live execution, integration and remote verification.

## Bounded implementation

1. Build a deterministic preview plan from the validated private TSI registry.
1. Show dated, product-specific stock recommendations, derivative
   recommendations, publisher portfolio snapshots, explicit transactions and
   a clearly limited ranking sample in separate stacked sections.
1. Keep publication, as-of, transaction-effective and ingestion dates distinct.
   Select the latest available source separately for each product, strategy,
   observation type, instrument type, ranking universe, source context and
   snapshot variant; ingestion never makes historical evidence current.
1. Preserve one exact observation per display row, full review fingerprints and
   source references. Never merge evidence by WKN or infer actions from rankings,
   holdings or disappearance. Unknown values stay blank/unresolved.
1. Display coverage and omission counts, unsupported sources and exception counts;
   do not export article text, OCR text, local paths or source aliases.
   Transaction tables contain only structured explicit transaction observations;
   summary-only transaction observations are withheld with a visible count/reason.
1. Prepare a scoped Sheets writer that creates or refreshes only its own `TSI`
   preview, writes values as RAW, uses no source-controlled formulas, protects
   the tab, verifies exact values and refuses an unowned existing TSI tab. A
   versioned ownership marker binds the exact sheet ID, payload hash and draft
   flags; validate it before any value, format or protection mutation. Every
   update request must address that TSI sheet ID or its exact quoted range.
1. Run two independent review iterations on frozen artifacts/code, primary
   validation and reversible live write/readback before loading the presentation.

## Draft boundary

Every observation remains `needs_review`, non-exportable and bound to exact
values/provenance. Plans and receipts state `privateDraftReviewOnly=true`,
`familyVisibleSafe=false`, `approvedCount=0`. This is a presentation preview,
not a complete cumulative import or financial approval. Visible section labels
and counts identify the selected subset and dated source coverage.

## Complementary views

`TSI` is a dated source-evidence presentation, not a DA calendar-week tab. A
persistent cumulative source-event ledger is a future proposal. A future
Search section should return company/WKN matches with source product, date,
observation type and a link back to the TSI evidence. A future Aktuell panel
should be separate and explicitly dated, using only explicit publisher actions;
rankings and snapshots never become Buy/Sell actions. No current Search or
Aktuell formulas, values, formats or generated indexes are modified here.

Bootstrap pruning is limited to known generated tab titles, so the new `TSI`
tab must not be added to that deletion set. Presentation creation must not call
the bootstrap, Search refresh, SEC or issue-export paths.

## Validation

Write focused synthetic regressions first for independent source-date selection,
product/strategy/universe separation, one-observation provenance, omitted counts,
unknown fields, no action inference, RAW formula-like strings and TSI-only API
requests. Run compilation, the full unittest suite, bundled weekly tests and
diff checks. All real plans, receipts and source-derived rows remain ignored
under `data/private/tsi-sheets-presentation/` with private permissions.
