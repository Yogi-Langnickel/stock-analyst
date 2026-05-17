"""Local rule-based extraction for labelled magazine recommendation cards."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import re
from typing import Sequence

from stock_analyst.extraction import RawTextExtractor, extract_pdf_text
from stock_analyst.schemas import InstrumentType, ReviewStatus


LABEL_ALIASES = {
    "Akt. Kurs": "current_price",
    "Empfehlungskurs": "entry_price",
    "Performance": "performance_since_recommendation",
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
    "Knock-out": "base_price",
    "Omega / Hebel": "omega_hebel",
    "Omega": "omega_hebel",
    "Hebel": "omega_hebel",
    "Laufzeit": "runtime",
}

CARD_END_MARKERS = {
    "Quelle:",
    "Foto:",
    "Weitere Informationen",
}
CARD_START_TYPES = {
    "Aktie": InstrumentType.STOCK,
    "ETF": InstrumentType.ETF,
    "Fonds": InstrumentType.FUND,
    "Rohstoff": InstrumentType.COMMODITY,
    "Commodity": InstrumentType.COMMODITY,
    "Krypto": InstrumentType.CRYPTO,
    "Crypto": InstrumentType.CRYPTO,
    "Forex": InstrumentType.FOREX,
    "Währung": InstrumentType.FOREX,
    "Devisen": InstrumentType.FOREX,
    "Derivat": InstrumentType.DERIVATIVE,
    "Zertifikat": InstrumentType.DERIVATIVE,
    "Option": InstrumentType.DERIVATIVE,
}

EURO_SUFFIX_RE = re.compile(r"(?<=\d)\s*€")
USD_SUFFIX_RE = re.compile(r"(?<=\d)\s*\$")
ISSUE_DATE_RE = re.compile(r"\b\d{2}/\d{4}\b")
WKN_RE = re.compile(r"^[A-Z0-9]{6}$")
PERCENT_RE = re.compile(r"^[+-]?\d+(?:,\d+)?\s*%$")
YEAR_RE = re.compile(r"^20\d{2}e?$")
DECIMAL_VALUE_RE = re.compile(r"^\d+(?:,\d+)?\*?$")
MONEY_VALUE_RE = re.compile(r"^[+-]?\d+(?:,\d+)?\s+(?:EUR|USD)$")


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
    entry_price: str | None = None
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
            "entryPrice": self.entry_price,
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


@dataclass(frozen=True)
class _VisualChanceRiskPair:
    chance: int
    risk: int


@dataclass(frozen=True)
class _VisualDotRating:
    page_number: int
    y_midpoint: float
    x_midpoint: float
    kind: str
    rating: int


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
    visual_pairs_by_page = (
        _visual_chance_risk_pairs_by_page(pdf_path) if extractor is None else {}
    )
    cards: list[RecommendationCard] = []

    for page in extraction.pages:
        cards.extend(
            extract_recommendation_cards_from_lines(
                page.text.splitlines(),
                issue_id=resolved_issue_id,
                page_number=page.page_number,
                visual_chance_risk_pairs=visual_pairs_by_page.get(page.page_number, ()),
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
    visual_chance_risk_pairs: Sequence[_VisualChanceRiskPair] = (),
) -> tuple[RecommendationCard, ...]:
    """Extract card rows from page lines produced by local PDF text extraction."""

    normalized_lines = [_clean_line(line) for line in lines if _clean_line(line)]
    if _looks_like_external_newsletter_ad(normalized_lines):
        return ()
    cards: list[RecommendationCard] = []
    index = 0
    while index < len(normalized_lines):
        line = normalized_lines[index]
        explicit_card_start = _instrument_type_for_card_start(line) is not None
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

    table_cards = _extract_duel_table_cards(
        normalized_lines,
        issue_id=issue_id,
        page_number=page_number,
    )
    existing_wkns = {card.wkn for card in cards if card.wkn}
    cards.extend(card for card in table_cards if card.wkn not in existing_wkns)

    return _apply_visual_chance_risk_pairs(tuple(cards), visual_chance_risk_pairs)


def _extract_duel_table_cards(
    lines: Sequence[str],
    *,
    issue_id: str,
    page_number: int,
) -> tuple[RecommendationCard, ...]:
    try:
        header_index = lines.index("Unternehmen")
    except ValueError:
        return ()
    if "Empf.-" not in lines[header_index:] or "Risiko" not in lines[header_index:]:
        return ()

    try:
        start_index = header_index + lines[header_index:].index("Risiko") + 1
    except ValueError:
        return ()

    cards: list[RecommendationCard] = []
    index = start_index
    while index + 8 < len(lines):
        name = lines[index]
        wkn = lines[index + 1]
        if not WKN_RE.match(wkn):
            index += 1
            continue

        current_price = lines[index + 2]
        market_cap = _market_cap_from_billions_value(lines[index + 3])
        dividend_yield = _percentage_from_table_value(lines[index + 4])
        kuv_26e = _dash_to_empty(lines[index + 5])
        kgv_26e = _dash_to_empty(lines[index + 6])
        index += 7

        performance_since_recommendation: str | None = None
        if index < len(lines) and PERCENT_RE.match(lines[index]):
            performance_since_recommendation = lines[index]
            index += 1

        recommendation_status: str | None = None
        if index < len(lines) and lines[index] == "Neuempfehlung":
            recommendation_status = "new_recommendation"
            index += 1
        elif index < len(lines) and lines[index].lower() == "kein kauf":
            recommendation_status = "no_buy"
            index += 1

        target: str | None = None
        stop: str | None = None
        if index + 1 < len(lines) and MONEY_VALUE_RE.match(lines[index]):
            target = lines[index]
            stop = lines[index + 1] if MONEY_VALUE_RE.match(lines[index + 1]) else None
            index += 2 if stop is not None else 1

        if index + 1 >= len(lines) or not _is_dot_rating(lines[index]):
            continue
        chance = _rating_from_dots(lines[index])
        risk = _rating_from_dots(lines[index + 1]) if _is_dot_rating(lines[index + 1]) else None
        index += 2 if risk is not None else 1

        cards.append(
            RecommendationCard(
                issue_id=issue_id,
                page=page_number,
                instrument_name=name,
                instrument_type=InstrumentType.STOCK,
                wkn=wkn,
                current_price=current_price,
                target=target,
                stop=stop,
                chance=chance,
                risk=risk,
                recommendation_status=recommendation_status,
                market_cap=market_cap,
                performance_since_recommendation=performance_since_recommendation,
                dividend_yield=dividend_yield,
                kuv_26e=kuv_26e,
                kgv_26e=kgv_26e,
                extraction_notes=("duel_table_extraction",),
            )
        )

    return tuple(cards)


def _apply_visual_chance_risk_pairs(
    cards: tuple[RecommendationCard, ...],
    visual_pairs: Sequence[_VisualChanceRiskPair],
) -> tuple[RecommendationCard, ...]:
    if not visual_pairs:
        return cards

    pair_index = 0
    updated_cards: list[RecommendationCard] = []
    for card in cards:
        if pair_index >= len(visual_pairs) or card.chance is None or card.risk is None:
            updated_cards.append(card)
            continue
        pair = visual_pairs[pair_index]
        pair_index += 1
        if card.chance == pair.chance and card.risk == pair.risk:
            updated_cards.append(card)
            continue
        notes = tuple(dict.fromkeys(card.extraction_notes + ("visual_rating_from_pdf",)))
        updated_cards.append(replace(card, chance=pair.chance, risk=pair.risk, extraction_notes=notes))

    return tuple(updated_cards)


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

    instrument_type = _instrument_type_for_card_start(raw_type) or InstrumentType.STOCK
    if instrument_type != InstrumentType.DERIVATIVE and _looks_like_derivative(instrument_name):
        instrument_type = InstrumentType.DERIVATIVE
    recommendation_status = "new_recommendation" if "new_recommendation" in fields else None
    if "no_buy" in fields:
        recommendation_status = "no_buy"
    if "recommended_issue" in fields or "performance_since_recommendation" in fields:
        recommendation_status = recommendation_status or "follow_up"
    if instrument_type == InstrumentType.DERIVATIVE:
        recommendation_status = recommendation_status or "new_recommendation"

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
            entry_price=fields.get("entry_price"),
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

        if combined.lower() == "kein kauf":
            fields["no_buy"] = "Kein Kauf"
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
    if line in {"Omega / Hebel", "Omega"}:
        return line, 1
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
    if key == "entry_price" and start_index + 1 < len(lines):
        if re.match(r"^\d{2}\.\d{2}\.\d{4}$", lines[start_index]):
            return lines[start_index + 1], start_index + 2
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


def _visual_chance_risk_pairs_by_page(pdf_path: Path) -> dict[int, tuple[_VisualChanceRiskPair, ...]]:
    try:
        import fitz  # type: ignore[import-not-found]
        from PIL import Image
    except ModuleNotFoundError:
        return {}

    try:
        document = fitz.open(pdf_path)
    except Exception:
        return {}

    result: dict[int, tuple[_VisualChanceRiskPair, ...]] = {}
    zoom = 6
    with document:
        for page_index, page in enumerate(document):
            candidate_spans: list[tuple[str, Sequence[float]]] = []
            page_dict = page.get_text("dict")
            for block in page_dict.get("blocks", []):
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        text = span.get("text", "")
                        if not _is_dot_rating(text) or len(text) != 5:
                            continue
                        kind = _dot_rating_kind_from_span_color(span.get("color"))
                        if kind is None:
                            continue
                        bbox = span.get("bbox")
                        if not bbox:
                            continue
                        candidate_spans.append((kind, bbox))
            if not candidate_spans:
                continue

            dot_ratings: list[_VisualDotRating] = []
            pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            image = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
            for kind, bbox in candidate_spans:
                rating = _visual_dot_rating_from_bbox(image, bbox, zoom=zoom)
                if rating is None:
                    continue
                x0, y0, x1, y1 = bbox
                dot_ratings.append(
                    _VisualDotRating(
                        page_number=page_index + 1,
                        y_midpoint=(float(y0) + float(y1)) / 2,
                        x_midpoint=(float(x0) + float(x1)) / 2,
                        kind=kind,
                        rating=rating,
                    )
                )
            pairs = _pair_visual_dot_ratings(dot_ratings)
            if pairs:
                result[page_index + 1] = pairs

    return result


def _dot_rating_kind_from_span_color(color: object) -> str | None:
    if not isinstance(color, int):
        return None
    red = (color >> 16) & 255
    green = (color >> 8) & 255
    blue = color & 255
    if green > red and green > blue:
        return "chance"
    if red > green and red > blue:
        return "risk"
    return None


def _visual_dot_rating_from_bbox(image, bbox: Sequence[float], *, zoom: int) -> int | None:
    x0, y0, x1, y1 = [int(value * zoom) for value in bbox]
    if x1 <= x0 or y1 <= y0:
        return None
    crop = image.crop((x0, y0, x1, y1))
    width, height = crop.size
    if width <= 0 or height <= 0:
        return None

    segment_counts: list[int] = []
    for index in range(5):
        segment = crop.crop(
            (
                int(index * width / 5),
                0,
                int((index + 1) * width / 5),
                height,
            )
        )
        colors = segment.getcolors(maxcolors=1000000) or []
        colored_pixels = 0
        for count, (red, green, blue) in colors:
            if max(red, green, blue) - min(red, green, blue) > 30 and min(red, green, blue) < 245:
                colored_pixels += count
        segment_counts.append(colored_pixels)

    max_count = max(segment_counts, default=0)
    if max_count <= 0:
        return None
    threshold = max_count * 0.5
    return sum(1 for count in segment_counts if count >= threshold) or None


def _pair_visual_dot_ratings(
    dot_ratings: Sequence[_VisualDotRating],
) -> tuple[_VisualChanceRiskPair, ...]:
    chances = sorted(
        (rating for rating in dot_ratings if rating.kind == "chance"),
        key=lambda rating: (rating.y_midpoint, rating.x_midpoint),
    )
    risks = sorted(
        (rating for rating in dot_ratings if rating.kind == "risk"),
        key=lambda rating: (rating.y_midpoint, rating.x_midpoint),
    )
    unused_risks = list(risks)
    pairs: list[_VisualChanceRiskPair] = []
    for chance in chances:
        nearest_index: int | None = None
        nearest_distance = 999.0
        for index, risk in enumerate(unused_risks):
            distance = abs(chance.y_midpoint - risk.y_midpoint)
            if distance < nearest_distance:
                nearest_distance = distance
                nearest_index = index
        if nearest_index is None or nearest_distance > 8:
            continue
        risk = unused_risks.pop(nearest_index)
        pairs.append(_VisualChanceRiskPair(chance=chance.rating, risk=risk.rating))
    return tuple(pairs)


def _market_cap_from_billions_value(value: str) -> str | None:
    if DECIMAL_VALUE_RE.match(value):
        return f"{value} Mrd. EUR"
    return None


def _percentage_from_table_value(value: str) -> str | None:
    if value == "–":
        return None
    if DECIMAL_VALUE_RE.match(value):
        return f"{value} %"
    return value if PERCENT_RE.match(value) else None


def _dash_to_empty(value: str) -> str | None:
    return None if value == "–" else value


def _rating_from_dots(value: str | None) -> int | None:
    if value is None:
        return None
    rating = value.count("•")
    return rating or None


def _looks_like_derivative(instrument_name: str) -> bool:
    lowered = instrument_name.lower()
    return any(
        token in lowered
        for token in ("call", "put", "zertifikat", "discount", "turbo", "long", "short")
    )


def _looks_like_external_newsletter_ad(lines: Sequence[str]) -> bool:
    joined = " ".join(lines)
    return "www.hebeltrader.de" in joined or "HEBELTRADER-Anlagegrundsätze" in joined


def _instrument_type_for_card_start(raw_type: str) -> InstrumentType | None:
    return CARD_START_TYPES.get(raw_type)


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
