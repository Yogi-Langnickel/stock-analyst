"""Local inventory of high-value magazine sections and table surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import re
from typing import Sequence

from stock_analyst.extraction import RawTextExtractor, extract_pdf_text
from stock_analyst.processing_policy import (
    DEFAULT_MAGAZINE_PROCESSING_POLICY,
    MagazineProcessingPolicy,
    filter_magazine_processing_pages,
    is_statistics_section_text,
)
from stock_analyst.schemas import ReviewStatus


class MagazineSectionKind(str, Enum):
    DIVIDEND_STRATEGY = "dividend_strategy"
    DERIVATIVE_TIPS_OVERVIEW = "derivative_tips_overview"
    AKTIONAER_DEPOT_POSITIONS = "aktionaer_depot_positions"
    AKTIONAER_DEPOT_TRANSACTIONS = "aktionaer_depot_transactions"
    CHART_CHECK = "chart_check"
    QUICK_CHECK = "quick_check"
    STATISTICS_CONTEXT = "statistics_context"
    LOW_PRIORITY_BACK_MATTER = "low_priority_back_matter"


SHEET_DESTINATIONS = {
    MagazineSectionKind.DIVIDEND_STRATEGY: "Dividend Focus",
    MagazineSectionKind.DERIVATIVE_TIPS_OVERVIEW: "Derivative Tips",
    MagazineSectionKind.AKTIONAER_DEPOT_POSITIONS: "AKTIONAER Depot",
    MagazineSectionKind.AKTIONAER_DEPOT_TRANSACTIONS: "Depot Transactions",
    MagazineSectionKind.CHART_CHECK: "Chart Check",
    MagazineSectionKind.QUICK_CHECK: "Stock Quickcheck",
    MagazineSectionKind.STATISTICS_CONTEXT: "Statistics Context",
    MagazineSectionKind.LOW_PRIORITY_BACK_MATTER: "Extraction Audit",
}

SECTION_TITLES = {
    MagazineSectionKind.DIVIDEND_STRATEGY: "Dividend strategy tables",
    MagazineSectionKind.DERIVATIVE_TIPS_OVERVIEW: "Derivate tips overview",
    MagazineSectionKind.AKTIONAER_DEPOT_POSITIONS: "AKTIONAER depot positions",
    MagazineSectionKind.AKTIONAER_DEPOT_TRANSACTIONS: "Depot transaction table",
    MagazineSectionKind.CHART_CHECK: "Chart check",
    MagazineSectionKind.QUICK_CHECK: "Aktien im Quick-Check",
    MagazineSectionKind.STATISTICS_CONTEXT: "Statistics context",
    MagazineSectionKind.LOW_PRIORITY_BACK_MATTER: "Low-priority back matter",
}

WKN_RE = re.compile(r"(?<![A-Z0-9])(?:[A-Z][A-Z0-9]{5}|[0-9]{6})(?![A-Z0-9])")
WKN_FALSE_POSITIVES = {
    "AKTION",
    "CLEVER",
    "CRISPR",
    "DEGIRO",
    "EUROPA",
    "GLOBAL",
    "NUTZEN",
}


@dataclass(frozen=True)
class MagazineSectionCandidate:
    issue_id: str
    page: int
    section_kind: MagazineSectionKind
    section_title: str
    suggested_sheet: str
    priority: str
    reason: str
    wkns: tuple[str, ...]
    review_status: ReviewStatus = ReviewStatus.NEEDS_REVIEW
    extraction_notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "issueId": self.issue_id,
            "page": self.page,
            "sectionKind": self.section_kind.value,
            "sectionTitle": self.section_title,
            "suggestedSheet": self.suggested_sheet,
            "priority": self.priority,
            "reason": self.reason,
            "reviewStatus": self.review_status.value,
            "wknCount": len(self.wkns),
        }
        if self.wkns:
            result["wkns"] = list(self.wkns)
        if self.extraction_notes:
            result["extractionNotes"] = list(self.extraction_notes)
        return result


@dataclass(frozen=True)
class MagazineSectionInventory:
    issue_id: str
    pdf_path: Path
    page_count: int
    external_services_enabled: bool
    sections: tuple[MagazineSectionCandidate, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "issueId": self.issue_id,
            "pdfPath": str(self.pdf_path),
            "pageCount": self.page_count,
            "externalServicesEnabled": self.external_services_enabled,
            "sections": [section.to_dict() for section in self.sections],
        }


def build_section_inventory_from_pdf(
    pdf_path: Path,
    *,
    issue_id: str | None = None,
    extractor: RawTextExtractor | None = None,
    min_embedded_chars: int = 40,
    processing_policy: MagazineProcessingPolicy = DEFAULT_MAGAZINE_PROCESSING_POLICY,
) -> MagazineSectionInventory:
    """Find high-value table/section surfaces using local embedded text only."""

    extraction = extract_pdf_text(
        pdf_path,
        extractor=extractor,
        min_embedded_chars=min_embedded_chars,
    )
    resolved_issue_id = issue_id or _issue_id_from_filename(pdf_path)
    sections: list[MagazineSectionCandidate] = []
    pages = filter_magazine_processing_pages(
        extraction.pages,
        policy=processing_policy,
    )

    for page in pages:
        sections.extend(
            extract_section_candidates_from_lines(
                page.text.splitlines(),
                issue_id=resolved_issue_id,
                page_number=page.page_number,
            )
        )

    return MagazineSectionInventory(
        issue_id=resolved_issue_id,
        pdf_path=pdf_path,
        page_count=extraction.page_count,
        external_services_enabled=False,
        sections=tuple(sections),
    )


def extract_section_candidates_from_lines(
    lines: Sequence[str],
    *,
    issue_id: str,
    page_number: int,
) -> tuple[MagazineSectionCandidate, ...]:
    normalized_lines = tuple(_clean_line(line) for line in lines if _clean_line(line))
    text = "\n".join(normalized_lines)
    sections: list[MagazineSectionCandidate] = []

    if _is_dividend_strategy(normalized_lines, text):
        sections.append(
            _candidate(
                issue_id,
                page_number,
                MagazineSectionKind.DIVIDEND_STRATEGY,
                "high",
                "Dividend table with payout timing, yields, targets, and stops.",
                normalized_lines,
            )
        )

    if _is_derivative_overview(normalized_lines, text):
        reason = (
            "Derivative overview table with WKN, type, strike/cap, runtime, "
            "performance, target, and stop."
        )
        sections.append(
            _candidate(
                issue_id,
                page_number,
                MagazineSectionKind.DERIVATIVE_TIPS_OVERVIEW,
                "high",
                reason,
                normalized_lines,
            )
        )

    if _is_depot_positions(normalized_lines, text):
        reason = (
            "Publisher model-depot positions with purchase date, size, value, "
            "performance, and stop."
        )
        sections.append(
            _candidate(
                issue_id,
                page_number,
                MagazineSectionKind.AKTIONAER_DEPOT_POSITIONS,
                "high",
                reason,
                normalized_lines,
            )
        )

    if _is_depot_transactions(normalized_lines, text):
        sections.append(
            _candidate(
                issue_id,
                page_number,
                MagazineSectionKind.AKTIONAER_DEPOT_TRANSACTIONS,
                "high",
                "Publisher model-depot transaction table, including no-transaction weeks.",
                normalized_lines,
            )
        )

    if _is_chart_check(normalized_lines, text):
        reason = (
            "Chart-check section with multiple stocks, technical context, "
            "and recommendation metadata."
        )
        sections.append(
            _candidate(
                issue_id,
                page_number,
                MagazineSectionKind.CHART_CHECK,
                "medium",
                reason,
                normalized_lines,
                notes=("attach_to_stock_when_wkn_matches",),
            )
        )

    if _is_quick_check(normalized_lines, text):
        reason = (
            "Quick-check table contains publisher evaluations that should "
            "attach to matching stock rows."
        )
        sections.append(
            _candidate(
                issue_id,
                page_number,
                MagazineSectionKind.QUICK_CHECK,
                "medium",
                reason,
                normalized_lines,
                notes=("attach_to_stock_when_wkn_matches",),
            )
        )

    if _is_statistics_context(normalized_lines, text):
        reason = (
            "Statistics table is useful as stock context but should not create "
            "recommendation rows by itself."
        )
        sections.append(
            _candidate(
                issue_id,
                page_number,
                MagazineSectionKind.STATISTICS_CONTEXT,
                "low",
                reason,
                normalized_lines,
                notes=("context_only",),
            )
        )

    if _is_low_priority_back_matter(normalized_lines, page_number):
        reason = (
            "Back matter after the statistics section is usually ads, imprint, "
            "books, or app promotion."
        )
        sections.append(
            _candidate(
                issue_id,
                page_number,
                MagazineSectionKind.LOW_PRIORITY_BACK_MATTER,
                "low",
                reason,
                normalized_lines,
                notes=("skip_unless_wkn_or_manual_review_signal",),
            )
        )

    return tuple(sections)


def _candidate(
    issue_id: str,
    page_number: int,
    kind: MagazineSectionKind,
    priority: str,
    reason: str,
    lines: Sequence[str],
    *,
    notes: tuple[str, ...] = (),
) -> MagazineSectionCandidate:
    return MagazineSectionCandidate(
        issue_id=issue_id,
        page=page_number,
        section_kind=kind,
        section_title=SECTION_TITLES[kind],
        suggested_sheet=SHEET_DESTINATIONS[kind],
        priority=priority,
        reason=reason,
        wkns=_extract_wkns(lines),
        extraction_notes=notes,
    )


def _is_dividend_strategy(lines: Sequence[str], text: str) -> bool:
    return (
        ("Dividende" in lines and "ohne Ende" in lines)
        or (
            _contains_all(lines, ("Monat", "Unternehmen", "WKN"))
            and _contains_all(lines, ("Dividenden-", "rendite"))
        )
        or (
            _contains_all(lines, ("Nächster", "Zahltag", "Ziel", "Stopp"))
            and "Cum-Tag" in text
        )
    )


def _is_derivative_overview(lines: Sequence[str], text: str) -> bool:
    return (
        "Derivate" in text
        and (
            _contains_all(lines, ("Basiswert", "WKN", "Emittent", "Typ"))
            or _contains_all(lines, ("Empf.", "kurs", "Empfehlung"))
            or _contains_all(lines, ("Heft", "Empfehlung", "Chance", "Risiko"))
            or _contains_all(lines, ("Strike / Cap", "Laufzeit", "Hebel / Omega"))
        )
    )


def _is_depot_positions(lines: Sequence[str], text: str) -> bool:
    return (
        "AKTIONÄR-Depot" in text
        and _contains_all(lines, ("Aktie/Derivat", "WKN", "Kauf-", "datum"))
    )


def _is_depot_transactions(lines: Sequence[str], text: str) -> bool:
    return (
        "AKTIONÄR-Depot" in text
        and (
            "Durchgeführte Transaktionen" in text
            or _contains_all(lines, ("Transaktion", "Wertpapier", "Transaktions-datum"))
            or "Diese Woche keine Transaktionen" in text
        )
    )


def _is_chart_check(lines: Sequence[str], text: str) -> bool:
    return "Chart-Check" in text and (
        len(_extract_wkns(lines)) >= 2
        or _contains_any(lines, ("Ziel", "Stopp", "Perform. seit Empf."))
    )


def _is_quick_check(lines: Sequence[str], text: str) -> bool:
    wkn_count = len(_extract_wkns(lines))
    return ("Aktien im Quick-Check" in text and wkn_count >= 3) or (
        wkn_count >= 8 and _contains_any(lines, ("52/25", "43/25", "02/26"))
    )


def _is_statistics_context(lines: Sequence[str], text: str) -> bool:
    return is_statistics_section_text(lines) or (
        "Statistik" in text and len(_extract_wkns(lines)) >= 2
    )


def _is_low_priority_back_matter(lines: Sequence[str], page_number: int) -> bool:
    return page_number >= 118 and _contains_any(
        lines,
        ("Bücher", "Letzte Seite", "digitale Ausgaben", "WERBUNG"),
    )


def _extract_wkns(lines: Sequence[str]) -> tuple[str, ...]:
    found: list[str] = []
    for line in lines:
        for match in WKN_RE.findall(line):
            if match in WKN_FALSE_POSITIVES:
                continue
            if match not in found:
                found.append(match)
    return tuple(found)


def _contains_all(lines: Sequence[str], values: Sequence[str]) -> bool:
    return all(value in lines for value in values)


def _contains_any(lines: Sequence[str], values: Sequence[str]) -> bool:
    return any(value in lines for value in values)


def _clean_line(line: str) -> str:
    cleaned = line.replace("\u2009", " ").replace("\u202f", " ").replace("\u2003", " ")
    cleaned = cleaned.replace("\ufeff", "").replace("\b", "")
    return " ".join(cleaned.split())


def _issue_id_from_filename(pdf_path: Path) -> str:
    match = re.match(r"DA_(?P<year>20\d{2})_(?P<week>\d{2})", pdf_path.stem)
    if match:
        return f"{match.group('year')}-W{match.group('week')}"
    return pdf_path.stem
