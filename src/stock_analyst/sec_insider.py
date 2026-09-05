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
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

import certifi


SEC_TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_SUBMISSIONS_ARCHIVE_URL = "https://data.sec.gov/submissions/{name}"
SEC_ARCHIVES_URL = (
    "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{document}"
)
DEFAULT_LOOKBACK_DAYS = 365
DEFAULT_MAX_REQUESTS = 100
DEFAULT_CACHE_DIR = Path("data/market-cache/sec-edgar")
ACCESSION_RE = re.compile(r"^\d{10}-\d{2}-\d{6}$")


class SecInsiderError(RuntimeError):
    """Raised when safe SEC insider enrichment cannot continue."""


class _SecPayloadValidationError(SecInsiderError):
    """Raised when fetched SEC bytes fail their content contract."""


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
    form_type: str = "4"
    filing_accession: str = ""
    original_submission_date: str = ""
    period_of_report: str = ""
    correction_status: str = "original"
    security_kind: str = "non_derivative"

    @property
    def is_stock_purchase_or_sale(self) -> bool:
        return (
            self.security_kind == "non_derivative"
            and self.transaction_code.strip().upper() in {"P", "S", "PURCHASE", "SALE"}
        )

    def to_sheet_row(self) -> list[str]:
        relationship = self.relationship
        if self.correction_status == "effective_correction":
            relationship = _join_unique((relationship, "Form 4/A correction"))
        elif self.correction_status == "ambiguous_correction":
            relationship = _join_unique(
                (relationship, "Form 4/A correction - original ambiguous")
            )
        return [
            self.company,
            self.wkn,
            self.ticker,
            self.insider,
            relationship,
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
    transaction_revisions: tuple[SecInsiderTransaction, ...] = ()
    archive_file_count: int = 0
    archive_coverage_partial: bool = False


@dataclass(frozen=True)
class _SecForm4Filing:
    accession: str
    document: str
    filing_date: str
    form_type: str


FetchBytes = Callable[[str, str], bytes]
ValidateBytes = Callable[[bytes], None]


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

    def get(
        self,
        url: str,
        cache_path: Path,
        *,
        ttl: timedelta | None,
        validator: ValidateBytes | None = None,
    ) -> bytes:
        full_path = self.config.cache_dir / cache_path
        if full_path.exists() and (
            ttl is None
            or self.now.timestamp() - full_path.stat().st_mtime <= ttl.total_seconds()
        ):
            cached_payload = full_path.read_bytes()
            try:
                if validator is not None:
                    validator(cached_payload)
            except SecInsiderError:
                _quarantine_cache_file(full_path)
            else:
                self.cache_hit_count += 1
                return cached_payload
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
        if validator is not None:
            validator(payload)
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
        validator=_validate_ticker_json,
    )
    records = parse_sec_ticker_records(ticker_payload)
    resolved, unresolved_count = resolve_sec_issuers(candidates, records)
    cutoff = effective_now.date() - timedelta(days=config.lookback_days)
    transactions: list[SecInsiderTransaction] = []
    filing_count = 0
    failed_issuer_count = 0
    failed_filing_count = 0

    pending_filings: list[tuple[SecResolvedIssuer, _SecForm4Filing]] = []
    archive_file_count = 0
    archive_coverage_partial = False
    for issuer in resolved:
        try:
            submission_payload = client.get(
                SEC_SUBMISSIONS_URL.format(cik=issuer.cik),
                Path("submissions") / f"CIK{issuer.cik}.json",
                ttl=timedelta(hours=24),
                validator=_validate_submissions_json,
            )
        except SecInsiderError:
            failed_issuer_count += 1
            archive_coverage_partial = True
            if client.request_budget_exhausted:
                break
            continue
        issuer_filings = list(
            _recent_form4_filing_records(submission_payload, cutoff=cutoff)
        )
        archive_names, archive_metadata_complete = _required_submission_archive_names(
            submission_payload,
            cutoff=cutoff,
        )
        issuer_archive_failed = not archive_metadata_complete
        for archive_name in archive_names:
            try:
                archive_payload = client.get(
                    SEC_SUBMISSIONS_ARCHIVE_URL.format(name=archive_name),
                    Path("submissions") / "archives" / archive_name,
                    ttl=timedelta(hours=24),
                    validator=_validate_submission_archive_json,
                )
            except SecInsiderError:
                issuer_archive_failed = True
                if client.request_budget_exhausted:
                    break
                continue
            archive_file_count += 1
            issuer_filings.extend(
                _recent_form4_filing_records(
                    archive_payload,
                    cutoff=cutoff,
                    archived=True,
                )
            )
        if issuer_archive_failed:
            archive_coverage_partial = True
            failed_issuer_count += 1
        pending_filings.extend(
            (issuer, filing)
            for filing in {
                (item.accession, item.document): item for item in issuer_filings
            }.values()
        )
        if client.request_budget_exhausted:
            break

    for issuer, filing in sorted(
        pending_filings,
        key=lambda item: item[1].filing_date,
        reverse=True,
    ):
        accession_compact = filing.accession.replace("-", "")
        filing_url = SEC_ARCHIVES_URL.format(
            cik=int(issuer.cik),
            accession=accession_compact,
            document=filing.document,
        )
        try:
            xml_payload = client.get(
                filing_url,
                Path("filings")
                / str(int(issuer.cik))
                / f"{accession_compact}-raw.xml",
                ttl=None,
                validator=_validate_xml,
            )
        except _SecPayloadValidationError:
            filing_count += 1
            failed_filing_count += 1
            continue
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
                    filing_date=filing.filing_date,
                    filing_url=filing_url,
                    date_updated=effective_now.date().isoformat(),
                    form_type=filing.form_type,
                    filing_accession=filing.accession,
                )
            )
        except SecInsiderError:
            failed_filing_count += 1

    revisions, effective_transactions = _project_effective_transactions(transactions)
    unique = {
        transaction.filing_url: transaction for transaction in effective_transactions
    }
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
        transaction_revisions=revisions,
        archive_file_count=archive_file_count,
        archive_coverage_partial=archive_coverage_partial,
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
    return tuple(
        (filing.accession, filing.document, filing.filing_date)
        for filing in _recent_form4_filing_records(payload, cutoff=cutoff)
    )


def _recent_form4_filing_records(
    payload: bytes,
    *,
    cutoff: date,
    archived: bool = False,
) -> tuple[_SecForm4Filing, ...]:
    data = json.loads(payload.decode("utf-8"))
    recent = (
        data
        if archived and isinstance(data, Mapping)
        else data.get("filings", {}).get("recent", {})
        if isinstance(data, Mapping)
        else {}
    )
    if not isinstance(recent, Mapping):
        return ()
    forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])
    documents = recent.get("primaryDocument", [])
    filing_dates = recent.get("filingDate", [])
    result: list[_SecForm4Filing] = []
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
            result.append(
                _SecForm4Filing(
                    accession=str(accession),
                    document=raw_document,
                    filing_date=parsed_date.isoformat(),
                    form_type=str(form),
                )
            )
    return tuple(result)


def _required_submission_archive_names(
    payload: bytes,
    *,
    cutoff: date,
) -> tuple[tuple[str, ...], bool]:
    data = json.loads(payload.decode("utf-8"))
    filings = data.get("filings", {}) if isinstance(data, Mapping) else {}
    raw_files = filings.get("files", []) if isinstance(filings, Mapping) else []
    if not isinstance(raw_files, list):
        return (), False
    names: list[str] = []
    complete = True
    for raw in raw_files:
        if not isinstance(raw, Mapping):
            complete = False
            continue
        name = str(raw.get("name") or "").strip()
        filing_to_text = str(raw.get("filingTo") or "").strip()
        try:
            filing_to = date.fromisoformat(filing_to_text)
        except ValueError:
            filing_to = None
            complete = False
        if filing_to is not None and filing_to < cutoff:
            continue
        if not name or Path(name).name != name or not name.endswith(".json"):
            complete = False
            continue
        names.append(name)
    return tuple(dict.fromkeys(names)), complete


def parse_form4_transactions(
    payload: bytes,
    *,
    issuer: SecResolvedIssuer,
    filing_date: str,
    filing_url: str,
    date_updated: str,
    form_type: str = "4",
    filing_accession: str = "",
) -> tuple[SecInsiderTransaction, ...]:
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as error:
        raise SecInsiderError("SEC Form 4 document is not valid XML") from error
    owners = _owner_values(root)
    insider = _join_unique(owner[0] for owner in owners)
    relationship = _join_unique(owner[1] for owner in owners)
    ticker = _first_descendant_text(root, "issuerTradingSymbol") or issuer.ticker
    original_submission_date = _first_descendant_text(
        root, "dateOfOriginalSubmission"
    )
    period_of_report = _first_descendant_text(root, "periodOfReport")
    nodes = [
        node
        for node in root.iter()
        if _local_name(node.tag) in {"nonDerivativeTransaction", "derivativeTransaction"}
    ]
    transactions: list[SecInsiderTransaction] = []
    for index, node in enumerate(nodes, 1):
        security_kind = (
            "derivative"
            if _local_name(node.tag) == "derivativeTransaction"
            else "non_derivative"
        )
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
                form_type=form_type,
                filing_accession=filing_accession,
                original_submission_date=original_submission_date,
                period_of_report=period_of_report,
                security_kind=security_kind,
            )
        )
    return tuple(transactions)


def _project_effective_transactions(
    transactions: Sequence[SecInsiderTransaction],
) -> tuple[tuple[SecInsiderTransaction, ...], tuple[SecInsiderTransaction, ...]]:
    """Retain filing revisions while projecting only effective Form 4 activity."""

    by_filing: dict[str, list[SecInsiderTransaction]] = {}
    for transaction in transactions:
        filing_identity = transaction.filing_url.split("#", 1)[0]
        by_filing.setdefault(filing_identity, []).append(transaction)

    amendment_groups: dict[tuple[str, str, str, str], list[str]] = {}
    for filing_identity, filing_rows in by_filing.items():
        first = filing_rows[0]
        if first.form_type.upper() != "4/A":
            continue
        if first.original_submission_date or first.period_of_report:
            key = (
                first.cik,
                first.insider.casefold(),
                first.original_submission_date,
                first.period_of_report,
            )
        else:
            # Without amendment linkage metadata, do not guess that unrelated
            # Form 4/A filings supersede one another.
            key = (first.cik, first.insider.casefold(), filing_identity, "")
        amendment_groups.setdefault(key, []).append(filing_identity)

    effective_amendments: set[str] = set()
    superseded_amendments: set[str] = set()
    for filing_identities in amendment_groups.values():
        ordered = sorted(
            filing_identities,
            key=lambda identity: (
                by_filing[identity][0].filing_date,
                by_filing[identity][0].filing_accession,
                identity,
            ),
        )
        effective_amendments.add(ordered[-1])
        superseded_amendments.update(ordered[:-1])

    superseded_originals: set[str] = set()
    ambiguous_amendments: set[str] = set()
    for amendment_identity in effective_amendments:
        amendment = by_filing[amendment_identity][0]
        if not amendment.original_submission_date or not amendment.period_of_report:
            ambiguous_amendments.add(amendment_identity)
            continue
        matching_originals: list[str] = []
        for filing_identity, filing_rows in by_filing.items():
            original = filing_rows[0]
            if original.form_type.upper() == "4/A":
                continue
            if (
                original.cik == amendment.cik
                and original.insider.casefold() == amendment.insider.casefold()
                and original.filing_date == amendment.original_submission_date
                and original.period_of_report == amendment.period_of_report
            ):
                matching_originals.append(filing_identity)
        if len(matching_originals) == 1:
            superseded_originals.add(matching_originals[0])
        else:
            # Form 4/A exposes an original-submission date, not a stable original
            # accession. Retain all originals unless the issuer/owner/date/period
            # tuple resolves exactly one filing; omission is worse than duplication.
            ambiguous_amendments.add(amendment_identity)

    revisions: list[SecInsiderTransaction] = []
    effective: list[SecInsiderTransaction] = []
    for filing_identity, filing_rows in by_filing.items():
        if filing_identity in superseded_originals:
            status = "superseded"
        elif filing_identity in superseded_amendments:
            status = "superseded_correction"
        elif filing_identity in ambiguous_amendments:
            status = "ambiguous_correction"
        elif filing_identity in effective_amendments:
            status = "effective_correction"
        else:
            status = "original"
        projected_rows = [
            replace(transaction, correction_status=status)
            for transaction in filing_rows
        ]
        revisions.extend(projected_rows)
        if status in {"original", "effective_correction", "ambiguous_correction"}:
            effective.extend(projected_rows)
    return tuple(revisions), tuple(effective)


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


def _validated_json_object(payload: bytes) -> Mapping[str, object]:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _SecPayloadValidationError("SEC response is not valid JSON") from error
    if not isinstance(value, Mapping):
        raise _SecPayloadValidationError("SEC JSON response is not an object")
    return value


def _validate_ticker_json(payload: bytes) -> None:
    value = _validated_json_object(payload)
    usable_records = 0
    for record in value.values():
        if not isinstance(record, Mapping):
            continue
        cik = str(record.get("cik_str") or "").strip()
        ticker = str(record.get("ticker") or "").strip()
        title = str(record.get("title") or "").strip()
        if cik.isdigit() and ticker and title:
            usable_records += 1
    if usable_records == 0:
        raise _SecPayloadValidationError("SEC ticker response has no usable records")


def _validate_submissions_json(payload: bytes) -> None:
    value = _validated_json_object(payload)
    filings = value.get("filings")
    if not isinstance(filings, Mapping):
        raise _SecPayloadValidationError("SEC submissions response is malformed")
    recent = filings.get("recent")
    if not isinstance(recent, Mapping):
        raise _SecPayloadValidationError("SEC submissions response is malformed")
    _validate_filing_arrays(recent, payload_name="SEC submissions response")
    if not isinstance(filings.get("files"), list):
        raise _SecPayloadValidationError("SEC submissions archive list is malformed")


def _validate_submission_archive_json(payload: bytes) -> None:
    value = _validated_json_object(payload)
    _validate_filing_arrays(value, payload_name="SEC submissions archive")


def _validate_filing_arrays(
    value: Mapping[str, object],
    *,
    payload_name: str,
) -> None:
    required_arrays = ("form", "accessionNumber", "primaryDocument", "filingDate")
    if any(not isinstance(value.get(name), list) for name in required_arrays):
        raise _SecPayloadValidationError(f"{payload_name} is malformed")
    lengths = {len(value[name]) for name in required_arrays}
    if len(lengths) != 1:
        raise _SecPayloadValidationError(
            f"{payload_name} filing arrays have mismatched lengths"
        )
    for index, (form, accession, document, filing_date) in enumerate(
        zip(*(value[name] for name in required_arrays))
    ):
        if (
            not isinstance(form, str)
            or not form.strip()
            or form != form.strip()
            or any(ord(character) < 32 for character in form)
        ):
            raise _SecPayloadValidationError(
                f"{payload_name} filing row {index} has an invalid form"
            )
        if not isinstance(accession, str) or ACCESSION_RE.fullmatch(accession) is None:
            raise _SecPayloadValidationError(
                f"{payload_name} filing row {index} has an invalid accession"
            )
        if not _safe_primary_document(document):
            raise _SecPayloadValidationError(
                f"{payload_name} filing row {index} has an invalid primary document"
            )
        if not isinstance(filing_date, str):
            raise _SecPayloadValidationError(
                f"{payload_name} filing row {index} has an invalid filing date"
            )
        try:
            date.fromisoformat(filing_date)
        except ValueError as error:
            raise _SecPayloadValidationError(
                f"{payload_name} filing row {index} has an invalid filing date"
            ) from error


def _safe_primary_document(value: object) -> bool:
    if not isinstance(value, str) or not value or value != value.strip():
        return False
    raw_document = re.sub(
        r"^xslF345X\d+/",
        "",
        value,
        flags=re.IGNORECASE,
    )
    return bool(
        raw_document
        and raw_document not in {".", ".."}
        and "/" not in raw_document
        and "\\" not in raw_document
    )


def _validate_xml(payload: bytes) -> None:
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as error:
        raise _SecPayloadValidationError("SEC Form 4 document is not valid XML") from error
    if _local_name(root.tag) != "ownershipDocument":
        raise _SecPayloadValidationError("SEC Form 4 document has an unexpected root")


def _quarantine_cache_file(path: Path) -> Path:
    candidate = path.with_suffix(f"{path.suffix}.corrupt")
    suffix = 1
    while candidate.exists():
        candidate = path.with_suffix(f"{path.suffix}.corrupt.{suffix}")
        suffix += 1
    path.replace(candidate)
    return candidate


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
