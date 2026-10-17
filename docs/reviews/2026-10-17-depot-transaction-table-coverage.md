# Depot transaction coverage review

Date: 2026-10-17
Baseline: `69fe7de225882099d2e9e49c19e92c41a2646f38`
Branch: `fix/depot-transaction-week43`

The focused change preserves printed transaction prices, accepts explicit
missing performance cells, and supports the controlled inline booking action.
All source material and operational artifacts remain private and ignored.

1. Extraction/data-fidelity review: passed after two required corrections. The
   reviewer corrected an initial mistaken claim that booking price was missing;
   the numeric source price is retained exactly. A missing identifier followed
   by another inline booking row must fail rather than merge the identities;
   the guard and synthetic regression now enforce this. No findings remain.
1. Privacy/workbook-operations review: passed with no required or advisory
   findings. Focused validation passed all six depot tests and 42 workbook tests.
   Booking stays in `Depot Transactions` and cannot become an `Aktuell` Buy/Sell
   action. The review grants no family approval or separate provider authority.

The developer and primary independently passed Python compilation, all 366
repository tests and `git diff --check`. The source-price proof is private and
reported only as equality booleans. The primary independently verified the
frozen source/test/memory/incident hashes before acceptance.

At this documentation checkpoint, whole-issue visual reconciliation and the
live private draft import, cumulative SEC refresh and blocked-fetch cache replay
are still pending. Completion of this parser repair alone does not establish
weekly refresh completion or family-visible readiness.
