# Explicit publisher action coverage

Date: 2026-10-03
Status: reviewed; 348 tests passed

The weekly private issue review found that the current `develop` parser could
omit an explicit Wait stock card and stopped derivative actions from `Aktuell`.
The stock card field collector recognized Buy, Sell and Hold labels but omitted
the standalone German and English Wait labels. An earlier recommendation issue
could also override an explicit Wait when normalizing stock cells. The action
mapper recognized `Ausgestoppt` but missed the same word split at a hyphen.

The correction recognizes exact standalone Wait labels, preserves explicit
Hold and Wait when earlier issue provenance exists, and maps the exact
hyphenated stopped word to Sell. Incidental prose, unrelated adjacent cards
and unrecognized statuses remain excluded. Source references and draft manual
review gates are preserved.

The test gap was coverage of explicit action labels and layout word wrapping
through extraction into the current-action view. Four synthetic regressions
were added before implementation: six assertions failed on the prior code.
The corrected extraction and workbook suites pass 78 tests, including existing
Buy, Sell, Hold, follow-up and paired-table cases. Whole-issue reconciliation and
independent data-fidelity and workbook-operations reviews gate live delivery.

Both specialized review iterations passed with no remaining required findings.
Compile validation, the full 348-test suite and whitespace checks passed.
The retired depot-table limitation remains an advisory finding: four private,
reviewer-owned exceptions preserve that gap without changing the active workbook
surface. A stale external schema checker was adjudicated against the current
repository's active schemas. Live weekly delivery requires separate operational
verification and is not asserted by this code review.

Learning classification: local-only. Maintain exact-token action recognition
and test both extraction and downstream current-action provenance. A separate
retired depot-table parser limitation is retained as reviewer-owned exceptions
in private reconciliation; it is outside this correction.

No source document content, private identities, financial values or workbook
identifiers are retained in this report.
