# Derivative overview tokenization

Date: 2026-09-14

## Impact and root cause

Embedded PDF extraction combined adjacent ratio and strike columns for currency
derivatives into one token. The strict standalone ratio check dropped those
base rows. The equal-count pairing gate correctly left all retrospective
metrics unassigned and emitted a mismatch exception, preventing ordinal shifts.

## Correction and validation

Recognize a complete combined ratio and numeric strike with a supported currency
suffix. Retain the printed numeric and currency content; remove extraction
whitespace immediately before a decimal comma. Count the combined value as one
original token so the following underlying stays aligned. Reject incomplete or
extra-field combinations. Adjacent-page and equal-count pairing gates remain.

Embedded WKN recovery is evaluated only before the row's direction token and
only when the resulting underlying, issuer, and product fields parse completely.
Mixed embedded and standalone candidates fail closed because neither shape is
non-heuristic evidence of which token is the WKN. Multiple valid candidates,
an empty issuer, and a missing real WKN also fail closed; issuer suffixes are
never globally rewritten.

A synthetic 13-row paired spread reproduces two combined cells and two stopped
positions. It failed with 11 base rows before the fix. The regression now checks
every row's identity, ordinal prices, runtime, leverage and both source pages,
plus blank targets/stops and the stopped action. A second regression rejects
ambiguous combinations. Additional regressions cover a merged underlying/WKN,
a six-letter issuer suffix, a missing real WKN, and an underlying ending in a
WKN-shaped token immediately before a standalone WKN. The exact inverse
ambiguity—an embedded real WKN followed by a standalone WKN-shaped issuer
prefix—also fails closed. All 16 focused derivative-table tests pass.

Local source validation confirms 13 paired rows, both page references on every
row, two stopped positions, and no pairing exception. No private source values
or identifiers were added to tracked files.

## Durable learning

Keep token accounting in the original extracted representation when splitting
adjacent financial columns. Do not rank competing identifier shapes without a
non-heuristic source constraint; fail closed when candidates remain ambiguous.
Row-count recovery alone is insufficient: verify identity and ordinal metric
alignment after every affected token.

Transferability: local-only. The recognized layout belongs to the derivative
overview extractor; no broader document or provider policy is changed.
