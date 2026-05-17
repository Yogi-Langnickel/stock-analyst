"""Disabled-by-default market data enrichment helpers."""

from __future__ import annotations

import csv
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from io import StringIO
from pathlib import Path
import re
from typing import Mapping


DEFAULT_PROVIDER_ENV = "STOCK_ANALYST_MARKET_DATA_PROVIDER"
DEFAULT_MARKET_CACHE_DIR = Path("data/market-cache")
MARKET_CACHE_DIR_ENV = "STOCK_ANALYST_MARKET_DATA_CACHE_DIR"
MARKET_DAILY_CALL_LIMIT_ENV = "STOCK_ANALYST_MARKET_DATA_DAILY_CALL_LIMIT"
MARKET_TERMS_VERSION_ENV = "STOCK_ANALYST_MARKET_DATA_TERMS_VERSION"
DEFAULT_FMP_DAILY_CALL_LIMIT = 235
DEFAULT_FMP_ENDPOINTS = ("batch-quote-short", "profile", "dividends")
SECRET_PARAM_MARKERS = ("authorization", "credential", "key", "password", "secret", "token")


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
    rate_limit_notes: tuple[str, ...] = ()
    cache_required_before_live: bool = True
    daily_call_budget: int | None = None
    bandwidth_notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class MarketDataConfig:
    requested_provider: str
    provider: ProviderMetadata
    enabled: bool
    reason: str


@dataclass(frozen=True)
class MarketDataPlanningConfig:
    provider_config: MarketDataConfig
    cache_dir: Path
    daily_call_limit: int
    terms_version: str | None = None
    credential_configured: bool = False


PROVIDER_METADATA: dict[str, ProviderMetadata] = {
    "disabled": ProviderMetadata(
        provider_id="disabled",
        display_name="Disabled",
        status="available",
        credentials_required=False,
        network_access=False,
        purpose="Default provider for tests and local PDF intake.",
        safety_notes=("No network calls.", "No secrets."),
        rate_limit_notes=("Not applicable while enrichment is disabled.",),
        cache_required_before_live=False,
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
        rate_limit_notes=(
            "Live request terms and acceptable rates must be confirmed before fetching.",
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
        rate_limit_notes=("Free-key quota is tight; cache and background opt-in are required.",),
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
        rate_limit_notes=("Credit accounting is required before any live request scheduling.",),
    ),
    "fmp": ProviderMetadata(
        provider_id="fmp",
        display_name="Financial Modeling Prep",
        status="metadata_only",
        credentials_required=True,
        network_access=False,
        credential_env_var="FMP_API_KEY",
        purpose="Optional future quote, profile, and fundamentals context for reviewer enrichment.",
        safety_notes=(
            "Adapter is not implemented.",
            "Dry-run planning must not read or expose FMP_API_KEY.",
            "Cache, call-budget accounting, and bandwidth accounting are required before live calls.",
        ),
        rate_limit_notes=(
            "Hard dry-run planning budget: 235 calls per day.",
            "Live adapter must stop scheduling before this budget is exceeded.",
        ),
        daily_call_budget=DEFAULT_FMP_DAILY_CALL_LIMIT,
        bandwidth_notes=("Plan against a 512MB/month bandwidth ceiling before live access.",),
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
        rate_limit_notes=("SEC fair-access throttling is required before live calls.",),
    ),
}


@dataclass(frozen=True)
class MarketDataRequestDescriptor:
    provider: str
    symbol: str
    endpoint: str
    params: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class MarketDataPlannedRequest:
    descriptor: MarketDataRequestDescriptor
    cache_key: str
    cache_path: Path
    budget_action: str
    consumes_budget: bool
    reason: str | None = None


@dataclass(frozen=True)
class MarketDataBudgetLedger:
    daily_call_limit: int
    charged_call_count: int
    cache_hit_count: int
    denied_call_count: int

    @property
    def remaining_daily_call_budget(self) -> int:
        return max(self.daily_call_limit - self.charged_call_count, 0)


@dataclass(frozen=True)
class MarketDataEnrichmentPlan:
    provider: str
    status: str
    dry_run: bool
    network_access: bool
    daily_call_limit: int
    planned_call_count: int
    charged_call_count: int
    cache_hit_count: int
    denied_call_count: int
    remaining_daily_call_budget: int
    bandwidth_note: str
    ledger: MarketDataBudgetLedger
    requests: tuple[MarketDataPlannedRequest, ...] = ()
    reason: str | None = None


@dataclass(frozen=True)
class MarketDataCacheMetadata:
    provider: str
    symbol: str
    cache_key: str
    cache_path: Path
    safe_identity: Mapping[str, object]
    retrieved_at: datetime | None = None
    observed_on: date | None = None
    ttl_seconds: int | None = None
    expires_at: datetime | None = None
    source_url_hash: str | None = None
    terms_checked_at: date | None = None
    terms_version: str | None = None


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


def describe_market_data_request(
    *,
    provider: str,
    symbol: str,
    endpoint: str,
    params: Mapping[str, object] | None = None,
) -> MarketDataRequestDescriptor:
    """Build a normalized, credential-free descriptor for a future provider request."""

    normalized_provider = provider.strip().lower()
    normalized_endpoint = endpoint.strip().lower()
    normalized_symbol = symbol.strip().upper()

    if not normalized_provider:
        raise ValueError("market data provider is required")
    if normalized_provider not in PROVIDER_METADATA:
        raise ValueError(f"unknown market data provider: {normalized_provider}")
    if not normalized_endpoint:
        raise ValueError("market data endpoint is required")
    if not normalized_symbol:
        raise ValueError("market data symbol is required")

    return MarketDataRequestDescriptor(
        provider=normalized_provider,
        symbol=normalized_symbol,
        endpoint=normalized_endpoint,
        params=_normalize_safe_cache_params(params or {}),
    )


def plan_fmp_enrichment_requests(
    symbols: tuple[str, ...],
    *,
    endpoints: tuple[str, ...] = DEFAULT_FMP_ENDPOINTS,
    cache_root: Path = DEFAULT_MARKET_CACHE_DIR,
    daily_call_limit: int = DEFAULT_FMP_DAILY_CALL_LIMIT,
    terms_version: str | None = None,
) -> MarketDataEnrichmentPlan:
    """Plan FMP enrichment descriptors without reading secrets or making network calls."""

    provider = PROVIDER_METADATA["fmp"]
    if daily_call_limit <= 0:
        raise ValueError("FMP daily call limit must be positive")

    normalized_symbols = _normalize_unique_symbols(symbols)
    normalized_endpoints = _normalize_unique_endpoints(endpoints)
    planned_call_count = len(normalized_symbols) * len(normalized_endpoints)
    bandwidth_note = provider.bandwidth_notes[0] if provider.bandwidth_notes else ""

    if not normalized_symbols:
        ledger = MarketDataBudgetLedger(
            daily_call_limit=daily_call_limit,
            charged_call_count=0,
            cache_hit_count=0,
            denied_call_count=0,
        )
        return MarketDataEnrichmentPlan(
            provider=provider.provider_id,
            status="empty",
            dry_run=True,
            network_access=False,
            daily_call_limit=daily_call_limit,
            planned_call_count=0,
            charged_call_count=0,
            cache_hit_count=0,
            denied_call_count=0,
            remaining_daily_call_budget=ledger.remaining_daily_call_budget,
            bandwidth_note=bandwidth_note,
            ledger=ledger,
            reason="no symbols were supplied for FMP enrichment planning",
        )

    requests: list[MarketDataPlannedRequest] = []
    charged_call_count = 0
    cache_hit_count = 0
    denied_call_count = 0
    normalized_terms_version = terms_version.strip() if terms_version else None

    for symbol in normalized_symbols:
        for endpoint in normalized_endpoints:
            descriptor = describe_market_data_request(
                provider=provider.provider_id,
                symbol=symbol,
                endpoint=endpoint,
                params={"symbol": symbol},
            )
            cache = build_market_data_cache_metadata(
                descriptor,
                cache_root=cache_root,
                terms_version=normalized_terms_version,
            )

            if cache.cache_path.exists():
                cache_hit_count += 1
                requests.append(
                    MarketDataPlannedRequest(
                        descriptor=descriptor,
                        cache_key=cache.cache_key,
                        cache_path=cache.cache_path,
                        budget_action="cache_hit",
                        consumes_budget=False,
                        reason="local cache hit; budget not consumed",
                    )
                )
                continue

            if charged_call_count >= daily_call_limit:
                denied_call_count += 1
                requests.append(
                    MarketDataPlannedRequest(
                        descriptor=descriptor,
                        cache_key=cache.cache_key,
                        cache_path=cache.cache_path,
                        budget_action="denied",
                        consumes_budget=False,
                        reason=(
                            f"hard daily FMP call limit reached at {daily_call_limit} calls; "
                            "live calls remain disabled"
                        ),
                    )
                )
                continue

            charged_call_count += 1
            requests.append(
                MarketDataPlannedRequest(
                    descriptor=descriptor,
                    cache_key=cache.cache_key,
                    cache_path=cache.cache_path,
                    budget_action="charge",
                    consumes_budget=True,
                )
            )

    ledger = MarketDataBudgetLedger(
        daily_call_limit=daily_call_limit,
        charged_call_count=charged_call_count,
        cache_hit_count=cache_hit_count,
        denied_call_count=denied_call_count,
    )
    status = "over_budget" if denied_call_count else "planned"
    reason = (
        "planned FMP enrichment requests exceed the hard daily "
        f"limit of {daily_call_limit} calls"
        if denied_call_count
        else None
    )

    return MarketDataEnrichmentPlan(
        provider=provider.provider_id,
        status=status,
        dry_run=True,
        network_access=False,
        daily_call_limit=daily_call_limit,
        planned_call_count=planned_call_count,
        charged_call_count=charged_call_count,
        cache_hit_count=cache_hit_count,
        denied_call_count=denied_call_count,
        remaining_daily_call_budget=ledger.remaining_daily_call_budget,
        bandwidth_note=bandwidth_note,
        ledger=ledger,
        requests=tuple(requests),
        reason=reason,
    )


def build_market_data_cache_metadata(
    descriptor: MarketDataRequestDescriptor,
    *,
    cache_root: Path = DEFAULT_MARKET_CACHE_DIR,
    retrieved_at: datetime | None = None,
    observed_on: date | None = None,
    ttl_seconds: int | None = None,
    source_url: str | None = None,
    terms_checked_at: date | None = None,
    terms_version: str | None = None,
) -> MarketDataCacheMetadata:
    """Return deterministic cache metadata without creating files or making network calls."""

    normalized_retrieved_at = _normalize_cache_datetime(retrieved_at)
    if ttl_seconds is not None and ttl_seconds < 0:
        raise ValueError("market data cache ttl_seconds cannot be negative")
    expires_at = (
        normalized_retrieved_at + timedelta(seconds=ttl_seconds)
        if normalized_retrieved_at is not None and ttl_seconds is not None
        else None
    )
    normalized_terms_version = terms_version.strip() if terms_version else None

    safe_identity: Mapping[str, object] = {
        "provider": descriptor.provider,
        "symbol": descriptor.symbol,
        "endpoint": descriptor.endpoint,
        "params": descriptor.params,
    }
    payload = json.dumps(safe_identity, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    cache_key = "-".join(
        (
            _slug_for_cache(descriptor.symbol),
            _slug_for_cache(descriptor.endpoint),
            digest,
        )
    )
    cache_path = cache_root / descriptor.provider / f"{cache_key}.json"

    return MarketDataCacheMetadata(
        provider=descriptor.provider,
        symbol=descriptor.symbol,
        cache_key=cache_key,
        cache_path=cache_path,
        safe_identity=safe_identity,
        retrieved_at=normalized_retrieved_at,
        observed_on=observed_on,
        ttl_seconds=ttl_seconds,
        expires_at=expires_at,
        source_url_hash=_hash_source_url(source_url),
        terms_checked_at=terms_checked_at,
        terms_version=normalized_terms_version,
    )


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


def load_market_data_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        raise ValueError(f"market data env file does not exist: {path}")

    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"invalid market data env line {line_number}: expected KEY=VALUE")

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key:
            raise ValueError(f"invalid market data env line {line_number}: key is empty")
        values[key] = value

    return values


def load_market_data_symbol_file(path: Path) -> tuple[str, ...]:
    """Read reviewer-controlled ticker symbols from a local private text file."""

    if not path.exists():
        raise ValueError(f"market data symbol file does not exist: {path}")

    symbols: list[str] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        for raw_symbol in line.split(","):
            symbol = raw_symbol.strip()
            if not symbol:
                continue
            if any(character.isspace() for character in symbol):
                raise ValueError(
                    f"invalid market data symbol on line {line_number}: "
                    "symbols must not contain whitespace"
                )
            symbols.append(symbol)

    return _normalize_unique_symbols(tuple(symbols))


def load_market_data_planning_config(
    *,
    env: Mapping[str, str] | None = None,
    env_file: Path | None = None,
    default_provider: str = "disabled",
) -> MarketDataPlanningConfig:
    source = dict(os.environ if env is None else env)
    if not source.get(DEFAULT_PROVIDER_ENV):
        source[DEFAULT_PROVIDER_ENV] = default_provider
    if env_file is not None:
        source.update(load_market_data_env_file(env_file))
        if not source.get(DEFAULT_PROVIDER_ENV):
            source[DEFAULT_PROVIDER_ENV] = default_provider

    provider_config = load_market_data_config(source)
    daily_call_limit = _parse_positive_int_env(
        source,
        MARKET_DAILY_CALL_LIMIT_ENV,
        provider_config.provider.daily_call_budget or DEFAULT_FMP_DAILY_CALL_LIMIT,
    )
    cache_dir = Path(source.get(MARKET_CACHE_DIR_ENV, str(DEFAULT_MARKET_CACHE_DIR))).expanduser()
    terms_version = source.get(MARKET_TERMS_VERSION_ENV)
    normalized_terms_version = terms_version.strip() if terms_version else None
    credential_env_var = provider_config.provider.credential_env_var
    credential_configured = bool(credential_env_var and source.get(credential_env_var))

    return MarketDataPlanningConfig(
        provider_config=provider_config,
        cache_dir=cache_dir,
        daily_call_limit=daily_call_limit,
        terms_version=normalized_terms_version,
        credential_configured=credential_configured,
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


def _normalize_safe_cache_params(params: Mapping[str, object]) -> tuple[tuple[str, str], ...]:
    normalized: list[tuple[str, str]] = []

    for raw_key, raw_value in params.items():
        key = str(raw_key).strip().lower()
        if not key:
            raise ValueError("market data cache parameter names cannot be blank")
        if any(marker in key for marker in SECRET_PARAM_MARKERS):
            raise ValueError(f"market data cache parameter must not contain secrets: {key}")
        normalized.append((key, str(raw_value)))

    return tuple(sorted(normalized))


def _parse_positive_int_env(source: Mapping[str, str], name: str, default: int) -> int:
    raw_value = source.get(name)
    if raw_value is None or not raw_value.strip():
        return default

    try:
        parsed = int(raw_value)
    except ValueError as error:
        raise ValueError(f"{name} must be a positive integer") from error

    if parsed <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return parsed


def _normalize_unique_symbols(symbols: tuple[str, ...]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()

    for raw_symbol in symbols:
        symbol = raw_symbol.strip().upper()
        if not symbol or symbol in seen:
            continue
        normalized.append(symbol)
        seen.add(symbol)

    return tuple(normalized)


def _normalize_unique_endpoints(endpoints: tuple[str, ...]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()

    for raw_endpoint in endpoints:
        endpoint = raw_endpoint.strip().lower()
        if not endpoint:
            raise ValueError("FMP enrichment endpoint cannot be blank")
        if endpoint in seen:
            continue
        normalized.append(endpoint)
        seen.add(endpoint)

    if not normalized:
        raise ValueError("at least one FMP enrichment endpoint is required")

    return tuple(normalized)


def _slug_for_cache(value: str) -> str:
    slug = re.sub(r"[^a-z0-9._-]+", "-", value.strip().lower()).strip("-")
    return slug or "request"


def _normalize_cache_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _hash_source_url(source_url: str | None) -> str | None:
    if not source_url:
        return None
    normalized_url = source_url.strip()
    if not normalized_url:
        return None
    return hashlib.sha256(normalized_url.encode("utf-8")).hexdigest()[:16]
