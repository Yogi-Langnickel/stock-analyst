# 2026-05-18 Dividend Focus Optional Valuations

## Slice

Tightened the dividend-focus parser/export path for dividend strategy rows whose
optional valuation cells are printed as missing values.

## Completed Work

- `DividendStrategyRow.market_cap_billions_eur` and `kgv_2026e` now allow
  `None` at the data model boundary and normalize dash-like table markers to
  blank strings during parsing.
- Row-major and column-major dividend strategy extraction now keep rows when
  market cap or P/E is `-`, `–`, `—`, `k.A.`, `k. A.`, `n/a`, or `N/A`, as long
  as the row still has a valid month, company, WKN, current price, and dividend
  yield.
- `Dividend Focus` workbook rows now coerce optional dividend cells to blank
  strings, avoiding `None` values in Google Sheet row DTOs.
- Added focused unit coverage for dash-valued optional dividend valuation cells
  and workbook row null-safety.

## Validation

- `PYTHONPATH=src python3 -m unittest tests.test_dividend_strategy tests.test_workbook_export`
  passed.
- Local aggregate check against `data/private/issues/DA_2026_03.pdf` made no
  enrichment or Google calls. The embedded-text workbook plan emitted zero rows
  with `externalServicesEnabled=False` and `googleWritesEnabled=False`.
- Local aggregate check against ignored OCR text artifacts for DA_2026_03 pages
  18-19 found the artifacts present, but the dividend line parser still emitted
  zero rows from those OCR lines.

## Residual Risks

- This slice improves the dividend parser once the table appears in row-major or
  column-major line order, but it does not solve OCR line segmentation for
  DA_2026_03 pages 18-19.
- The missing-value marker set is intentionally conservative. Other publication
  spellings should be added only when seen in real extracted text or a focused
  fixture.

## Next Slice

Next phase should address price/as-of semantics before broader parser expansion.
Risk: `Current Price*` currently contains magazine-source values before
enrichment, so the workbook can imply daily/enriched freshness even when the
cell is still the printed issue value.

Follow-ups:

- Add strict workbook schema validation so every planned row has exactly the
  configured tab width and contains only sheet-safe scalar values.
- Add a derivative overview alignment guard so base-table rows and retrospective
  metrics cannot silently merge by position when a row is skipped or OCR order
  changes.
- After the price/as-of work, build an OCR-specific dividend table line
  normalizer for DA_2026_03 pages 18-19. Keep it local-only and fixture-driven:
  start from ignored OCR artifacts, convert the noisy page text into row-major
  or column-major lines, then feed the existing dividend parser without
  committing private extracted text.
