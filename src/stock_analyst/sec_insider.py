"""Cached, source-linked SEC EDGAR Form 4 insider enrichment."""

from __future__ import annotations

import json
import re
import ssl
import time
import unicodedata
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

import certifi


SEC_TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_ARCHIVES_URL = (
    "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{document}"
)
DEFAULT_LOOKBACK_DAYS = 365
DEFAULT_MAX_REQUESTS = 100
DEFAULT_CACHE_DIR = Path("data/market-cache/sec-edgar")


class SecInsiderError(RuntimeError):
    """Raised when safe SEC insider enrichment cannot continue."""


@dataclass(frozen=True)
class SecInsiderConfig:
    user_agent: str
    cache_dir: Path = DEFAULT_CACHE_DIR
    lookback_days: int = DEFAULT_LOOKBACK_DAYS
    max_requests: int = DEFAULT_MAX_REQUESTS


@dataclass(frozen=True)
class SecStockCandidate:
    company: str
    wkn: str
    symbol: str | None
    source_ref: str


@dataclass(frozen=True)
class SecTickerRecord:
    cik: str
    ticker: str
    title: str


@dataclass(frozen=True)
class SecResolvedIssuer:
    cik: str
    ticker: str
    company: str
    wkn: str
    source_ref: str


@dataclass(frozen=True)
class SecInsiderTransaction:
    company: str
    wkn: str
    ticker: str
    cik: str
    insider: str
    relationship: str
    transaction_date: str
    transaction_code: str
    direction: str
    shares: str
    price: str
    transaction_value: str
    shares_owned_after: str
    filing_date: str
    filing_url: str
    signal: str
    review_status: str
    source_ref: str
    date_updated: str

    def to_sheet_row(self) -> list[str]:
        return [
            self.company,
            self.wkn,
            self.ticker,
            self.insider,
            self.relationship,
            self.shares_owned_after,
            self.transaction_date,
            _simplified_transaction(self.transaction_code),
            self.direction,
            self.shares,
            self.price,
            self.transaction_value,
        ]


@dataclass(frozen=True)
class SecInsiderEnrichmentResult:
    transactions: tuple[SecInsiderTransaction, ...]
    candidate_count: int
    resolved_issuer_count: int
    unresolved_candidate_count: int
    filing_count: int
    failed_issuer_count: int
    failed_filing_count: int
    network_request_count: int
    cache_hit_count: int
    request_budget_exhausted: bool


FetchBytes = Callable[[str, str], bytes]


class _CachedSecClient:
    def __init__(
        self,
        config: SecInsiderConfig,
        *,
        fetch_bytes: FetchBytes | None = None,
        now: datetime | None = None,
    ) -> None:
        self.config = config
        self.fetch_bytes = fetch_bytes or _fetch_sec_bytes
        self.now = now or datetime.now(timezone.utc)
        self.network_request_count = 0
        self.cache_hit_count = 0
        self.request_budget_exhausted = False
        self._last_request_at: float | None = None

    def get(self, url: str, cache_path: Path, *, ttl: timedelta | None) -> bytes:
        full_path = self.config.cache_dir / cache_path
        if full_path.exists() and (
            ttl is None
            or self.now.timestamp() - full_path.stat().st_mtime <= ttl.total_seconds()
        ):
            self.cache_hit_count += 1
            return full_path.read_bytes()
        if self.network_request_count >= self.config.max_requests:
            self.request_budget_exhausted = True
            raise SecInsiderError("SEC request budget exhausted")
        if self.fetch_bytes is _fetch_sec_bytes and self._last_request_at is not None:
            delay = 0.12 - (time.monotonic() - self._last_request_at)
            if delay > 0:
                time.sleep(delay)
        self.network_request_count += 1
        try:
            payload = self.fetch_bytes(url, self.config.user_agent)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as error:
            raise SecInsiderError("SEC request failed") from error
        self._last_request_at = time.monotonic()
        full_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = full_path.with_suffix(f"{full_path.suffix}.tmp")
        temporary.write_bytes(payload)
        temporary.replace(full_path)
        return payload


def load_sec_insider_config(values: Mapping[str, str]) -> SecInsiderConfig | None:
    user_agent = str(values.get("SEC_USER_AGENT") or "").strip()
    if not user_agent:
        return None
    if "@" not in user_agent:
        raise SecInsiderError(
            "SEC_USER_AGENT must identify the application and a monitored contact email"
        )
    if len(user_agent.split()) == 1:
        user_agent = f"Stock Analyst {user_agent}"
    return SecInsiderConfig(
        user_agent=user_agent,
        cache_dir=Path(
            values.get("STOCK_ANALYST_SEC_CACHE_DIR") or DEFAULT_CACHE_DIR
        ).expanduser(),
        lookback_days=_positive_int(
            values.get("STOCK_ANALYST_INSIDER_LOOKBACK_DAYS"),
            DEFAULT_LOOKBACK_DAYS,
        ),
        max_requests=_positive_int(
            values.get("STOCK_ANALYST_SEC_MAX_REQUESTS"),
            DEFAULT_MAX_REQUESTS,
        ),
    )


def enrich_sec_form4(
    candidates: Sequence[SecStockCandidate],
    config: SecInsiderConfig,
    *,
    fetch_bytes: FetchBytes | None = None,
    now: datetime | None = None,
) -> SecInsiderEnrichmentResult:
    effective_now = now or datetime.now(timezone.utc)
    client = _CachedSecClient(
        config,
        fetch_bytes=fetch_bytes,
        now=effective_now,
    )
    ticker_payload = client.get(
        SEC_TICKER_MAP_URL,
        Path("company-tickers.json"),
        ttl=timedelta(days=7),
    )
    records = parse_sec_ticker_records(ticker_payload)
    resolved, unresolved_count = resolve_sec_issuers(candidates, records)
    cutoff = effective_now.date() - timedelta(days=config.lookback_days)
    transactions: list[SecInsiderTransaction] = []
    filing_count = 0
    failed_issuer_count = 0
    failed_filing_count = 0

    pending_filings: list[tuple[str, SecResolvedIssuer, str, str]] = []
    for issuer in resolved:
        try:
            submission_payload = client.get(
                SEC_SUBMISSIONS_URL.format(cik=issuer.cik),
                Path("submissions") / f"CIK{issuer.cik}.json",
                ttl=timedelta(hours=24),
            )
        except SecInsiderError:
            failed_issuer_count += 1
            if client.request_budget_exhausted:
                break
            continue
        filings = recent_form4_filings(submission_payload, cutoff=cutoff)
        pending_filings.extend(
            (filing_date, issuer, accession, document)
            for accession, document, filing_date in filings
        )

    for filing_date, issuer, accession, document in sorted(
        pending_filings,
        key=lambda item: item[0],
        reverse=True,
    ):
        accession_compact = accession.replace("-", "")
        filing_url = SEC_ARCHIVES_URL.format(
            cik=int(issuer.cik),
            accession=accession_compact,
            document=document,
        )
        try:
            xml_payload = client.get(
                filing_url,
                Path("filings")
                / str(int(issuer.cik))
                / f"{accession_compact}-raw.xml",
                ttl=None,
            )
        except SecInsiderError:
            failed_filing_count += 1
            if client.request_budget_exhausted:
                break
            continue
        filing_count += 1
        try:
            transactions.extend(
                parse_form4_transactions(
                    xml_payload,
                    issuer=issuer,
                    filing_date=filing_date,
                    filing_url=filing_url,
                    date_updated=effective_now.date().isoformat(),
                )
            )
        except SecInsiderError:
            failed_filing_count += 1

    unique = {transaction.filing_url: transaction for transaction in transactions}
    ordered = tuple(
        sorted(
            unique.values(),
            key=lambda item: (
                item.transaction_date,
                item.filing_date,
                item.company.casefold(),
                item.insider.casefold(),
            ),
            reverse=True,
        )
    )
    return SecInsiderEnrichmentResult(
        transactions=ordered,
        candidate_count=len(candidates),
        resolved_issuer_count=len(resolved),
        unresolved_candidate_count=unresolved_count,
        filing_count=filing_count,
        failed_issuer_count=failed_issuer_count,
        failed_filing_count=failed_filing_count,
        network_request_count=client.network_request_count,
        cache_hit_count=client.cache_hit_count,
        request_budget_exhausted=client.request_budget_exhausted,
    )


def parse_sec_ticker_records(payload: bytes) -> tuple[SecTickerRecord, ...]:
    data = json.loads(payload.decode("utf-8"))
    if not isinstance(data, Mapping):
        raise SecInsiderError("SEC ticker map is not a JSON object")
    records: list[SecTickerRecord] = []
    for raw in data.values():
        if not isinstance(raw, Mapping):
            continue
        cik = str(raw.get("cik_str") or "").strip()
        ticker = str(raw.get("ticker") or "").strip().upper()
        title = str(raw.get("title") or "").strip()
        if cik.isdigit() and ticker and title:
            records.append(SecTickerRecord(cik=cik.zfill(10), ticker=ticker, title=title))
    return tuple(records)


def resolve_sec_issuers(
    candidates: Sequence[SecStockCandidate],
    records: Sequence[SecTickerRecord],
) -> tuple[tuple[SecResolvedIssuer, ...], int]:
    by_ticker = {record.ticker: record for record in records}
    by_name: dict[str, list[SecTickerRecord]] = {}
    for record in records:
        by_name.setdefault(_company_key(record.title), []).append(record)

    grouped: dict[str, list[tuple[SecStockCandidate, SecTickerRecord]]] = {}
    unresolved = 0
    for candidate in candidates:
        record = None
        symbol = str(candidate.symbol or "").strip().upper()
        if symbol in by_ticker:
            record = by_ticker[symbol]
        if record is None:
            matches = by_name.get(_company_key(candidate.company), [])
            unique_ciks = {match.cik for match in matches}
            if len(unique_ciks) == 1 and matches:
                record = matches[0]
        if record is None:
            unresolved += 1
            continue
        grouped.setdefault(record.cik, []).append((candidate, record))

    resolved: list[SecResolvedIssuer] = []
    for cik, matches in grouped.items():
        candidates_for_cik = [candidate for candidate, _record in matches]
        record = matches[0][1]
        resolved.append(
            SecResolvedIssuer(
                cik=cik,
                ticker=record.ticker,
                company=candidates_for_cik[0].company or record.title,
                wkn=_join_unique(item.wkn for item in candidates_for_cik),
                source_ref=_join_unique(item.source_ref for item in candidates_for_cik),
            )
        )
    return tuple(sorted(resolved, key=lambda item: item.company.casefold())), unresolved


def recent_form4_filings(
    payload: bytes,
    *,
    cutoff: date,
) -> tuple[tuple[str, str, str], ...]:
    data = json.loads(payload.decode("utf-8"))
    recent = data.get("filings", {}).get("recent", {}) if isinstance(data, Mapping) else {}
    if not isinstance(recent, Mapping):
        return ()
    forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])
    documents = recent.get("primaryDocument", [])
    filing_dates = recent.get("filingDate", [])
    result: list[tuple[str, str, str]] = []
    for form, accession, document, filing_date in zip(
        forms, accessions, documents, filing_dates
    ):
        try:
            parsed_date = date.fromisoformat(str(filing_date))
        except ValueError:
            continue
        if str(form) not in {"4", "4/A"} or parsed_date < cutoff:
            continue
        if accession and document:
            raw_document = re.sub(
                r"^xslF345X\d+/",
                "",
                str(document),
                flags=re.IGNORECASE,
            )
            result.append((str(accession), raw_document, parsed_date.isoformat()))
    return tuple(result)


def parse_form4_transactions(
    payload: bytes,
    *,
    issuer: SecResolvedIssuer,
    filing_date: str,
    filing_url: str,
    date_updated: str,
) -> tuple[SecInsiderTransaction, ...]:
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as error:
        raise SecInsiderError("SEC Form 4 document is not valid XML") from error
    owners = _owner_values(root)
    insider = _join_unique(owner[0] for owner in owners)
    relationship = _join_unique(owner[1] for owner in owners)
    ticker = _first_descendant_text(root, "issuerTradingSymbol") or issuer.ticker
    nodes = [
        node
        for node in root.iter()
        if _local_name(node.tag) in {"nonDerivativeTransaction", "derivativeTransaction"}
    ]
    transactions: list[SecInsiderTransaction] = []
    for index, node in enumerate(nodes, 1):
        transaction_date = _nested_text(node, "transactionDate", "value")
        code = _nested_text(node, "transactionCoding", "transactionCode")
        acquired_disposed = _nested_text(
            node,
            "transactionAmounts",
            "transactionAcquiredDisposedCode",
            "value",
        )
        shares = _nested_text(node, "transactionAmounts", "transactionShares", "value")
        price = _nested_text(
            node,
            "transactionAmounts",
            "transactionPricePerShare",
            "value",
        )
        shares_after = _nested_text(
            node,
            "postTransactionAmounts",
            "sharesOwnedFollowingTransaction",
            "value",
        )
        direction = {"A": "Acquired", "D": "Disposed"}.get(
            acquired_disposed.upper(), acquired_disposed
        )
        transactions.append(
            SecInsiderTransaction(
                company=issuer.company,
                wkn=issuer.wkn,
                ticker=ticker,
                cik=issuer.cik,
                insider=insider,
                relationship=relationship,
                transaction_date=transaction_date,
                transaction_code=code,
                direction=direction,
                shares=shares,
                price=price,
                transaction_value=_multiply(shares, price),
                shares_owned_after=shares_after,
                filing_date=filing_date,
                filing_url=f"{filing_url}#transaction-{index}",
                signal=_signal(code, acquired_disposed),
                review_status="needs_review",
                source_ref=issuer.source_ref,
                date_updated=date_updated,
            )
        )
    return tuple(transactions)


def _fetch_sec_bytes(url: str, user_agent: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": "application/json, application/xml, text/xml, */*",
        },
    )
    tls_context = ssl.create_default_context(cafile=certifi.where())
    with urllib.request.urlopen(  # noqa: S310
        request,
        timeout=30,
        context=tls_context,
    ) as response:
        return response.read()


def _company_key(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    tokens = re.findall(r"[a-z0-9]+", ascii_value.casefold())
    removable = {
        "inc", "incorporated", "corp", "corporation", "company", "co",
        "limited", "ltd", "plc", "holdings", "holding", "group", "common",
        "stock", "ordinary", "shares", "class",
    }
    return "".join(token for token in tokens if token not in removable)


def _owner_values(root: ET.Element) -> tuple[tuple[str, str], ...]:
    result: list[tuple[str, str]] = []
    for owner in (node for node in root.iter() if _local_name(node.tag) == "reportingOwner"):
        name = _first_descendant_text(owner, "rptOwnerName")
        relationship_parts: list[str] = []
        flags = (
            ("isDirector", "Director"),
            ("isOfficer", "Officer"),
            ("isTenPercentOwner", "10% owner"),
            ("isOther", "Other"),
        )
        for tag, label in flags:
            if _first_descendant_text(owner, tag) in {"1", "true", "True"}:
                relationship_parts.append(label)
        officer_title = _first_descendant_text(owner, "officerTitle")
        if officer_title:
            relationship_parts.append(officer_title)
        result.append((name, _join_unique(relationship_parts)))
    return tuple(result)


def _nested_text(node: ET.Element, *path: str) -> str:
    current = node
    for tag in path:
        current = next(
            (child for child in current if _local_name(child.tag) == tag),
            None,
        )
        if current is None:
            return ""
    return (current.text or "").strip()


def _first_descendant_text(node: ET.Element, tag: str) -> str:
    match = next((child for child in node.iter() if _local_name(child.tag) == tag), None)
    return (match.text or "").strip() if match is not None else ""


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _multiply(left: str, right: str) -> str:
    try:
        return format(Decimal(left) * Decimal(right), "f")
    except (InvalidOperation, ValueError):
        return ""


def _signal(code: str, direction: str) -> str:
    normalized = (code.upper(), direction.upper())
    if normalized == ("P", "A"):
        return "Open-market purchase"
    if normalized == ("S", "D"):
        return "Open-market sale"
    return "Review transaction code"


def _simplified_transaction(code: str) -> str:
    return {
        "P": "purchase",
        "S": "sale",
        "M": "Conversion",
        "F": "Payment",
        "G": "Gift",
        "A": "Awarded",
        "J": "Other",
    }.get(code.strip().upper(), "Other")


def _join_unique(values: Iterable[str]) -> str:
    result: list[str] = []
    for value in values:
        for part in str(value or "").split(" | "):
            normalized = part.strip()
            if normalized and normalized not in result:
                result.append(normalized)
    return " | ".join(result)


def _positive_int(value: str | None, default: int) -> int:
    if value is None or not value.strip():
        return default
    try:
        parsed = int(value)
    except ValueError as error:
        raise SecInsiderError("SEC enrichment limits must be positive integers") from error
    if parsed <= 0:
        raise SecInsiderError("SEC enrichment limits must be positive integers")
    return parsed
