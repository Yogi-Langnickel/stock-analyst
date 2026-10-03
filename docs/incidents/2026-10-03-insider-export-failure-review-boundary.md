# Insider export failure review boundary

Status: reviewed and validated. Data-fidelity and privacy/governance reviewers
passed both formal review iterations with no unresolved required findings.

An approved workbook export could report `familyVisibleSafe=true` after the
insider ledger merge failed. The exception path downgraded the combined result
only when the schema migration had retained existing rows. With an initially
empty ledger, a merge could commit a new unreviewed row and then fail while
returning its response, leaving the result with an unsupported family-safety
claim.

The failure path now always returns the combined result as a private draft
requiring insider review. An incomplete refresh does not establish approval,
including when enrichment fails before a merge. Error reporting retains only
the exception class and aggregate failure state, without private exception
messages. Successful empty refreshes retain their existing behavior.

The test gap was coverage of enrichment failure without a family-safety
assertion, and absence of a post-write failure with an initially empty ledger.
Synthetic no-network coverage now simulates a committed insider row followed
by a lost merge response for both empty and nonempty initial ledgers. Existing
pre-enrichment failure coverage also verifies the conservative result and
error redaction. Before the fix, the Google-access suite ran 80 tests with two
expected assertion failures.

Validation: 80 Google-access tests and the full 356-test suite passed;
`compileall` and `git diff --check` passed.

Learning classification: durable local implementation rule. A failure response
must not infer approval from an initial row count; provider mutations can have
indeterminate outcomes. This incident is source-agnostic and contains no private
publication content, identities, credentials, or workbook identifiers. No live
provider operations were performed for this repair.
