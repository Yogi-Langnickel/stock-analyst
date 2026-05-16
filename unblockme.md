# Stock Analyst Unblock Notes

Status: non-blocking for local implementation
Created: 2026-05-15

Local development can continue on scoped branches. These items block
live-provider enablement only.

## Git Flow

- `origin` is configured at `https://github.com/Yogi-Langnickel/stock-analyst.git`.
- `develop` tracks `origin/develop` and remains the integration branch.
- Use scoped feature branches from `develop` for new PR/review work.

## Market Data Providers

- Live provider fetching remains disabled by default.
- Before enabling Stooq, Alpha Vantage, Twelve Data, or SEC adapters, confirm
  terms, rate limits, user-agent/cache requirements, and whether the app is
  local-only or hosted.
- Ticker/ISIN/WKN normalization is not implemented yet, so market data lookup
  must initially use explicit reviewer-provided ticker symbols.
