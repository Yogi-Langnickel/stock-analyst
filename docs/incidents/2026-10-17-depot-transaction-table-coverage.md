# Depot transaction table coverage

Date: 2026-10-17
Status: focused remediation accepted in two independent review iterations

The latest private weekly refresh stopped before any live write because the
accepted depot transaction parser rejected an explicitly printed dash in the
performance column. Local visual inspection also found a booking transaction
whose action and instrument share one embedded-text line. Its printed numeric
price must be preserved. The parser previously recognized purchase and sale
actions only and required numeric values in both columns. Its fail-closed
behavior preserved the existing workbook.

The repair adds the controlled source action `Einbuchung`, splits its inline
instrument when present, retains numeric values unchanged, and normalizes an
explicit dash performance cell to blank. Numeric prices remain mandatory for
every action. A blank performance cell records unavailable source information;
it never implies a zero return or a purchase recommendation. All four physical
tail cells remain mandatory, with strict identity, quantity, date and value
validation.

Synthetic regressions cover an ordered sale, purchase and booking table,
both supported dash glyphs, missing cells, malformed values, unknown actions,
and ambiguous identity. The workbook regression proves that booking stays in
`Depot Transactions`, preserves its numeric price and blank performance, and creates no
`Aktuell` recommendation. No private publication content is retained here.

The incident is local parser coverage. The general lesson is already covered
by the weekly workflow: structural schema validation cannot prove whole-issue
completeness, and a failed source parse must block live replacement rather than
discard a row or invent a value. No workspace policy change is needed.

The extraction reviewer corrected an initial mistaken dash-price diagnosis;
numeric booking prices remain mandatory and were verified equal to the private
source. That reviewer also found a missing-identifier case that could consume
the following inline booking row. The parser now rejects the embedded next-row
action and a synthetic regression preserves this failure boundary.

The extraction review and subsequent privacy/workbook-operations review passed
the corrected frozen change without remaining required or advisory findings.
Developer and primary validation passed compile, all 366 repository tests and
the diff check. Whole-issue reconciliation and the live private draft refresh
remain separate operational gates. See
[the review record](../reviews/2026-10-17-depot-transaction-table-coverage.md).
