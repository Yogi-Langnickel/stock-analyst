# Global Insider And Public-Official Data Plan

Status: proposed implementation plan
Reviewed: 2026-08-15
Scope: automate the weekly private issue workflow and extend official-source
enrichment beyond US SEC Form 4 without changing the meaning of existing data.

## Outcome And Recommendation

Implement Proposal 1, the local-first orchestrator, now. It is the lowest-cost,
lowest-privacy-risk path and builds on the current issue importer, approval gate,
Google Sheets exporter, and cached SEC Form 4 refresh. Run it twice weekly and
on demand. Move to Proposal 3, an always-on private runner, only if missed runs
or workstation availability become an operational problem. Proposal 2 is useful
only if remote intake status is worth the extra cloud and privacy controls.

“Automate everything” means automating detection, extraction, candidate
reconciliation, enrichment, validation, staging, and status reporting. It does
not remove the mandatory human approval step before magazine-derived rows become
family-visible. Public regulatory data is contextual evidence, not a generated
buy or sell recommendation.

The first global-source wave should pilot the Netherlands AFM, Sweden FI,
France AMF, Brazil CVM, Korea OpenDART, Japan EDINET, the US House, Norway's
Storting, the UK Commons interests API, France HATVP, and Brazil TSE. Each source
must retain its actual semantics. In particular, ownership changes, large-holder
reports, holdings/interests, material changes, and asset snapshots must never be
presented as insider trades.

## Three End-To-End Automation Proposals

All three proposals use the same safe state machine:

`detected -> checksummed -> extracted -> reconciled -> needs_review -> approved
-> exported`, followed independently by `SEC/global refresh -> validated ->
published`. A failed enrichment must not roll back or invalidate an already
approved issue export, and a draft issue must never become family-visible merely
because enrichment succeeded.

| Proposal | End-to-end design | Cost | Complexity | Reliability and operations | Privacy | Decision |
| --- | --- | --- | --- | --- | --- | --- |
| 1. Local-first orchestrator | A `launchd` job and one idempotent CLI command discover the newest PDF in the known private folder, checksum it, build the issue plan and candidate manifest, pause for review, export approved rows, refresh SEC and enabled global adapters, then emit a metadata-only run report. | Lowest; existing Mac, no new service | Low to medium | Good while the Mac is awake; missed scheduled runs are recovered by the next run or manual command. A lock prevents overlap. | Best: PDF, extracted text, caches, and approvals stay local; only approved rows go to the private Sheet. | **Recommended now** |
| 2. Google metadata coordinator plus local worker | A small Cloud Scheduler/Cloud Run job checks private Drive metadata and queues a source identifier; a local authenticated worker downloads and processes the PDF, then reports redacted status. Regulatory adapters may run in Cloud Run, but magazine extraction remains local. | Low recurring cloud cost plus engineering time | High | Good detection and notifications, but two control planes, queue recovery, cloud IAM, key rotation, and local-worker availability must be operated. | Better than cloud PDF processing because the coordinator sees metadata only, but Drive identifiers and run metadata enter cloud logs and require explicit retention rules. | **Defer** until remote status is valuable |
| 3. Always-on private container runner | A dedicated Mac mini, NAS, or home server runs a containerized scheduler, private queue, local cache, review UI, and Sheets exporter. It polls the known location, performs all parsing and official-source refreshes, and exposes health only on the private network. | Hardware/electricity plus backups; little or no cloud spend | Medium to high | Best unattended operation if storage, upgrades, backups, alerting, and recovery are maintained. No laptop sleep issue. | Strong: private payloads remain on controlled hardware, but the new host becomes a sensitive system requiring disk encryption and access control. | **Preferred future upgrade** if Proposal 1 misses runs |

Proposal 1 implementation should produce a portable container boundary so the
same command can later move to Proposal 3. Do not use a public CI artifact store
for PDFs, extracted text, approval files, caches, or workbook exports.

## Semantic Model

The following families are deliberately separate:

| Semantic family | Meaning | Must not be labelled as |
| --- | --- | --- |
| `manager_transaction` | A person with management responsibility or related person reported an acquisition, disposal, grant, exercise, transfer, or other security transaction. | Open-market buy/sell unless the source code proves it |
| `public_official_transaction` | A legislator, judge, or other covered official disclosed a purchase, sale, or exchange, often as an amount range. | Exact price, exact quantity, beneficial ownership, or investment advice |
| `role_aggregate` | Transactions/positions are aggregated for a role or body rather than attributed to a named natural person. | A named insider's trade |
| `ownership_change` | A filing reports a change in ownership or beneficial interest. It may include causes other than a market trade. | A Form 4-equivalent transaction |
| `large_holder_report` | A threshold-based large-shareholding report or amendment. | A director/PDMR transaction |
| `holding_or_interest` | A current interest, appointment, beneficial-control state, or periodically declared holding. | A dated purchase or sale |
| `material_change` | A reportable change to assets, liabilities, income, or interests. | A securities transaction unless explicitly stated |
| `asset_snapshot` | Assets declared at an election, appointment, start/end of office, or periodic reporting date. | A continuous transaction feed |

## Official Regulatory And Corporate Sources

“Pilot” authorizes a fixture-based adapter proof only. Production network access
still requires the compliance gates below. “Hold” means no automated retrieval.
“Reject” means the identified access path must not be automated; a separately
licensed or explicitly permitted feed may be reconsidered.

| Jurisdiction and official source | Actual semantic family | Access finding | Decision and rationale |
| --- | --- | --- | --- |
| United States — [SEC EDGAR APIs and fair-access guidance](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) | `manager_transaction`; Form 4 is the current canonical US feed | Structured submissions metadata and filing XML; identified, paced access is required | **Keep/extend.** Preserve the existing cache, filing identity, partial-run reporting, and zero-network replay. Only transaction code `P` plus `Acquired`, or `S` plus `Disposed`, supports automatic open-market wording. |
| Netherlands — [AFM MAR Article 19 managers' transactions register](https://www.afm.nl/en/sector/registers/meldingenregisters/transacties-leidinggevenden-mar19-) | `manager_transaction` | Official register offers CSV and XML exports | **Pilot first.** Best initial non-US adapter because the official export is structured and transaction-level. Verify export terms, stable IDs, corrections, and rate expectations before scheduling. |
| Sweden — [Finansinspektionen PDMR register](https://www.fi.se/en/our-registers/pdmr-transactions/) and [public search](https://marknadssok.fi.se/publiceringsklient/en-GB) | `manager_transaction` | Official public register exposes person, issuer, instrument, date, volume, price, currency, and status | **Pilot.** Confirm a supported export or retrieval contract; do not bind to undocumented page internals. |
| France — [AMF managers' declarations](https://www.amf-france.org/fr/formulaires-et-declarations/societes-cotees-et-operations-financieres/declarations-des-dirigeants-formulaires-et-declarations) and [BDIF search](https://bdif.amf-france.org/fr?typesInformation=DD) | `manager_transaction` | Official declarations and downloadable records are available | **Pilot.** Start with a bounded fixture and revision study; retain the original declaration link and French transaction wording. |
| Germany — [BaFin Directors' Dealings](https://www.bafin.de/DE/Aufsicht/BoersenMaerkte/Transparenz/InformationspflichtenEmittenten/DirectorsDealings/directorsdealings_artikel.html) | `manager_transaction` | BaFin states that its database contains reported and published directors' dealings | **Bounded pilot only after terms review.** Do not schedule until the supported query/export method and reuse terms are recorded. |
| Brazil — [CVM Valores Mobiliarios Negociados e Detidos](https://dados.cvm.gov.br/dataset/cia_aberta-doc-vlmo) | `role_aggregate`, with holdings as supplied | Official weekly open-data ZIPs cover the last five years and may be republished with corrections | **Pilot.** Never manufacture a named person: the source can aggregate by governing-body role. Model re-presentations as revisions. |
| Korea — [DART disclosure system](https://dart.fss.or.kr/) and [OpenDART developer portal](https://opendart.fss.or.kr/) | `ownership_change` for executives/major shareholders; separate `large_holder_report` filings also exist | Official API-key service and filing system | **Pilot in Ownership Changes.** It is not a Form 4 clone. Preserve report type and reason; do not reduce every change to buy/sell. |
| Japan — [EDINET search and API guidance](https://disclosure2.edinet-fsa.go.jp/week0020.aspx) | `large_holder_report` | Official API v2 requires registration/key; the source exposes reports of possession of large volume | **Pilot only as Large Holder Reports.** Do not place EDINET large-volume filings in manager transactions. |
| United Kingdom — [FCA National Storage Mechanism FAQ, January 2026](https://www.fca.org.uk/publication/primary-market/fca-nsm-help-and-faqs.pdf) | PDMR documents can represent `manager_transaction`; NSM also contains `large_holder_report` and other filings | The NSM supports interactive search/CSV, but the specialist terms review found programmatic access prohibited | **Reject direct automation.** Hold until the FCA supplies a documented API, bulk feed, or written permission. Manual links may be recorded without copying content. |
| United Kingdom — [Companies House Persons with Significant Control API](https://developer-specs.company-information.service.gov.uk/companies-house-public-data-api/reference/persons-with-significant-control) and [daily PSC snapshot](https://download.companieshouse.gov.uk/en_pscdata.html) | `holding_or_interest` / beneficial-control context | Official API and daily JSON snapshot | **Pilot as ownership context only.** A PSC notification is not a director trade. Minimize personal fields and never export addresses or birth details. |
| Canada — [SEDAR+ terms of use](https://sedarplus.ca/onlinehelp/terms-of-use/) / SEDI insider reports | `manager_transaction`; closest Canadian analogue to Form 4 | Public reports exist, but the terms prohibit robots, automated searches, scraping, and automated copying without permission | **Reject direct automation; hold for a feed agreement.** Do not scrape SEDI/SEDAR+. |
| Chile — [CMF Article 12 transaction tool](https://www.cmfchile.cl/portal/estadisticas/626/w4-propertyvalue-45866.html) | `manager_transaction`; Article 20 must remain a distinct reporting basis where applicable | Official interactive query, but no verified bulk/API retrieval contract | **Hold automation.** Use a small manual sample to validate semantics and request permission or a supported feed before adapter work. |
| Norway — [Finanstilsynet MAR/PDMR guidance](https://www.finanstilsynet.no/en/topics/market-abuse-regulation-mar-in-norway/) | `manager_transaction` notifications | Official page explains submission through Altinn and issuer publication, but no regulator retrieval feed was verified | **Hold.** Do not infer that a submission portal is a public collection API. Issuer announcements are not a regulator feed. |
| Ireland — [Central Bank manager-transaction notifications](https://www.centralbank.ie/regulation/industry-market-sectors/securities-markets/market-abuse-regulation/notification-of-managers-transactions) | `manager_transaction` notifications | Official page documents portal submission and issuer publication, not a public retrieval feed | **Hold.** Seek a supported public feed; do not automate the submission portal. |
| India — [NSE listed-company disclosures](https://www.nseindia.com/companies-listing/corporate-filings-insider-trading) | `manager_transaction` disclosures | Relevant disclosures exist, but a stable, permission-compatible official retrieval feed was not verified | **Hold/reject current automation path.** Reassess only with documented API/bulk terms or written permission. |
| Hong Kong — [HKEX Disclosure of Interests Online](https://www2.hkexnews.hk/ListedCompanyPublications/SDW/Search/SDWSearch.aspx) | `ownership_change` / interests disclosure; may contain transaction details | Official interactive system; no approved bulk/API path was verified | **Hold/reject current automation path.** Do not scrape DION. |
| Australia — [ASX company announcements](https://www.asx.com.au/markets/trade-our-cash-market/announcements) | Director-interest notices can encode `manager_transaction`; substantial-holder notices are `large_holder_report` | Official announcements are mostly documents and terms/data-licensing constraints were not cleared | **Hold/reject current automation path.** Consider a licensed announcements feed; do not treat all Appendix 3Y changes as market trades. |
| Singapore — [SGX company announcements](https://www.sgx.com/securities/company-announcements) | Director/CEO interest changes are `ownership_change` and sometimes `manager_transaction` | Official announcement documents, but no permission-compatible bulk feed was verified | **Hold/reject current automation path.** Reassess only with a documented API or licence. |
| Mexico — [CNBV](https://www.gob.mx/cnbv) | No verified candidate feed | No official, structured, semantically adequate transaction feed was established | **Reject for this phase.** Keep as a research backlog; do not substitute a tracker. |
| Argentina — [CNV](https://www.argentina.gob.ar/cnv) | No verified candidate feed | No official, structured, semantically adequate transaction feed was established | **Reject for this phase.** Keep as a research backlog; do not substitute a tracker. |

## Official Politician And Public-Official Sources

These sources belong in separate public-official views. They must never be mixed
into the 12-column SEC ledger or described as corporate-insider filings.

| Jurisdiction and official source | Actual semantic family | Access finding | Decision and rationale |
| --- | --- | --- | --- |
| United States House — [Clerk financial disclosures and PTRs](https://disclosures-clerk.house.gov/FinancialDisclosure) | `public_official_transaction` for Periodic Transaction Reports; annual reports are `holding_or_interest` | Official search and source documents | **Pilot.** Start with PTR metadata and amount ranges. Confirm supported download behavior, amendments, and acceptable automation before scheduling. |
| United States Senate — [electronic financial disclosure search](https://efdsearch.senate.gov/search/) | `public_official_transaction` for PTRs; annual reports are `holding_or_interest` | Official session/attestation flow | **Manual/hold.** Do not automate acceptance, session controls, or document retrieval without explicit compliance approval. |
| Norway Storting — [Register of Members' Appointments and Economic Interests](https://www.stortinget.no/en/in-english/members-of-the-storting/registered-interest/) | `public_official_transaction` plus `holding_or_interest` | The official rules require covered members to register transactions, dates, and values; the register also includes non-transaction interests | **Pilot; best foreign transaction candidate.** Keep transactions and standing interests as separate record types. Confirm a stable official export before scheduling. |
| United States judiciary — [Federal Judicial Financial Disclosure Reports](https://pub.jefs.uscourts.gov/) and [filing instructions](https://www.uscourts.gov/sites/default/files/2025-03/judiciary-financial-disclosure-filing-instructions.pdf) | `public_official_transaction` for AO 10T; other reports are `holding_or_interest` | Registration/attestation is required each time and statutory use restrictions apply | **Manual/hold.** Do not automate registration, attestation, or downloads. Record only manually approved metadata and official links. |
| Ukraine — [NACP public declaration register](https://public.nazk.gov.ua/) | `material_change` and asset declarations | Official declarations may report significant changes in assets; a stable, permission-cleared retrieval contract was not established | **Hold.** Do not convert asset changes into securities trades or infer beneficial ownership. Reassess API availability and safety constraints before a pilot. |
| United Kingdom Commons — [Register of Members' Financial Interests](https://www.parliament.uk/mps-lords-and-offices/standards-and-financial-interests/parliamentary-commissioner-for-standards/registers-of-interests/register-of-members-financial-interests/) | `holding_or_interest` | Official page provides an API under the Open Parliament Licence; members report registrable-interest changes | **Pilot.** Store category, dates, declared text-derived structured facts, and source revision; do not call a change a securities transaction unless explicitly reported as one. |
| France — [HATVP open data](https://www.hatvp.fr/open-data/) | `asset_snapshot` and `holding_or_interest` | Official CSV index and XML declarations under the Etalab Open Licence | **Pilot.** Preserve declaration type and reporting date. Do not derive transaction histories by differencing snapshots for presentation as trades. |
| Australia — [Register of Senators' Interests](https://www.aph.gov.au/Parliamentary_Business/Committees/Senate/Senators_Interests/Senators_Interests_Register) and [House Members' Interests](https://www.aph.gov.au/Senators_and_Members/Members/Register) | `holding_or_interest`; alteration notices are changes, not necessarily trades | Official online registers include declarations and alterations, with document-heavy and chamber-specific formats | **Manual/hold.** Build fixtures only after reuse terms and stable retrieval are confirmed. Never expose confidential family-interest fields that are not in the public register. |
| Brazil — [TSE candidate open data](https://dadosabertos.tse.jus.br/dataset/?groups=candidatos) | `asset_snapshot` at election/candidacy reporting points | Official CSV datasets, including candidate assets, with dataset-level licence metadata | **Pilot.** Treat each election/reporting date as a snapshot, never as a live politician-trade feed. |
| Canada — [Conflict of Interest and Ethics Commissioner public registry](https://ciec-ccie.parl.gc.ca/en/public-registry) | `material_change` and `holding_or_interest` | Official searchable registry exposes disclosure summaries and notices of material change, but no supported bulk/API feed was verified | **Hold automation; allow manual research.** A material-change notice can cover assets, liabilities, or other interests and is not necessarily a trade. |

Community trackers, media databases, GitHub mirrors, and commercial
aggregators are **rejected as canonical sources**. They may be used manually to
discover a missing official filing, but every retained record must resolve to an
official source document. Their derived classifications must not enter the
canonical dataset.

## Compliance And Licensing Gate

Every adapter has a committed metadata descriptor but no credentials or private
identifiers. Network execution remains disabled until all required fields are
approved:

- official owner, jurisdiction, source URL, semantic family, and source fields;
- access mode (`api`, `bulk`, `export`, or `manual`), authentication, documented
  rate limit, robots position, terms/licence URL and version/date checked;
- permitted caching, retention, redistribution, attribution, and deletion rules;
- personal-data minimization review and an explicit list of prohibited fields;
- maintainer, test fixture provenance, request budget, retry/backoff policy,
  and kill switch;
- a `network_enabled` decision signed off separately from parser completion.

A terms change, authentication failure, robots denial, unexpected login wall,
CAPTCHA, or response-schema drift automatically disables the adapter. There is
no paywall bypass, CAPTCHA bypass, session imitation, proxy rotation, or stealth
scraping. A manual or held source stays manual/held until the gate is reopened;
its existence in this plan is not permission to automate it.

## Canonical Schemas

Use append-only, source-faithful records internally. Google Sheets receives
only the curated display projection.

### Source and document records

```text
SourceDescriptor
  source_key, owner, jurisdiction, semantic_families[], official_url
  access_mode, licence_url, terms_version, terms_checked_at
  request_budget, cache_policy, network_enabled, decision, decision_reason

SourceDocument
  source_document_id, source_key, native_document_id, canonical_url
  published_at, effective_at, retrieved_at, content_hash
  native_revision, revision_sequence, supersedes_document_id
  retrieval_status, parse_status, review_status
```

`source_document_id` is `source_key:native_document_id` when an official stable
ID exists. Otherwise use `source_key:` plus a digest of the official canonical
URL and source-supplied publication identifier. The content hash detects silent
replacement; it is not the public identity and must never be used to hash a
credential or private identifier.

### Event and state records

```text
DisclosureRecord
  disclosure_id, source_document_id, native_record_id, semantic_family
  jurisdiction, issuer_ref, person_ref, role_as_reported
  instrument_ref, event_date, publication_date, action_as_reported
  normalized_action, direction, quantity_or_range, price_or_range
  currency, value_or_range, holding_after_or_range
  period_start, period_end, notes_code, amendment_status
  source_url, parser_version, parse_confidence, review_status
```

Never coerce ranges to midpoints. Never infer a missing price, quantity,
currency, issuer, instrument, person, action, or direction. Preserve the source
literal/code in a private canonical field and map to a normalized value only
when the source documentation supports it.

### Identity and matching

- Issuers use a local `IssuerIdentity` table keyed by an internal UUID, with
  reviewed aliases for WKN, ISIN, LEI, CIK, exchange+ticker, official registry
  identifiers, name, and validity dates.
- Match unique exact official identifiers first. A ticker is exchange-scoped,
  not globally unique. Name normalization can propose candidates but cannot
  auto-link an ambiguous issuer.
- People use a source-scoped `PersonIdentity` with official filer ID when
  supplied, normalized name, role, jurisdiction, and validity dates. Do not
  merge people across jurisdictions from name similarity alone.
- Closely associated persons, spouses, dependants, trusts, and controlled
  entities retain the relationship reported by the source. Do not infer the
  underlying beneficial owner or household portfolio.
- Unresolved and ambiguous identities remain visible in QA but are omitted from
  issuer-specific Sheet views until reviewed.

### Deduplication, corrections, and revisions

1. Prefer a source-native record/filing ID.
2. For SEC Form 4, retain the current filing-transaction identity, including
   accession/document and transaction position; continue linking the Company
   cell to the filing.
3. For documents containing multiple rows, derive `disclosure_id` from
   `source_document_id + native_record_id`, or a deterministic row locator when
   no native row ID exists.
4. Never deduplicate across semantic families merely because person, issuer,
   and date match.
5. A corrected/re-presented filing creates a new document revision that
   supersedes the prior revision. Keep both internally; the current Sheet view
   shows the latest effective revision and a correction marker.
6. A replay over an unchanged cache must perform zero network requests and add
   zero records. Report retained records and prevented duplicates.

## Phased Implementation Plan

### Phase 0 — Baseline and acceptance tests

1. Capture metadata-only current state: branch, dirty files, corpus latest
   filename/checksum, current issue ID, workbook tab/header shapes, and SEC
   refresh status. Never log PDF text, rows, Sheet/Drive IDs, or credentials.
2. Freeze the existing 12-column `Insider Activity` contract in a regression
   test, including Company-cell filing links, simplified transaction labels,
   green `Acquired` rows, red `Disposed` rows, and filing-identity deduplication.
3. Define completion separately: issue extraction complete, candidate
   reconciliation complete, private reviewer export complete, family approval
   complete, SEC refresh complete/partial, and each global source
   complete/partial/disabled.
4. Add source-fixture licensing notes. Fixtures contain synthetic or minimally
   necessary official snippets, never copied private magazine content.

### Phase 1 — Orchestrator and run ledger

1. Add a single idempotent weekly command with `--dry-run`, `--issue-only`,
   `--sec-only`, `--global-only`, and `--cached-only` modes.
2. Discover the newest correctly named PDF in the known private location,
   checksum it, and compare it with the private intake manifest. A new name with
   a repeated checksum is a duplicate; a changed checksum under an imported name
   is a blocking revision requiring review.
3. Acquire a per-workspace lock and write an ignored metadata-only `RunRecord`
   containing phase statuses, counts, durations, adapter budgets, cache hits,
   and redacted failure classes.
4. Resume from the last safe phase after interruption. Never clear live Sheet
   rows before replacement data has been validated and written.

### Phase 2 — Latest issue pipeline

1. Run local extraction and generate the workbook plan plus the whole-issue
   source-candidate manifest.
2. Reconcile every candidate one-to-one with an emitted row or a reviewer-owned
   exception. `--allow-draft-rows` remains private reviewer triage and cannot
   satisfy family-visible completion.
3. Generate a hash-bound approval file. Pause only at the human review gate and
   surface metadata counts/exception types, not source text, in notifications.
4. After approval, export the issue tab and rebuild `Aktuell`; verify literal
   latest-issue/`Aktuell` parity for the approved rows and verify tab
   protections.

### Phase 3 — Canonical disclosure store

1. Implement the descriptors and schemas above in an ignored local SQLite
   database or versioned JSONL store; SQLite is preferred once more than two
   adapters exist because revisions and identity mappings need transactions.
2. Add migrations, source enable/disable state, provenance, raw-response cache
   metadata, and an append-only revision table.
3. Encrypt the host disk, keep raw caches outside Git, restrict permissions,
   and back up only to an approved encrypted private destination.
4. Add export projections that cannot cross semantic-family boundaries.

### Phase 4 — Adapter pilots

1. Build one `SourceAdapter` interface: `discover(since)`, `fetch(document)`,
   `parse(payload)`, `normalize(records)`, and `checkpoint()`.
2. Start transaction pilots with AFM, then FI and AMF. Start non-transaction
   pilots with CVM VLMO, OpenDART ownership changes, EDINET large-holder reports,
   Companies House PSC, UK Commons interests, HATVP, and TSE assets.
3. Pilot US House PTR and Storting transactions in their own public-official
   schema. Preserve reported amount ranges and source-specific roles.
4. Add BaFin only after its terms/export gate passes. Do not implement network
   clients for held/rejected sources.
5. Each adapter ships with parser fixtures, schema-drift detection, correction
   tests, pagination/budget tests, and a forced-offline cache replay.

### Phase 5 — Resolution and reviewer QA

1. Build issuer candidates from reviewed WKN/ISIN/LEI/CIK/exchange+ticker
   mappings. Require exact unique matches for automatic linking.
2. Queue ambiguous issuer/person/instrument mappings in a separate private QA
   artifact. A reviewer can approve or reject a mapping with timestamp and
   evidence URL.
3. Validate dates, currencies, signs, quantity/value ranges, direction/code
   combinations, relationship types, and holdings-after arithmetic only where
   the source supplies enough information.
4. Compare document counts to parsed-record counts, expose amendments and
   rejected rows, and sample source links. Do not infer an unresolved issuer
   from nearby matches.
5. Run a second independent persona review before enabling each substantial
   adapter: data-fidelity reviewer, then privacy/compliance reviewer. Resolve or
   explicitly classify every required finding.

### Phase 6 — Scheduling, monitoring, and recovery

1. Schedule Proposal 1 Thursday and Friday morning local time plus an on-demand
   run. Run SEC/global refresh even when no new issue is present.
2. Use per-source watermarks with overlap windows so late filings and revisions
   are found. Source publication time, event time, and retrieval time remain
   distinct.
3. Enforce source-specific budgets, exponential backoff, jitter, timeouts, and
   circuit breakers. Never rotate identities or proxies to evade limits.
4. Alert on: new issue awaiting review, candidate-reconciliation blocker,
   partial SEC/global run, terms recheck due, schema drift, repeated HTTP
   failures, unexpected row-count change, stale successful refresh, and Sheet
   verification failure.
5. Reports contain only counts, source keys, status, timing, and redacted error
   classes. No names, holdings, source text, URLs containing private IDs, or
   credentials appear in logs or notifications.
6. Recovery is cache-first: retry failed sources independently, replay without
   network, then publish only the validated projection. One source failure must
   not erase another source's prior good data.

### Phase 7 — Test and rollout gates

1. Unit-test every parser, normalizer, identity rule, semantic-family boundary,
   revision, and dedup key with synthetic data.
2. Contract-test official fixtures for field presence and types without network.
3. Integration-test the full dry run, approval pause/resume, replacement-write
   order, cache replay, partial status, and adapter kill switches.
4. Verify the exact SEC 12-column headers and formatting before and after every
   new view rollout.
5. Shadow each pilot locally for four weekly cycles. Compare a bounded sample
   against official documents and require zero unexplained duplicates, no
   semantic-family leakage, and documented unresolved matches.
6. Enable one new Sheet family at a time for private reviewers. Family-visible
   promotion requires explicit approval after visual inspection.
7. Recheck terms quarterly and on source behavior changes. Automatically disable
   an adapter whose review has expired.

## Google Sheets Presentation

### Preserve the SEC ledger exactly

Do not add, remove, rename, or reorder columns in `Insider Activity`:

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

Company cells keep their direct SEC filing hyperlinks. The full row stays green
for `Acquired` and red for `Disposed`. Transaction codes remain simplified for
display while the raw source code stays in the private canonical store. No
global or politician source writes to this tab.

### Separate semantic-family tabs

Add these protected, feature-gated views only after their corresponding pilot
passes. Keep raw/native detail in the local store and show a compact projection:

| View | Suggested visible fields | Reader cue |
| --- | --- | --- |
| `Global Manager Transactions` | Country, Company, WKN/ISIN, Person/Role, Relationship, Event date, Transaction, Direction, Quantity/range, Price/range + currency, Value/range, Holding after, Source | “Reported manager/PDMR transaction”; filter by country, company, date, and transaction class |
| `Ownership Changes` | Country, Company, Identifier, Reporter/role, Effective date, Previous holding, New holding, Change/reason, Filing type, Source | “Ownership change; not necessarily a market trade” |
| `Large Holder Reports` | Country, Issuer, Identifier, Holder, Threshold/holding, Report date, Change reason, Filing status, Source | “Threshold/large-holder filing” |
| `Public Official Transactions` | Country, Official, Office/chamber, Asset/instrument, Transaction date, Type, Amount range, Owner as reported, Filing date, Source | “Self-reported public-official transaction; values may be ranges” |
| `Public Official Interests` | Country, Official, Office, Interest category, Entity/asset, Start/effective date, End date, Disclosure type, Source | “Registered interest or holding; not a trade” |
| `Material Changes & Asset Snapshots` | Country, Official/candidate, Office/election, Record kind, Asset/category, Value/range, Effective/reporting date, Source | “Material change or dated snapshot; not a transaction feed” |
| `Disclosure Coverage` | Source, Jurisdiction, Semantic family, Status, Last successful refresh, Latest publication seen, Coverage window, Unresolved count, Partial reason, Terms review due | Operational transparency without private source content |

Use a frozen header, filters, alternating rows, compact date/currency formats,
and a first-row neutral legend on each new view. Do not overload red/green to
mean good/bad: only the existing SEC direction colors retain that convention.
For non-US transactions, display source currency; add a separately labelled FX
context field only if an official rate and observation date are retained.

Do not add the new families to `Search` until literal projection parity,
section isolation, source-link preservation, and protection tests exist. If
added later, stack each family in a separately titled section rather than
forcing unlike schemas into a single table. `Aktuell` remains magazine-only.

## Privacy, No-Advice, And No-Inference Safeguards

- Keep PDFs, extracted text, approval records, identifiers for private Drive or
  Sheets resources, credentials, caches, raw rows, and reviewer notes out of
  Git and logs.
- Export only fields already public in the official disclosure and necessary
  for the private family review use case. Drop addresses, full dates of birth,
  contact details, account identifiers, signatures, dependant details, and
  other unnecessary personal data even when present in a filing.
- Use neutral labels: “reported”, “disclosed”, “acquired”, “disposed”,
  “ownership changed”, or “interest registered”. Never describe a disclosure as
  suspicious, predictive, smart money, a recommendation, or proof of intent.
- Do not infer a trade from two snapshots; do not infer a voluntary buy/sell
  from grants, gifts, exercises, tax withholding, transfers, inheritance,
  corporate actions, or unexplained ownership changes.
- Do not rank politicians, judges, insiders, or companies by presumed motive,
  ethics, future performance, or family portfolio relevance.
- Show source coverage and staleness. Absence of a filing means “not observed in
  enabled sources”, not “no activity”. A held or disabled source is explicitly
  “not covered”.
- Keep magazine recommendations and external disclosures separately sourced.
  Enrichment never fills missing target, stop, price, ticker, WKN, ISIN, action,
  or recommendation fields.
- Standard reader notice: “This private digest summarizes magazine content and
  public disclosures. It is not personal financial advice, a recommendation,
  a suitability assessment, or evidence of intent.”

## Definition Of Done

The work is complete only when:

- the newest local issue is identified, fully candidate-reconciled, manually
  reviewed, exported in the correct mode, and verified against `Aktuell`;
- SEC refresh is a complete scan rather than request-budget-limited, its Sheet
  projection retains the exact 12-column contract, and cached replay is
  zero-network/idempotent;
- each enabled global adapter has a current compliance decision, source-faithful
  schema, deterministic identity/revision handling, passing offline and
  integration tests, and four successful shadow cycles;
- held/rejected sources have made no automated requests;
- every visible row links to an official source, unresolved identities remain
  unresolved, and every view carries the correct semantic/no-advice cue;
- the live private Sheet has been visually checked for filters, protections,
  links, formatting, row counts, and stale trailing data without exposing any
  private identifiers in the completion report.
