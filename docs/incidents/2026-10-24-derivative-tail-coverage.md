# Derivative table token boundary coverage

The weekly draft preflight correctly stopped when a structured derivative base table failed to parse. The source spread was visually complete; extraction had combined a strike and runtime into one token after a separate ratio. The existing parser handled combined ratio/strike tokens but did not handle this boundary.

The repair adds an exact strike/runtime grammar shared with combined ratio/strike parsing, including printed NOK, GBx, and index-point units. Standalone strikes are checked against the same grammar. The direction may also share the original combined numeric token; consumed counts remain in original reader tokens. It preserves explicit values and adjacent-page provenance and retains complete-table rejection for malformed tails. Synthetic positive and negative regressions prevent a valid prefix from masking omitted rows.

No live write occurred before reconciliation and independent review. All source artifacts remain ignored and private. Independent review and final validation evidence are recorded in the corresponding review document.
