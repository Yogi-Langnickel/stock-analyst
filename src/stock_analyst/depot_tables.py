"""Local extraction for publisher model-depot tables."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Sequence

from stock_analyst.extraction import RawTextExtractor, extract_pdf_text
from stock_analyst.schemas import ReviewStatus


WKN_RE = re.compile(r"^[A-Z0-9]{6}$")
DATE_RE = re.compile(
    r"\d{2}\.\d{2}(?:\./\d{2}\.\d{2})?\.\d{2}(?:/\d{2}\.\d{2}\.\d{2})*"
)
PRICE_RE = re.compile(r"\d+(?:\.\d{3})*,\d+\s*EUR\*?")
PERCENT_RE = re.compile(r"^[+-]?\d+(?:,\d+)?\s*%$")
QUANTITY_RE = re.compile(r"^\d+(?:\.\d{3})*$")
TRANSACTION_ACTIONS = {"Kauf", "Verkauf", "Teilkauf", "Teilverkauf"}


@dataclass(frozen=True)
class DepotPositionRow:
    issue_id: str
    page: int
    instrument: str
    wkn: str
    quantity: str
    buy_date: str
    buy_price: str
    current_price: str
    value: str
    performance_since_buy: str
    stop: str
    review_status: ReviewStatus = ReviewStatus.NEEDS_REVIEW


@dataclass(frozen=True)
class DepotTransactionRow:
    issue_id: str
    page: int
    action: str
    instrument: str = ""
    wkn: str = ""
    quantity: str = ""
    transaction_date: str = ""
    price: str = ""
    performance_since_buy: str = ""
    review_status: ReviewStatus = ReviewStatus.NEEDS_REVIEW


@dataclass(frozen=True)
class DepotTableExtraction:
    issue_id: str
    pdf_path: Path
    page_count: int
    external_services_enabled: bool
    positions: tuple[DepotPositionRow, ...]
    transactions: tuple[DepotTransactionRow, ...]


def build_depot_tables_from_pdf(
    pdf_path: Path,
    *,
    issue_id: str | None = None,
    extractor: RawTextExtractor | None = None,
    min_embedded_chars: int = 40,
) -> DepotTableExtraction:
    extraction = extract_pdf_text(
        pdf_path,
        extractor=extractor,
        min_embedded_chars=min_embedded_chars,
    )
    resolved_issue_id = issue_id or _issue_id_from_filename(pdf_path)
    positions, transactions = extract_depot_rows_from_page_lines(
        tuple((page.page_number, page.text.splitlines()) for page in extraction.pages),
        issue_id=resolved_issue_id,
    )
    return DepotTableExtraction(
        issue_id=resolved_issue_id,
        pdf_path=pdf_path,
        page_count=extraction.page_count,
        external_services_enabled=False,
        positions=positions,
        transactions=transactions,
    )


def extract_depot_rows_from_page_lines(
    pages: Sequence[tuple[int, Sequence[str]]],
    *,
    issue_id: str,
) -> tuple[tuple[DepotPositionRow, ...], tuple[DepotTransactionRow, ...]]:
    positions: list[DepotPositionRow] = []
    transactions: list[DepotTransactionRow] = []
    for page_number, raw_lines in pages:
        lines = tuple(_clean_line(line) for line in raw_lines if _clean_line(line))
        if _looks_like_depot_page(lines):
            positions.extend(
                _extract_position_rows(lines, issue_id=issue_id, page_number=page_number)
            )
            transactions.extend(
                _extract_transaction_rows(lines, issue_id=issue_id, page_number=page_number)
            )
    return tuple(positions), tuple(transactions)


def _extract_position_rows(
    lines: Sequence[str],
    *,
    issue_id: str,
    page_number: int,
) -> tuple[DepotPositionRow, ...]:
    try:
        end = lines.index("Depotwert")
    except ValueError:
        return ()
    header_kurs_indexes = [
        index for index, line in enumerate(lines[:end]) if line == "kurs"
    ]
    if not header_kurs_indexes:
        return ()
    start = header_kurs_indexes[-1] + 1

    body = lines[start:end]
    rows: list[DepotPositionRow] = []
    cursor = 0
    while cursor < len(body):
        wkn_index = _next_wkn_index(body, cursor)
        if wkn_index is None:
            raise ValueError("publisher depot position identity is incomplete")
        instrument = " ".join(body[cursor:wkn_index]).strip()
        if not instrument:
            raise ValueError("publisher depot position identity is incomplete")
        parsed, next_cursor = _parse_position_tail(body, wkn_index + 1)
        if parsed is None:
            raise ValueError("publisher depot position row does not match schema")
        if parsed is not None:
            rows.append(
                DepotPositionRow(
                    issue_id=issue_id,
                    page=page_number,
                    instrument=instrument,
                    wkn=body[wkn_index],
                    quantity=parsed["quantity"],
                    buy_date=parsed["buy_date"],
                    buy_price=parsed["buy_price"],
                    current_price=parsed["current_price"],
                    value=parsed["value"],
                    performance_since_buy=parsed["performance_since_buy"],
                    stop=parsed["stop"],
                )
            )
        cursor = next_cursor
    return tuple(rows)


def _extract_transaction_rows(
    lines: Sequence[str],
    *,
    issue_id: str,
    page_number: int,
) -> tuple[DepotTransactionRow, ...]:
    if "Diese Woche keine Transaktionen" in lines:
        return (
            DepotTransactionRow(
                issue_id=issue_id,
                page=page_number,
                action="Keine Transaktionen",
            ),
        )
    try:
        header_start = lines.index("Transaktion")
        body_start = lines.index("seit Kauf", header_start) + 1
    except ValueError:
        return ()
    header = lines[header_start:body_start]
    if not all(label in header for label in ("Wertpapier", "WKN", "Kurs", "Performance")):
        return ()
    rows: list[DepotTransactionRow] = []
    cursor = body_start
    boundaries = {"Aktie/Derivat", "Durchgeführte Transaktionen", "Hinweis auf Interessenkonflikte:"}
    while cursor < len(lines) and lines[cursor] not in boundaries:
        action = lines[cursor]
        if action not in TRANSACTION_ACTIONS:
            raise ValueError("publisher depot transaction row does not match schema")
        wkn_index = _next_wkn_index(lines, cursor + 1)
        if wkn_index is None or wkn_index == cursor + 1:
            raise ValueError("publisher depot transaction identity is incomplete")
        instrument_parts = lines[cursor + 1:wkn_index]
        if any(part in TRANSACTION_ACTIONS for part in instrument_parts):
            raise ValueError("publisher depot transaction identity is ambiguous")
        tail = lines[wkn_index + 1:wkn_index + 5]
        if len(tail) != 4 or not (
            QUANTITY_RE.fullmatch(tail[0])
            and re.fullmatch(r"\d{2}\.\d{2}\.\d{2}", tail[1])
            and PRICE_RE.fullmatch(tail[2])
            and PERCENT_RE.fullmatch(tail[3])
        ):
            raise ValueError("publisher depot transaction values are incomplete")
        rows.append(DepotTransactionRow(
            issue_id=issue_id, page=page_number, action=action,
            instrument=" ".join(instrument_parts), wkn=lines[wkn_index],
            quantity=tail[0], transaction_date=tail[1], price=tail[2],
            performance_since_buy=tail[3],
        ))
        cursor = wkn_index + 5
    return tuple(rows)


def _parse_position_tail(
    body: Sequence[str],
    start_index: int,
) -> tuple[dict[str, str] | None, int]:
    if start_index + 5 >= len(body):
        return None, start_index + 1
    quantity = body[start_index]
    if not QUANTITY_RE.match(quantity):
        return None, start_index + 1

    index = start_index + 1
    date_line = body[index]
    buy_date_match = DATE_RE.match(date_line)
    if buy_date_match is None:
        return None, index + 1
    buy_date = buy_date_match.group(0)
    remainder = date_line[buy_date_match.end() :].strip()
    if remainder and PRICE_RE.fullmatch(remainder) is None:
        return None, index + 1
    index += 1

    if remainder:
        buy_price = remainder
    else:
        if index >= len(body):
            return None, index
        buy_price = body[index]
        index += 1

    if index + 3 >= len(body):
        return None, index
    current_price = body[index]
    value = body[index + 1]
    performance_since_buy = body[index + 2]
    stop = body[index + 3]
    index += 4

    if not PRICE_RE.search(buy_price):
        return None, index
    if not PRICE_RE.search(current_price):
        return None, index
    if not PRICE_RE.search(value):
        return None, index
    if not PERCENT_RE.match(performance_since_buy):
        return None, index

    return (
        {
            "quantity": quantity,
            "buy_date": buy_date,
            "buy_price": buy_price,
            "current_price": current_price,
            "value": value,
            "performance_since_buy": performance_since_buy,
            "stop": "" if _is_dash(stop) else stop,
        },
        index,
    )


def _next_wkn_index(lines: Sequence[str], start_index: int) -> int | None:
    for index in range(start_index, len(lines)):
        if WKN_RE.match(lines[index]):
            return index
    return None


def _looks_like_depot_page(lines: Sequence[str]) -> bool:
    return (
        "AKTIONÄR-Depot" in lines
        and "Aktie/Derivat" in lines
        and "Durchgeführte Transaktionen" in lines
    )


def _clean_line(line: str) -> str:
    cleaned = line.replace("\u2009", " ").replace("\u202f", " ").replace("\u2003", " ")
    cleaned = cleaned.replace("\ufeff", "").replace("\b", "")
    cleaned = re.sub(r"(?<=\d)\s*€", " EUR", cleaned)
    cleaned = " ".join(cleaned.split())
    return cleaned


def _is_dash(value: str) -> bool:
    return value in {"-", "–"}


def _issue_id_from_filename(pdf_path: Path) -> str:
    match = re.match(r"DA_(?P<year>20\d{2})_(?P<week>\d{2})", pdf_path.stem)
    if match:
        return f"{match.group('year')}-W{match.group('week')}"
    return pdf_path.stem
