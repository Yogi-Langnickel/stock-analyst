"""Local extraction for derivative overview table rows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Sequence

from stock_analyst.extraction import RawTextExtractor, extract_pdf_text
from stock_analyst.schemas import ReviewStatus


WKN_RE = re.compile(r"^[A-Z0-9]{6}$")
ISSUE_RE = re.compile(r"^\d{2}/\d{2}\s*$")
DATE_RE = re.compile(r"^\d{2}\.\d{2}\.\d{2}$")
PRICE_RE = re.compile(r"^(?:\d+(?:\.\d{3})*,\d+|\d+,\d+)\s*(?:EUR|USD|HKD)$")
PERCENT_RE = re.compile(r"^[+-]?\d+(?:,\d+)?\s*%$")
RATIO_RE = re.compile(r"^\d+(?:,\d+)?$")
TYPE_WORDS = {
    "Call",
    "Put",
    "Zertifikat",
    "Discount-Call",
    "Discount-Put",
    "Index-Zertifikat",
    "Mini-Long",
    "Mini-Short",
    "Turbo-Call",
    "Turbo-Long",
    "Turbo-Short",
}


@dataclass(frozen=True)
class DerivativeOverviewRow:
    issue_id: str
    page: int
    underlying: str
    product: str
    direction: str
    wkn: str
    issuer: str
    ratio: str
    strike_cap: str
    omega_hebel: str
    runtime: str
    entry_price: str = ""
    current_price: str = ""
    performance_since_recommendation: str = ""
    target: str = ""
    stop: str = ""
    recommendation: str = ""
    metrics_page: int | None = None
    review_status: ReviewStatus = ReviewStatus.NEEDS_REVIEW

    @property
    def source_pages(self) -> tuple[int, ...]:
        if self.metrics_page is None or self.metrics_page == self.page:
            return (self.page,)
        return (self.page, self.metrics_page)

    def to_dict(self) -> dict[str, object]:
        return {
            "issueId": self.issue_id,
            "page": self.page,
            "underlying": self.underlying,
            "product": self.product,
            "direction": self.direction,
            "wkn": self.wkn,
            "issuer": self.issuer,
            "ratio": self.ratio,
            "strikeCap": self.strike_cap,
            "omegaHebel": self.omega_hebel,
            "runtime": self.runtime,
            "entryPrice": self.entry_price,
            "currentPrice": self.current_price,
            "performanceSinceRecommendation": self.performance_since_recommendation,
            "target": self.target,
            "stop": self.stop,
            "recommendation": self.recommendation,
            "metricsPage": self.metrics_page,
            "sourcePages": list(self.source_pages),
            "reviewStatus": self.review_status.value,
        }


@dataclass(frozen=True)
class DerivativeOverviewExtraction:
    issue_id: str
    pdf_path: Path
    page_count: int
    external_services_enabled: bool
    rows: tuple[DerivativeOverviewRow, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "issueId": self.issue_id,
            "pdfPath": str(self.pdf_path),
            "pageCount": self.page_count,
            "externalServicesEnabled": self.external_services_enabled,
            "rows": [row.to_dict() for row in self.rows],
        }


def build_derivative_overview_from_pdf(
    pdf_path: Path,
    *,
    issue_id: str | None = None,
    extractor: RawTextExtractor | None = None,
    min_embedded_chars: int = 40,
) -> DerivativeOverviewExtraction:
    extraction = extract_pdf_text(
        pdf_path,
        extractor=extractor,
        min_embedded_chars=min_embedded_chars,
    )
    resolved_issue_id = issue_id or _issue_id_from_filename(pdf_path)
    rows = extract_derivative_overview_rows_from_page_lines(
        tuple((page.page_number, page.text.splitlines()) for page in extraction.pages),
        issue_id=resolved_issue_id,
    )
    return DerivativeOverviewExtraction(
        issue_id=resolved_issue_id,
        pdf_path=pdf_path,
        page_count=extraction.page_count,
        external_services_enabled=False,
        rows=rows,
    )


def extract_derivative_overview_rows_from_page_lines(
    pages: Sequence[tuple[int, Sequence[str]]],
    *,
    issue_id: str,
) -> tuple[DerivativeOverviewRow, ...]:
    base_tables: list[tuple[int, tuple[DerivativeOverviewRow, ...]]] = []
    metrics_tables: list[tuple[int, tuple[_DerivativeMetrics, ...]]] = []
    for page_number, lines in pages:
        normalized = tuple(_clean_line(line) for line in lines if _clean_line(line))
        if _looks_like_base_table(normalized):
            base_tables.append(
                (
                    page_number,
                    _extract_base_rows(
                        normalized,
                        issue_id=issue_id,
                        page_number=page_number,
                    ),
                )
            )
        if _looks_like_metrics_table(normalized):
            metrics_tables.append(
                (page_number, _extract_metrics_rows(normalized))
            )

    base_candidates = {
        base_index: tuple(
            metrics_index
            for metrics_index, (metrics_page, metrics_rows) in enumerate(metrics_tables)
            if abs(metrics_page - base_page) == 1
            and len(metrics_rows) == len(base_rows)
        )
        for base_index, (base_page, base_rows) in enumerate(base_tables)
    }
    metrics_candidates = {
        metrics_index: tuple(
            base_index
            for base_index, metrics_indexes in base_candidates.items()
            if metrics_index in metrics_indexes
        )
        for metrics_index in range(len(metrics_tables))
    }

    extracted: list[DerivativeOverviewRow] = []
    for base_index, (_, base_rows) in enumerate(base_tables):
        candidates = base_candidates[base_index]
        if len(candidates) != 1 or len(metrics_candidates[candidates[0]]) != 1:
            extracted.extend(base_rows)
            continue
        metrics_page, metrics_rows = metrics_tables[candidates[0]]
        extracted.extend(
            _apply_metrics(row, row_metrics, metrics_page=metrics_page)
            for row, row_metrics in zip(base_rows, metrics_rows)
        )
    return tuple(extracted)


@dataclass(frozen=True)
class _DerivativeMetrics:
    entry_price: str = ""
    current_price: str = ""
    performance: str = ""
    target: str = ""
    stop: str = ""
    recommendation: str = ""


def _extract_base_rows(
    lines: Sequence[str],
    *,
    issue_id: str,
    page_number: int,
) -> tuple[DerivativeOverviewRow, ...]:
    try:
        start = lines.index("Basiswert") + 1
        end = lines.index("Derivate-Tipps im Rückblick", start)
    except ValueError:
        return ()

    body = tuple(
        line
        for line in lines[start:end]
        if line
        not in {
            "WKN",
            "Emittent",
            "Typ",
            "Ratio",
            "Strike /",
            "Cap",
            "Laufzeit",
            "Hebel /",
            "Omega",
        }
    )
    rows: list[DerivativeOverviewRow] = []

    cursor = 0
    while cursor < len(body):
        wkn_index = _next_wkn_index(body, cursor)
        if wkn_index is None:
            break
        next_wkn_index = _next_wkn_index(body, wkn_index + 1) or len(body)
        underlying = " ".join(body[cursor:wkn_index]).strip()
        tail = body[wkn_index + 1 : next_wkn_index]
        parsed = _parse_base_tail(tail)
        if not underlying or parsed is None:
            cursor = wkn_index + 1
            continue
        rows.append(
            DerivativeOverviewRow(
                issue_id=issue_id,
                page=page_number,
                underlying=underlying,
                product=underlying,
                direction=str(parsed["direction"]),
                wkn=body[wkn_index],
                issuer=str(parsed["issuer"]),
                ratio=str(parsed["ratio"]),
                strike_cap=str(parsed["strike_cap"]),
                omega_hebel=str(parsed["omega_hebel"]),
                runtime=str(parsed["runtime"]),
            )
        )
        cursor = wkn_index + 1 + int(parsed["consumed"])

    return tuple(rows)


def _next_wkn_index(lines: Sequence[str], start_index: int) -> int | None:
    for index in range(start_index, len(lines)):
        if WKN_RE.match(lines[index]):
            return index
    return None


def _parse_base_tail(tail: Sequence[str]) -> dict[str, Any] | None:
    direction_match = _first_direction_match(tail)
    if direction_match is None:
        return None
    direction_index, direction, direction_consumed = direction_match
    issuer = " ".join(tail[:direction_index]).strip()
    index = direction_index + direction_consumed
    if index >= len(tail) or not RATIO_RE.match(tail[index]):
        return None
    ratio = tail[index]
    index += 1
    if index >= len(tail):
        return None
    strike_cap = tail[index]
    index += 1
    if index >= len(tail):
        return None
    runtime = tail[index]
    index += 1
    if index < len(tail) and _looks_like_duration(tail[index]):
        runtime = f"{runtime} ({tail[index]})"
        index += 1
    omega_hebel = ""
    if index < len(tail) and (_is_dash(tail[index]) or RATIO_RE.match(tail[index])):
        omega_hebel = tail[index]
        index += 1
    return {
        "issuer": issuer,
        "direction": direction,
        "ratio": ratio,
        "strike_cap": strike_cap,
        "runtime": runtime,
        "omega_hebel": "" if _is_dash(omega_hebel) else omega_hebel,
        "consumed": index,
    }


def _first_direction_match(lines: Sequence[str]) -> tuple[int, str, int] | None:
    for index in range(len(lines)):
        candidate = lines[index]
        if candidate in TYPE_WORDS:
            return index, candidate, 1
        if candidate.endswith("-") and index + 1 < len(lines):
            joined = f"{candidate}{lines[index + 1]}"
            if joined in TYPE_WORDS:
                return index, joined, 2
    return None


def _extract_metrics_rows(lines: Sequence[str]) -> tuple[_DerivativeMetrics, ...]:
    try:
        start = lines.index("Empfehlung") + 1
    except ValueError:
        return ()

    rows: list[_DerivativeMetrics] = []
    index = start
    while index + 3 < len(lines):
        if not ISSUE_RE.match(lines[index]) or not DATE_RE.match(lines[index + 1]):
            index += 1
            continue
        row_start = index + 2
        row_end = _next_metrics_row_index(lines, row_start)
        tokens = _expanded_metrics_tokens(lines[row_start:row_end])

        token_index = 0
        entry_price, token_index = _next_price_or_status(tokens, token_index)
        current_price, token_index = _next_price_or_status(tokens, token_index)
        performance = ""
        if token_index < len(tokens) and PERCENT_RE.match(tokens[token_index]):
            performance = tokens[token_index]
            token_index += 1
        target, token_index = _next_price_or_status(tokens, token_index)
        stop, token_index = _next_price_or_status(tokens, token_index)
        while token_index < len(tokens) and _is_dot_rating(tokens[token_index]):
            token_index += 1
        recommendation_parts: list[str] = []
        while token_index < len(tokens):
            if (
                tokens[token_index].startswith("*Verkaufskurs")
                or tokens[token_index] == "in Hongkong-Dollar"
            ):
                return tuple(rows)
            recommendation_parts.append(tokens[token_index])
            token_index += 1
            if len(recommendation_parts) >= 3:
                break
        rows.append(
            _DerivativeMetrics(
                entry_price=entry_price,
                current_price=current_price,
                performance=performance,
                target="" if target in {"Verkauft", "Verkaufen"} else target,
                stop="" if stop in {"Verkauft", "Verkaufen"} else stop,
                recommendation=" ".join(recommendation_parts).strip(),
            )
        )
        index = row_end
    return tuple(rows)


def _next_price_or_status(lines: Sequence[str], index: int) -> tuple[str, int]:
    if index >= len(lines):
        return "", index
    current = lines[index]
    if current in {"Verkauft", "Verkaufen"}:
        return current, index + 1
    if _is_dot_rating(current) or PERCENT_RE.match(current):
        return "", index
    prices = _prices_from_line(current)
    if len(prices) >= 2:
        return prices[0], index + 1
    if prices:
        return prices[0], index + 1
    return current, index + 1


def _next_metrics_row_index(lines: Sequence[str], start_index: int) -> int:
    index = start_index
    while index < len(lines):
        if ISSUE_RE.match(lines[index]):
            return index
        if lines[index].startswith("*Verkaufskurs") or lines[index] == "in Hongkong-Dollar":
            return index
        index += 1
    return index


def _expanded_metrics_tokens(lines: Sequence[str]) -> tuple[str, ...]:
    tokens: list[str] = []
    for line in lines:
        matches = _prices_from_line(line)
        if matches:
            tokens.extend(matches)
            remainder = line
            for match in matches:
                remainder = remainder.replace(match, " ", 1)
            remainder = " ".join(remainder.split())
            if PERCENT_RE.match(remainder) or _is_dot_rating(remainder):
                tokens.append(remainder)
            continue
        tokens.append(line)
    return tuple(tokens)


def _prices_from_line(line: str) -> tuple[str, ...]:
    return tuple(
        match.group(0).strip()
        for match in re.finditer(r"\d+(?:\.\d{3})*,\d+\s*(?:EUR|USD|HKD)\*?", line)
    )


def _apply_metrics(
    row: DerivativeOverviewRow,
    metrics: _DerivativeMetrics,
    *,
    metrics_page: int,
) -> DerivativeOverviewRow:
    return DerivativeOverviewRow(
        issue_id=row.issue_id,
        page=row.page,
        underlying=row.underlying,
        product=row.product,
        direction=row.direction,
        wkn=row.wkn,
        issuer=row.issuer,
        ratio=row.ratio,
        strike_cap=row.strike_cap,
        omega_hebel=row.omega_hebel,
        runtime=row.runtime,
        entry_price=metrics.entry_price,
        current_price=metrics.current_price,
        performance_since_recommendation=metrics.performance,
        target=metrics.target,
        stop=metrics.stop,
        recommendation=metrics.recommendation,
        metrics_page=metrics_page,
    )


def _looks_like_base_table(lines: Sequence[str]) -> bool:
    return "Basiswert" in lines and "Derivate-Tipps im Rückblick" in lines


def _looks_like_metrics_table(lines: Sequence[str]) -> bool:
    return "Empfehlung" in lines and "Empf." in lines


def _looks_like_duration(value: str) -> bool:
    return "monat" in value.lower() or "jahr" in value.lower()


def _is_dash(value: str) -> bool:
    return value in {"-", "–"}


def _is_dot_rating(value: str) -> bool:
    return bool(value) and set(value) == {"•"}


def _clean_line(line: str) -> str:
    cleaned = line.replace("\u2009", " ").replace("\u202f", " ").replace("\u2003", " ")
    cleaned = cleaned.replace("\ufeff", "").replace("\b", "")
    cleaned = re.sub(r"(?<=\d)\s*€", " EUR", cleaned)
    cleaned = re.sub(r"(?<=\d)\s*\$", " USD", cleaned)
    cleaned = cleaned.replace("€", "EUR").replace("$", "USD")
    cleaned = " ".join(cleaned.split())
    return cleaned


def _issue_id_from_filename(pdf_path: Path) -> str:
    match = re.match(r"DA_(?P<year>20\d{2})_(?P<week>\d{2})", pdf_path.stem)
    if match:
        return f"{match.group('year')}-W{match.group('week')}"
    return pdf_path.stem
