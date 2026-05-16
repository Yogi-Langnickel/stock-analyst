"""Local rule-based extraction for labelled magazine recommendation cards."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Sequence

from stock_analyst.extraction import RawTextExtractor, extract_pdf_text
from stock_analyst.schemas import InstrumentType, ReviewStatus


LABEL_ALIASES = {
    "Akt. Kurs": "current_price",
    "WKN": "wkn",
    "Ziel": "target",
    "Stopp": "stop",
    "Markt-kapitalisierung": "market_cap",
    "Marktkapitalisierung": "market_cap",
    "Performance seit Erstempfehlung": "performance_since_recommendation",
    "Empfohlen in Ausgabe": "recommended_issue",
    "Dividendenrendite": "dividend_yield",
    "KUV 26e": "kuv_26e",
    "KGV 26e": "kgv_26e",
    "Nächster Termin": "next_report_date",
    "Kurs Basiswert": "underlying_price",
    "Basispreis": "base_price",
    "Omega / Hebel": "omega_hebel",
    "Laufzeit": "runtime",
}

CARD_END_MARKERS = {
    "Quelle:",
    "Foto:",
    "Weitere Informationen",
}

EURO_SUFFIX_RE = re.compile(r"(?<=\d)\s*€")
USD_SUFFIX_RE = re.compile(r"(?<=\d)\s*\$")
ISSUE_DATE_RE = re.compile(r"\b\d{2}/\d{4}\b")
WKN_RE = re.compile(r"^[A-Z0-9]{6}$")
PERCENT_RE = re.compile(r"^[+-]?\d+(?:,\d+)?\s*%$")
YEAR_RE = re.compile(r"^20\d{2}e?$")
DECIMAL_VALUE_RE = re.compile(r"^\d+(?:,\d+)?\*?$")


@dataclass(frozen=True)
class RecommendationCard:
    issue_id: str
    page: int
    instrument_name: str
    instrument_type: InstrumentType
    wkn: str | None
    current_price: str | None
    target: str | None
    stop: str | None
    chance: int | None
    risk: int | None
    recommendation_status: str | None
    market_cap: str | None = None
    performance_since_recommendation: str | None = None
    recommended_issue: str | None = None
    dividend_yield: str | None = None
    dividend_per_share_trend: str | None = None
    kuv_26e: str | None = None
    kgv_26e: str | None = None
    next_report_date: str | None = None
    underlying_price: str | None = None
    base_price: str | None = None
    omega_hebel: str | None = None
    runtime: str | None = None
    review_status: ReviewStatus = ReviewStatus.NEEDS_REVIEW
    extraction_notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "issueId": self.issue_id,
            "page": self.page,
            "instrumentName": self.instrument_name,
            "instrumentType": self.instrument_type.value,
            "reviewStatus": self.review_status.value,
        }

        optional_fields = {
            "wkn": self.wkn,
            "currentPrice": self.current_price,
            "target": self.target,
            "stop": self.stop,
            "chance": self.chance,
            "risk": self.risk,
            "recommendationStatus": self.recommendation_status,
            "marketCap": self.market_cap,
            "performanceSinceRecommendation": self.performance_since_recommendation,
            "recommendedIssue": self.recommended_issue,
            "dividendYield": self.dividend_yield,
            "dividendPerShareTrend": self.dividend_per_share_trend,
            "kuv26e": self.kuv_26e,
            "kgv26e": self.kgv_26e,
            "nextReportDate": self.next_report_date,
            "underlyingPrice": self.underlying_price,
            "basePrice": self.base_price,
            "omegaHebel": self.omega_hebel,
            "runtime": self.runtime,
        }
        for key, value in optional_fields.items():
            if value is not None:
                result[key] = value
        if self.extraction_notes:
            result["extractionNotes"] = list(self.extraction_notes)

        return result


@dataclass(frozen=True)
class RecommendationCardExtraction:
    issue_id: str
    pdf_path: Path
    page_count: int
    external_services_enabled: bool
    cards: tuple[RecommendationCard, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "issueId": self.issue_id,
            "pdfPath": str(self.pdf_path),
            "pageCount": self.page_count,
            "externalServicesEnabled": self.external_services_enabled,
            "cards": [card.to_dict() for card in self.cards],
        }


def extract_recommendation_cards_from_pdf(
    pdf_path: Path,
    *,
    issue_id: str | None = None,
    extractor: RawTextExtractor | None = None,
    min_embedded_chars: int = 40,
) -> RecommendationCardExtraction:
    """Extract draft recommendation cards from embedded text only."""

    extraction = extract_pdf_text(
        pdf_path,
        extractor=extractor,
        min_embedded_chars=min_embedded_chars,
    )
    resolved_issue_id = issue_id or _issue_id_from_filename(pdf_path)
    cards: list[RecommendationCard] = []

    for page in extraction.pages:
        cards.extend(
            extract_recommendation_cards_from_lines(
                page.text.splitlines(),
                issue_id=resolved_issue_id,
                page_number=page.page_number,
            )
        )

    return RecommendationCardExtraction(
        issue_id=resolved_issue_id,
        pdf_path=pdf_path,
        page_count=extraction.page_count,
        external_services_enabled=False,
        cards=tuple(cards),
    )


def extract_recommendation_cards_from_lines(
    lines: Sequence[str],
    *,
    issue_id: str,
    page_number: int,
) -> tuple[RecommendationCard, ...]:
    """Extract card rows from page lines produced by local PDF text extraction."""

    normalized_lines = [_clean_line(line) for line in lines if _clean_line(line)]
    cards: list[RecommendationCard] = []
    index = 0
    while index < len(normalized_lines):
        line = normalized_lines[index]
        explicit_card_start = line in {"Aktie", "Derivat", "Zertifikat", "Option"}
        derivative_card_start = (
            _looks_like_derivative(line)
            and _line_at(normalized_lines, index + 1) == "WKN"
        )
        if explicit_card_start or derivative_card_start:
            card, next_index = _parse_labelled_card(
                normalized_lines,
                index,
                issue_id=issue_id,
                page_number=page_number,
            )
            if card is not None:
                cards.append(card)
                index = next_index
                continue
        index += 1

    return tuple(cards)


def _parse_labelled_card(
    lines: Sequence[str],
    start_index: int,
    *,
    issue_id: str,
    page_number: int,
) -> tuple[RecommendationCard | None, int]:
    raw_type = lines[start_index]
    name_index = start_index + 1
    if _looks_like_derivative(raw_type) and name_index < len(lines) and lines[name_index] == "WKN":
        raw_type = "Derivat"
        name_index = start_index

    if name_index >= len(lines):
        return None, start_index + 1

    instrument_name = lines[name_index]
    fields, next_index = _collect_fields(lines, name_index + 1)
    wkn = fields.get("wkn")
    if wkn is None or not WKN_RE.match(wkn):
        return None, start_index + 1

    notes: list[str] = []
    chance = _rating_from_dots(fields.get("chance"))
    risk = _rating_from_dots(fields.get("risk"))
    if chance is None:
        notes.append("chance_rating_needs_review")
    if risk is None:
        notes.append("risk_rating_needs_review")

    instrument_type = (
        InstrumentType.DERIVATIVE
        if raw_type in {"Derivat", "Zertifikat", "Option"}
        or _looks_like_derivative(instrument_name)
        else InstrumentType.STOCK
    )
    recommendation_status = "new_recommendation" if "new_recommendation" in fields else None
    if "recommended_issue" in fields or "performance_since_recommendation" in fields:
        recommendation_status = recommendation_status or "follow_up"

    return (
        RecommendationCard(
            issue_id=issue_id,
            page=page_number,
            instrument_name=instrument_name,
            instrument_type=instrument_type,
            wkn=wkn,
            current_price=fields.get("current_price"),
            target=fields.get("target"),
            stop=fields.get("stop"),
            chance=chance,
            risk=risk,
            recommendation_status=recommendation_status,
            market_cap=fields.get("market_cap"),
            performance_since_recommendation=fields.get("performance_since_recommendation"),
            recommended_issue=fields.get("recommended_issue"),
            dividend_yield=fields.get("dividend_yield"),
            dividend_per_share_trend=fields.get("dividend_per_share_trend"),
            kuv_26e=fields.get("kuv_26e"),
            kgv_26e=fields.get("kgv_26e"),
            next_report_date=fields.get("next_report_date"),
            underlying_price=fields.get("underlying_price"),
            base_price=fields.get("base_price"),
            omega_hebel=fields.get("omega_hebel"),
            runtime=fields.get("runtime"),
            extraction_notes=tuple(notes),
        ),
        next_index,
    )


def _collect_fields(lines: Sequence[str], start_index: int) -> tuple[dict[str, str], int]:
    fields: dict[str, str] = {}
    chance_risk_pending: list[str] = []
    index = start_index

    while index < len(lines):
        line = lines[index]
        if line in {"Aktie", "Derivat", "Zertifikat", "Option"} and (
            "wkn" in fields or "current_price" in fields
        ):
            break
        if any(line.startswith(marker) for marker in CARD_END_MARKERS):
            break

        combined, consumed = _combined_label(lines, index)
        if combined in {"Chance", "Risiko"}:
            chance_risk_pending.append("chance" if combined == "Chance" else "risk")
            index += consumed
            continue

        if _is_dot_rating(line) and chance_risk_pending:
            fields[chance_risk_pending.pop(0)] = line
            index += 1
            continue

        key = LABEL_ALIASES.get(combined)
        if key is not None:
            if key == "performance_since_recommendation":
                value, recommended_issue, next_index = _performance_values_after_label(
                    lines, index + consumed
                )
                if value is not None:
                    fields[key] = value
                if recommended_issue is not None:
                    fields["recommended_issue"] = recommended_issue
                index = next_index
                continue

            value, next_index = _value_after_label(lines, index + consumed, key)
            if value is not None:
                fields[key] = value
            index = next_index
            continue

        if combined == "Neuempfehlung":
            fields["new_recommendation"] = "Neuempfehlung"
            dividend_trend = _dividend_trend_after_label(lines, index + consumed)
            if dividend_trend is not None:
                fields["dividend_per_share_trend"] = dividend_trend
            index += consumed
            continue

        index += 1

    return fields, index


def _combined_label(lines: Sequence[str], index: int) -> tuple[str, int]:
    line = lines[index]
    if line == "Markt-" and index + 1 < len(lines) and lines[index + 1] == "kapitalisierung":
        return "Markt-kapitalisierung", 2
    if (
        line == "Performance seit"
        and index + 1 < len(lines)
        and lines[index + 1] == "Erstempfehlung"
    ):
        return "Performance seit Erstempfehlung", 2
    if line == "Empfohlen" and index + 2 < len(lines):
        if lines[index + 1] == "in Ausgabe":
            return "Empfohlen in Ausgabe", 2
        if lines[index + 1] == "in" and lines[index + 2] == "Ausgabe":
            return "Empfohlen in Ausgabe", 3
    if line == "Omega / Hebel":
        return "Omega / Hebel", 1
    if line == "KUV" and index + 1 < len(lines) and lines[index + 1] == "26e":
        return "KUV 26e", 2
    if line == "KGV" and index + 1 < len(lines) and lines[index + 1] == "26e":
        return "KGV 26e", 2
    if line == "Nächster" and index + 1 < len(lines) and lines[index + 1] == "Termin":
        return "Nächster Termin", 2
    return line, 1


def _value_after_label(
    lines: Sequence[str],
    start_index: int,
    key: str,
) -> tuple[str | None, int]:
    if start_index >= len(lines):
        return None, start_index

    if key == "recommended_issue" and start_index + 1 < len(lines):
        if ISSUE_DATE_RE.search(lines[start_index]):
            return lines[start_index], start_index + 1
        return f"{lines[start_index]} {lines[start_index + 1]}", start_index + 2
    if (
        key == "runtime"
        and start_index + 1 < len(lines)
        and _looks_like_duration(lines[start_index + 1])
    ):
        return f"{lines[start_index]} ({lines[start_index + 1]})", start_index + 2
    if key == "next_report_date" and start_index + 1 < len(lines):
        return f"{lines[start_index]} {lines[start_index + 1]}", start_index + 2

    return lines[start_index], start_index + 1


def _looks_like_duration(value: str) -> bool:
    lowered = value.lower()
    return "monat" in lowered or "jahr" in lowered


def _performance_values_after_label(
    lines: Sequence[str],
    start_index: int,
) -> tuple[str | None, str | None, int]:
    value_index = start_index
    recommended_issue: str | None = None
    combined, consumed = _combined_label(lines, value_index)
    if combined == "Empfohlen in Ausgabe":
        value_index += consumed

    if value_index >= len(lines) or not PERCENT_RE.match(lines[value_index]):
        return None, None, start_index

    next_index = value_index + 1
    if next_index < len(lines) and ISSUE_DATE_RE.search(lines[next_index]):
        recommended_issue = lines[next_index]
        next_index += 1

    return lines[value_index], recommended_issue, next_index


def _dividend_trend_after_label(lines: Sequence[str], start_index: int) -> str | None:
    years: list[str] = []
    index = start_index
    while index < len(lines) and YEAR_RE.match(lines[index]):
        years.append(lines[index])
        index += 1

    if not years:
        return None

    values: list[str] = []
    while index < len(lines) and len(values) < len(years) and DECIMAL_VALUE_RE.match(lines[index]):
        values.append(lines[index])
        index += 1

    if len(values) != len(years):
        return None

    entries = [f"{year}={value} EUR" for year, value in zip(years, values)]
    return "; ".join(entries)


def _rating_from_dots(value: str | None) -> int | None:
    if value is None:
        return None
    rating = value.count("•")
    return rating or None


def _looks_like_derivative(instrument_name: str) -> bool:
    lowered = instrument_name.lower()
    return any(token in lowered for token in ("call", "put", "zertifikat", "discount"))


def _line_at(lines: Sequence[str], index: int) -> str | None:
    if 0 <= index < len(lines):
        return lines[index]
    return None


def _clean_line(line: str) -> str:
    cleaned = line.replace("\u2009", " ").replace("\u202f", " ").replace("\u2003", " ")
    cleaned = cleaned.replace("\ufeff", "").replace("\b", "")
    cleaned = EURO_SUFFIX_RE.sub(" EUR", cleaned)
    cleaned = USD_SUFFIX_RE.sub(" USD", cleaned)
    cleaned = cleaned.replace("€", "EUR").replace("$", "USD")
    cleaned = " ".join(cleaned.split())
    return cleaned


def _is_dot_rating(value: str) -> bool:
    return bool(value) and set(value) == {"•"}


def _issue_id_from_filename(pdf_path: Path) -> str:
    match = re.match(r"DA_(?P<year>20\d{2})_(?P<week>\d{2})", pdf_path.stem)
    if match:
        return f"{match.group('year')}-W{match.group('week')}"
    return pdf_path.stem
