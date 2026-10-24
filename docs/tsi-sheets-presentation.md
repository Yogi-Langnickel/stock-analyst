# TSI Google Sheets presentation

The `TSI` tab is a private draft presentation of dated publisher evidence.
It is a concrete layout preview, not the full cumulative source ledger. Every
row remains `needs_review`; no observation receives financial approval or family
publication authority. The underlying local registry remains unchanged.

## Layout

The first six rows explain source dates, irregular updates, subset coverage and
the proposed relationship to Search/Aktuell. The first three columns retain
the familiar WKN/company/action positions for recommendations. Three columns
and six rows are frozen; merged banners stay on their own side of that frozen
boundary. Source provenance and four distinct date roles remain visible near
the review column. Printed monetary values carry their explicit source currency;
unknown currencies are labelled unresolved, never defaulted or converted.

Separate stacked tables show:

- The latest available stock recommendations and derivative recommendations,
  grouped independently by product, strategy and source context. A publisher
  status such as a stopped-out note stays separate from an explicit action.
- Publisher model-portfolio positions and allocation-sidebar snapshots as
  separate evidence variants. They are never personal holdings.
- The latest available structured publisher transaction table. A newer issue
  without transactions does not make the older transaction source current.
  Summary-only transaction observations are withheld with visible counts.
- A top-five preview per ranking universe, each labelled with its source date
  and displayed/available counts. Ranking membership never means Buy.
- Source coverage, unsupported documents, supported-source exceptions and
  complete omission counts. Expected graphical review flags are distinguished
  from extraction exceptions; unsupported page counts are not financial rows.

Each financial display row binds to one original observation and exact review
fingerprint in the private plan. Same-WKN evidence from different source pages
is retained separately. Article text, OCR text, source aliases, local paths and
credentials do not enter the spreadsheet. Missing facts stay blank/unresolved.
The 17-column derivative preview intentionally omits the printed purchase price
and combined purchase-date/issue field; they remain unchanged in the private
observation binding. This is a selected-field presentation, not a complete
financial-field export.

## Irregular updates and future complementary views

TSI has no assumed weekly cadence and no DA calendar-week identity. Source
publication dates drive selection independently for each product, strategy,
observation type, instrument type, universe and snapshot variant. Ingestion date
is a separate field and never refreshes the financial meaning of old evidence.
Unknown source dates do not participate in latest-source selection.

A persistent cumulative ledger is a later proposal. That ledger could supply
a separate TSI Search result section keyed by company/WKN, source date, product
and observation type, linking back to the relevant evidence. The preview subset
must not be mistaken for complete Search coverage. Aktuell could later receive
a separately labelled, dated TSI panel using explicit publisher actions only;
rankings and portfolio membership must never create actions or overwrite the
DA weekly view. This presentation leaves both shared views unchanged.

The current bootstrap deletes only known retired generated tabs; `TSI` is not
in that set. A weekly core-tab reorder can move TSI after Insider Activity, but
its data survives. This writer does not call bootstrap, Search regeneration,
issue export, SEC enrichment or any Drive upload.

## Commands and live boundary

Create the ignored private plan first:

```sh
PYTHONPATH=src python3 -m stock_analyst.tsi_sheet_preview \
  --registry data/private/tsi-review-v1/local/registry.json \
  --output data/private/tsi-sheets-presentation/plan.json
```

After the concrete plan has been reviewed under the user's explicit TSI-tab
instruction, apply that exact plan hash:

```sh
PYTHONPATH=src python3 -m stock_analyst.tsi_sheet_preview \
  --registry data/private/tsi-review-v1/local/registry.json \
  --output data/private/tsi-sheets-presentation/plan.json \
  --apply --expected-plan-hash REVIEWED_PLAN_HASH --env-file .env
```

The writer uses only the existing configured workbook and the literal `TSI`
tab. It atomically creates a new tab with versioned initializing ownership
metadata, performs a reversible write/read/restore probe, writes selected
values using RAW, formats and protects only TSI, and verifies exact values.
Only after successful payload readback is the plan hash marked committed.

The operation is deliberately creation-only. An identical owned preview with
exact live values is a no-op. A changed plan, changed live content, incomplete
initializing marker or unowned existing `TSI` tab is preserved and refused;
this command never clears and replaces an existing presentation. A failed new
publish leaves an explicit initializing marker for investigation. The probe
cell is restored in `finally`, including a failed probe readback.
The restoration is read back and confirmed even when the probe itself fails.

Google Sheets values and identifiers, plans, receipts and any screenshots stay
private under ignored storage. The plan records `privateDraftReviewOnly=true`,
`familyVisibleSafe=false` and zero approvals. Sheet protection retains the
configured service account as editor; spreadsheet-owner access is unchanged.

## Validation

Synthetic regressions cover independent freshness, product/strategy/universe
separation, historical transactions, missing identity/date dispositions, exact
provenance, no action inference, mixed/unknown currency display, literal
formula-like values, frozen/merged boundaries, ownership/no-op refusal,
reversible-probe failure and safe private output. Compilation, the full
repository suite, bundled weekly tests and diff checks must pass. The primary
verifies real TSI readback and unchanged Search/Aktuell/Insider values after the
explicitly authorized live creation.
