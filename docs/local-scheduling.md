# Local Scheduling

Status: active plan
Last updated: 2026-05-17

The first scheduled Stock Analyst runner stays local-first and dry-run for
external services. It can import PDFs from private local storage, refresh the
local extraction quality report, and plan market-data enrichment requests
without making live provider calls.

## Local Runner

Run the safe local scheduled task manually:

```sh
scripts/stock-analyst-local-run
```

The runner writes ignored logs under `data/local-runs/` and prints the path to a
small summary JSON file. It uses these defaults:

| Setting | Default |
| --- | --- |
| Issues folder | `data/private/issues` |
| Upload folder | `data/uploads` |
| Env file | `.env` |
| Market-data symbol file | `data/private/enrichment-symbols.txt` |
| Run output | `data/local-runs` |
| Market-data budget ledger | `data/market-cache/_budgets` |

Override any path with environment variables:

```sh
STOCK_ANALYST_ISSUES_DIR=/path/to/issues \
STOCK_ANALYST_SYMBOL_FILE=/path/to/symbols.txt \
scripts/stock-analyst-local-run
```

The symbol file accepts one ticker per line or comma-separated tickers. Blank
lines and `#` comments are ignored:

```text
# review queue symbols
AAPL
MSFT, NVDA
```

## Provider Budgets

The local runner calls `market-data-plan`, not a live adapter. The planner uses
the local `.env` values and enforces provider-specific hard daily planning
budgets before any future network adapter can be enabled. Example FMP config:

```sh
FMP_API_KEY=...
STOCK_ANALYST_MARKET_DATA_PROVIDER=fmp
STOCK_ANALYST_MARKET_DATA_DAILY_CALL_LIMIT=235
STOCK_ANALYST_MARKET_DATA_CACHE_DIR=./data/market-cache
STOCK_ANALYST_MARKET_DATA_BUDGET_DIR=./data/market-cache/_budgets
STOCK_ANALYST_MARKET_DATA_TERMS_VERSION=fmp-personal-basic-reviewed-2026-05-17
```

The planner reads the local provider/day budget ledger before planning requests,
so prior same-day usage counts against the hard daily cap. The monthly 512MB
bandwidth ceiling is tracked as a planning constraint. Live FMP calls remain
blocked until cached response storage, request accounting, and bandwidth
accounting are implemented.

Other accepted local keys are `ALPHAVANTAGE_API_KEY`, `FINNHUB_API_KEY`,
`FINNHUB_SECRET`, and `TWELVEDATA_API_KEY`. When enrichment later moves to AWS
Lambda, copy all provider keys into AWS Secrets Manager instead of storing them
in Lambda environment variables.

## macOS launchd Example

Create `~/Library/LaunchAgents/com.stock-analyst.local-run.plist` with this
content, updating the `WorkingDirectory` path if your checkout moves:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.stock-analyst.local-run</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/yogi/Coding/projects/stock-analyst/scripts/stock-analyst-local-run</string>
  </array>
  <key>WorkingDirectory</key>
  <string>/Users/yogi/Coding/projects/stock-analyst</string>
  <key>StartCalendarInterval</key>
  <array>
    <dict>
      <key>Hour</key>
      <integer>8</integer>
      <key>Minute</key>
      <integer>15</integer>
      <key>Weekday</key>
      <integer>4</integer>
    </dict>
    <dict>
      <key>Hour</key>
      <integer>8</integer>
      <key>Minute</key>
      <integer>15</integer>
      <key>Weekday</key>
      <integer>5</integer>
    </dict>
  </array>
  <key>StandardOutPath</key>
  <string>/Users/yogi/Coding/projects/stock-analyst/data/local-runs/launchd.out.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/yogi/Coding/projects/stock-analyst/data/local-runs/launchd.err.log</string>
</dict>
</plist>
```

Create the local run folder once, then load it:

```sh
mkdir -p /Users/yogi/Coding/projects/stock-analyst/data/local-runs
launchctl load ~/Library/LaunchAgents/com.stock-analyst.local-run.plist
```

Unload it:

```sh
launchctl unload ~/Library/LaunchAgents/com.stock-analyst.local-run.plist
```

This schedule runs Thursday and Friday at 08:15 local time. Missed runs are
acceptable; launchd will not replay a run if the computer was off.
