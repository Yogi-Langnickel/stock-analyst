# Free Market Data Options

Status: active plan
Created: 2026-05-15
Last checked: 2026-05-17

Market data is enrichment only. It can help reviewers validate context, stale
prices, symbols, and broad market moves, but it must not overwrite magazine
source fields or fill missing recommendation details.

Enrichment is downstream of magazine extraction. Do not make live provider API
calls until magazine rows have been populated into the workbook flow. Provider
symbols must come from instruments already present in the sheet/export rows,
with a private symbol map used only to translate a magazine row, WKN, or name to
the provider's ticker format.

## Provider Status

| Provider | Current implementation | Credentials | Network in tests | Fit |
| --- | --- | --- | --- | --- |
| `disabled` | Available default | None | No | Tests, local PDF intake, family review |
| `stooq_csv` | Local CSV parser only | None | No | First deterministic price-context parser |
| `alpha_vantage` | Metadata and dry-run planner only | `ALPHAVANTAGE_API_KEY`; legacy alias `ALPHA_VANTAGE_API_KEY` | No | Sparse fallback fundamentals, intelligence, commodities, forex, and indicators under 25/day |
| `twelve_data` | Metadata and dry-run planner only | `TWELVEDATA_API_KEY`; legacy alias `TWELVE_DATA_API_KEY` | No | Bulk quote, technical, reference, and limited analysis planning under 800/day |
| `finnhub` | Metadata and dry-run planner only | `FINNHUB_API_KEY`; `FINNHUB_SECRET` kept private but unused by REST planner | No | Analyst, insider, earnings, quote, news, and sentiment context planning |
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

2. Workbook-backed enrichment candidates
   - First populate rows from the magazine into the workbook/export flow.
   - Build enrichment candidates from those rows only.
   - Use a private symbol map for provider ticker translations. Do not enrich
     arbitrary watchlist symbols that are not in the workbook.

3. Stooq CSV
   - Useful for no-key historical daily context and deterministic CSV parsing.
   - Best first live adapter because it avoids credentials and keeps failures
     simple.
   - Use workbook-backed provider symbols only once ticker/ISIN/WKN
     normalization or a private symbol map exists.

4. Twelve Data
   - Best first broad daily enrichment candidate because the free tier gives
     800 daily credits and supports batch requests.
   - Use for current price, quote snapshots, technical indicators, market
     metadata, and some fundamentals/analysis where the free plan allows it.
   - Treat endpoint credit weights as budget debits, not raw request counts.

5. Finnhub
   - Best candidate for analyst recommendation trends, insider activity,
     earnings surprise, company news, and quote fallback.
   - Free-tier daily limits were not confirmed in official docs during review;
     common references report 60 calls/minute. Keep a local default cap of
     500/day until live response headers are inspected and documented.

6. Alpha Vantage
   - Useful as a sparse fallback for company overview, quote, technical
     indicators, commodities, forex, crypto, economic indicators, news
     sentiment, and insider transactions.
   - Hard quota is only 25 calls/day, so do not use it for broad watchlist
     polling. Reserve it for high-confidence ticker enrichments or gaps from
     Twelve Data/Finnhub/FMP.

7. Financial Modeling Prep
   - Useful later for quote, profile, and fundamentals exploration.
   - Current implementation is metadata-only plus a dry-run request planner.
   - `FMP_API_KEY` is the expected future credential, but the planner does not
     read, store, or expose it.
   - Supported dry-run planning endpoints start with `batch-quote-short`,
     `profile`, and `dividends`.
   - Keep a hard planning budget of 235 calls/day and plan against a
     512MB/month bandwidth ceiling before live access.

8. SEC companyfacts and filings
   - Official free source for US fundamentals and filing metadata.
   - Use for issuer/company context, not price validation.

## Current Provider Notes

- Alpha Vantage: official support says free API service covers most datasets up
  to 25 requests per day and requires accepting Alpha Vantage terms when
  claiming a free key. The terms describe personal, non-commercial use and a
  separate commercial-use path. Source:
  <https://www.alphavantage.co/support/> and
  <https://www.alphavantage.co/terms_of_service/>.
  The official documentation covers daily time series, quote, symbol search,
  company overview, dividends, earnings, news sentiment, insider transactions,
  commodities, forex, crypto, economic indicators, and technical indicators.
  Source: <https://www.alphavantage.co/documentation/>.
- Twelve Data: Basic is listed as free with 8 API credits per minute and 800 per
  day, with endpoint-specific credit weights. The docs cover quote/price,
  time series, reference data, dividends, earnings, statistics, analyst ratings,
  recommendations, price targets, insider transactions, batches, and API usage.
  Sources: <https://twelvedata.com/docs> and <https://twelvedata.com/pricing>.
- Finnhub: REST authentication uses an API key via token query parameter or
  header. Useful documented endpoint families include quote, recommendations,
  insider activity, earnings, company news, sentiment, and fundamentals.
  Official docs were reviewed at <https://finnhub.io/docs/api/introduction>.
  Public references commonly report a free-tier limit of 60 calls/minute; keep
  the project cap conservative until live response headers confirm account
  limits.
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
4. Derive provider symbols from workbook rows via `--workbook-plan-file` and a
   private `--symbol-map-file`. Manual `--symbol` and `--symbol-file` planning
   are development-only and must not be used for live enrichment.
5. Attach enrichment output as source metadata with provider, observed date,
   and status.
6. Cache metadata must carry freshness and compliance review fields before any
   live adapter is enabled: `retrieved_at`, `observed_on` when the provider
   supplies one, `ttl_seconds`, `expires_at`, `source_url_hash` instead of raw
   URLs, `terms_checked_at`, and a terms version or review note.
7. Mark unavailable or ambiguous market rows as `needs_review`; never infer a
   missing price, stop loss, target, ticker, ISIN, WKN, or recommendation.
8. Add provider terms/rate-limit notes before enabling network calls.

## Enrichment Signal Plan

These signals are reviewer context only. They must never overwrite magazine
recommendations, target prices, stop prices, or WKN/source fields.

| Signal | Primary source | Fallback source | Notes |
| --- | --- | --- | --- |
| Analyst consensus | Finnhub recommendation trends; Twelve Data recommendations/analyst ratings | Alpha Vantage analyst/intelligence endpoints if quota allows | Store consensus date and source; stale consensus is still useful but must be labelled. |
| Insider buying | Finnhub insider sentiment or insider transactions | Alpha Vantage insider transactions; Twelve Data insider transactions if plan allows | Summarize recent net buying/selling, not individual advice. |
| Earnings surprise | Finnhub earnings surprises; Twelve Data earnings | Alpha Vantage earnings history/calendar | Keep estimate, actual, surprise percent, and event date. |
| Sentiment trend | Finnhub company news/sentiment; Alpha Vantage news sentiment | Local magazine mention trend | Cache aggressively; do not call news endpoints for every stock daily. |
| Volatility regime | Twelve Data ATR/standard deviation/time series | Alpha Vantage technical indicators | Can be calculated locally from cached OHLCV. |
| Momentum score | Twelve Data RSI/MACD/rate-of-change/time series | Alpha Vantage RSI/MACD/ROC | Prefer local calculation once OHLCV cache exists. |
| Valuation score | FMP/profile/fundamentals; Twelve Data statistics | Alpha Vantage company overview | Use transparent component fields such as PE, PS, market cap, growth. |
| Quality score | FMP/fundamentals; SEC companyfacts for US issuers | Twelve Data fundamentals | Keep as slow-moving weekly/monthly enrichment. |

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
  `STOCK_ANALYST_MARKET_DATA_BUDGET_DIR`,
  `STOCK_ANALYST_MARKET_DATA_DAILY_CALL_LIMIT`, and
  `STOCK_ANALYST_MARKET_DATA_TERMS_VERSION`, but command output exposes only
  whether credentials are configured.
- `--symbol-file ./data/private/enrichment-symbols.txt` supports private
  reviewer-controlled ticker lists for local development dry runs only. It is
  not an approved live-enrichment source.
- `--workbook-plan-file ./data/private/workbook-plan.json` is the preferred
  enrichment-planning source. It reads magazine-backed workbook rows and only
  plans provider requests for rows with a matching entry in a private
  `--symbol-map-file` CSV containing `source_id,wkn,name,symbol`.
- `scripts/stock-analyst-local-run` can run PDF import, extraction quality
  reporting, and workbook-backed market-data dry-run planning from the local
  machine without enabling live market-data network access. It no longer uses a
  free-form symbol file by default.

## Sixth Slice Implemented

- Alpha Vantage provider metadata now matches the local env name
  `ALPHAVANTAGE_API_KEY`, while still accepting the legacy
  `ALPHA_VANTAGE_API_KEY` alias.
- Twelve Data provider metadata now matches the local env name
  `TWELVEDATA_API_KEY`, while still accepting the legacy `TWELVE_DATA_API_KEY`
  alias.
- Finnhub provider metadata is available as `finnhub` with `FINNHUB_API_KEY`.
  `FINNHUB_SECRET` may exist in `.env` but is not used by the dry-run REST
  planner.
- `market-data-plan` can dry-run request budgets for `alpha_vantage`,
  `twelve_data`, `finnhub`, and `fmp` with provider-specific default endpoint
  sets and budgets.
- Live network adapters remain disabled until persistent cache storage, request
  accounting, response-header limit capture, and endpoint-specific credit
  weights are implemented.
- Dry-run planning now reads a provider/day budget ledger from
  `STOCK_ANALYST_MARKET_DATA_BUDGET_DIR` and counts prior local usage against
  the same daily cap. Missing ledgers default to zero prior usage.
- Market-data cache files now have a structured credential-free cache record
  format with metadata, freshness fields, source URL hash, terms review fields,
  and provider response payload. Raw provider URLs and API keys must not be
  stored in cache files.
