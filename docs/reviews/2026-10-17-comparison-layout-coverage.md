# Comparison layout coverage review

Date: 2026-10-17
Baseline: `d14ff47`
Branch: `fix/depot-transaction-week43`

1. Extraction/data-fidelity review: passed. Three complete source occurrences
   recovered from grouped-capitalization layout rows match the private source.
   Unsupported forecast-year metrics stay blank in supported-year fields.
   Whole-issue reconciliation covers 109 canonical source candidates with no
   exceptions, including both pages of each paired derivative row. All 32
   contributing pages were independently visually inspected.
1. Privacy/workbook-operations review: passed after correcting duplicate
   supported metric identity. Conflicting duplicate fields remain blank with
   `valuation_metrics_ambiguous`; mixed supported/unsupported-year columns keep
   only the supported value. No required findings remain. The accepted advisory
   is to leave wrapped historical issue tokens blank when their source binding
   is unavailable rather than assign them by proximity.

The developer and primary independently passed Python compilation, all 369
repository tests and `git diff --check`. The final focused recommendation-card
suite passed 42 tests. Tests cover missing/extra valuation cells, including
signed and unsigned performance, without shifting source columns.

The final ignored plan has 179 draft rows, 37 current-action rows and no approved
rows. Its bytes and authenticated reconciliation remain unchanged after the
duplicate-identity correction. Both reviewers accepted the frozen private
artifact package. No source row values, security identities or workbook access
identifiers are present in this record.

Live draft import, bounded cumulative SEC refresh and blocked-fetch cache replay
are pending at this review checkpoint. These reviews do not grant family
approval or imply that operational completion has already occurred.
