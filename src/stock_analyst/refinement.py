"""Page-by-page refinement map for reviewer parser training."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
import re
from typing import Sequence

from stock_analyst.extraction import RawTextExtractor, extract_pdf_text
from stock_analyst.section_inventory import (
    MagazineSectionCandidate,
    MagazineSectionKind,
    extract_section_candidates_from_lines,
)


REFINEMENT_HEADERS = (
    "Page_number",
    "section",
    "page_titel",
    "useful_info",
    "suggested_destination",
    "parser_hint",
    "reason",
    "reviewer_notes",
    "issue",
    "date_updated",
)

SECTION_LABELS = {
    MagazineSectionKind.DIVIDEND_STRATEGY: "Dividenden",
    MagazineSectionKind.DERIVATIVE_TIPS_OVERVIEW: "Derivate",
    MagazineSectionKind.AKTIONAER_DEPOT_POSITIONS: "AKTIONAER Depot",
    MagazineSectionKind.AKTIONAER_DEPOT_TRANSACTIONS: "Depot Transactions",
    MagazineSectionKind.CHART_CHECK: "chart-check",
    MagazineSectionKind.QUICK_CHECK: "Quick-Check",
    MagazineSectionKind.STATISTICS_CONTEXT: "Statistik",
    MagazineSectionKind.LOW_PRIORITY_BACK_MATTER: "back-matter",
}


@dataclass(frozen=True)
class RefinementPageRow:
    issue_id: str
    page_number: int
    section: str
    page_title: str
    useful_info: str
    suggested_destination: str
    parser_hint: str
    reason: str
    reviewer_notes: str
    date_updated: str

    def values(self) -> tuple[str, ...]:
        return (
            str(self.page_number),
            self.section,
            self.page_title,
            self.useful_info,
            self.suggested_destination,
            self.parser_hint,
            self.reason,
            self.reviewer_notes,
            self.issue_id,
            self.date_updated,
        )

    def to_dict(self) -> dict[str, object]:
        return dict(zip(REFINEMENT_HEADERS, self.values(), strict=True))


@dataclass(frozen=True)
class RefinementPlan:
    issue_id: str
    pdf_path: Path
    external_services_enabled: bool
    rows: tuple[RefinementPageRow, ...]

    def to_dict(self) -> dict[str, object]:
        useful_count = sum(1 for row in self.rows if row.useful_info == "yes")
        return {
            "issueId": self.issue_id,
            "pdfPath": str(self.pdf_path),
            "externalServicesEnabled": self.external_services_enabled,
            "rowCount": len(self.rows),
            "usefulInfoYesCount": useful_count,
            "usefulInfoNoCount": len(self.rows) - useful_count,
            "headers": list(REFINEMENT_HEADERS),
            "rows": [row.to_dict() for row in self.rows],
        }


def build_refinement_plan_from_pdf(
    pdf_path: Path,
    *,
    issue_id: str | None = None,
    extractor: RawTextExtractor | None = None,
    min_embedded_chars: int = 40,
    current_utc_date: date | str | None = None,
) -> RefinementPlan:
    extraction = extract_pdf_text(
        pdf_path,
        extractor=extractor,
        min_embedded_chars=min_embedded_chars,
    )
    resolved_issue_id = issue_id or _issue_id_from_filename(pdf_path)
    date_updated = _date_cell_value(current_utc_date) or _current_utc_date()
    rows = tuple(
        _classify_page(
            issue_id=resolved_issue_id,
            page_number=page.page_number,
            lines=page.text.splitlines(),
            date_updated=date_updated,
        )
        for page in extraction.pages
    )
    return RefinementPlan(
        issue_id=resolved_issue_id,
        pdf_path=pdf_path,
        external_services_enabled=False,
        rows=rows,
    )


def _classify_page(
    *,
    issue_id: str,
    page_number: int,
    lines: Sequence[str],
    date_updated: str,
) -> RefinementPageRow:
    normalized_lines = tuple(_clean_line(line) for line in lines if _clean_line(line))
    candidates = extract_section_candidates_from_lines(
        normalized_lines,
        issue_id=issue_id,
        page_number=page_number,
    )
    section = _section_for_page(page_number, normalized_lines, candidates)
    suggested_destination = _suggested_destination(section, candidates)
    useful_info = _useful_info(page_number, section, candidates, normalized_lines)
    parser_hint = _parser_hint(section, candidates)
    reason = _reason_for_page(page_number, section, candidates)

    return RefinementPageRow(
        issue_id=issue_id,
        page_number=page_number,
        section=section,
        page_title=_page_title(normalized_lines, section),
        useful_info=useful_info,
        suggested_destination=suggested_destination,
        parser_hint=parser_hint,
        reason=reason,
        reviewer_notes="",
        date_updated=date_updated,
    )


def _section_for_page(
    page_number: int,
    lines: Sequence[str],
    candidates: Sequence[MagazineSectionCandidate],
) -> str:
    if page_number == 1:
        return "Cover"
    if _contains_any(lines[:8], ("Editorial",)):
        return "Editorial"
    if page_number <= 5 or _contains_any(lines[:8], ("Inhalt",)):
        return "Inhalt/front-matter"
    if _looks_like_ad_page(lines):
        return "Werbung"
    explicit_section = _explicit_section_for_page(lines)
    if explicit_section:
        return explicit_section
    if _contains_any(lines, ("Titelstory", "Titelthema", "Titel-Story")):
        return "Titelstory"
    if candidates:
        return SECTION_LABELS.get(candidates[0].section_kind, candidates[0].section_kind.value)
    if _contains_any(lines, ("Kryptow", "Bitcoin", "Ethereum", "Krypto")):
        return "Kryptowährungen"
    if _contains_any(lines, ("Aktie", "Hot-Stock")):
        return "Aktien"
    if _contains_any(lines, ("Dividende", "Dividendenrendite", "Ausschüttung")):
        return "Dividenden"
    if _contains_any(lines, ("Derivate", "Call", "Put", "Zertifikat", "Hebel", "Basispreis", "Omega")):
        return "Derivate"
    if _contains_any(lines, ("Rohstoff", "Gold", "Silber", "Kupfer", "Öl")):
        return "Rohstoffe"
    if _contains_any(lines, ("Währung", "Devisen", "Forex")):
        return "Forex"
    if _contains_any(lines, ("Fonds", "ETF")):
        return "ETF/Fonds"
    if _contains_any(lines, ("Chart-Check", "52-Wochen-Hoch", "52-Wochen-Tief")):
        return "chart-check"
    if _contains_any(lines, ("Kursziel", "WKN")):
        return "Aktien"
    if _contains_any(lines, ("Statistik", "52-Wochen", "Indizes")):
        return "Statistik"
    if _contains_any(lines, ("Impressum", "Abo", "Buch", "App", "Podcast")):
        return "back-matter"
    return "unknown"


def _suggested_destination(
    section: str,
    candidates: Sequence[MagazineSectionCandidate],
) -> str:
    destinations = {
        "Aktien": "Stocks",
        "Titelstory": "Stocks",
        "Dividenden": "Dividend Focus",
        "Derivate": "Derivative Tips",
        "Kryptowährungen": "",
        "Rohstoffe": "",
        "Forex": "",
        "ETF/Fonds": "",
        "chart-check": "Stocks",
        "Chart der Woche": "Stocks",
        "Dax-Check": "Stocks",
        "Wall-Street-Check": "Stocks",
        "Rohstoff-Check": "Derivative Tips",
        "Quick-Check": "Stocks",
        "Statistik": "Stocks",
        "AKTIONÄR-Indizes": "",
        "News": "",
        "Werbung": "",
        "Bücher": "",
        "Impressum": "",
        "Letzte Seite": "",
        "Social Media Weekly": "",
    }
    if section in destinations:
        return destinations[section]
    if candidates:
        return "; ".join(_unique(candidate.suggested_sheet for candidate in candidates))
    return "review"


def _useful_info(
    page_number: int,
    section: str,
    candidates: Sequence[MagazineSectionCandidate],
    lines: Sequence[str],
) -> str:
    if section in {
        "Cover",
        "Editorial",
        "Inhalt/front-matter",
        "Werbung",
        "Bücher",
        "Impressum",
        "Letzte Seite",
        "Social Media Weekly",
        "AKTIONÄR-Indizes",
        "Kryptowährungen",
        "Rohstoffe",
        "Forex",
        "ETF/Fonds",
    }:
        return "no"
    if page_number <= 5:
        return "no"
    if candidates and any(candidate.priority in {"high", "medium"} for candidate in candidates):
        return "yes"
    if section in {"back-matter", "unknown"}:
        return "no"
    if section in {
        "News",
        "Statistik",
        "chart-check",
        "Chart der Woche",
        "Dax-Check",
        "Wall-Street-Check",
        "Rohstoff-Check",
        "Quick-Check",
    }:
        return "yes"
    if section in {"Aktien", "Titelstory", "Dividenden", "Derivate"}:
        return "yes" if _has_extraction_signal(lines) else "no"
    return "yes"


def _parser_hint(
    section: str,
    candidates: Sequence[MagazineSectionCandidate],
) -> str:
    if candidates:
        kinds = ", ".join(_unique(candidate.section_kind.value for candidate in candidates))
        return f"section_inventory:{kinds}"
    if section in {
        "Cover",
        "Editorial",
        "Werbung",
        "Bücher",
        "Impressum",
        "Letzte Seite",
        "Social Media Weekly",
        "AKTIONÄR-Indizes",
    }:
        return "ignore_or_manual_review"
    if section in {"Kryptowährungen", "Rohstoffe", "Forex"}:
        return "future_parser_needed"
    if section in {"back-matter", "Inhalt/front-matter", "unknown"}:
        return "ignore_or_manual_review"
    return "manual_classification_seed"


def _reason_for_page(
    page_number: int,
    section: str,
    candidates: Sequence[MagazineSectionCandidate],
) -> str:
    if section == "Cover":
        return "Cover page is normally not useful for extraction."
    if section == "Editorial":
        return "Editorial/front matter is normally not useful for extraction."
    if section == "Werbung":
        return "Advertising or promotional page; do not extract investment rows."
    if section in {"Bücher", "Impressum", "Letzte Seite", "Social Media Weekly", "AKTIONÄR-Indizes"}:
        return "Reviewer-seeded non-digest surface; do not extract investment rows automatically."
    if page_number <= 5:
        return "Early front matter is normally not useful for extraction."
    if candidates:
        return "; ".join(_unique(candidate.reason for candidate in candidates))
    if section == "back-matter":
        return "Likely low-value back matter or promotional page."
    if section == "unknown":
        return "No reliable parser marker found in embedded text."
    if section == "News":
        return "Reviewer-confirmed news surface; use as a manual classification seed."
    if section == "Titelstory":
        return "Reviewer-confirmed title-story surface; route explicit instruments to Stocks."
    return f"Keyword-based first-pass classification as {section}."


def _explicit_section_for_page(lines: Sequence[str]) -> str:
    checks = (
        ("Titelstory", ("Titelstory", "Titelthema", "Titel-Story")),
        ("News", ("News", "Meldungen", "Kurzmeldungen")),
        ("Dividenden", ("Dividendenstrategie", "Dividenden-Strategie")),
        ("Social Media Weekly", ("Social Media Weekly",)),
        ("AKTIONÄR-Indizes", ("AKTIONÄR-Indizes", "AKTIONAER-Indizes", "DER AKTIONÄR-Indizes")),
        ("Chart der Woche", ("Chart der Woche",)),
        ("Dax-Check", ("Dax-Check", "DAX-Check")),
        ("Wall-Street-Check", ("Wall-Street-Check",)),
        ("Rohstoff-Check", ("Rohstoff-Check",)),
        ("Quick-Check", ("Aktien im Quick-Check", "Quick-Check", "Quickcheck")),
        ("Bücher", ("Bücher", "Buchtipp", "Buchtipps")),
        ("Impressum", ("Impressum",)),
        ("Letzte Seite", ("Letzte Seite",)),
        ("Statistik", ("Statistik",)),
    )
    top_lines = lines[:20]
    for section, markers in checks:
        if _contains_any(top_lines, markers):
            return section
    return ""


def _looks_like_ad_page(lines: Sequence[str]) -> bool:
    if not _contains_any(lines, ("Anzeige", "Werbung", "Advertorial", "Sonderveröffentlichung", "PR-Anzeige")):
        return False
    # Advertising markers can appear inside real articles. Treat them as a
    # section marker only when the embedded text looks like a compact ad page.
    return len(lines) <= 35


def _has_extraction_signal(lines: Sequence[str]) -> bool:
    return _contains_any(
        lines,
        (
            "WKN",
            "ISIN",
            "Kursziel",
            "Stopp",
            "Stop",
            "Chance",
            "Risiko",
            "Marktkap",
            "KGV",
            "KUV",
            "Dividendenrendite",
            "Basispreis",
            "Omega",
            "Hebel",
            "Zertifikat",
        ),
    )


def _page_title(lines: Sequence[str], section: str) -> str:
    for line in lines[:45]:
        if _looks_like_title(line, section):
            return line[:120]
    return ""


def _looks_like_title(line: str, section: str) -> bool:
    if len(line) < 4 or len(line) > 140:
        return False
    lowered = line.casefold()
    skip_exact = {
        "der aktionär",
        "aktionär",
        "inhalt",
        "statistik",
        "aktien",
        "derivate",
        "chart-check",
        "quick-check",
        section.casefold(),
    }
    if lowered in skip_exact:
        return False
    if re.fullmatch(r"\d{1,3}", line):
        return False
    if re.search(r"\b\d{2}/20\d{2}\b", line):
        return False
    if re.fullmatch(r"[A-Z0-9]{6}", line):
        return False
    if line.count(" ") == 0 and len(line) < 10:
        return False
    return bool(re.search(r"[A-Za-zÄÖÜäöüß]", line))


def _contains_any(lines: Sequence[str], needles: Sequence[str]) -> bool:
    text = "\n".join(lines).casefold()
    return any(needle.casefold() in text for needle in needles)


def _unique(values: Sequence[str] | object) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return tuple(result)


def _date_cell_value(value: date | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, date):
        return value.isoformat()
    return value.strip()


def _current_utc_date() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _issue_id_from_filename(pdf_path: Path) -> str:
    stem = pdf_path.stem
    parts = stem.split("_")
    if len(parts) >= 3 and parts[0] == "DA" and parts[1].isdigit() and parts[2].isdigit():
        return f"{parts[1]}-W{parts[2]}"
    return stem


def _clean_line(line: str) -> str:
    cleaned = line.replace("\u2009", " ").replace("\u202f", " ").replace("\u2003", " ")
    cleaned = cleaned.replace("\ufeff", "").replace("\b", "")
    return " ".join(cleaned.split())
