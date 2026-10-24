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

Iteration 1 reviewed frozen feature commit
`a374a99befab0490ee9d1bb2b19c14ec950c4077` with independent domain/source and
QA/privacy/governance lenses. Outcome: **FAIL, required corrections**:

- P1: reject source-directory and retained-file symlinks before any source
  copy, including symlinks into another private source tree.
- P1: reset inherited ranking universe on a fresh unsupported universe title;
  preserve the candidate with unresolved universe rather than assigning the
  preceding table's universe.
- P2: map each Top-Tipp stock/derivative column to its own record or exception,
  including one-valid/one-malformed and both-malformed identifier cases.
- P2: retain the supported printed `Hebel` variant as a typed leverage field.
- Operational: restrict only assistant-owned generated artifact directories to
  `0700` and files to `0600`; preserve original sources and shared private roots.

Focused regressions reproduced each behavioral defect before the fixes.
Confinement tests verify no writes outside the selected source-storage subtree,
including another directory inside the private root. These defects did not
reach develop. The parser/confinement learnings are local to this integration;
no cross-repository policy or user-memory change is required.

The primary independently ran compilation, 444 full-suite tests, seven bundled
weekly tests and diff checks on the first review baseline. It also performed a
fresh import, ordinary repeat and explicit reprocess with socket connections
blocked: extraction call counts were 24 / 0 / 24, both repeated registries were
byte-identical, zero network attempts occurred and every original source hash
remained unchanged. The full private HTML preview passed an actual headless
Chrome visual inspection, including the newest-first document index.

All 153 supported source pages were visually inspected across the primary and
two source reviewers. Source-level mapping established 3,600 ranking rows, 90
full portfolio rows, 44 transaction-table rows, 14 explicit cover summaries,
219 recommendation observations and 153 commentary/context observations. Eight
allocation sidebars add 80 separate snapshot rows. The remaining graphical
sidebar has ten unresolved row candidates in an explicit full-sidebar region
exception. One conflicting printed page-header date is retained as a separate
exception, and competing maturity evidence remains linked for review.

Accepted v1 limits: legacy/special-report parsing is unsupported; screenshot
proof is synthetic only; ranking graphics and portfolio category bands require
visual review; source date/maturity conflicts remain unresolved. None grants
approval or export authority.

Iteration 2 reviewed corrected frozen commit
`1dcba589369fbcdd5d5f20b4c0323b4fd68c1687`. The independent domain reviewer
passed the corrections. QA outcome: **FAIL, one required P2 correction**. The
pipeline still invoked the Top-Tipp column parser only when an optional
`Ersatzschein` label was present, silently omitting both explicit instrument
columns when that optional row was absent.

A pipeline-level synthetic regression reproduced the missing candidates before
the minimal correction. Top-Tipp header/column recognition now invokes the
parser independently of the optional alternative-warrant row. The existing
private corpus already contains that row, so its values, record counts and
reconciliation hash are unchanged by this correction. Compilation, the full
451-test suite, seven bundled tests and diff checks passed on the corrected
baseline.

The primary also verified the actual CLI on the second baseline with socket
connections blocked: fresh/repeat/reprocess extraction counts were 24 / 0 / 24,
CLI receipts and registry bytes were identical for both repeat modes, zero
network attempts occurred and all original source file hashes were unchanged.
The result remained 4,200 observations, zero approvals and zero exportable
records. The final private reconciliation hash matches its registry.

Final independent re-review accepted code commit
`e7253cf9228ad0435d7c8612338e24e57aa41af0`: **PASS from both reviewers, no
required feedback remaining**. The domain reviewer passed 41 focused TSI tests,
verified all 24 retained source hashes and confirmed the 4,200-record private
mapping/review gates. QA independently reproduced the corrected optional-row
case with two recommendations, zero exceptions and two candidates, and passed
the same 41 focused tests. This closes the required two persona iterations and
the focused corrective re-review.

The primary independently passed compilation, all 451 repository tests, seven
bundled weekly tests and diff checks on that exact code commit. It verified
finite, in-bounds source regions for every observation, globally unique
observation IDs, 900 ranking rows in each of four distinct universes, two typed
leverage fields and ignored status for private artifacts. The source-page review
was divided into 49 pages for the domain reviewer, 54 for QA and 50 for the
primary, covering all 153 supported pages.

The private registry, offline preview and accepted extraction reconciliation are
`data/private/tsi-review-v1/local/registry.json`,
`data/private/tsi-review-v1/preview-v1.html` and
`data/private/tsi-review-v1/reconciliation-v1.json`. Reconciliation acceptance is
QA evidence only: all 4,200 observations remain `needs_review`, zero approvals
exist and zero records are exportable. Accepted limitations above remain visible
in the preview and private source mapping.

The primary assistant owns remote SHA publication evidence and the separate
governance closeout review. Develop integration and publication are pending
those final gates; no master promotion or external publication is authorized.
