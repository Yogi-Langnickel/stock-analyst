---
name: stock-analyst-weekly-refresh
description: "Run the private Stock Analyst weekly Der Aktionaer workflow end to end: discover the newest DA PDF, build and reconcile a reviewer workbook plan, visually inspect whole-issue candidates, perform an authorized draft Google Sheets import, refresh the cumulative SEC Form 4 Insider Activity ledger, prove cache idempotency, and close out with redacted verification. Use when the user asks for the usual Stock Analyst weekly update or refresh, including natural-language requests about a new issue in the known private location. Do not execute a refresh merely to investigate or repair the skill."
---

# Stock Analyst Weekly Refresh

Treat the PDF, extracted content, workbook rows, review artifacts, credentials, and live identifiers as private. Treat magazine output as source summarization, never independent financial advice.

## Goal lifecycle

The user has explicitly designated invocation of this weekly-refresh skill as a
tracked goal, including token-usage reporting (standing instruction reaffirmed
2026-09-14). An explicit user invocation therefore requests goal tracking; merely
loading this skill as supporting context does not. Ordinary use of other skills
does not inherit this authorization.

The primary assistant owns goal registration, completion, and usage reporting.
Before discovery or delegation, it calls `get_goal` and reuses an existing goal
only when it covers this same requested weekly refresh.
If another unfinished goal exists, do not overwrite it, mark it complete, or fold
unrelated work into it; report the conflict and obtain the user's direction.
When creation is permitted, call `create_goal` with the concrete weekly delivery
objective and then `get_goal` to confirm the objective and active status before
proceeding. Never supply a token budget unless the user explicitly requests one.
If registration or confirmation fails, report that narrow blocker without
claiming goal-scoped accounting.

Developer/reviewer agents execute only the assigned slice and report evidence
into the primary's objective. They do not create or complete a separate goal or
start another team. Missing goal or scope context goes back to the primary.

Goal tracking and live-workbook authorization are separate: preserve the private
reviewer delivery authorized below, or the user's explicit offline-only scope.
Keep the goal active through required verification and redacted closeout. Mark it
complete only when that authorized scope is actually fulfilled; follow the
platform's blocked-state conditions if completion is prevented. After verified
completion, report the final token usage returned by the goal tooling. If no
usage is returned, say accounting is unavailable; never estimate or invent it.

## Read the current contract

1. Use the explicitly assigned, verified Stock Analyst worktree. If none is assigned, the primary uses `/Users/yogi/Coding/projects/stock-analyst` only to discover and verify the appropriate checkout and branch before execution; the familiar path is not checkout authority.
2. Read `AGENTS.md`, `docs/agent-memory.md`, `docs/google-sheets-layout.md`, `docs/weekly-execution.md`, and relevant command help. `AGENTS.md#weekly-execution-authorization` is the canonical existing-authority boundary; `docs/weekly-execution.md` supplies the first-request template and completion checks. Current repository behavior overrides examples in this skill.
3. Read [references/weekly-contract.md](references/weekly-contract.md) before a live import or Insider Activity refresh.
4. Inspect `git status --short --branch`. Preserve all existing changes. Follow the authorized repository delivery mode; never include private artifacts or unrelated user changes. Promotion to `master` always requires separate explicit approval.
5. The primary delegates commands that create retained plans, manifests, caches, or reports to a named, bounded developer agent, including established commands. Its handoff supplies the verified worktree, required instructions and skill paths, artifact scope, and validation evidence. The assigned developer executes that slice directly; the primary coordinates and verifies the result.

## Execute the weekly workflow

### Authorization default for this skill

An explicit request to perform the established weekly refresh, including a normal
natural-language request such as "the latest issue is loaded; do the weekly update",
invokes this skill and authorizes the established live **private reviewer-workbook**
delivery: replace or create the
selected issue tab in the configured Google Sheet, refresh `Aktuell` when the
issue is newest, regenerate `Search`, and merge the cumulative Insider Activity
ledger through the
configured bounded SEC refresh. The ledger may rewrite retained prior rows as well
as add new rows; describe that effect in the first escalation. Do not stop
after offline planning or ask for a second import confirmation. Treat only an
explicit user request for `offline`, `dry-run`, `do not write`, or an equivalent
restriction as withholding the live write.

This authorization is limited to the known private workbook and the selected
issue's normal draft-refresh scope and its established cumulative effects. It
never authorizes family approval,
family-visible publication, unrelated Sheet cleanup, credential changes, or
Git publication. Draft rows remain `needs_review` and must be reported as
`familyVisibleSafe=false` / `privateDraftReviewOnly=true`, with zero synthetic approvals.

Before the first network escalation, use the redacted template in the repository
`docs/weekly-execution.md`: cite the original invocation, known configured private
destination continuity, issue/`Aktuell` replacement, `Search` regeneration, cumulative
ledger rewrite/merge, bounded SEC access, and draft flags. Do not request redundant
consent or broaden permission settings. A rejection means "existing task authority;
execution review rejected". Obey its actual governing instruction; reassessment
requires material evidence or a permitted safer action, never another wrapper,
credential, destination, or weakened setting. If the rejection requires user
approval, explain that runtime requirement and its stated reason. Acceptance proves
launch permission only. No wording can guarantee a future hosted decision.

### 1. Discover the newest private issue

Run the metadata-only corpus command against the configured private issue directory. Select the reported `latestPath`; do not infer “latest” from shell ordering, reveal private directory listings, or open another issue unnecessarily.

Confirm that the filename and live tab use `DA_YYYY_NN`, while the workbook plan uses `YYYY-WNN` (for example, `DA_2026_34.pdf` / `DA_2026_34` and `2026-W34`). Require those identifiers to describe the same year and week and confirm the PDF signature. During offline preflight, report live-tab freshness as `pending_live_check`; it is not an offline blocker to content readiness. Stop offline work only on local ambiguity, malformed naming, an identifier mismatch, or an unexpected local duplicate.

### 2. Build and structurally validate the plan

Write command output directly to a private ignored artifact; never let workbook JSON containing row values enter chat or logs.

```bash
scripts/stock-analyst workbook-export-plan "$LATEST_PDF" > data/private/review/latest-workbook-plan.json
```

Require successful plan construction, the expected `YYYY-WNN` plan issue ID, its matching `DA_YYYY_NN` PDF/tab ID, `manualReviewRequired=true`, `approvedRows=0`, nonzero source provenance, active tab schemas, and no stale widths. A structurally valid plan proves schema conformity only; it does not prove whole-issue completeness or reviewer approval.

### 3. Reconcile the whole issue and inspect candidates

Inventory every actionable candidate across labelled recommendation cards, structured action tables, and paired/following tables. Use embedded-text extraction first and Poppler-rendered pages as an additive visual check. Visually inspect every candidate page and any mismatch or exception page locally. Do not upload page images or extracted text.

Create a private structural candidate inventory using [references/weekly-contract.md](references/weekly-contract.md). Map every candidate one-to-one to a workbook `sourceId`, or record a reviewer-owned exception. Initialize one stable private key before the first manifest build:

```bash
python3 /path/to/stock-analyst-weekly-refresh/scripts/reconcile_manifest.py init-key \
  --key-file data/private/review/reconciliation-hmac.key
```

The initializer refuses to overwrite an existing key. Reuse that key to build and validate each redacted manifest. Validation checks the manifest-wide HMAC before trusting counts or provenance, then checks the keyed workbook/source-page fingerprint:

```bash
python3 /path/to/stock-analyst-weekly-refresh/scripts/reconcile_manifest.py build \
  --candidates data/private/review/latest-candidates.json \
  --plan data/private/review/latest-workbook-plan.json \
  --output data/private/review/latest-reconciliation.json \
  --key-file data/private/review/reconciliation-hmac.key
python3 /path/to/stock-analyst-weekly-refresh/scripts/reconcile_manifest.py validate \
  data/private/review/latest-reconciliation.json \
  --plan data/private/review/latest-workbook-plan.json \
  --key-file data/private/review/reconciliation-hmac.key
```

Keep the key in ignored private storage and never print, commit, or share it.

If the repository already has its source-text-free legacy manifest, migrate it deterministically rather than rewriting 76+ mappings by hand:

```bash
python3 /path/to/stock-analyst-weekly-refresh/scripts/reconcile_manifest.py migrate-legacy \
  --legacy-manifest data/private/review/DA_YYYY_NN-source-candidate-manifest.json \
  --plan data/private/workbook-plans/DA_YYYY_NN.json \
  --issue-tab-id DA_YYYY_NN \
  --document-page-count PAGE_COUNT \
  --output data/private/review/DA_YYYY_NN-redacted-reconciliation.json \
  --key-file data/private/review/reconciliation-hmac.key
```

Obtain `PAGE_COUNT` from local PDF metadata, not source extraction. The migration rejects source text, incomplete visual status, non-one-to-one candidates, unsafe review status, unknown row kinds, missing plan mappings, and uninspected pages. For a non-empty legacy `exceptions` list, supply both `--exception-owner` with an opaque reviewer ID and `--exception-reason` with a controlled reason; otherwise migration fails closed.

Do not claim extraction completeness unless all candidates and every listed primary/secondary source page are visually inspected and every candidate is mapped exactly once or has an explicit reviewer-owned exception.

### 4. Preserve the review boundary

- Use `--allow-draft-rows` only for an explicitly authorized private reviewer import. Report `familyVisibleSafe=false` and `privateDraftReviewOnly=true`.
- Do not describe a draft import as approved or family-ready.
- For a family-visible export, require a private reviewer CSV and a `workbook-approval-audit` plan with exact row-hash matches. Never synthesize approvals.
- Preserve issue, page, and source-block provenance for every extracted row.

### 5. Import the authorized reviewer draft

An explicit request to perform this weekly refresh is itself a request to load the newest
selected issue into the known/usual private reviewer workbook, including
replacement of the same issue tab. Do not require the user to separately say
"import" or "load". It does not authorize family approval, unrelated Sheet
cleanup, or publishing Git changes.

Immediately before the write, query the live workbook through the repository's redacted metadata path and compare the newest live `DA_YYYY_NN` tab with the locally selected issue. Resolve a same/newer live issue conflict before writing. This just-in-time comparison is the required freshness gate; do not treat the earlier offline `pending_live_check` state as content failure.

Run the repository export command with its environment file, `--allow-draft-rows`,
and `--require-sec-enrichment`. A missing SEC configuration then fails before
workbook writes. Capture partial/failure receipts without masking the command exit.
Use the maintained `google-sheets-verify-plan` command in step 9 for live checks;
do not recreate an issue-specific verifier. Capture the JSON result to a private file and summarize only redacted aggregates. Verify:

- the issue tab exists and is the newest issue;
- `Aktuell` has literal column/value parity with that issue's current-action rows, with stale tails cleared;
- `Search` excludes `Aktuell` and retains the editable `Search!C1:E1` exception;
- managed protections were reconciled without replacing compatible manual protections;
- the result explicitly identifies private draft mode and is not family-visible.

### 6. Refresh cumulative SEC Form 4 data

Require `SEC_USER_AGENT` without printing its value. Unresolved or non-US
candidates are explicitly uncovered and counted; they do not justify inventing a
CIK or silently broadening the issuer set. An ambiguous mapping is an identity
blocker for that candidate: leave it unresolved, and report the aggregate coverage
limit. Coverage of resolved issuers may still be complete under the fields below.
Preserve the existing cumulative ledger and deduplicate by stable filing/transaction identity. Never infer unresolved issuers. Normalize styled `xslF345X##/` document paths to raw XML, retain verified TLS, use validated accession-keyed raw-XML cache entries, pace SEC requests, and isolate malformed or unavailable filings.

Classify the run from returned evidence:

- **Complete:** `requestBudgetExhausted=false`, `archiveCoveragePartial=false`, `failedIssuerCount=0`, and `failedFilingCount=0` after the intended candidate/lookback scan.
- **Partial:** any request-budget exhaustion, partial archive coverage, or issuer/filing failure. Report the exact aggregate and do not extrapolate missing data.

If a higher request ceiling is needed for a one-time cache fill, keep it explicit and bounded. Do not retry indefinitely.

### 7. Preserve the exact Insider Activity contract

Use exactly these 12 visible columns, in order:

`Company, WKN, Ticker, Insider, Relationship, Shares owned after, Transaction date, Transaction, Direction, Shares, Price in USD, Transaction value`

Keep the filing URL as the `Company` cell hyperlink, not a visible URL column.
The visible ledger retains only non-derivative stock transactions labelled
`purchase` or `sale`, with `Acquired` or `Disposed` direction. Transaction label
and direction are independent source fields; do not require particular pairs or
infer cash consideration or open-market execution. Other parsed transaction
types are excluded. Rows 1-2 carry reviewer instructions and row 3
carries headers. Keep full-row direction formatting from row 4 with
`=$I4="Acquired"` in green and `=$I4="Disposed"` in red. Reconcile existing compatible protections; fail closed on an incompatible manual whole-sheet protection.

### 8. Prove zero-network idempotency

After a complete cache-populating scan, rerun the exact same insider-only
candidate set, configuration, and retained time input, with outbound SEC fetching
disabled at the execution boundary. Prefer a repository-provided cache-only/insider-only entrypoint. If none exists, use the current `enrich_sec_form4` API with a fetch function that raises on every call; do not use a full issue re-export merely for replay.

Require zero attempted fetches, `networkRequestCount=0`, `rowsAdded=0`, unchanged
retained-row count, duplicate prevention consistent with the cached result, and
exact ledger, transaction and revision equality against the original result.
Counts alone do not prove content equality. A cache miss, attempted fetch, or
changed candidate/configuration/time input fails the exact replay proof. Do not
call a replay idempotent based only on “no visible changes.”

### 9. Verify and close out

Report only issue ID and aggregates. Never print source text, row values, credentials, account identities, folder/sheet IDs, spreadsheet titles, or private URLs.

Run the maintained read-only verifier against the exact retained plan after the
export and SEC refresh:

```bash
scripts/stock-analyst google-sheets-verify-plan data/private/review/latest-workbook-plan.json \
  --env-file .env --expected-ledger-rows EXPECTED_RETAINED_ROW_COUNT
```

Obtain the expected retained ledger count from the successful enrichment receipt;
do not substitute the live count as its own expectation. The verifier performs
GET-only checks, returns only redacted booleans/counts, and exits nonzero with
`status=incomplete` on a contract mismatch. Require `ok=true`, `status=verified`,
and passing checks for plan/issue/`Aktuell` parity, tab order, Search content and
editable exception, ledger schema/links/directions, and protections.

Require the export's top-level `ok=true` and `deliveryStatus=written`, plus the
separate successful live verification and exact zero-network replay. The exporter
always leaves `verificationStatus=pending` and `weeklyRefreshComplete=false`;
write success does not claim end-to-end completion. An `issueExport` success
nested in `deliveryStatus=incomplete` proves only the issue-write phase succeeded;
report incomplete weekly delivery and preserve that receipt.
Configured SEC failure/partial coverage is incomplete, not a successful weekly
refresh. Uncovered unresolved candidates remain explicit coverage limitations.
Never complete the goal from an accepted launch, a zero-row delta, unit tests,
or a successful issue phase alone.

Run:

```bash
PYTHONPYCACHEPREFIX=.pycache python3 -m compileall src tests
PYTHONPATH=src python3 -m unittest discover tests
git diff --check
git status --short --branch
```

Distinguish repository changes that predated the run from changes made during it. Never commit private artifacts.

When the weekly task requires repository changes and delivery to `develop` is authorized, normal completion includes all of the following:

1. Work on a scoped feature branch and run two specialized persona-review iterations: first data-fidelity/extraction QA, then privacy/workbook-operations QA.
2. Remediate every required finding and classify any remaining advisory finding with a concrete rationale. Re-run affected tests after each remediation round.
3. Create an intentional feature commit containing only the reviewed scope.
4. Merge the reviewed feature into `develop`, then re-run the prescribed compile, full test, and diff checks on the integrated state.
5. Push `develop` to the verified `origin/develop`, fetch/inspect the remote ref, and require its SHA to equal the validated local `develop` SHA.
6. Finish with a clean closeout report covering branch/status, validation evidence, review disposition, local and remote SHAs, and any remaining risks.

Do not merge or push `master` as part of this workflow. Prepare promotion evidence only; wait for a separate explicit approval before any `master` promotion.

## Stop conditions

An explicit offline/dry-run/do-not-write restriction stops the live-write portion
only. Complete the authorized offline planning and validation scope; it is not a
blocker to that offline task. Report live delivery as outside the requested scope.

For the portion that is authorized, stop and report the narrow blocker when the
newest PDF is ambiguous, candidate reconciliation is incomplete, a source value
would need invention, reviewer approval evidence is missing for a family export,
a protection conflict is incompatible, an ambiguous SEC identity would need
invention, the required SEC phase fails or is partial, live verification is
incomplete, or cache replay attempts network access. Report unresolved/non-US
candidate counts as uncovered coverage; do not treat those counts alone as a
failure of an otherwise complete resolved-issuer scan.
