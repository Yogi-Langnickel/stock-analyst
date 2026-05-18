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
DATE_RE = re.compile(r"^\d{1,2}\.\d{2}\.\d{2,4}$")
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
    extraction_notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class _NormalizedDividendLines:
    lines: tuple[str, ...]
    ocr_line_normalized: bool = False


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
    normalized = _normalize_dividend_table_lines(lines)
    rows = _extract_row_major_rows(
        normalized.lines,
        issue_id=issue_id,
        page_number=page_number,
    )
    if rows:
        return _tag_ocr_normalized_rows(rows, normalized.ocr_line_normalized)

    rows = _extract_column_major_rows(
        normalized.lines,
        issue_id=issue_id,
        page_number=page_number,
    )
    return _tag_ocr_normalized_rows(rows, normalized.ocr_line_normalized)


def extract_dividend_strategy_continuations_from_lines(
    lines: Sequence[str],
) -> tuple[_DividendContinuation, ...]:
    normalized = _normalize_dividend_table_lines(lines)
    continuations: list[_DividendContinuation] = []

    for index, line in enumerate(normalized.lines):
        if line not in MONTHS or index + 6 >= len(normalized.lines):
            continue

        company = normalized.lines[index + 1]
        payout_count = normalized.lines[index + 2]
        next_cum_day = normalized.lines[index + 3]
        next_pay_day = normalized.lines[index + 4]
        target = normalized.lines[index + 5]
        stop = normalized.lines[index + 6]
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
                    extraction_notes=("ocr_line_normalized",)
                    if normalized.ocr_line_normalized
                    else (),
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
                dividend_yield=_normalize_percent(dividend_yield),
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
                dividend_yield=_normalize_percent(dividend_yields[index]),
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
        extraction_notes=_append_extraction_notes(
            row.extraction_notes,
            continuation.extraction_notes,
        ),
    )


def _tag_ocr_normalized_rows(
    rows: Sequence[DividendStrategyRow],
    ocr_line_normalized: bool,
) -> tuple[DividendStrategyRow, ...]:
    if not ocr_line_normalized:
        return tuple(rows)
    return tuple(
        replace(
            row,
            extraction_notes=_append_extraction_notes(
                row.extraction_notes,
                ("ocr_line_normalized",),
            ),
        )
        for row in rows
    )


def _append_extraction_notes(
    existing: Sequence[str],
    additions: Sequence[str],
) -> tuple[str, ...]:
    notes = list(existing)
    for note in additions:
        if note not in notes:
            notes.append(note)
    return tuple(notes)


def _row_key(month: str, company: str) -> tuple[str, str]:
    return (month, "".join(company.casefold().split()))


def _normalize_currency(value: str) -> str:
    return re.sub(r"\s*€$", " EUR", value)


def _normalize_percent(value: str) -> str:
    return re.sub(r"\s*%$", " %", value)


def _valid_optional_number(value: str) -> bool:
    return bool(NUMBER_RE.match(value) or value in MISSING_VALUE_MARKERS)


def _normalize_optional_number(value: str) -> str:
    if value in MISSING_VALUE_MARKERS:
        return ""
    return value


def _clean_line(line: str) -> str:
    return " ".join(line.strip().split())


def _normalize_dividend_table_lines(lines: Sequence[str]) -> _NormalizedDividendLines:
    """Convert OCR-collapsed dividend table lines into strict parser input cells."""

    normalized: list[str] = []
    ocr_line_normalized = False
    for raw_line in lines:
        line = _clean_line(raw_line)
        if not line:
            continue
        expanded = _expand_inline_dividend_line(line)
        if expanded:
            normalized.extend(expanded)
            ocr_line_normalized = True
        else:
            normalized.append(line)
    return _NormalizedDividendLines(tuple(normalized), ocr_line_normalized)


def _expand_inline_dividend_line(line: str) -> tuple[str, ...]:
    tokens = tuple(line.split())
    return (
        _expand_inline_dividend_base_row(tokens)
        or _expand_inline_dividend_continuation_row(tokens)
        or ()
    )


def _expand_inline_dividend_base_row(tokens: Sequence[str]) -> tuple[str, ...]:
    if len(tokens) < 7 or tokens[0] not in MONTHS:
        return ()

    wkn_index = _first_wkn_token_index(tokens, start=2)
    if wkn_index is None or wkn_index + 5 != len(tokens):
        return ()

    price = tokens[wkn_index + 1]
    market_cap = tokens[wkn_index + 2]
    dividend_yield = tokens[wkn_index + 3]
    kgv = tokens[wkn_index + 4]
    if not (
        PRICE_RE.match(price)
        and _valid_optional_number(market_cap)
        and PERCENT_RE.match(dividend_yield)
        and _valid_optional_number(kgv)
    ):
        return ()

    company = " ".join(tokens[1:wkn_index])
    if not company:
        return ()

    return (
        tokens[0],
        company,
        tokens[wkn_index],
        price,
        market_cap,
        dividend_yield,
        kgv,
    )


def _expand_inline_dividend_continuation_row(tokens: Sequence[str]) -> tuple[str, ...]:
    if len(tokens) < 7 or tokens[-1] not in MONTHS:
        return ()

    payout_count, next_cum_day, next_pay_day, target, stop = tokens[:5]
    if not (
        NUMBER_RE.match(payout_count)
        and DATE_RE.match(next_cum_day)
        and DATE_RE.match(next_pay_day)
        and PRICE_RE.match(target)
        and PRICE_RE.match(stop)
    ):
        return ()

    company = " ".join(tokens[5:-1])
    if not company:
        return ()

    return (
        tokens[-1],
        company,
        payout_count,
        next_cum_day,
        next_pay_day,
        target,
        stop,
    )


def _first_wkn_token_index(tokens: Sequence[str], *, start: int) -> int | None:
    for index in range(start, len(tokens)):
        if WKN_RE.match(tokens[index]):
            return index
    return None


def _issue_id_from_filename(pdf_path: Path) -> str:
    return pdf_path.stem
