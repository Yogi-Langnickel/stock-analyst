# Free Market Data Options

Status: active plan  
Created: 2026-05-15

Market data is enrichment only. It can help reviewers validate context, stale
prices, symbols, and broad market moves, but it must not overwrite magazine
source fields or fill missing recommendation details.

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

5. SEC companyfacts and filings
   - Official free source for US fundamentals and filing metadata.
   - Use for issuer/company context, not price validation.

## Implementation Plan

1. Keep `STOCK_ANALYST_MARKET_DATA_PROVIDER=disabled` as the default.
2. Parse Stooq CSV from local fixture text first; network fetching remains a
   separate adapter behind explicit configuration.
3. Add cache files under ignored `data/market-cache` before enabling any live
   provider.
4. Attach enrichment output as source metadata with provider, observed date,
   and status.
5. Mark unavailable or ambiguous market rows as `needs_review`; never infer a
   missing price, stop loss, target, ticker, ISIN, WKN, or recommendation.
6. Add provider terms/rate-limit notes before enabling network calls.

## First Slice Implemented

- `stock_analyst.market_data.market_data_disabled`
- `stock_analyst.market_data.parse_stooq_daily_csv`
- Unit tests proving missing prices stay review-gated.
