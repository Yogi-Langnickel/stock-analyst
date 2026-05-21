# Refinement Tab Review

Date: 2026-05-21

## Context

The live Google Sheet `Refinement` tab was manually reviewed through the full
issue after an earlier partial review through page 49. This handoff captures
only non-content-specific parser recognition learnings. Do not add extracted
article text, page titles, reviewer notes, spreadsheet IDs, or private sheet
exports to the repo.

## Recognition Updates

- `Cover`, `Editorial`, `Inhalt/front-matter`, and `Werbung` should be treated
  as non-useful for investment-row extraction.
- `Bücher`, `Impressum`, `Letzte Seite`, social-media filler, index-only pages,
  and generic future-parser surfaces such as crypto/forex/commodity/ETF should
  not be marked useful unless a focused parser later owns them.
- `News` is useful only when it is an explicit section marker, not when the word
  appears incidentally in an article or footer.
- `Titelstory` is a useful review surface when explicit instrument/extraction
  signals are present; intro/spread pages can be non-useful in a given issue.
- Dax, Wall-Street, Rohstoff, chart-check, quick-check, and statistics markers
  should beat generic financial keywords.
- Mixed stock/derivative pages can occur. They need review and should not be
  forced into a single tab until the row-level instrument type is explicit.
- Page numbers, page titles, and reviewer notes from one issue must not be
  hard-coded as future issue rules.

## Validation Notes

- The local parser recognition update is covered by
  `tests/test_refinement.py`.
- The sheet read used reviewed classification fields and formatting metadata
  only for parser-recognition learning; no private row text, page titles,
  reviewer notes, spreadsheet IDs, or extracted article text was committed.
- Full-issue comparison after the first update reduced mismatch counts on the
  reviewed issue from 67 to 20 for section labels, 31 to 17 for useful-info,
  and 94 to 30 for suggested destination.
- A follow-up refinement pass on 2026-05-22 reduced the same comparison to 16
  section-label mismatches, 0 useful-info mismatches, and 5 suggested-destination
  mismatches. Remaining section differences are mostly blank reviewer labels
  versus coarse non-useful local labels; avoid hard-coding page numbers to erase
  those.
- `google-sheets-refinement` now preserves reviewer-owned fields for existing
  page rows: section, page title, useful-info, suggested destination, and
  reviewer notes.
