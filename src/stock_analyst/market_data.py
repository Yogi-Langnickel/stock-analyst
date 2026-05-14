"""Disabled-by-default market data enrichment helpers."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from io import StringIO


@dataclass(frozen=True)
class MarketQuote:
    symbol: str
    source: str
    observed_on: date
    close: Decimal
    currency: str | None = None


@dataclass(frozen=True)
class MarketDataResult:
    symbol: str
    provider: str
    status: str
    quote: MarketQuote | None = None
    reason: str | None = None


def market_data_disabled(symbol: str) -> MarketDataResult:
    return MarketDataResult(
        symbol=symbol,
        provider="disabled",
        status="unavailable",
        reason="market data enrichment is disabled by default",
    )


def parse_stooq_daily_csv(csv_text: str, *, symbol: str) -> MarketDataResult:
    """Parse Stooq daily CSV text and return the newest valid close price."""

    reader = csv.DictReader(StringIO(csv_text.strip()))
    latest_quote: MarketQuote | None = None

    for row in reader:
        observed_raw = row.get("Date")
        close_raw = row.get("Close")

        if not observed_raw or not close_raw:
            continue

        try:
            observed_on = date.fromisoformat(observed_raw)
            close = Decimal(close_raw)
        except (ValueError, InvalidOperation):
            continue

        quote = MarketQuote(
            symbol=symbol,
            source="stooq",
            observed_on=observed_on,
            close=close,
        )

        if latest_quote is None or quote.observed_on > latest_quote.observed_on:
            latest_quote = quote

    if latest_quote is None:
        return MarketDataResult(
            symbol=symbol,
            provider="stooq",
            status="needs_review",
            reason="no valid close price was found in provider CSV",
        )

    return MarketDataResult(
        symbol=symbol,
        provider="stooq",
        status="available",
        quote=latest_quote,
    )
