"""Disabled-by-default market data enrichment helpers."""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from io import StringIO
from typing import Mapping


DEFAULT_PROVIDER_ENV = "STOCK_ANALYST_MARKET_DATA_PROVIDER"


@dataclass(frozen=True)
class ProviderMetadata:
    provider_id: str
    display_name: str
    status: str
    credentials_required: bool
    network_access: bool
    credential_env_var: str | None = None
    user_agent_env_var: str | None = None
    purpose: str = ""
    safety_notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class MarketDataConfig:
    requested_provider: str
    provider: ProviderMetadata
    enabled: bool
    reason: str


PROVIDER_METADATA: dict[str, ProviderMetadata] = {
    "disabled": ProviderMetadata(
        provider_id="disabled",
        display_name="Disabled",
        status="available",
        credentials_required=False,
        network_access=False,
        purpose="Default provider for tests and local PDF intake.",
        safety_notes=("No network calls.", "No secrets."),
    ),
    "stooq_csv": ProviderMetadata(
        provider_id="stooq_csv",
        display_name="Stooq CSV",
        status="fixture_parser_available",
        credentials_required=False,
        network_access=False,
        purpose="Parse caller-supplied Stooq daily CSV text for reviewer context.",
        safety_notes=(
            "Live fetching is not implemented.",
            "Use explicit reviewer-provided ticker symbols.",
        ),
    ),
    "alpha_vantage": ProviderMetadata(
        provider_id="alpha_vantage",
        display_name="Alpha Vantage",
        status="metadata_only",
        credentials_required=True,
        network_access=False,
        credential_env_var="ALPHA_VANTAGE_API_KEY",
        purpose="Optional future daily quote, forex, crypto, and indicator context.",
        safety_notes=(
            "Adapter is not implemented.",
            "Cache and quota controls are required before live calls.",
        ),
    ),
    "twelve_data": ProviderMetadata(
        provider_id="twelve_data",
        display_name="Twelve Data",
        status="metadata_only",
        credentials_required=True,
        network_access=False,
        credential_env_var="TWELVE_DATA_API_KEY",
        purpose="Optional future quote, time-series, reference, and indicator context.",
        safety_notes=(
            "Adapter is not implemented.",
            "Credit accounting is required before live calls.",
        ),
    ),
    "sec_companyfacts": ProviderMetadata(
        provider_id="sec_companyfacts",
        display_name="SEC companyfacts",
        status="metadata_only",
        credentials_required=False,
        network_access=False,
        user_agent_env_var="SEC_USER_AGENT",
        purpose="Optional future US issuer fundamentals and filing metadata context.",
        safety_notes=(
            "Adapter is not implemented.",
            "Fair-access user-agent and request throttling are required before live calls.",
        ),
    ),
}


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


def available_provider_metadata() -> tuple[ProviderMetadata, ...]:
    return tuple(PROVIDER_METADATA.values())


def load_market_data_config(env: Mapping[str, str] | None = None) -> MarketDataConfig:
    source = os.environ if env is None else env
    requested_provider = source.get(DEFAULT_PROVIDER_ENV, "disabled").strip() or "disabled"
    provider = PROVIDER_METADATA.get(requested_provider)

    if provider is None:
        return MarketDataConfig(
            requested_provider=requested_provider,
            provider=PROVIDER_METADATA["disabled"],
            enabled=False,
            reason=f"unknown market data provider: {requested_provider}",
        )

    if provider.provider_id == "disabled":
        return MarketDataConfig(
            requested_provider=requested_provider,
            provider=provider,
            enabled=False,
            reason="market data enrichment is disabled by default",
        )

    if provider.status == "fixture_parser_available":
        return MarketDataConfig(
            requested_provider=requested_provider,
            provider=provider,
            enabled=True,
            reason="local parser is available for caller-supplied fixture text only",
        )

    if provider.credential_env_var and not source.get(provider.credential_env_var):
        return MarketDataConfig(
            requested_provider=requested_provider,
            provider=provider,
            enabled=False,
            reason=f"missing credential environment variable: {provider.credential_env_var}",
        )

    if provider.user_agent_env_var and not source.get(provider.user_agent_env_var):
        return MarketDataConfig(
            requested_provider=requested_provider,
            provider=provider,
            enabled=False,
            reason=f"missing user-agent environment variable: {provider.user_agent_env_var}",
        )

    return MarketDataConfig(
        requested_provider=requested_provider,
        provider=provider,
        enabled=False,
        reason="live provider adapter is not implemented",
    )


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
