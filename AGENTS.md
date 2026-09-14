# Stock Analyst Agent Instructions

Read this file before changing the project.

## Project Purpose

Stock Analyst is a private family tool for turning family-owned Der Aktionaer
PDF issues into reviewable investment-publication digests. It extracts
recommendations, market context, instrument identifiers, and source references.

This project summarizes source material. It must not present generated output as
independent financial advice.

## Hard Rules

- Keep all PDFs, extracted text, recommendations, uploads, review notes, and
  Google Drive or Sheets identifiers private.
- Do not commit PDFs, screenshots of magazine content, extracted article text,
  credentials, OAuth tokens, API keys, `.env` files, or private spreadsheet
  exports.
- Manual review is required before a digest is visible to family readers or
  exported to Google Sheets.
- Preserve source references for every extracted row: issue, page, and source
  block when available.
- Never invent missing prices, stop losses, targets, tickers, ISINs, WKNs, or
  recommendations.
- Use German as the source language. English summaries are optional translations
  from reviewed extracted facts.
- External news collection is enrichment only. It must not replace the magazine
  source record.
- Scrapling is optional for permitted public company/news enrichment. Do not use
  it for paywall bypass, CAPTCHA bypass, proxy rotation, or stealth scraping.

## Workflow

- Work on scoped branches. Completed deliverables target `develop`.
- Take implementation work from planning through reviewed merge into `develop`
  when the path is clear. `master` is release/promotion only; the assistant may
  prepare promotion evidence, but must not merge into `master` without explicit
  user approval.
- Before substantial or high-risk work is merged into `develop`, run two
  persona review iterations with relevant reviewers, address required feedback,
  and classify any remaining feedback with rationale.
- Use `rg` and `rg --files` for search.
- Keep plans in `docs/`.
- Keep reusable implementation code under `src/stock_analyst/`.
- Add focused tests before changing extraction, normalization, review gating, or
  export behavior.
- Run `PYTHONPYCACHEPREFIX=.pycache python3 -m compileall src tests` after
  scaffold or Python changes.
- Run `PYTHONPATH=src python3 -m unittest discover tests` for the current
  standard-library test suite.

## Memory

This repo starts with lightweight documentation:

- `docs/agent-memory.md`
- `docs/implementation-plan.md`
- `docs/persona-review.md`
- `docs/security-and-privacy.md`

Add repo memory only when repeated implementation work needs durable rules.

## Workspace Agent Bootstrap

This project participates in the Coding workspace orchestration policy.
Read `/Users/yogi/Coding/AGENTS.md` to resolve the accepted local `develop`
version of `codex-workspace-orchestration/AGENTS.md` and its compact workspace
memory, then apply this file and task-relevant project memory and skills.
Do not treat the branch occupying the named orchestration directory as accepted
policy without verifying its Git identity and selected authority.

Preserve the assigned role: the main assistant coordinates and delegates;
a named developer mutates only its explicitly assigned authorized surface;
a reviewer stays read-only. Opening workspace instructions does not change a
worker's role. The handoff must supply the checkout, baseline, file scope,
relevant context paths, delivery authority, validation, and stop conditions.

For a linked or relocated checkout, use `git rev-parse --git-common-dir` to
identify the primary repository and workspace. If the workspace adapter or
required context is unavailable, report that gap to the parent/user before
dependent changes. Never guess missing policy or broaden your own authority.
