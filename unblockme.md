# Stock Analyst Unblock Notes

Status: non-blocking for local implementation  
Created: 2026-05-15

Local development can continue on scoped branches. These items block normal
remote PR flow or live-provider enablement only.

## Git Flow

- No remote is configured for this repository.
- Current implementation work is on `feature/free-api-intake-plan`.
- Before a PR/review flow exists, configure a remote and decide whether
  `develop` remains the integration branch.

## Market Data Providers

- Live provider fetching remains disabled by default.
- Before enabling Stooq, Alpha Vantage, Twelve Data, or SEC adapters, confirm
  terms, rate limits, user-agent/cache requirements, and whether the app is
  local-only or hosted.
- Ticker/ISIN/WKN normalization is not implemented yet, so market data lookup
  must initially use explicit reviewer-provided ticker symbols.
