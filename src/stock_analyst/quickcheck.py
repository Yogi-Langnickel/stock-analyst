"""Parser for the magazine's Aktien im Quick-Check table."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Sequence

from stock_analyst.schemas import ReviewStatus


WKN_RE = re.compile(r"^[A-Z0-9]{6}$")
MONEY_RE = re.compile(
    r"^(?:verkauft|[+-]?\d+(?:,\d+)?\s+(?:EUR|USD)\*?)(?:\s*!?)?$"
)
MONEY_TOKEN_RE = re.compile(
    r"(?:verkauft|[+-]?\d+(?:,\d+)?\s+(?:EUR|USD)\*?\s*!?)"
)
ISSUE_RE = re.compile(r"^\d{2}/\d{2}$")
PERCENT_RE = re.compile(r"^[+-]?\d+(?:,\d+)?\s*%$")
EURO_SUFFIX_RE = re.compile(r"(?<=\d)\s*€")


@dataclass(frozen=True)
class QuickcheckRow:
    issue_id: str
    page: int
    instrument: str
    wkn: str
    current_price: str
    recommendation_price: str
    recommended_issue: str
    performance_since_recommendation: str
    target: str
    stop: str
    comment: str
    review_status: ReviewStatus = ReviewStatus.NEEDS_REVIEW

    def to_dict(self) -> dict[str, object]:
        return {
            "issueId": self.issue_id,
            "page": self.page,
            "instrument": self.instrument,
            "wkn": self.wkn,
            "currentPrice": self.current_price,
            "recommendationPrice": self.recommendation_price,
            "recommendedIssue": self.recommended_issue,
            "performanceSinceRecommendation": self.performance_since_recommendation,
            "target": self.target,
            "stop": self.stop,
            "comment": self.comment,
            "reviewStatus": self.review_status.value,
        }


def extract_quickcheck_rows_from_page_lines(
    pages: Sequence[tuple[int, Sequence[str]]],
    *,
    issue_id: str,
) -> tuple[QuickcheckRow, ...]:
    rows: list[QuickcheckRow] = []
    for page_number, lines in pages:
        rows.extend(
            extract_quickcheck_rows_from_lines(
                lines,
                issue_id=issue_id,
                page_number=page_number,
            )
        )
    return tuple(rows)


def extract_quickcheck_rows_from_lines(
    lines: Sequence[str],
    *,
    issue_id: str,
    page_number: int,
) -> tuple[QuickcheckRow, ...]:
    normalized_lines = [_clean_line(line) for line in lines if _clean_line(line)]
    if "Aktien im Quick-Check" not in normalized_lines:
        return ()

    title_index = normalized_lines.index("Aktien im Quick-Check")
    header_index = _index_or_none(normalized_lines, "Unternehmen", start=title_index)
    if header_index is None:
        return ()

    summary_rows = _parse_summary_rows(normalized_lines[:title_index])
    detail_rows = _parse_detail_rows(normalized_lines[title_index + 1 : header_index])
    row_count = min(len(summary_rows), len(detail_rows))

    rows: list[QuickcheckRow] = []
    for index in range(row_count):
        summary = summary_rows[index]
        detail = detail_rows[index]
        rows.append(
            QuickcheckRow(
                issue_id=issue_id,
                page=page_number,
                instrument=summary["instrument"],
                wkn=summary["wkn"],
                current_price=summary["current_price"],
                recommendation_price=summary["recommendation_price"],
                recommended_issue=summary["recommended_issue"],
                performance_since_recommendation=summary["performance"],
                target=detail["target"],
                stop=detail["stop"],
                comment=detail["comment"],
            )
        )

    return tuple(rows)


def _parse_summary_rows(lines: Sequence[str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    index = 0
    while index < len(lines):
        wkn_index = _next_wkn_index(lines, index)
        if wkn_index is None:
            break
        if wkn_index == index:
            index += 1
            continue

        name = " ".join(lines[index:wkn_index])
        if wkn_index + 3 >= len(lines):
            break
        price_pair = _consume_money_pair(lines, wkn_index + 1)
        if price_pair is None:
            index = wkn_index + 1
            continue
        current_price, recommendation_price, next_index = price_pair
        if next_index + 1 >= len(lines):
            break
        recommended_issue = lines[next_index]
        performance = lines[next_index + 1]
        if not ISSUE_RE.match(recommended_issue) or not PERCENT_RE.match(performance):
            index = wkn_index + 1
            continue

        rows.append(
            {
                "instrument": name,
                "wkn": lines[wkn_index],
                "current_price": current_price,
                "recommendation_price": recommendation_price,
                "recommended_issue": recommended_issue,
                "performance": performance,
            }
        )
        index = next_index + 2
    return rows


def _parse_detail_rows(lines: Sequence[str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    index = 0
    while index < len(lines):
        money_pair = _consume_money_pair(lines, index)
        if money_pair is None:
            index += 1
            continue
        target, stop, index = money_pair

        comment_lines: list[str] = []
        while index < len(lines) and _consume_money_pair(lines, index) is None:
            comment_lines.append(lines[index])
            index += 1

        rows.append(
            {
                "target": target,
                "stop": stop,
                "comment": " ".join(comment_lines),
            }
        )
    return rows


def _consume_money_pair(lines: Sequence[str], index: int) -> tuple[str, str, int] | None:
    if index >= len(lines):
        return None

    first_line_values = _money_values_from_line(lines[index])
    if len(first_line_values) >= 2:
        return first_line_values[0], first_line_values[1], index + 1

    if len(first_line_values) == 1 and index + 1 < len(lines):
        second_line_values = _money_values_from_line(lines[index + 1])
        if second_line_values:
            return first_line_values[0], second_line_values[0], index + 2

    return None


def _money_values_from_line(line: str) -> list[str]:
    if line == "verkauft":
        return [line]
    values = [value.strip() for value in MONEY_TOKEN_RE.findall(line)]
    return [value for value in values if MONEY_RE.match(value)]


def _next_wkn_index(lines: Sequence[str], start: int) -> int | None:
    for index in range(start, len(lines)):
        if WKN_RE.match(lines[index]):
            return index
    return None


def _index_or_none(lines: Sequence[str], value: str, *, start: int = 0) -> int | None:
    try:
        return lines.index(value, start)
    except ValueError:
        return None


def _clean_line(line: str) -> str:
    cleaned = line.replace("\u2009", " ").replace("\u202f", " ").replace("\u2003", " ")
    cleaned = EURO_SUFFIX_RE.sub(" EUR", cleaned)
    cleaned = cleaned.replace("€", "EUR").replace("$", "USD")
    cleaned = " ".join(cleaned.split())
    return cleaned
