# Weekly delivery reliability and permission recurrence

Date: 2026-10-24 (Australia/Melbourne)
Status: implementation reviewed and verified; factual validation and dispositions
are recorded in the [delivery review](../reviews/2026-10-24-weekly-delivery-reliability.md).
Git delivery and installed-skill synchronization evidence is recorded separately
in the final closeout.
Type: private workbook operations / completion reporting / reusable workflow.
Transferability: workspace-general principle; Stock Analyst-specific fixes.

## Impact and evidence

The user confirmed that recent private reviewer imports were complete and
satisfactory. The investigation's fresh read-only check of DA_2026_44 found the
41 current actions matching `Aktuell`, 23,132 insider rows and filing hyperlinks,
and passing Search/protection/layout checks. No current workbook repair or
repeat import was justified by these findings.

The permission recurrence was an execution-review rejection despite existing
weekly task authority. Earlier contradictory blanket export-approval wording
had already been clarified in AGENTS and the security review gate. The installed
weekly skill still did not route directly to the canonical first-request
instruction. The workspace incident
`docs/incidents/2026-10-24-stock-analyst-permission-regression.md` in the accepted
orchestration repository records the actual rejected/accepted calls. The
reviewer's internal decision trace is unavailable; this work does not attribute
causation to a model/client/policy rollout or promise permanent hosted acceptance.

A general code review additionally demonstrated three independent failure modes:

- The insider Company filing hyperlink and remaining transaction cells were
  updated separately. An injected failure could pair a new identity with old
  transaction values.
- Search cleared its existing generated index before writing the replacement.
  An injected write failure could leave Search empty.
- SEC enrichment failure could coexist with top-level `ok=true` and a zero
  process exit. Automation could mistake issue publication for full delivery.

Live verification also relied on issue-specific private helper scripts rather
than a maintained command with explicit incomplete status. The baseline suite
passed all 372 tests, showing that these failure paths were untested rather than
establishing their safety.

## Remediation and prevention

The ledger now binds filing identity and transaction values in one atomic update.
Search writes a replacement before stale-tail cleanup. The export reports
configured SEC failure/partial coverage as overall incomplete with a nonzero
exit, preserving the issue-phase receipt. Weekly use explicitly requires SEC
configuration before writes. The maintained `google-sheets-verify-plan` command
provides GET-only, redacted live contract checks against the retained plan and
expected ledger count.

The tracked five-file weekly skill bundle now points to the canonical AGENTS
authority and [weekly execution instructions](../weekly-execution.md). It
recognizes ordinary natural-language weekly requests and supplies concrete
first-escalation evidence: original invocation, known destination continuity,
cumulative effects, draft flags, zero approvals, and bounded SEC access. It
requires complete phase receipts, exact fetch-disabled replay, and the maintained
live verifier. Its source-controlled installer checks drift and synchronizes only
owned files after reviewed integration. Existing reconciler tests and UI metadata
are retained.

Runtime rejection remains distinct from missing consent. The actual governing
denial must be obeyed, including any required approval; no wrapper, credential,
destination, or setting bypass is permitted. The user should receive the real
runtime reason without an invented claim that their earlier authority vanished.

## Validation and disposition

Two complete independent review iterations passed after required verifier
corrections for hidden managed tabs and reviewer columns. The live verifier also
correctly evaluates effective highest-priority direction-formatting rules while
preserving equivalent retained lower-priority rules; no Sheet cleanup was needed.
The independent skill forward review covered eight safe scenarios, with both
advisory clarifications incorporated.

Primary validation passed all 410 repository tests, compilation and diff checks;
the seven preserved reconciliation tests and system skill validator also passed.
The maintained read-only live verifier returned `status=verified` with all 29
checks true, covering 41 current actions, 23,132 ledger rows and filing links,
and 24,316 Search entries. No live workbook writes, imports or SEC fetches occurred
during remediation. The user's satisfactory recent import was preserved.

## Limits and follow-through

A synthetic payload using the current 23,132-row ledger size measured
17,200,721 bytes for the atomic write. Google recommends approximately 2 MB per
request, states no hard request-size limit, and times out processing beyond 180
seconds ([official Sheets limits](https://developers.google.com/workspace/sheets/api/limits)).
Production write latency remains an accepted residual limitation: the atomic
write performance has not been exercised by repeating a satisfactory import. A timeout leaves the
remote outcome unknown: read back the live ledger before deciding whether to
retry. Smaller writes would need a separate atomicity design to preserve the
identity/value guarantee.

The whole weekly operation is not a cross-tab transaction. A completed issue
phase can remain visible when a later phase fails; keep receipts and repair the
remaining phase after checking live state. A timeout can leave a remote outcome
unknown, requiring read-only verification before retry. Exact replay and PDF
candidate/visual review remain separate gates from live Sheets verification.
Unresolved/non-US SEC candidates stay explicitly uncovered; ambiguous identity
must never be guessed.

This remediation does not change credentials, configured destinations, runtime
permission settings, family approval rules, provider accounts, or master. It does
not repeat a satisfactory import to test prose. A future hosted rejection remains
possible; the concrete prevention is consistent authority, complete visible
scope, reproducible failure checks, and explicit completion evidence.
