# 2026-05-18 OCR Fixture Artifact Review Planning

## Slice

Extended `ocr-fixture-plan` with a deterministic, metadata-only review-planning
summary for private visual/OCR artifacts. The report identifies fixture pages
with render and OCR text artifacts available, missing, or not configured, and
emits exact local `visual-ocr-review` commands for filling gaps.

## Completed Work

- Added `artifactReviewPlanning` to `ocr-fixture-plan` output.
- Summarizes render and OCR text availability by unique fixture page.
- Emits compact page selections such as `2-3,5-6` for deterministic local
  commands.
- Uses shell-safe quoting for private PDF and artifact paths.
- Keeps the new review-planning summary free of OCR text, article text, and
  artifact hashes; existing per-artifact metadata remains unchanged.
- Added synthetic tests for missing artifact summaries, command generation,
  unconfigured private paths, and page range formatting.

## Boundaries

- No enrichment provider calls.
- No Google reads or writes.
- No PDFs, PNGs, OCR text, article text, or private artifacts were committed.
- The command only plans local reviewer actions and does not approve extracted
  rows or infer missing source values.

## Residual Risks

- The generated OCR command uses `--write-ocr-text` because missing OCR text
  artifacts cannot be created otherwise; reviewers must continue to store that
  output only under ignored private paths.
- Artifact matching still depends on the current `visual-ocr-review` naming
  convention based on PDF filename and page number.
