# Free Market Data Options

Status: active plan
Created: 2026-05-15
Last checked: 2026-05-15

Market data is enrichment only. It can help reviewers validate context, stale
prices, symbols, and broad market moves, but it must not overwrite magazine
source fields or fill missing recommendation details.

## Provider Status

| Provider | Current implementation | Credentials | Network in tests | Fit |
| --- | --- | --- | --- | --- |
| `disabled` | Available default | None | No | Tests, local PDF intake, family review |
| `stooq_csv` | Local CSV parser only | None | No | First deterministic price-context parser |
| `alpha_vantage` | Metadata only | `ALPHA_VANTAGE_API_KEY` | No | Optional future key-based daily and cross-asset context |
| `twelve_data` | Metadata only | `TWELVE_DATA_API_KEY` | No | Optional future quote/time-series/reference context |
| `fmp` | Metadata and dry-run planner only | `FMP_API_KEY` | No | Optional future Financial Modeling Prep quote/profile/fundamentals context |
| `sec_companyfacts` | Metadata only | No key; `SEC_USER_AGENT` before live access | No | Optional future US issuer fundamentals and filing metadata |

`STOCK_ANALYST_MARKET_DATA_PROVIDER` defaults to `disabled`. Selecting
`stooq_csv` only enables parsing caller-supplied CSV text; it does not fetch
from Stooq. Selecting key-based or SEC providers does not enable live calls
because adapters, cache policy, throttling, and terms checks are not complete.

## Recommended Order

1. Disabled provider
   - Default for tests, local PDF intake, and family review.
   - No network calls and no secrets.

2. Stooq CSV
   - Useful for no-key historical daily context and deterministic CSV parsing.
   - Best first live adapter because it avoids credentials and keeps failures
     simple.
   - Use explicit reviewer-provided ticker symbols until ticker/ISIN/WKN
     normalization exists.

3. Alpha Vantage
   - Good optional key-based source for daily equities, symbol search, forex,
     crypto, commodities, economic indicators, and technical indicators.
   - Free-key quotas are tight, so cache responses and keep batch/background
     enrichment opt-in.

4. Twelve Data
   - Useful later for real-time or near-real-time quote and time-series
     exploration under a free Basic plan.
   - Treat as optional because it requires a key and has per-minute credit
     limits.

5. Financial Modeling Prep
   - Useful later for quote, profile, and fundamentals exploration.
   - Current implementation is metadata-only plus a dry-run request planner.
   - `FMP_API_KEY` is the expected future credential, but the planner does not
     read, store, or expose it.
   - Supported dry-run planning endpoints start with `batch-quote-short`,
     `profile`, and `dividends`.
   - Keep a hard planning budget of 235 calls/day and plan against a
     512MB/month bandwidth ceiling before live access.

6. SEC companyfacts and filings
   - Official free source for US fundamentals and filing metadata.
   - Use for issuer/company context, not price validation.

## Current Provider Notes

- Alpha Vantage: official support says free API service covers most datasets up
  to 25 requests per day and requires accepting Alpha Vantage terms when
  claiming a free key. The terms describe personal, non-commercial use and a
  separate commercial-use path. Source:
  <https://www.alphavantage.co/support/> and
  <https://www.alphavantage.co/terms_of_service/>.
- Twelve Data: Basic is listed as free with 8 API credits per minute and 800 per
  day, with endpoint-specific credit weights. Source:
  <https://twelvedata.com/pricing>.
- Financial Modeling Prep: first project slice is bounded to metadata and
  dry-run planning only. Treat the configured limit as a hard 235 calls/day
  budget with a 512MB/month bandwidth planning note until live terms, endpoint
  weights, caching, and accounting are reviewed.
- SEC companyfacts: the official SEC API exposes
  `data.sec.gov/api/xbrl/companyfacts/CIK##########.json`, bulk companyfacts ZIP
  data, and real-time API updates. SEC fair-access guidance limits each user to
  no more than 10 requests per second and requires efficient, identified
  automated access. Sources:
  <https://www.sec.gov/search-filings/edgar-application-programming-interfaces>
  and <https://www.sec.gov/about/developer-resources>.
- Stooq CSV: keep as the first no-key parser for reviewer-supplied CSV text.
  Before adding a live downloader, confirm Stooq terms, acceptable request
  rates, caching expectations, and symbol coverage for US/EU instruments.

## Implementation Plan

1. Keep `STOCK_ANALYST_MARKET_DATA_PROVIDER=disabled` as the default.
2. Parse Stooq CSV from local fixture text first; network fetching remains a
   separate adapter behind explicit configuration.
3. Add cache files under ignored `data/market-cache` before enabling any live
   provider.
4. Attach enrichment output as source metadata with provider, observed date,
   and status.
5. Cache metadata must carry freshness and compliance review fields before any
   live adapter is enabled: `retrieved_at`, `observed_on` when the provider
   supplies one, `ttl_seconds`, `expires_at`, `source_url_hash` instead of raw
   URLs, `terms_checked_at`, and a terms version or review note.
6. Mark unavailable or ambiguous market rows as `needs_review`; never infer a
   missing price, stop loss, target, ticker, ISIN, WKN, or recommendation.
7. Add provider terms/rate-limit notes before enabling network calls.

## First Slice Implemented

- `stock_analyst.market_data.market_data_disabled`
- `stock_analyst.market_data.parse_stooq_daily_csv`
- Unit tests proving missing prices stay review-gated.

## Second Slice Implemented

- Static provider metadata for disabled, Stooq CSV, Alpha Vantage, Twelve Data,
  and SEC companyfacts.
- `stock_analyst.market_data.load_market_data_config` resolves provider choice
  from environment-like mappings without reading or exposing secret values.
- Unit tests prove provider metadata does not permit live network access and
  key-based providers remain metadata-only until adapters are explicitly built.

## Third Slice Implemented

- Provider metadata now records rate-limit notes and whether cache files are
  required before live access.
- `stock_analyst.market_data.describe_market_data_request` normalizes known
  provider request identity for future cache lookup.
- `stock_analyst.market_data.build_market_data_cache_metadata` returns a
  deterministic path under ignored `data/market-cache` without creating files
  or making network calls.
- Unit tests prove cache identity rejects credential-like parameters and
  unknown provider IDs.

## Fourth Slice Implemented

- Cache metadata now includes placeholders or caller-supplied values for
  `retrieved_at`, `observed_on`, `ttl_seconds`, `expires_at`,
  `source_url_hash`, `terms_checked_at`, and `terms_version`.
- `source_url_hash` stores a SHA-256 prefix of the source URL so future cache
  records can be audited without retaining raw provider URLs that may include
  sensitive query structure.
- TTL expiry is computed only from supplied metadata; live providers remain
  disabled and no network access is added.

## Fifth Slice Implemented

- Financial Modeling Prep provider metadata is available as `fmp` with future
  credential env var `FMP_API_KEY`.
- FMP remains metadata-only and `network_access=False`; selecting it with a key
  still reports that the live adapter is not implemented.
- `stock_analyst.market_data.plan_fmp_enrichment_requests` creates dry-run
  `batch-quote-short`, `profile`, and `dividends` request descriptors without
  reading secrets or making network calls.
- The planner enforces a hard 235 calls/day default budget, denies call 236,
  treats local cache hits as budget-free, and carries the 512MB/month bandwidth
  planning note.
- `scripts/stock-analyst market-data-plan --env-file .env --symbol AAPL`
  supports dry-run planning from local env files. It recognizes
  `FMP_API_KEY`, `STOCK_ANALYST_MARKET_DATA_CACHE_DIR`,
  `STOCK_ANALYST_MARKET_DATA_DAILY_CALL_LIMIT`, and
  `STOCK_ANALYST_MARKET_DATA_TERMS_VERSION`, but command output exposes only
  whether credentials are configured.
- `--symbol-file ./data/private/enrichment-symbols.txt` supports private
  reviewer-controlled ticker lists for local scheduled dry runs.
- `scripts/stock-analyst-local-run` can run PDF import, extraction quality
  reporting, and FMP dry-run planning from the local machine without enabling
  live market-data network access.
