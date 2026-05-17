"""Parser for the magazine's Chart-Check pages."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Sequence

from stock_analyst.schemas import ReviewStatus


WKN_RE = re.compile(r"^[A-Z0-9]{6}$")
TABLE_LABELS = {
    "Ziel",
    "Akt. Kurs",
    "52-W.- Hoch",
    "52-W.- Tief",
    "Perform. 1 Jahr",
    "Perform. 5 Jahre",
    "Weitere Infos unter",
    "Stopp",
    "Empf.- Kurs",
    "Empfehlung in Ausgabe",
    "Perform. seit Empf.",
    "Dividenden- rendite",
    "Nächster Termin",
}


@dataclass(frozen=True)
class ChartCheckRow:
    issue_id: str
    page: int
    instrument: str
    wkn: str
    sector: str
    signal: str
    current_price: str = ""
    recommendation_price: str = ""
    recommended_issue: str = ""
    performance_since_recommendation: str = ""
    target: str = ""
    stop: str = ""
    dividend_yield: str = ""
    next_report_date: str = ""
    high_52w: str = ""
    low_52w: str = ""
    performance_1y: str = ""
    performance_5y: str = ""
    trend: str = "needs_review"
    support: str = ""
    resistance: str = ""
    review_status: ReviewStatus = ReviewStatus.NEEDS_REVIEW

    def to_dict(self) -> dict[str, object]:
        return {
            "issueId": self.issue_id,
            "page": self.page,
            "instrument": self.instrument,
            "wkn": self.wkn,
            "sector": self.sector,
            "signal": self.signal,
            "currentPrice": self.current_price,
            "recommendationPrice": self.recommendation_price,
            "recommendedIssue": self.recommended_issue,
            "performanceSinceRecommendation": self.performance_since_recommendation,
            "target": self.target,
            "stop": self.stop,
            "dividendYield": self.dividend_yield,
            "nextReportDate": self.next_report_date,
            "high52w": self.high_52w,
            "low52w": self.low_52w,
            "performance1y": self.performance_1y,
            "performance5y": self.performance_5y,
            "trend": self.trend,
            "support": self.support,
            "resistance": self.resistance,
            "reviewStatus": self.review_status.value,
        }


def extract_chart_check_rows_from_page_lines(
    pages: Sequence[tuple[int, Sequence[str]]],
    *,
    issue_id: str,
) -> tuple[ChartCheckRow, ...]:
    rows: list[ChartCheckRow] = []
    for page_number, lines in pages:
        rows.extend(
            extract_chart_check_rows_from_lines(
                lines,
                issue_id=issue_id,
                page_number=page_number,
            )
        )
    return tuple(rows)


def extract_chart_check_rows_from_lines(
    lines: Sequence[str],
    *,
    issue_id: str,
    page_number: int,
) -> tuple[ChartCheckRow, ...]:
    normalized_lines = [_clean_line(line) for line in lines if _clean_line(line)]
    if "Chart-Check" not in normalized_lines:
        return ()

    instruments = _extract_instruments(normalized_lines)
    if not instruments:
        return ()

    bullets = _extract_bullet_summaries(normalized_lines)
    table_fields = _extract_table_fields(normalized_lines, row_count=len(instruments))
    rows: list[ChartCheckRow] = []
    for index, instrument in enumerate(instruments):
        signal_parts = [
            instrument["sector"],
            bullets[index] if index < len(bullets) else "",
        ]
        fields = table_fields[index] if index < len(table_fields) else {}
        rows.append(
            ChartCheckRow(
                issue_id=issue_id,
                page=page_number,
                instrument=instrument["instrument"],
                wkn=instrument["wkn"],
                sector=instrument["sector"],
                signal="; ".join(part for part in signal_parts if part),
                current_price=fields.get("current_price", ""),
                recommendation_price=fields.get("recommendation_price", ""),
                recommended_issue=fields.get("recommended_issue", ""),
                performance_since_recommendation=fields.get(
                    "performance_since_recommendation", ""
                ),
                target=fields.get("target", ""),
                stop=fields.get("stop", ""),
                dividend_yield=fields.get("dividend_yield", ""),
                next_report_date=fields.get("next_report_date", ""),
                high_52w=fields.get("high_52w", ""),
                low_52w=fields.get("low_52w", ""),
                performance_1y=fields.get("performance_1y", ""),
                performance_5y=fields.get("performance_5y", ""),
            )
        )

    return tuple(rows)


def _extract_table_fields(
    lines: Sequence[str],
    *,
    row_count: int,
) -> list[dict[str, str]]:
    if row_count <= 0:
        return []
    try:
        start = _last_chart_table_label_index(lines) + 1
    except ValueError:
        return [{} for _ in range(row_count)]

    values: list[str] = []
    for line in lines[start:]:
        if _is_dot_rating(line) or line.startswith("•"):
            break
        if line.startswith("von "):
            break
        values.append(_normalize_money(line))

    groups: list[list[str]] = []
    index = 0
    for _ in range(12):
        if index + row_count > len(values):
            break
        groups.append(values[index : index + row_count])
        index += row_count

    rows = [dict() for _ in range(row_count)]
    mapping = (
        ("target", 0),
        ("stop", 1),
        ("current_price", 2),
        ("recommendation_price", 3),
        ("high_52w", 4),
        ("low_52w", 5),
        ("performance_1y", 6),
        ("performance_5y", 7),
        ("dividend_yield", 8),
    )
    for field_name, group_index in mapping:
        if group_index >= len(groups):
            continue
        for row_index, value in enumerate(groups[group_index]):
            rows[row_index][field_name] = value

    if len(groups) > 10:
        for row_index, value in enumerate(groups[10]):
            rows[row_index]["next_report_date"] = value
    if len(groups) > 11:
        for row_index, value in enumerate(groups[11]):
            rows[row_index]["performance_since_recommendation"] = value

    remaining = values[index:]
    for row_index in range(row_count):
        issue_index = row_index * 2
        if issue_index + 1 < len(remaining):
            issue = remaining[issue_index]
            issue_date = remaining[issue_index + 1]
            if re.match(r"^\d{2}/\d{2}$", issue):
                rows[row_index]["recommended_issue"] = f"{issue} {issue_date}"

    return rows


def _extract_instruments(lines: Sequence[str]) -> list[dict[str, str]]:
    wkn_indexes = [index for index, line in enumerate(lines) if WKN_RE.match(line)]
    instruments: list[dict[str, str]] = []
    for wkn_index in wkn_indexes:
        if wkn_index == 0:
            continue
        name = lines[wkn_index - 1]
        if _looks_like_table_label(name) or _looks_like_numeric_chart_label(name):
            continue
        instruments.append(
            {
                "instrument": name,
                "wkn": lines[wkn_index],
                "sector": "",
                "wkn_index": str(wkn_index),
            }
        )

    if not instruments:
        return []

    last_wkn_index = int(instruments[-1]["wkn_index"])
    sector_lines: list[str] = []
    for line in lines[last_wkn_index + 1 :]:
        if _looks_like_table_label(line) or _looks_like_numeric_chart_label(line):
            break
        if WKN_RE.match(line):
            continue
        sector_lines.append(line)
        if len(sector_lines) >= len(instruments):
            break

    for index, sector in enumerate(sector_lines):
        instruments[index]["sector"] = sector

    for instrument in instruments:
        instrument.pop("wkn_index", None)

    return instruments


def _extract_bullet_summaries(lines: Sequence[str]) -> list[str]:
    summaries: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.startswith("•"):
            index += 1
            continue

        summary_lines = [_strip_bullet(line)]
        index += 1
        while index < len(lines):
            next_line = lines[index]
            if next_line.startswith("•") or next_line.startswith("von "):
                break
            if _looks_like_numeric_chart_label(next_line):
                break
            summary_lines.append(next_line)
            index += 1
        summaries.append(_compact_summary(" ".join(summary_lines)))
    return summaries


def _looks_like_table_label(line: str) -> bool:
    return line in TABLE_LABELS


def _looks_like_numeric_chart_label(line: str) -> bool:
    if re.match(r"^\d+(?:,\d+)?(?:\s*[€%])?$", line):
        return True
    return line in {"A", "J", "O", "GD50"} or line.startswith("in ")


def _is_dot_rating(value: str) -> bool:
    return bool(value) and set(value) == {"•"}


def _last_index(lines: Sequence[str], value: str) -> int:
    for index in range(len(lines) - 1, -1, -1):
        if lines[index] == value:
            return index
    raise ValueError(value)


def _last_chart_table_label_index(lines: Sequence[str]) -> int:
    for index in range(len(lines) - 1, 0, -1):
        if lines[index] == "Termin" and lines[index - 1] == "Nächster":
            return index
        if lines[index] == "Nächster Termin":
            return index
    raise ValueError("Nächster Termin")


def _normalize_money(value: str) -> str:
    cleaned = value.replace("€", "EUR").replace("$", "USD")
    cleaned = re.sub(r"(?<=\d)\s*EUR", " EUR", cleaned)
    cleaned = re.sub(r"(?<=\d)\s*USD", " USD", cleaned)
    return " ".join(cleaned.split())


def _strip_bullet(line: str) -> str:
    return line.lstrip("•").strip()


def _compact_summary(value: str, max_length: int = 320) -> str:
    compacted = " ".join(value.split())
    if len(compacted) <= max_length:
        return compacted
    return compacted[: max_length - 1].rstrip() + "…"


def _clean_line(line: str) -> str:
    cleaned = line.replace("\u2009", " ").replace("\u202f", " ").replace("\u2003", " ")
    cleaned = cleaned.replace(" ", " ").replace(" ", " ")
    return " ".join(cleaned.split())
