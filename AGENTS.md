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
- Manual approval is required before a digest is visible to family readers or
  exported as an approved family Google Sheets digest. The existing authorized
  weekly private reviewer-workbook workflow may import `needs_review` rows into
  the known configured workbook with `--allow-draft-rows`, zero synthetic
  approvals, `privateDraftReviewOnly=true`, and `familyVisibleSafe=false`.
  This records the user's existing weekly-workflow authority; it grants no new
  destination, credential change, family publication, or other external action.
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

## Weekly Execution Authorization

A normal request to run the latest weekly update or refresh for the usual issue
and known private reviewer workbook invokes the established authorized weekly
workflow, as recorded in `stock-analyst-weekly-refresh` and the user's standing
scope. An explicit offline, dry-run, do-not-write, or equivalent restriction
withholds live writes. This recognition records existing authority only.

For the existing authorized weekly refresh, carry its bounded authority into the
first network-escalation request: cite the original user invocation and the
`stock-analyst-weekly-refresh` authorization for the known configured private
reviewer workbook. Describe issue/`Aktuell` replacement, `Search` regeneration,
cumulative Insider Activity merge, and the bounded SEC public-data refresh.
State the `needs_review`, zero-approval and private-draft flags. Include retained
ledger rewrites when applicable; do not describe the outgoing payload as only
the newest issue's rows. Keep destination identifiers and private values out of
the justification. Preserve all source reconciliation, visual, freshness,
protection, SEC and exact-replay gates.

Do not ask for another user confirmation before this already-authorized action.
A runtime denial is a separate execution decision: report "existing task
authority; execution review rejected" and obey the governing denial instruction.
Use only permitted safer actions or material evidence for reassessment; never
bypass the decision through another wrapper, credential, destination or permission
setting. If the governing denial requires user approval, explain that it is the
runtime requirement and cite its stated reason; do not claim the original task
lacked authority. A later acceptance proves launch permission only; completion
requires successful receipts, exact replay and independent live verification.

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
