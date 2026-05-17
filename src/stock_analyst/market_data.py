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
MARKET_BUDGET_DIR_ENV = "STOCK_ANALYST_MARKET_DATA_BUDGET_DIR"
MARKET_DAILY_CALL_LIMIT_ENV = "STOCK_ANALYST_MARKET_DATA_DAILY_CALL_LIMIT"
MARKET_TERMS_VERSION_ENV = "STOCK_ANALYST_MARKET_DATA_TERMS_VERSION"
DEFAULT_ALPHA_VANTAGE_DAILY_CALL_LIMIT = 25
DEFAULT_FMP_DAILY_CALL_LIMIT = 235
DEFAULT_TWELVE_DATA_DAILY_CALL_LIMIT = 800
DEFAULT_FINNHUB_DAILY_CALL_LIMIT = 500
DEFAULT_ALPHA_VANTAGE_ENDPOINTS = ("global-quote", "overview")
DEFAULT_FMP_ENDPOINTS = ("batch-quote-short", "profile", "dividends")
DEFAULT_TWELVE_DATA_ENDPOINTS = ("price", "quote", "statistics")
DEFAULT_FINNHUB_ENDPOINTS = (
    "quote",
    "recommendation-trends",
    "insider-sentiment",
    "earnings-surprises",
    "company-news",
)
DEFAULT_PROVIDER_ENDPOINTS = {
    "alpha_vantage": DEFAULT_ALPHA_VANTAGE_ENDPOINTS,
    "fmp": DEFAULT_FMP_ENDPOINTS,
    "twelve_data": DEFAULT_TWELVE_DATA_ENDPOINTS,
    "finnhub": DEFAULT_FINNHUB_ENDPOINTS,
}
SECRET_PARAM_MARKERS = ("authorization", "credential", "key", "password", "secret", "token")


@dataclass(frozen=True)
class ProviderMetadata:
    provider_id: str
    display_name: str
    status: str
    credentials_required: bool
    network_access: bool
    credential_env_var: str | None = None
    credential_env_aliases: tuple[str, ...] = ()
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
    budget_dir: Path
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
        credential_env_var="ALPHAVANTAGE_API_KEY",
        credential_env_aliases=("ALPHA_VANTAGE_API_KEY",),
        purpose=(
            "Optional future daily quote, symbol search, fundamental, intelligence, "
            "forex, commodity, and indicator context."
        ),
        safety_notes=(
            "Adapter is not implemented.",
            "Use only high-value sparse enrichment because the free quota is 25 calls/day.",
            "Cache and quota controls are required before live calls.",
        ),
        rate_limit_notes=(
            "Hard dry-run planning budget: 25 calls per day.",
            "Use for fallback fundamentals or sparse signals, not broad daily polling.",
        ),
        daily_call_budget=DEFAULT_ALPHA_VANTAGE_DAILY_CALL_LIMIT,
    ),
    "twelve_data": ProviderMetadata(
        provider_id="twelve_data",
        display_name="Twelve Data",
        status="metadata_only",
        credentials_required=True,
        network_access=False,
        credential_env_var="TWELVEDATA_API_KEY",
        credential_env_aliases=("TWELVE_DATA_API_KEY",),
        purpose=(
            "Optional future bulk quote, time-series, reference, fundamentals, "
            "analysis, regulatory, and indicator context."
        ),
        safety_notes=(
            "Adapter is not implemented.",
            "Credit accounting is required before live calls.",
        ),
        rate_limit_notes=(
            "Free tier has 8 API credits per minute and 800 per day.",
            "Endpoint credit weights must be honored before live calls.",
        ),
        daily_call_budget=DEFAULT_TWELVE_DATA_DAILY_CALL_LIMIT,
    ),
    "finnhub": ProviderMetadata(
        provider_id="finnhub",
        display_name="Finnhub",
        status="metadata_only",
        credentials_required=True,
        network_access=False,
        credential_env_var="FINNHUB_API_KEY",
        credential_env_aliases=("FINNHUB_TOKEN",),
        purpose=(
            "Optional future quote, analyst recommendation, insider, earnings, "
            "news sentiment, and company fundamental context."
        ),
        safety_notes=(
            "Adapter is not implemented.",
            "FINNHUB_SECRET is recorded as a private local value but is not required for REST planning.",
            "Cache and quota controls are required before live calls.",
        ),
        rate_limit_notes=(
            "Free-tier references commonly report 60 calls per minute.",
            "No project-wide daily cap has been confirmed, so the local default planning cap is 500/day.",
        ),
        daily_call_budget=DEFAULT_FINNHUB_DAILY_CALL_LIMIT,
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
    prior_charged_call_count: int = 0

    @property
    def remaining_daily_call_budget(self) -> int:
        return max(
            self.daily_call_limit
            - self.prior_charged_call_count
            - self.charged_call_count,
            0,
        )


@dataclass(frozen=True)
class MarketDataEnrichmentPlan:
    provider: str
    status: str
    dry_run: bool
    network_access: bool
    daily_call_limit: int
    planned_call_count: int
    charged_call_count: int
    prior_charged_call_count: int
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
class MarketDataCacheRecord:
    metadata: MarketDataCacheMetadata
    response_payload: object
    stored_at: datetime


@dataclass(frozen=True)
class MarketDataBudgetState:
    provider: str
    budget_date: date
    daily_call_limit: int
    charged_call_count: int = 0
    updated_at: datetime | None = None


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


def plan_market_data_enrichment_requests(
    provider_id: str,
    symbols: tuple[str, ...],
    *,
    endpoints: tuple[str, ...] | None = None,
    cache_root: Path = DEFAULT_MARKET_CACHE_DIR,
    daily_call_limit: int | None = None,
    prior_charged_call_count: int = 0,
    terms_version: str | None = None,
) -> MarketDataEnrichmentPlan:
    """Plan provider enrichment descriptors without secrets or network calls."""

    normalized_provider_id = provider_id.strip().lower()
    provider = PROVIDER_METADATA.get(normalized_provider_id)
    if provider is None:
        raise ValueError(f"unknown market data provider: {normalized_provider_id}")

    resolved_limit = daily_call_limit or provider.daily_call_budget
    if resolved_limit is None:
        raise ValueError(f"{provider.provider_id} daily call limit must be configured")
    if resolved_limit <= 0:
        raise ValueError(f"{provider.provider_id} daily call limit must be positive")
    if prior_charged_call_count < 0:
        raise ValueError(f"{provider.provider_id} prior charged call count cannot be negative")

    normalized_symbols = _normalize_unique_symbols(symbols)
    normalized_endpoints = _normalize_unique_endpoints(
        endpoints or DEFAULT_PROVIDER_ENDPOINTS.get(provider.provider_id, ())
    )
    if not normalized_endpoints:
        raise ValueError(f"{provider.provider_id} has no dry-run endpoints configured")
    planned_call_count = len(normalized_symbols) * len(normalized_endpoints)
    bandwidth_note = provider.bandwidth_notes[0] if provider.bandwidth_notes else ""

    if not normalized_symbols:
        ledger = MarketDataBudgetLedger(
            daily_call_limit=resolved_limit,
            charged_call_count=0,
            cache_hit_count=0,
            denied_call_count=0,
            prior_charged_call_count=prior_charged_call_count,
        )
        return MarketDataEnrichmentPlan(
            provider=provider.provider_id,
            status="empty",
            dry_run=True,
            network_access=False,
            daily_call_limit=resolved_limit,
            planned_call_count=0,
            charged_call_count=0,
            prior_charged_call_count=prior_charged_call_count,
            cache_hit_count=0,
            denied_call_count=0,
            remaining_daily_call_budget=ledger.remaining_daily_call_budget,
            bandwidth_note=bandwidth_note,
            ledger=ledger,
            reason=f"no symbols were supplied for {provider.display_name} enrichment planning",
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

            if prior_charged_call_count + charged_call_count >= resolved_limit:
                denied_call_count += 1
                requests.append(
                    MarketDataPlannedRequest(
                        descriptor=descriptor,
                        cache_key=cache.cache_key,
                        cache_path=cache.cache_path,
                        budget_action="denied",
                        consumes_budget=False,
                        reason=(
                            f"hard daily {provider.display_name} call limit reached at "
                            f"{resolved_limit} calls; "
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
        daily_call_limit=resolved_limit,
        charged_call_count=charged_call_count,
        cache_hit_count=cache_hit_count,
        denied_call_count=denied_call_count,
        prior_charged_call_count=prior_charged_call_count,
    )
    status = "over_budget" if denied_call_count else "planned"
    reason = (
        f"planned {provider.display_name} enrichment requests exceed the hard daily "
        f"limit of {resolved_limit} calls"
        if denied_call_count
        else None
    )

    return MarketDataEnrichmentPlan(
        provider=provider.provider_id,
        status=status,
        dry_run=True,
        network_access=False,
        daily_call_limit=resolved_limit,
        planned_call_count=planned_call_count,
        charged_call_count=charged_call_count,
        prior_charged_call_count=prior_charged_call_count,
        cache_hit_count=cache_hit_count,
        denied_call_count=denied_call_count,
        remaining_daily_call_budget=ledger.remaining_daily_call_budget,
        bandwidth_note=bandwidth_note,
        ledger=ledger,
        requests=tuple(requests),
        reason=reason,
    )


def plan_fmp_enrichment_requests(
    symbols: tuple[str, ...],
    *,
    endpoints: tuple[str, ...] = DEFAULT_FMP_ENDPOINTS,
    cache_root: Path = DEFAULT_MARKET_CACHE_DIR,
    daily_call_limit: int = DEFAULT_FMP_DAILY_CALL_LIMIT,
    prior_charged_call_count: int = 0,
    terms_version: str | None = None,
) -> MarketDataEnrichmentPlan:
    """Plan FMP enrichment descriptors without reading secrets or making network calls."""

    return plan_market_data_enrichment_requests(
        "fmp",
        symbols,
        endpoints=endpoints,
        cache_root=cache_root,
        daily_call_limit=daily_call_limit,
        prior_charged_call_count=prior_charged_call_count,
        terms_version=terms_version,
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


def write_market_data_cache_record(
    metadata: MarketDataCacheMetadata,
    response_payload: object,
    *,
    stored_at: datetime | None = None,
) -> Path:
    """Persist a credential-free market data response cache record."""

    normalized_stored_at = _normalize_cache_datetime(stored_at) or datetime.now(timezone.utc)
    metadata.cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "metadata": _cache_metadata_to_payload(metadata),
        "responsePayload": response_payload,
        "storedAt": normalized_stored_at.isoformat(),
    }
    metadata.cache_path.write_text(
        f"{json.dumps(payload, sort_keys=True, separators=(',', ':'))}\n",
        encoding="utf-8",
    )
    return metadata.cache_path


def read_market_data_cache_record(path: Path) -> MarketDataCacheRecord:
    """Read a previously persisted market data cache record."""

    if not path.exists():
        raise ValueError(f"market data cache record does not exist: {path}")

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"market data cache record is not an object: {path}")

    metadata_payload = payload.get("metadata")
    if not isinstance(metadata_payload, dict):
        raise ValueError(f"market data cache record is missing metadata: {path}")

    return MarketDataCacheRecord(
        metadata=_cache_metadata_from_payload(metadata_payload, cache_path=path),
        response_payload=payload.get("responsePayload"),
        stored_at=_normalize_cache_datetime(
            datetime.fromisoformat(str(payload.get("storedAt")))
        )
        or datetime.now(timezone.utc),
    )


def market_data_budget_path(
    *,
    provider: str,
    budget_date: date,
    budget_root: Path,
) -> Path:
    normalized_provider = provider.strip().lower()
    if normalized_provider not in PROVIDER_METADATA:
        raise ValueError(f"unknown market data provider: {normalized_provider}")
    return budget_root / f"{budget_date.isoformat()}-{normalized_provider}.json"


def load_market_data_budget_state(
    *,
    provider: str,
    budget_date: date,
    daily_call_limit: int,
    budget_root: Path,
) -> MarketDataBudgetState:
    path = market_data_budget_path(
        provider=provider,
        budget_date=budget_date,
        budget_root=budget_root,
    )
    if not path.exists():
        return MarketDataBudgetState(
            provider=provider.strip().lower(),
            budget_date=budget_date,
            daily_call_limit=daily_call_limit,
        )

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"market data budget file is not an object: {path}")

    stored_provider = str(payload.get("provider") or "").strip().lower()
    stored_date = date.fromisoformat(str(payload.get("budgetDate")))
    if stored_provider != provider.strip().lower() or stored_date != budget_date:
        raise ValueError(f"market data budget file does not match requested provider/date: {path}")

    charged_call_count = _non_negative_int_payload(payload, "chargedCallCount")
    stored_limit = _non_negative_int_payload(payload, "dailyCallLimit")
    updated_at = _optional_datetime_payload(payload.get("updatedAt"))

    return MarketDataBudgetState(
        provider=stored_provider,
        budget_date=stored_date,
        daily_call_limit=stored_limit or daily_call_limit,
        charged_call_count=charged_call_count,
        updated_at=updated_at,
    )


def write_market_data_budget_state(
    state: MarketDataBudgetState,
    *,
    budget_root: Path,
) -> Path:
    if state.charged_call_count < 0:
        raise ValueError("market data charged_call_count cannot be negative")
    if state.daily_call_limit <= 0:
        raise ValueError("market data daily_call_limit must be positive")

    path = market_data_budget_path(
        provider=state.provider,
        budget_date=state.budget_date,
        budget_root=budget_root,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    updated_at = state.updated_at or datetime.now(timezone.utc)
    payload = {
        "provider": state.provider,
        "budgetDate": state.budget_date.isoformat(),
        "dailyCallLimit": state.daily_call_limit,
        "chargedCallCount": state.charged_call_count,
        "updatedAt": updated_at.isoformat(),
    }
    path.write_text(f"{json.dumps(payload, sort_keys=True)}\n", encoding="utf-8")
    return path


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

    credential_env_var = _configured_credential_env_var(provider, source)
    if provider.credential_env_var and credential_env_var is None:
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


def _configured_credential_env_var(
    provider: ProviderMetadata,
    source: Mapping[str, str],
) -> str | None:
    for name in (provider.credential_env_var, *provider.credential_env_aliases):
        if name and source.get(name):
            return name
    return None


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
    budget_dir = Path(
        source.get(MARKET_BUDGET_DIR_ENV, str(cache_dir / "_budgets"))
    ).expanduser()
    terms_version = source.get(MARKET_TERMS_VERSION_ENV)
    normalized_terms_version = terms_version.strip() if terms_version else None
    credential_configured = _configured_credential_env_var(
        provider_config.provider,
        source,
    ) is not None

    return MarketDataPlanningConfig(
        provider_config=provider_config,
        cache_dir=cache_dir,
        budget_dir=budget_dir,
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


def _non_negative_int_payload(payload: Mapping[str, object], key: str) -> int:
    raw_value = payload.get(key, 0)
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"market data budget {key} must be a non-negative integer") from error
    if parsed < 0:
        raise ValueError(f"market data budget {key} must be a non-negative integer")
    return parsed


def _cache_metadata_to_payload(metadata: MarketDataCacheMetadata) -> dict[str, object]:
    payload: dict[str, object] = {
        "provider": metadata.provider,
        "symbol": metadata.symbol,
        "cacheKey": metadata.cache_key,
        "safeIdentity": metadata.safe_identity,
    }
    if metadata.retrieved_at is not None:
        payload["retrievedAt"] = metadata.retrieved_at.isoformat()
    if metadata.observed_on is not None:
        payload["observedOn"] = metadata.observed_on.isoformat()
    if metadata.ttl_seconds is not None:
        payload["ttlSeconds"] = metadata.ttl_seconds
    if metadata.expires_at is not None:
        payload["expiresAt"] = metadata.expires_at.isoformat()
    if metadata.source_url_hash is not None:
        payload["sourceUrlHash"] = metadata.source_url_hash
    if metadata.terms_checked_at is not None:
        payload["termsCheckedAt"] = metadata.terms_checked_at.isoformat()
    if metadata.terms_version is not None:
        payload["termsVersion"] = metadata.terms_version
    return payload


def _cache_metadata_from_payload(
    payload: Mapping[str, object],
    *,
    cache_path: Path,
) -> MarketDataCacheMetadata:
    provider = str(payload.get("provider") or "").strip()
    symbol = str(payload.get("symbol") or "").strip()
    cache_key = str(payload.get("cacheKey") or "").strip()
    safe_identity = payload.get("safeIdentity")
    if not provider or not symbol or not cache_key:
        raise ValueError(f"market data cache record metadata is incomplete: {cache_path}")
    if not isinstance(safe_identity, dict):
        raise ValueError(f"market data cache record safe identity is invalid: {cache_path}")

    return MarketDataCacheMetadata(
        provider=provider,
        symbol=symbol,
        cache_key=cache_key,
        cache_path=cache_path,
        safe_identity=dict(safe_identity),
        retrieved_at=_optional_datetime_payload(payload.get("retrievedAt")),
        observed_on=_optional_date_payload(payload.get("observedOn")),
        ttl_seconds=(
            _non_negative_int_payload(payload, "ttlSeconds")
            if payload.get("ttlSeconds") is not None
            else None
        ),
        expires_at=_optional_datetime_payload(payload.get("expiresAt")),
        source_url_hash=_optional_string_payload(payload.get("sourceUrlHash")),
        terms_checked_at=_optional_date_payload(payload.get("termsCheckedAt")),
        terms_version=_optional_string_payload(payload.get("termsVersion")),
    )


def _optional_date_payload(value: object) -> date | None:
    if value is None:
        return None
    return date.fromisoformat(str(value))


def _optional_datetime_payload(value: object) -> datetime | None:
    if value is None:
        return None
    return _normalize_cache_datetime(datetime.fromisoformat(str(value)))


def _optional_string_payload(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


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
            raise ValueError("market data enrichment endpoint cannot be blank")
        if endpoint in seen:
            continue
        normalized.append(endpoint)
        seen.add(endpoint)

    if not normalized:
        raise ValueError("at least one market data enrichment endpoint is required")

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
