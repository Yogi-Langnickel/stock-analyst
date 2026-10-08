# Weekly refresh table coverage regression

Date: 2026-10-08
Status: remediation reviewed in two independent rounds

Whole-issue visual reconciliation found four extraction/export defects in the
accepted `develop` baseline. Structural workbook validation alone did not expose
missing source occurrences or lost explicit actions. The private reviewer import
was held while the defects were repaired; no family approvals were created.

The derivative base parser did not support combined ratio, CHF/DKK strike and
runtime cells. Failed candidate lookup retained a valid prefix of the table.
Split header labels could also enter the first instrument name. The repair
preserves merged cell boundaries, supports the printed currencies and runtime,
filters the structural headers and rejects an incomplete base table. Pairing
still requires a unique adjacent table with the same row count and retains both
source pages.

The depot parser supported only the explicit no-transactions marker. It also
truncated purchase-date lists containing two fully specified dates. The repair
retains the complete printed date list and parses executed transaction rows only
under the transaction header, with exact action, identifier, quantity, date,
price and performance fields. Malformed or ambiguous rows fail locally.

Chart Check and Quick Check preserved a literal sold target in their parsed DTOs,
but export price sanitation removed it before the current-action projection.
The repair recognizes the exact controlled literal as Sell while leaving the
non-numeric target blank. Nearby prose does not become an action.

A comparison-table row was lost because its book-value and forecast-year headers
were outside the valuation parser's assumptions. The repair consumes ordered
header-declared metric columns, retains the source row and recommendation, and
maps only supported metric/year combinations to the existing workbook fields.
Book-value and unsupported forecast-year values remain blank. Missing cells do
not justify guessing a column.

Synthetic regressions cover complete and malformed combined derivative rows,
dual-page provenance, full purchase-date lists, executed partial sales, ambiguous
transaction identities, controlled target Sell actions, comparison no-buy rows,
and mixed supported/unsupported valuation columns. Tests contain invented
companies and values; source PDFs, images and workbook artifacts remain ignored.

The process gap was a mismatch between schema validation and source coverage.
Future refreshes require independent whole-issue candidate discovery, actual
visual inspection, one-to-one canonical row reconciliation with all contributing
pages, and a keyed private manifest before any reviewer write. Current repository
preflight owns the schema; stale external skill-validator column assumptions are
reported separately.

Rebuilt local evidence contains 105 supported source occurrences reconciled to
102 canonical rows, plus six explicitly deferred promotional fund candidates.
All 108 candidates and every contributing source page were visually inspected;
the keyed reconciliation validates against the rebuilt plan. The plan contains
171 draft rows and 30 current-action rows, with no approved rows. Independent
review accepted the six controlled exceptions; they are not generated stock
recommendations or family approvals.

The developer and primary each passed compile, all 364 repository tests and the
diff check. The developer also passed 103 focused tests. The first extraction
review passed; the privacy review required owner-only modes on two private
artifacts. That correction changed permissions to `0600` without changing bytes
or the manifest HMAC. Both final reviewers passed without remaining findings.
At the review freeze, the code remediation was ready for develop integration and
live import and replay were pending. Subsequent operational evidence is retained
privately and reported by the primary.

Transfer classification: local parser fixes, with a workspace-general lesson
that complete schema validation does not prove complete source extraction.
The existing weekly-refresh and issue-QA skills already require the relevant
independent visual reconciliation gate, so no workspace policy change is needed.

Validation and review results are recorded in
[the review record](../reviews/2026-10-08-weekly-refresh-table-coverage.md).
