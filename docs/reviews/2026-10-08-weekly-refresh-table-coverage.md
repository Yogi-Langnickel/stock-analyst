# Weekly refresh table coverage review

Date: 2026-10-08
Baseline: `fd3ca37dfe91d9d57248a2409111e3cb30303592`
Branch: `chore/weekly-refresh-2026-42`

Scope: derivative and depot structural extraction, explicit stock Sell projection,
comparison-table metric-header alignment, synthetic regressions, and the incident
and focused workflow record. Private data remains outside Git. The delivery path
is reviewed publication to `origin/develop` under the user's standing authority;
master promotion and family approval are outside this task.

The extraction reviewer independently inspected the complete issue and identified
the missing derivative/depot rows, executed transaction, target Sell actions and
comparison no-buy row. The privacy and workbook-operations reviewer requires a
just-in-time newest-issue check, compatible manual protections, no unrelated tab
deletion, preservation of user filter state, and a hard-disabled SEC replay.

Developer: `/root/weekly_refresh_developer`.

Independent reviewers: `/root/extraction_reviewer` (source fidelity) and
`/root/workbook_privacy_reviewer` (privacy and workbook operations).

Round 1: both named reviewers passed the implementation and bounded operations
helper. Extraction review found no remaining required defects. Privacy review
required `0600` modes on the plan and reconciliation manifest. The developer
applied that correction; hashes and keyed validation remained unchanged. The
primary independently confirmed source/schema counts and passed the same full
repository checks.

Round 1 tracked diff SHA256:
`638750e3c7ddcc2f5daf553e671d0744ca55f748870d153208218acc43647937`.

Round 1 document SHA256s:

- Incident: `85c57c9dd0458e46eb377a6ad5d4295cede7df6487490c4820e4806e15d630a5`.
- Review record: `b7bc3ceb5a8b3dc92c60746b93c749422a4392ffebb3190e1ceea2d7b5c6eac9`.

Held private artifact SHA256s (retained unchanged for both rounds):

- Plan: `77bb2f6ba2da9c30254efbeaf810e8f9a469d444682ee9dc3ddaf1540ac0887b`.
- Candidate inventory: `5c96b3eec2737789abb2986f6e9b81c7ee2ff20f257c695a9aad8ca306da8fbf`.
- Reconciliation: `6b9d4d5e019eef502bd1bf4bc9972f0c7af23d36f1bbf891877fdca17f35e294`.
- Visual record: `22d2173f2ec743c0c6ee8f79611fc0838d20c0ea5d611d5d80b3b364ec64a46d`.
- Bounded operations helper: `85074f97e2d187067e0f5e48fe8de2e73e5e814003ea779338f398666dfe78c3`.

Source inventory: 29 cards, 27 Chart Check rows, 20 Quick Check rows, 14 paired
derivatives, 14 depot positions and one executed transaction. Three stock
identity consolidations produce 102 canonical mappings with all contributing
pages retained. Six promotional fund transactions use the controlled
`reviewer_deferred` exception with the opaque extraction-reviewer owner; that
reviewer accepted the scope. All 108 candidates were visually inspected, and the
HMAC validation verified the 171-row plan with 30 current actions, all
`needs_review` and zero approved rows.

Round 2: `/root/extraction_reviewer` and `/root/workbook_privacy_reviewer` each
passed the held snapshot, with no remaining required or optional findings. Code
and private artifact bytes were unchanged. The only required round 1 correction,
owner-only artifact permissions, was verified alongside the unchanged HMAC.

Round 2 held tracked diff SHA256:
`638750e3c7ddcc2f5daf553e671d0744ca55f748870d153208218acc43647937`.

Round 2 held document SHA256s:

- Incident: `62ce8588e615207fc94b7b1964b09a87f66aa8329f772cb5ac00e6664708cba2`.
- Review record: `30ce3bf0187315cb460ae8c068f4e9d8af156c7209076c08d83e95467cb30359`.

These final documentation updates record the returned review disposition only.
The primary owns final commit acceptance, develop integration, integrated checks
and remote SHA verification before the authorized private reviewer import.

Validation: 103 targeted tests and all 364 repository tests passed. Developer and
primary passed `PYTHONPYCACHEPREFIX=.pycache python3 -m compileall src tests`,
`PYTHONPATH=src python3 -m unittest discover tests` and `git diff --check`.
The same full checks are required again on integrated `develop`.

Read-only workbook preflight found the previous issue newest and the selected
issue absent, correct core/issue order, no unrelated cleanup risk, two compatible
manual protections and no incompatible whole-sheet conflict. Ledger structure,
hyperlinks, protection, instruction banner and exact filter range passed. The
reviewers accepted an explicit 3,000-request SEC ceiling for the configured
365-day scan, followed by identical candidate/time/config replay with outbound
SEC fetch raising on every call. At the review freeze, live import and replay
were pending; subsequent operational evidence is retained privately and reported
by the primary.

The private draft still requires manual review. Sponsored fund transactions are
explicit reviewer-owned deferred candidates rather than generated stock actions.
The private reconciliation seals counts and all source pages; it does not approve
source row values or establish family-visible readiness.
