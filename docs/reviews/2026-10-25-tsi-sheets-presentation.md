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

Iteration 1 reviewed frozen feature commit
`772da7678be87f3f2bb83cfd81a2f28ea709d258`. The independent domain reviewer
passed; QA required a P2 presentation correction: long coverage and footer
notes were still ordinary single cells despite their required caveats. A
synthetic formatting invariant reproduced the missing spans before the fix.
Coverage, source-document and footer notes now use freeze-safe `A:C` / `D:Q`
merged spans without crossing frozen column C, retaining readable row heights.

Two optional observations were addressed rather than deferred. Probe
restoration verification now runs inside `finally`, so a failed probe still
confirms the cleared cell; a failure-path regression reproduced the absent
second read before correction. The guide explicitly lists the derivative
purchase fields intentionally omitted from this selected-field preview but
preserved in its exact private binding. No source financial values changed.

Iteration 2 accepted frozen code commit
`264336dac5f33eece880d3284e1d3b0736e17b79` from both independent reviewers
with no required feedback remaining. The primary independently passed
compilation, 465 full tests, seven bundled tests, exact source bindings and
private flags for all 66 selected observations, and the complete 143-by-17
payload before explicitly releasing live creation.

The bounded writer created the fresh TSI tab, restored its reversible probe,
protected/formatted only that tab and verified exact RAW values. Its identical
owned repeat returned a no-op. Engineering success did not change any source
review state: zero approvals and `familyVisibleSafe=false` remain explicit.

The primary's native Google PDF inspection covered all six exported pages.
Coverage/footer caveats and section layouts were readable. It found a final
display defect: three ranking-change cells used a font-specific private-use
glyph that rendered as an unreadable box. A synthetic regression reproduced
the unrenderable glyph before the display-only correction. The projection now
labels private-use/surrogate glyphs `[graphic: review]` without interpreting
direction; numeric deltas and `NEU` remain literal and private source bindings
retain their original exact glyphs. Source financial facts and all 66 IDs are
unchanged. This native-rendering learning is local to this TSI presentation.

A private, one-off correction plan is prepared for those three ranking-delta
cells only. It requires the exact old ownership, old complete live values,
frozen old/new plan hashes and unchanged source bindings before RAW updates,
then verifies the full new grid before committing its new ownership hash. It
does not add a reusable refresh operation or modify styles/protections. The
primary must approve the focused re-review before that correction executes.

The primary independently confirmed 71 live tabs, TSI in index 2, 17 visible
columns, six frozen rows, three frozen columns, one correct protection and zero
formulas in TSI. All existing tab metadata except shifted indices and all full
Search/Aktuell/Insider values/formulas matched the pre-write snapshot. The final
glyph correction and remote SHA publication remain pending their required
gates. No source observation approval is implied by engineering review or
successful presentation readback.
