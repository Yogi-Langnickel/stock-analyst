# Security And Privacy

Status: active draft  
Created: 2026-05-14

## Classification

This project handles private family documents, extracted copyrighted magazine
content, private spreadsheet exports, and potentially sensitive financial
interests. Treat it as private by default.

## Data Rules

- Do not commit source PDFs.
- Do not commit extracted article text or screenshots of magazine pages.
- Do not commit Google Drive IDs, Sheets IDs, OAuth tokens, service-account
  files, API keys, or `.env` files.
- Keep generated digests private and family-only.
- Keep external news summaries short and source-linked.
- Do not store full scraped news articles.
- Family-facing outputs must use "Reviewed Magazine Mentions" or similarly
  neutral wording instead of app-owned recommendations.
- Standard disclaimer: "This summarizes magazine content for private family
  reading. It is not personal financial advice, a recommendation, or a
  suitability assessment."

## Review Gate

Manual review is mandatory before:

- showing a digest to family readers
- exporting rows to Google Sheets
- translating summaries for sharing
- using extracted rows as fixtures

## External Services

Use least data necessary:

- Prefer local PDF extraction first.
- Prefer local OCR first.
- Use OCR only for pages or images that need it.
- Send small source-linked chunks to LLM extraction, not full PDFs, unless a
  later approved architecture requires it.
- Do not send full PDFs to LLM providers.
- Do not use remote OCR or LLM providers until provider data-use, retention,
  logging, and deletion controls are documented and approved.
- Use Google Drive and Sheets only through configured private credentials.
- Minimum auth, roles, and audit must exist before enabling Drive/Sheets export.
- Family-shared Sheets exports are approved-only and must not contain raw
  extracted article text.

## Google Access

- Use the narrowest practical Drive and Sheets scopes.
- Prefer file/folder-scoped access over broad Drive access.
- Keep source PDFs in a dedicated private family folder.
- Protect exported ranges where family members should not edit generated cells.
- Document credential rotation and revocation before beta use.

## Scrapling Policy

Allowed:

- permitted public company pages
- public exchange pages
- public RSS/news pages
- server-side allowlisted fetching
- caching for repeatable development
- robots.txt and terms review per source

Forbidden:

- paywall bypass
- CAPTCHA bypass
- login-protected scraping
- proxy rotation for evasion
- stealth collection of copyrighted source content
- full-page body caching for news pages

## Financial Copy

Use neutral wording:

- "The magazine recommends..."
- "The article mentions..."
- "The extracted stop loss is..."

Avoid:

- "You should buy..."
- "This is safe..."
- "Guaranteed..."
- personalized portfolio recommendations
