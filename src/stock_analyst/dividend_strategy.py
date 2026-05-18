"""Local extraction for dividend strategy table rows."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import re
from typing import Sequence

from stock_analyst.extraction import RawTextExtractor, extract_pdf_text
from stock_analyst.schemas import ReviewStatus


MONTHS = {
    "Januar",
    "Februar",
    "März",
    "April",
    "Mai",
    "Juni",
    "Juli",
    "August",
    "September",
    "Oktober",
    "November",
    "Dezember",
}

WKN_RE = re.compile(r"^[A-Z0-9]{6}$")
PRICE_RE = re.compile(r"^\d+(?:,\d+)?\s*€$")
PERCENT_RE = re.compile(r"^\d+(?:,\d+)?\s*%$")
NUMBER_RE = re.compile(r"^\d+(?:,\d+)?$")
DATE_RE = re.compile(r"^\d{2}\.\d{2}\.\d{2,4}$")
MISSING_VALUE_MARKERS = {"-", "–", "—", "k.A.", "k. A.", "n/a", "N/A"}


@dataclass(frozen=True)
class DividendStrategyRow:
    issue_id: str
    page: int
    month: str
    company: str
    wkn: str
    current_price: str
    market_cap_billions_eur: str | None
    dividend_yield: str
    kgv_2026e: str | None
    payout_count: str | None = None
    next_cum_day: str | None = None
    next_pay_day: str | None = None
    target: str | None = None
    stop: str | None = None
    review_status: ReviewStatus = ReviewStatus.NEEDS_REVIEW
    extraction_notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "issueId": self.issue_id,
            "page": self.page,
            "month": self.month,
            "company": self.company,
            "wkn": self.wkn,
            "currentPrice": self.current_price,
            "marketCapBillionsEur": self.market_cap_billions_eur,
            "dividendYield": self.dividend_yield,
            "kgv2026e": self.kgv_2026e,
            "reviewStatus": self.review_status.value,
        }
        optional_fields = {
            "payoutCount": self.payout_count,
            "nextCumDay": self.next_cum_day,
            "nextPayDay": self.next_pay_day,
            "target": self.target,
            "stop": self.stop,
        }
        for key, value in optional_fields.items():
            if value is not None:
                result[key] = value
        if self.extraction_notes:
            result["extractionNotes"] = list(self.extraction_notes)
        return result


@dataclass(frozen=True)
class DividendStrategyExtraction:
    issue_id: str
    pdf_path: Path
    page_count: int
    external_services_enabled: bool
    rows: tuple[DividendStrategyRow, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "issueId": self.issue_id,
            "pdfPath": str(self.pdf_path),
            "pageCount": self.page_count,
            "externalServicesEnabled": self.external_services_enabled,
            "rows": [row.to_dict() for row in self.rows],
        }


@dataclass(frozen=True)
class _DividendContinuation:
    month: str
    company: str
    payout_count: str | None = None
    next_cum_day: str | None = None
    next_pay_day: str | None = None
    target: str | None = None
    stop: str | None = None


def build_dividend_strategy_from_pdf(
    pdf_path: Path,
    *,
    issue_id: str | None = None,
    extractor: RawTextExtractor | None = None,
    min_embedded_chars: int = 40,
) -> DividendStrategyExtraction:
    """Extract dividend strategy rows using local embedded text only."""

    extraction = extract_pdf_text(
        pdf_path,
        extractor=extractor,
        min_embedded_chars=min_embedded_chars,
    )
    resolved_issue_id = issue_id or _issue_id_from_filename(pdf_path)
    rows: list[DividendStrategyRow] = []
    rows = list(
        extract_dividend_strategy_rows_from_page_lines(
            tuple((page.page_number, page.text.splitlines()) for page in extraction.pages),
            issue_id=resolved_issue_id,
        )
    )
    return DividendStrategyExtraction(
        issue_id=resolved_issue_id,
        pdf_path=pdf_path,
        page_count=extraction.page_count,
        external_services_enabled=False,
        rows=tuple(rows),
    )


def extract_dividend_strategy_rows_from_page_lines(
    pages: Sequence[tuple[int, Sequence[str]]],
    *,
    issue_id: str,
) -> tuple[DividendStrategyRow, ...]:
    rows: list[DividendStrategyRow] = []
    continuations: dict[tuple[str, str], _DividendContinuation] = {}

    for page_number, page_lines in pages:
        rows.extend(
            extract_dividend_strategy_rows_from_lines(
                page_lines,
                issue_id=issue_id,
                page_number=page_number,
            )
        )
        for continuation in extract_dividend_strategy_continuations_from_lines(page_lines):
            continuations[_row_key(continuation.month, continuation.company)] = continuation

    return tuple(_apply_continuation(row, continuations) for row in rows)


def extract_dividend_strategy_rows_from_lines(
    lines: Sequence[str],
    *,
    issue_id: str,
    page_number: int,
) -> tuple[DividendStrategyRow, ...]:
    normalized_lines = tuple(_clean_line(line) for line in lines if _clean_line(line))
    rows = _extract_row_major_rows(
        normalized_lines,
        issue_id=issue_id,
        page_number=page_number,
    )
    if rows:
        return rows

    return _extract_column_major_rows(
        normalized_lines,
        issue_id=issue_id,
        page_number=page_number,
    )


def extract_dividend_strategy_continuations_from_lines(
    lines: Sequence[str],
) -> tuple[_DividendContinuation, ...]:
    normalized_lines = tuple(_clean_line(line) for line in lines if _clean_line(line))
    continuations: list[_DividendContinuation] = []

    for index, line in enumerate(normalized_lines):
        if line not in MONTHS or index + 6 >= len(normalized_lines):
            continue

        company = normalized_lines[index + 1]
        payout_count = normalized_lines[index + 2]
        next_cum_day = normalized_lines[index + 3]
        next_pay_day = normalized_lines[index + 4]
        target = normalized_lines[index + 5]
        stop = normalized_lines[index + 6]
        if (
            NUMBER_RE.match(payout_count)
            and DATE_RE.match(next_cum_day)
            and DATE_RE.match(next_pay_day)
            and PRICE_RE.match(target)
            and PRICE_RE.match(stop)
        ):
            continuations.append(
                _DividendContinuation(
                    month=line,
                    company=company,
                    payout_count=payout_count,
                    next_cum_day=next_cum_day,
                    next_pay_day=next_pay_day,
                    target=_normalize_currency(target),
                    stop=_normalize_currency(stop),
                )
            )

    return tuple(continuations)


def _extract_row_major_rows(
    lines: Sequence[str],
    *,
    issue_id: str,
    page_number: int,
) -> tuple[DividendStrategyRow, ...]:
    rows: list[DividendStrategyRow] = []

    for index, line in enumerate(lines):
        if line not in MONTHS or index + 6 >= len(lines):
            continue

        company = lines[index + 1]
        wkn = lines[index + 2]
        current_price = lines[index + 3]
        market_cap = lines[index + 4]
        dividend_yield = lines[index + 5]
        kgv = lines[index + 6]
        if not (
            WKN_RE.match(wkn)
            and PRICE_RE.match(current_price)
            and _valid_optional_number(market_cap)
            and PERCENT_RE.match(dividend_yield)
            and _valid_optional_number(kgv)
        ):
            continue

        rows.append(
            DividendStrategyRow(
                issue_id=issue_id,
                page=page_number,
                month=line,
                company=company,
                wkn=wkn,
                current_price=_normalize_currency(current_price),
                market_cap_billions_eur=_normalize_optional_number(market_cap),
                dividend_yield=dividend_yield,
                kgv_2026e=_normalize_optional_number(kgv),
            )
        )

    return tuple(rows)


def _extract_column_major_rows(
    lines: Sequence[str],
    *,
    issue_id: str,
    page_number: int,
) -> tuple[DividendStrategyRow, ...]:
    months = _values_between(lines, "Monat", "Unternehmen")
    companies = _values_between(lines, "Unternehmen", "WKN")
    wkns = _values_between(lines, "WKN", "Aktueller Kurs")
    prices = _values_between(lines, "Aktueller Kurs", "Marktkap. in Milliarden €")
    market_caps = _values_between(lines, "Marktkap. in Milliarden €", "Dividendenrendite")
    dividend_yields = _values_between(lines, "Dividendenrendite", "KGV 2026e")
    kgvs = _values_after(lines, "KGV 2026e")
    row_count = min(
        len(months),
        len(companies),
        len(wkns),
        len(prices),
        len(market_caps),
        len(dividend_yields),
        len(kgvs),
    )
    rows: list[DividendStrategyRow] = []

    for index in range(row_count):
        if not (
            months[index] in MONTHS
            and WKN_RE.match(wkns[index])
            and PRICE_RE.match(prices[index])
            and _valid_optional_number(market_caps[index])
            and PERCENT_RE.match(dividend_yields[index])
            and _valid_optional_number(kgvs[index])
        ):
            continue

        rows.append(
            DividendStrategyRow(
                issue_id=issue_id,
                page=page_number,
                month=months[index],
                company=companies[index],
                wkn=wkns[index],
                current_price=_normalize_currency(prices[index]),
                market_cap_billions_eur=_normalize_optional_number(market_caps[index]),
                dividend_yield=dividend_yields[index],
                kgv_2026e=_normalize_optional_number(kgvs[index]),
                extraction_notes=("column_major_text_order",),
            )
        )

    return tuple(rows)


def _values_between(lines: Sequence[str], start: str, end: str) -> tuple[str, ...]:
    try:
        start_index = lines.index(start) + 1
        end_index = lines.index(end, start_index)
    except ValueError:
        return ()

    return tuple(lines[start_index:end_index])


def _values_after(lines: Sequence[str], start: str) -> tuple[str, ...]:
    try:
        start_index = lines.index(start) + 1
    except ValueError:
        return ()

    return tuple(line for line in lines[start_index:] if line not in MONTHS)[:24]


def _apply_continuation(
    row: DividendStrategyRow,
    continuations: dict[tuple[str, str], _DividendContinuation],
) -> DividendStrategyRow:
    continuation = continuations.get(_row_key(row.month, row.company))
    if continuation is None:
        return row

    return replace(
        row,
        payout_count=continuation.payout_count,
        next_cum_day=continuation.next_cum_day,
        next_pay_day=continuation.next_pay_day,
        target=continuation.target,
        stop=continuation.stop,
    )


def _row_key(month: str, company: str) -> tuple[str, str]:
    return (month, company.casefold())


def _normalize_currency(value: str) -> str:
    return value.replace(" €", " EUR").replace("€", "EUR")


def _valid_optional_number(value: str) -> bool:
    return bool(NUMBER_RE.match(value) or value in MISSING_VALUE_MARKERS)


def _normalize_optional_number(value: str) -> str:
    if value in MISSING_VALUE_MARKERS:
        return ""
    return value


def _clean_line(line: str) -> str:
    return " ".join(line.strip().split())


def _issue_id_from_filename(pdf_path: Path) -> str:
    return pdf_path.stem
