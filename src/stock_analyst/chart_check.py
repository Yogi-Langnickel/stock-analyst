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
    rows: list[ChartCheckRow] = []
    for index, instrument in enumerate(instruments):
        signal_parts = [
            instrument["sector"],
            bullets[index] if index < len(bullets) else "",
        ]
        rows.append(
            ChartCheckRow(
                issue_id=issue_id,
                page=page_number,
                instrument=instrument["instrument"],
                wkn=instrument["wkn"],
                sector=instrument["sector"],
                signal="; ".join(part for part in signal_parts if part),
            )
        )

    return tuple(rows)


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
