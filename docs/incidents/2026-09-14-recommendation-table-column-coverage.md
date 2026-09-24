# Recommendation card and table coverage

Date: 2026-09-14

## Impact and root cause

Whole-issue visual review found supported stock recommendations missing from
the draft plan. Both table extraction paths assumed a dividend column was
always present. A table without that column shifted valuation and action
fields. A separate labelled stock card used a printed exchange symbol and no
WKN; the parser rejected it despite its explicit recommendation and prices.
Context-only derivative cards also acquired an implicit Buy status solely
because they were derivatives.

## Correction

Read dividend-column presence from the table header in both primary and layout
extraction. Preserve conditional purchase limits as printed conditions and
dated follow-ups as historical references. Keep ambiguous missing valuation
cells unset, and retain primary values when additive layout extraction finds
the same instrument.

Accept a stock card with no WKN only when it has an explicit stock label,
recognized exchange-labelled symbol, explicit new recommendation, and valid
current, target, and stop prices. Keep WKN blank, retain the symbol in source
metadata, and normalize the exchange plus symbol as the fallback stock identity.
The visible source ID contains only a SHA-256-derived `symbol-` token, not the
raw symbol. Consolidation carries the same internal symbol identity, so two
same-name stocks with different exchange symbols cannot collapse. An invalid
printed WKN does not qualify for this fallback.

Only usable target or stop prices may trigger the existing implicit derivative
recommendation rule. Explicit action signals still survive absent prices.
Context cards remain source-linked draft records without becoming current
recommendations.

## Validation and prevention

Synthetic tests cover the four-row table pattern through primary, layout, and
combined extraction; conditional and historical actions; absent and ambiguous
valuation cells; symbol-only positive and negative cases; distinct same-page
source IDs; same-name/different-symbol consolidation; and context derivative
retention with explicit action overrides. The corrected plans retained 161 and
134 rows, with complete one-to-one reconciliation of 88 and 79 candidates and
no exceptions.
Private source text, names, identifiers, values, and images are excluded from
regression fixtures and this report.

Retain whole-issue source discovery and visual reconciliation as separate gates
from structural plan validation. Column variants and missing identifiers must
not be inferred from row length or repaired by hand-editing private rows.

Transferability: local-only, covering magazine extraction and reviewer-plan
identity and action semantics.
