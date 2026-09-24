# SEC mixed-form document validation

Date: 2026-09-14

## Impact

The weekly Form 4 refresh rejected otherwise usable issuer submissions when
unrelated filing forms contained styled document paths. The cumulative ledger
was retained, but issuer coverage was partial. Increasing the request ceiling
could not resolve the validation failure.

## Root cause

The shared recent/archive validator required every filing's primary document
to satisfy the Form 4 fetch-path contract. SEC submission metadata includes
other filing forms with different styled paths. The fetch planner filters for
Form 4 and Form 4/A only after payload validation, so those unrelated paths
prevented the intended filings from reaching the planner.

## Correction and validation

Retain array shape and equal-length validation plus form, accession, document
string type, and date checks for every row. Form 4 and Form 4/A accept only a
safe document leaf, with historical blank documents ignored solely before the
active cutoff. Unrelated forms accept blank metadata, a safe leaf, or one safe
`xsl`-prefixed styled-directory component containing alphanumerics, dots,
underscores, or hyphens followed by a safe leaf. Traversal, backslashes,
multiple path segments, outer whitespace, control characters, unsafe leaves,
and non-string values remain rejected. Unrelated forms never become document
fetch targets.

Synthetic regressions cover recent and archived mixed-form payloads, unrelated
styled and empty document strings, valid Form 4 and Form 4/A extraction,
exact fetch counts, and replay with a fetch function that fails on every call.
Additional boundary cases preserve rejection of unsafe amendment paths and
non-string documents. Read-only diagnosis attributed all 114 failed issuers to
this local validator: 97 quarantined submission files contained 3,281 otherwise
safe unrelated-form styled paths with underscore-bearing directories, while 17
stale canonical files had the same shape. Corrected validation made all 97
quarantines restorable with zero conflicts or unrecoverable files. The focused
SEC suite passes afterward (29 tests).

The bounded cache fill then completed both issue scans with zero issuer or
filing failures, no archive partial state, and no exhausted request budget.
Final cache replay used a fetch function that raises on every call and proved
zero network requests, zero added rows, and an unchanged 17,058-row ledger.

## Durable learning

Validate shared provider metadata independently from the stricter contract for
the subset selected for retrieval. Keep strict path safety at that selection
boundary and test that unrelated rows cannot create outbound document requests.

Transferability: local-only. This change concerns the SEC submissions adapter;
no other provider's validation policy is changed.
