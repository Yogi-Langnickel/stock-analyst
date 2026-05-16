# OCR Options

Status: active recommendation  
Created: 2026-05-16

## Current Recommendation

Use a three-stage OCR policy:

1. Embedded text first with PyMuPDF. This is fastest, free, private, and already
   works for the current local PDFs.
2. Local Tesseract second for pages where embedded text is missing or too poor
   to extract labelled card fields.
3. Google Cloud Vision only as an explicit fallback for pages that remain
   unreadable locally and are worth the data-processing tradeoff.

Do not send full issues to remote OCR by default. If remote OCR is enabled,
send only queued pages that need it, keep source page references, and write
results to ignored private storage for manual review.

## Google Vision Unit Clarification

For Google Cloud Vision pricing, a unit is feature usage on an image. For
multi-page PDF/TIFF files, Google states that each page is treated as an
individual image. That means a 125-page PDF is roughly 125 units when processed
with `DOCUMENT_TEXT_DETECTION`.

As checked on 2026-05-16, Google Cloud Vision pricing lists the first 1,000
units per month as free for `DOCUMENT_TEXT_DETECTION`, then USD 1.50 per 1,000
units for the next tier. At the expected volume of 125 pages per issue and up
to 5 issues per month, the expected 625 pages/month should fit inside that free
Vision OCR tier. This excludes Cloud Storage, networking, and any other Google
services, and pricing must be rechecked before enabling the provider.

Sources:

- https://cloud.google.com/vision/pricing
- https://cloud.google.com/vision/docs/pdf

## Option Comparison

| Option | Pros | Cons | Use Here |
| --- | --- | --- | --- |
| Embedded PDF text | No provider cost, no network, preserves page references, fast enough for full issues | Fails on scanned/image-only pages and may have imperfect reading order | Default first pass for every PDF |
| Local Tesseract | No provider cost, private, can run per page, good enough for many scans | Needs local install, slower than embedded text, can struggle with magazine layouts/tables | First OCR fallback for low-text pages |
| Google Cloud Vision | Strong OCR, handles PDF/TIFF async flows, likely free at current dev volume | Sends page images/PDF content to Google, requires GCS/API setup, pricing can change | Optional fallback after explicit approval |
| Google Document AI | Better layout/document structure than Vision for some documents | More setup, usually more expensive, unnecessary until card/table failures justify it | Defer |

## Implementation Notes

- Keep OCR page-scoped. Do not reprocess pages that already have enough
  embedded text and labelled card fields.
- Store OCR output as draft extraction evidence, never approved rows.
- Cache OCR outputs by source PDF checksum, page number, provider, and provider
  version/config.
- Record `ocr_status` separately from recommendation review status.
- Keep provider selection configurable so local development remains fully
  offline.

## Next Implementation Slice

1. Add a local `ocr-needed` report listing pages below the embedded-text
   threshold or pages where required fixture fields are missing.
2. Add a Tesseract adapter behind an explicit local config flag.
3. Add a remote OCR queue contract without implementing Google calls yet.
4. Only after review, add a Google Vision adapter that processes selected pages,
   not complete issues by default.
