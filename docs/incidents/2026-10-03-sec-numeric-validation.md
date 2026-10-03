# SEC numeric parsing and multiplication boundary

Status: reviewed and validated. Data-fidelity and privacy/governance reviewers
passed both formal review iterations with no unresolved required findings.

The Form 4 parser retained numeric field strings without checking that their
nonempty contents represented finite numbers. Multiplication returned a blank
for some malformed inputs, could return nonfinite text, and could let decimal
overflow escape the per-filing error boundary. Its default decimal precision
also rounded legitimate products with more than 28 significant digits.

Every nonempty quantity, price, and post-transaction holding now passes finite
Decimal validation before a parsed transaction can be retained. An ASCII signed
decimal/scientific syntax check rejects underscores and non-ASCII digits that
Decimal would otherwise accept. Leading/trailing decimal points and valid
exponent notation remain supported. Blank and
footnote-only fields remain blank. Original valid numeric strings, including
zero, negative and fractional values, remain unchanged. Multiplication uses a
local precision sufficient for the exact product's significant digits, retains
the existing exponent bounds, rejects nonfinite products, and reports decimal
arithmetic errors as `SecInsiderError`. An invalid filing is isolated and
increments the failed-filing count while valid filings continue. It contributes
no fabricated zero or partially parsed rows. The combined export reports an
incomplete insider refresh when that count is nonzero.

A local inexact-arithmetic trap also prevents silent nonzero underflow from
becoming a fabricated zero. The exact coefficient precision means any inexact
product indicates a bounds failure. Caller precision and traps remain unchanged.

The prior tests lacked nonfinite and malformed numeric inputs, blank operands
paired with invalid values, trapped and untrapped overflow, and products beyond
the default decimal precision. Synthetic no-network regressions cover those
cases plus blanks, footnote-only values, zero, negative and fractional
precision, and mixed valid/invalid filings. Before the fix, the expanded SEC
suite ran 35 tests with 20 expected failures and three overflow errors.
An additional underflow regression failed before the local trap was added.
The reviewer-required lexical regression had 18 expected failures before its
guard was added, with valid decimal/scientific syntax controls preserved.

Validation: 36 SEC-insider tests and the full 356-test suite passed;
`compileall` and `git diff --check` passed. The exact-product test also checks
that multiplication leaves the caller's decimal precision unchanged.

Learning classification: durable local parser rule. Parse every supplied
numeric field before retaining a transaction, validate arithmetic results, and
translate arithmetic failures at the boundary that isolates one filing. Error
messages contain no numeric source value. This incident is source-agnostic and
contains no private publication content, identities, credentials, or workbook
identifiers. No live provider operations were performed for this repair.
