# 2026-05-18 OCR Fixture Plan

## Slice

Added a privacy-safe OCR/page fixture planning command for high-value local
review pages. This slice is metadata-only: it defines expected sections and
intended extraction targets, and can summarize local render/OCR artifacts
without exposing OCR text or article text.

## Completed Work

- Added `stock_analyst.ocr_fixtures` with default `DA_2026_03` fixture coverage
  for pages 18-19, 22, 37, 61-63, 66, and 78-89.
- Added `scripts/stock-analyst ocr-fixture-plan` and CLI support for optional
  `--pdf`, `--artifact-dir`, `--issue-id`, and private `--fixture-manifest`.
- Reports page numbers, expected section labels, intended extraction targets,
  artifact availability, artifact paths, SHA-256 hashes, byte counts, and OCR
  character counts only.
- Rejects private fixture manifests containing text-bearing keys such as
  `text`, `ocrText`, `sourceText`, `rawText`, or `lines`.
- Added deterministic synthetic tests for default fixture coverage, artifact
  metadata, private metadata manifests, and manifest text-key rejection.

## Boundaries

- No enrichment provider calls.
- No Google reads or writes.
- No private OCR text, extracted article text, PDFs, images, or artifacts were
  committed.
- The command is a planning/review aid only; it does not approve rows or infer
  missing source values.

## Residual Risks

- The default fixture plan is manually curated metadata. It should be adjusted
  as page maps evolve.
- Artifact matching assumes the current `visual-ocr-review` artifact naming
  convention based on PDF filename and page number.
