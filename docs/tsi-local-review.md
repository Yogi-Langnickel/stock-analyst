# Private TSI local review

TSI v1 is a local reviewer workflow. It does not write Sheets, regenerate Search,
refresh SEC data, access email, publish to family readers or create approvals.
All observations remain `needs_review`, non-exportable and private. The separate
Der Aktionaer workflow is unchanged. Publisher evidence is not personal holdings
or independent financial advice.

## Commands

```sh
scripts/stock-analyst tsi-import data/private/tsi \
  --output-dir data/private/tsi-review-v1/local
scripts/stock-analyst tsi-status data/private/tsi-review-v1/local/registry.json
scripts/stock-analyst tsi-preview data/private/tsi-review-v1/local/registry.json \
  --output data/private/tsi-review-v1/preview.html
```

Open the HTML locally. Its typed tables separate recommendations, rankings,
publisher snapshots, explicit transactions and commentary. Historical dates and
unresolved facts remain visible; ingestion does not make a source current.
Verified source previews are embedded without remote assets. CLI output contains aggregate counts and statuses, never source text or
financial values. Generated output must stay inside this checkout's ignored
`data/private/` tree. The preview requires `.html`; it refuses to replace source
evidence or unrelated files and atomically replaces only its own marked output.

Import a manually supplied PNG/JPEG file or folder using the same import command.
Optional `--region X0 Y0 X1 Y1` uses whole-pixel coordinates in the full original.
The original is retained, and OCR word boxes keep the crop origin. For example:

```sh
scripts/stock-analyst tsi-import data/private/tsi/screenshot.png \
  --output-dir data/private/tsi-review-v1/local --region 0 0 1200 800
```

Replace the example path and crop with a manually supplied image and coordinates
inside its actual dimensions. OCR uses local Tesseract TSV, preferring installed
German/English models and recording the selected language. Missing decoder,
executable or language models have explicit unavailable statuses; no external
OCR is attempted. OCR does not infer transactions or recommendation types; screenshot observations remain unresolved commentary for
review. Missing header/date, cropped context and OCR uncertainty stay visible.
There were no real screenshot sources in the supplied corpus; screenshot proof
uses synthetic fixtures and a local synthetic OCR run.

Exact duplicate bytes share one extraction while every source alias remains in
the registry. Original source files are untouched. Repeating an ordinary import
preserves the registry, observation identities and first ingestion timestamps.
Use `--reprocess` after parser upgrades, to retry unavailable OCR or to change
crop/OCR options; it processes each unique hash once, keeps aliases and first ingestion time, and recalculates
review fingerprints. Cached image option changes require `--reprocess`.
`--no-ocr` permits validated image intake without running OCR. CLI failures use
a generic message to avoid exposing source contents; inspect the private
registry/preview for recorded extraction statuses and exceptions. Concurrent
imports fail busy; a crashed import's `registry.lock` requires local inspection
before removal, rather than automatic lock stealing.

## Source and observation contract

The versioned, source-neutral registry keys documents by complete SHA-256.
Documents retain original publication/product, source aliases, stored original,
publication date, first ingestion time, media type, extraction status, page
inventory, observations and exceptions. Filename hints are not source authority.
Modern issue dates come from explicit printed date/issue headers; strategy
inception dates are separate source context. Conflicting page-header dates are
flagged with both document and printed page dates retained.

The dedicated modern TSI USA adapter scans every page. It parses the Top-Tipp
stock and derivative columns, stock/derivative recommendation lists, publisher
portfolio tables, ranking universes and explicit transaction tables/summaries.
Entry banners retain printed WKN, price and purchase date; a printed purchase
date alone does not establish an executed transaction. Older USA/Premium,
transaction notices and Aktienreports retain their source identities with
explicit unsupported pages. No DA opening-page skip or calendar-week identity
is used.

Each observation has its own identity, separate from nullable instrument
identity. Printed names alone never become canonical instruments. Derivatives
retain warrant WKN, alternative WKN and underlying separately. Raw printed
strings retain approximations, currencies, alternative values and source
statuses. Recommendations, rankings, publisher snapshots, explicit publisher
transactions and commentary stay distinct. Ranking membership never implies
Buy; publisher portfolios never imply personal holdings; disappearance never
implies a sale. Sidebar allocations carry `snapshot_variant=allocation_sidebar`
and remain separate evidence from the full portfolio table. A sidebar whose
text geometry cannot be reconciled produces a specific region exception.

Publication, as-of, transaction-effective and ingestion dates stay separate.
Portfolio purchase dates remain printed snapshot fields. Only explicit
transaction-table dates become transaction-effective dates. Unknown dates stay
null. Differing publisher maturity evidence is linked as a possible conflict;
source values are not overwritten. Colored ranking history, arrows and graphical
bars require visual review and are explicitly unresolved even when numeric
rank/score text is available. Portfolio category bands similarly require review.

Evidence includes document hash, page, bounding box, source text hash, extraction
method and version. The review fingerprint binds exact semantic values and
provenance, including identity, type, all dates, publication/product,
strategy/universe and ingestion. `review_decision_matches` recomputes the actual
fingerprint; it does not trust the stored hash and does not grant approval or
export authority. A changed date, identifier, record type or source region
invalidates a prior decision. This milestone has no approval-writing command.

## Coverage and verification

Every page records `observation_count`, observation IDs and exception IDs.
`candidate_count` counts structured financial/action candidates and unresolved
layout regions, excluding commentary and a pure header-date conflict. Therefore
a `no_candidate` page can retain commentary while its candidate count is zero.
`parsed`, `exception`, `unsupported` and `no_candidate` are distinct statuses.
Counts describe extraction inventory, not approval or proof of completeness.
The preview shows source regions, unresolved exceptions and possible image/PDF
overlaps for review; overlap suggestions never merge their observations.

The private corpus was rechecked at 36 PDFs, 24 unique hashes, 12 duplicate
copies and 462 unique pages, with embedded text on every page. Nine modern TSI
USA issues cover 153 pages; the remaining 15 documents and 309 pages are visibly
unsupported.
Visual reconciliation evidence, source-level counts and final record/exception
mapping are retained privately; raw source contents,
screenshots and reviewer artifacts are ignored and never committed.

Committed regressions use synthetic evidence only. Required checks are
`PYTHONPYCACHEPREFIX=.pycache python3 -m compileall src tests`,
`PYTHONPATH=src python3 -m unittest discover tests`, bundled weekly-skill tests,
and `git diff --check`. Independent persona review and primary replay/source
verification must pass before develop integration.
