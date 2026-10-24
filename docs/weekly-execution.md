# Weekly execution and completion

The normal Stock Analyst weekly request authorizes the existing private reviewer
workflow. [AGENTS.md](../AGENTS.md#weekly-execution-authorization) is the canonical
boundary. The tracked [weekly skill](../skills/stock-analyst-weekly-refresh/SKILL.md)
carries that boundary into execution; loading it to repair or audit the project
does not itself request a refresh or start a tracked weekly goal.

## Carry existing authority into the first request

A normal request such as “the latest issue is loaded; do the weekly update”
invokes the established workflow without another import confirmation. An explicit
offline, dry-run, do-not-write, or equivalent restriction takes priority. A new
destination, credential change, family approval, or permission-setting change
is outside this authority.

Read the current user invocation and repository authority before preparing the
first network escalation. Describe the actual command and all of its effects,
including retained cumulative rows. Use this redacted template, replacing the
bracketed text from evidence rather than inventing authorization:

> The user requested “[original weekly invocation, with private details redacted]”.
> AGENTS.md#weekly-execution-authorization and stock-analyst-weekly-refresh record
> the existing private reviewer-workbook authority for that request. This command
> uses the same configured private workbook and credentials, replaces the selected
> issue tab and latest Aktuell view, regenerates Search, and merges/rewrites the
> cumulative Insider Activity ledger including retained prior rows. It performs
> the configured public SEC refresh within [actual request ceiling and lookback].
> Rows remain needs_review, with zero synthetic approvals,
> privateDraftReviewOnly=true and familyVisibleSafe=false. No new destination,
> credential change, or family publication is included. Execute this exact scoped
> command with network access under the existing task authority.

Do not include sheet/folder IDs, workbook titles, account identities, private
URLs, source values, or credentials. A read-only smoke check or verifier has a
smaller scope: describe only its actual reads rather than copying write effects
into that request. Do not infer a larger SEC ceiling from an example; use the
bounded settings that apply to the current run.

If execution review rejects a request, preserve the distinction: **existing task
authority; execution review rejected**. Obey the actual governing rejection.
Continue permitted safer work or present material evidence for a permitted
reassessment. If the rejection requires user approval, explain that runtime
requirement and its stated reason; do not claim the original request lacked
consent. Changing wrappers, credentials, destinations, or permission settings to
get around a rejection is prohibited. Accepted launch, existing authority, and
completed delivery are three separate facts. Better evidence in a request reduces
local ambiguity; it cannot guarantee a hosted review decision.

## Publish the established reviewer surface

Complete whole-issue candidate reconciliation, local visual inspection, exact
schema checks, and the just-in-time live freshness gate before writing. Keep
private artifacts in ignored storage and preserve compatible manual protections.
The Google Sheet intentionally publishes the current-action reviewer projection:
issue tabs and `Aktuell`, cumulative `Insider Activity`, and `Search`. Retired
canonical extraction/audit tabs remain local. A successful publication check
therefore compares the documented visible projection, not every internal plan row.

The established live weekly export requires its configured SEC phase:

```sh
scripts/stock-analyst google-access-smoke --env-file .env
scripts/stock-analyst google-sheets-export-plan data/private/review/latest-workbook-plan.json \
  --env-file .env --allow-draft-rows --require-sec-enrichment \
  > data/private/review/latest-export-result.json
```

The primary delegates commands that create retained artifacts to the assigned
developer. Keep process exit status and the private receipt; do not mask a failed
exit with a later successful shell command. Missing required SEC configuration
fails before workbook writes. A configured SEC failure or partial scan returns
`ok=false`, `deliveryStatus=incomplete`, and a nonzero exit even when the issue phase
succeeded. The nested `issueExport` receipt preserves evidence of that completed
phase, so recovery can address the remaining phase without treating the whole run
as successful or blindly repeating the issue export. A successful write result
uses `deliveryStatus=written` while leaving `verificationStatus=pending` and
`weeklyRefreshComplete=false`. The exporter does not claim end-to-end completion.

The cumulative ledger writes each Company's filing hyperlink and its transaction
values together in one atomic Sheets update. A rejected ledger update retains the
previous identity/value pairs. Search writes its replacement before clearing stale
tails, preserving the previous index if replacement fails. These protections cover
their respective writes; the complete weekly operation spans multiple requests
and has no cross-tab transaction or rollback guarantee. A later failure can leave
completed phases visible. Preserve their receipts and verify actual live state.

## Prove completion

A complete SEC scan has no exhausted request budget, partial archive coverage,
issuer failures, or filing failures. Non-US/unresolved candidates are explicitly
uncovered and counted; an otherwise complete resolved-issuer scan does not imply
coverage of them. Ambiguous identity is a blocker for mapping that candidate,
never a reason to guess an issuer. Do not silently expand coverage or turn an
unresolved count into a claim of complete issuer coverage.

After the cache-populating scan, repeat the exact candidate/configuration/time
inputs through a fetch-disabled insider-only boundary. Require zero fetch
attempts, zero network requests, zero rows added, unchanged retained rows and
exact ledger/transaction/revision equality. This proof is separate from the
Sheets verifier and must not use another full issue export merely to replay.

Run the maintained GET-only verifier against the exact retained plan:

```sh
scripts/stock-analyst google-sheets-verify-plan data/private/review/latest-workbook-plan.json \
  --env-file .env --expected-ledger-rows EXPECTED_RETAINED_ROW_COUNT \
  > data/private/review/latest-live-verification.json
```

Take `EXPECTED_RETAINED_ROW_COUNT` from the successful enrichment receipt; the
live count cannot serve as its own expectation. The verifier returns redacted
counts and booleans, never rows or live identifiers. Require `ok=true` and
`status=verified`, with successful checks of the plan/issue/latest-view values,
Search index/configuration, ledger schema/hyperlinks/directions, tab order, and
managed protections. Its receipt states `readOnly=true`; it explicitly leaves
`secReplayVerified`, `sourceCompletenessVerified`, and `approvalVerified` false.
A mismatch returns `status=incomplete` and a nonzero exit.
The command reads workbook state without changing it. It does not prove PDF
extraction completeness, reviewer approval, or SEC/cache completion by itself.

Weekly completion requires all three: complete export/SEC receipt, exact
fetch-disabled replay, and passing live verification. Test success, an accepted
launch, a successful issue phase, or no visible row changes cannot replace those
gates. Report phase-specific incomplete status and aggregate coverage limits;
complete the tracked goal only when its authorized scope is verified.

## Keep the installed skill synchronized

The five reviewed files under `skills/stock-analyst-weekly-refresh/` are the
tracked source of the installed bundle, including its reconciler, tests, reference
contract, and UI metadata. Do not edit the installed copy independently. After
reviewed integration, inspect drift using the checked-out reviewed commit:

```sh
scripts/install-weekly-skill --check
```

The command is read-only and returns `sourceDigest`, `installedDigest`, and the
owned paths that differ. A mismatch exits nonzero. Synchronize only after review,
using the exact reviewed commit and both digests from that inspection:

```sh
scripts/install-weekly-skill --install \
  --source-commit REVIEWED_DEVELOP_SHA \
  --expected-source-digest SOURCE_DIGEST \
  --expected-installed-digest INSTALLED_DIGEST
scripts/install-weekly-skill --check
```

The installer checks commit identity and clean tracked bundle/installer state,
refuses changed source or installed bytes and owned symlinks, replaces only the
five owned files atomically per file, and verifies byte equality afterward.
Unowned installed files are preserved; other skills are untouched. An ordinary
file-operation failure restores completed replacements when rollback succeeds.
A hard process or machine interruption can leave a mixed installed version;
`--check` exposes that state before use. There is no recursive deletion of the
installed skill directory. Tests use temporary destinations; actual installation
outside the writable workspace follows the runtime's escalation rules without a
second task-authorization question. Restart/reload Codex if its skill catalog has
already cached the prior bundle; an exact on-disk check does not prove that an
existing conversation has reloaded its instructions.
