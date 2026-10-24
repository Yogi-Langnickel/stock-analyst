# Weekly private artifact contract

Use this reference for live refreshes and for the redacted whole-issue manifest helper.

## Candidate inventory input

Keep the JSON under a directory whose path includes a `private` component. Use only structural metadata:

```json
{
  "schemaVersion": 3,
  "planIssueId": "2099-W01",
  "issueTabId": "DA_2099_01",
  "discoveryScope": "whole_issue",
  "documentPageCount": 100,
  "candidates": [
    {
      "candidateId": "candidate-001",
      "page": 12,
      "sourcePages": [12],
      "sourceKind": "labelled_card",
      "disposition": "mapped",
      "rowSourceId": "opaque-workbook-source-id",
      "visuallyInspected": true
    },
    {
      "candidateId": "candidate-002",
      "page": 27,
      "sourcePages": [27, 28],
      "sourceKind": "paired_action_table",
      "disposition": "exception",
      "exceptionOwner": "reviewer-opaque-id",
      "exceptionReasonCode": "missing_following_action_table",
      "visuallyInspected": true
    }
  ]
}
```

`planIssueId` must use the repository workbook-plan form `YYYY-WNN`. `issueTabId` must use the private PDF/live-tab stem form `DA_YYYY_NN`; the helper requires both identifiers to represent the same year and week.

Never place company names, security identifiers, article titles, source text, reviewer notes, row values, prices, targets, or recommendations in this inventory. `candidateId`, `rowSourceId`, and `exceptionOwner` are read only to produce keyed HMAC references and are never emitted.

Before the first build, run `init-key --key-file <private-path>`. The helper creates exactly one 32-byte key with owner-only permissions and refuses to overwrite it. Keep that stable key in ignored private storage and supply the same `--key-file` to `build`, `migrate-legacy`, and `validate`. Never commit, print, copy into a manifest, or place the key beside public artifacts.

Every mapped candidate must name one unique workbook `sourceId`. Every exception must have an opaque owner and a controlled slug-like reason code. Set `sourcePages` to every page contributing to the candidate, starting with the primary `page`; retain paired/following secondary pages. Every listed page must be visually inspected. `discoveryScope` is an explicit reviewer assertion that candidate discovery covered the entire issue, not an inference made by the helper.

## Manifest output

The helper writes only:

- plan issue ID, matching PDF/tab ID, and schema version;
- a structural fingerprint of the workbook plan excluding `values` and warnings;
- candidate, mapped, exception, page, inspection, and plan-row counts;
- HMAC-SHA256 candidate/row/owner references and a non-secret key fingerprint;
- per-candidate source-page provenance included in the keyed plan fingerprint and page inventory;
- a manifest-wide HMAC-SHA256 over canonical JSON excluding only the MAC field;
- page numbers and controlled source/reason codes.

The manifest is deterministic for the same inputs and stable private key. Validation verifies the manifest-wide MAC before trusting any manifest field. With `--plan`, it also proves that the referenced workbook plan has the same keyed structural and source-page fingerprint. It deliberately does not prove semantic correctness of private row values.

Schema version 3 seals the whole manifest and binds all source pages. Existing version-1 or version-2 manifests must be rebuilt from their private inventory or migrated again from the source-text-free legacy manifest using the stable key. Key loss or intentional rotation requires rebuilding every manifest that must remain verifiable; the helper fails closed on MAC or key mismatch.

## Legacy manifest migration

Use `migrate-legacy` for the existing private manifest with exactly these top-level fields: `issueId`, `candidates`, `exceptions`, `visuallyInspectedPages`, `private`, and `sourceTextIncluded`. Require `private=true` and `sourceTextIncluded=false`.

For each legacy candidate, require structural fields only: `page`, `rowKind`, `sourceId`, `reconciliation`, `visualInspection`, `reviewStatus`, and optional `sourcePages`. Require `one_normalized_row`, `complete`, `needs_review`, a page included in `visuallyInspectedPages`, and a matching `sourceId` and page in the workbook plan. The legacy extraction `rowKind` may differ from the normalized workbook row kind; the stable source ID and page are the mapping contract.

Require the PDF metadata page count through `--document-page-count`; do not infer it from the last candidate page. Reject non-empty exceptions unless both controlled `--exception-reason` and opaque `--exception-owner` are provided. Never trust free-form legacy exception text.

Offline inspection cannot establish which issue tab is currently newest in the live workbook. Record `pending_live_check` while proving local content readiness, then perform a redacted live metadata comparison immediately before any write.

## Live verification fields

Use the repository's maintained `google-sheets-verify-plan PLAN --env-file .env
--expected-ledger-rows N` command, not a new issue-specific helper. Obtain `N`
from the successful SEC receipt. Read `docs/weekly-execution.md` in the verified
repository for phase statuses and the separate exact fetch-disabled replay gate.
The verifier's `status=verified` is a live-surface check, not proof of source
completeness, approval, SEC coverage or complete weekly delivery.

Keep live verification redacted and aggregate-only:

- issue ID; issue row count; current-action count; literal issue/`Aktuell` parity boolean;
- tab order boolean; `Search` exclusion and editable-range booleans; protected-tab counts;
- Insider Activity header parity, grid width, row count, hyperlink count, accepted-label boolean, direction counts, and formula booleans;
- SEC candidate/resolved/unresolved/filing/failure counts, request count, cache-hit count, request-budget status, and complete/partial status;
- replay network-request count, rows added, duplicates prevented, retained rows, and unchanged-row-count boolean.

Do not include sample rows as evidence.

## Ledger invariants

Keep 12 visible columns in this exact order:

1. Company
2. WKN
3. Ticker
4. Insider
5. Relationship
6. Shares owned after
7. Transaction date
8. Transaction
9. Direction
10. Shares
11. Price in USD
12. Transaction value

Preserve filing links on Company cells. Preserve managed protections and the editable `Search!C1:E1` exception. Use full-row conditional formatting based on Direction in column I.

Treat transaction code and direction independently. Reserve open-market language for the repository-supported purchase/acquired and sale/disposed combinations. Do not treat calculated shares times price as proof of cash consideration.
