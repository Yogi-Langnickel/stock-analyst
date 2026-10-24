# TSI Sheets presentation review

## Authority and scope

The user explicitly requested a Google Sheets tab called `TSI` and a concrete
presentation complementary to Search/Aktuell, allowing irregular TSI arrival
and varying formats. The implementation creates a private draft preview in the
existing configured reviewer workbook. It does not approve rows or modify
Search/Aktuell. The primary owns live execution, independent readback and Git
publication; this note does not claim those actions before their gates pass.

The implementation plan was frozen before coding at SHA-256
`22773e77410e0eabc9c7bff3ef608f906fe8779f92e72004b8e99588b5b7581c`
and passed pre-code domain/privacy review. The required ownership, structured
transaction and preview-versus-ledger wording boundaries were included.

## Meaningful synthetic checks

Tests preceded implementation and reproduced missing module, unsafe existing
preview replacement, frozen-column merge, private-output overwrite and missing
currency presentation defects before their corrections.

- Latest available source is selected independently by product, strategy,
  observation/instrument type, universe, source context and snapshot variant.
- Newer summary-only evidence does not displace the latest available structured
  transaction source; omission counts include withheld summaries and history.
- Ranking/snapshot membership and a printed stopped-out status do not generate
  Buy/Sell actions. Same-WKN differing evidence remains distinct.
- Formula-like source strings remain literal RAW cell values. Mixed source
  currencies remain explicit, with no conversion or inferred default unit.
- Existing unowned, changed, different-plan and incomplete TSI tabs are refused
  before mutation. Exact owned plan/value repeats are no-ops.
- Fresh-tab ownership is initialized atomically with creation, reversible probe
  failures restore their cell, and only exact payload readback commits its hash.
- No merged header crosses the first-three-frozen-column boundary; private plan
  output cannot overwrite a source registry or unrelated file.

## Concrete private plan

The initial real-data projection contains 66 evidence rows in nine typed
sections, in a 143-row by 17-column grid. It identifies all observations not
shown through explicit history/sample/unstructured/commentary dispositions.
Source coverage distinguishes two supported-source exception regions from 15
unsupported documents comprising 309 pages; it does not label all 311 source
exceptions as errors in the 66 displayed rows. Every row remains `needs_review`.

Plans and visual artifacts stay under ignored
`data/private/tsi-sheets-presentation/`. Source values, source aliases, workbook
identifiers, credentials and screenshots are not committed. A local private
HTML preview is available for layout inspection; the primary verifies native
Sheets rendering after the authorized creation.

## Persona review and final delivery

Iteration 1: pending stable feature baseline and independent domain/QA review.

Iteration 2: pending required-fix resolution and independent re-review.

Live write/readback, unchanged core-tab checks and remote SHA publication are
pending primary verification. No source observation approval is implied by
engineering review or successful presentation readback.
