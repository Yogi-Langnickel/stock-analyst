# Derivative table tail coverage review

The weekly draft workflow found a complete adjacent derivative spread rejected because the embedded reader joined strike and runtime while leaving the ratio separate. The parser now accepts that explicit token boundary and controlled NOK, GBx, and index-point strike units. It also accepts a controlled direction, ratio, strike, and runtime combined in one original reader token. It retains the printed strike and runtime, original-token consumed counts, and both source pages.

Synthetic regressions were written before the parser change and failed as expected. They exercise mixed units, field alignment, unknown units, absent units, surplus tokens, and malformed runtime shapes. A malformed later row still rejects the complete base table. No private source content is included in this review.

Review iteration 1: independent extraction/data-fidelity PASS, no required findings. An advisory to add a durable first-row combined-token case was deferred: the reviewer independently tested that placement followed by two rows, and the private source spread verifies full sequence alignment.
Review iteration 2: independent privacy/workbook-operations PASS, no required findings. Primary compile, full 372-test suite, and diff checks passed. Focused derivative tests passed; both newly supported token shapes failed before their corresponding changes.
