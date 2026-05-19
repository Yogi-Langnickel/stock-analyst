"""Magazine processing scope and provider cost guard policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence, TypeVar


DEFAULT_FRONT_MATTER_PAGE_COUNT = 5
DEFAULT_REMOTE_OCR_MONTHLY_PAGE_BUDGET = 900
RUNNING_HEADER_LINE_COUNT = 3


class PageLike(Protocol):
    page_number: int
    text: str


PageT = TypeVar("PageT", bound=PageLike)


@dataclass(frozen=True)
class MagazineProcessingPolicy:
    front_matter_page_count: int = DEFAULT_FRONT_MATTER_PAGE_COUNT
    cut_after_statistics: bool = True


DEFAULT_MAGAZINE_PROCESSING_POLICY = MagazineProcessingPolicy()


@dataclass(frozen=True)
class MagazineProcessingWindow:
    front_matter_page_count: int
    statistics_page: int | None
    first_included_page: int | None
    last_included_page: int | None
    skipped_front_matter_pages: tuple[int, ...]
    skipped_back_matter_pages: tuple[int, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "frontMatterPageCount": self.front_matter_page_count,
            "statisticsPage": self.statistics_page,
            "firstIncludedPage": self.first_included_page,
            "lastIncludedPage": self.last_included_page,
            "skippedFrontMatterPages": list(self.skipped_front_matter_pages),
            "skippedBackMatterPages": list(self.skipped_back_matter_pages),
        }


def filter_magazine_processing_pages(
    pages: Sequence[PageT],
    *,
    policy: MagazineProcessingPolicy = DEFAULT_MAGAZINE_PROCESSING_POLICY,
) -> tuple[PageT, ...]:
    """Return pages in the useful magazine processing window.

    The default window skips early front matter, including the Inhalt pages,
    and includes pages only through the first detected Statistik body section.
    The Statistik page itself is kept as context; pages after it are dropped
    from normal extraction/OCR planning.
    """

    window = build_magazine_processing_window(pages, policy=policy)

    return tuple(
        page
        for page in pages
        if _is_in_processing_window(page.page_number, window)
    )


def build_magazine_processing_window(
    pages: Sequence[PageLike],
    *,
    policy: MagazineProcessingPolicy = DEFAULT_MAGAZINE_PROCESSING_POLICY,
) -> MagazineProcessingWindow:
    statistics_page = (
        _first_statistics_page(pages) if policy.cut_after_statistics else None
    )
    first_included_page = None
    last_included_page = None
    skipped_front: list[int] = []
    skipped_back: list[int] = []

    for page in pages:
        if page.page_number <= policy.front_matter_page_count:
            skipped_front.append(page.page_number)
            continue
        if statistics_page is not None and page.page_number > statistics_page:
            skipped_back.append(page.page_number)
            continue
        first_included_page = first_included_page or page.page_number
        last_included_page = page.page_number

    return MagazineProcessingWindow(
        front_matter_page_count=policy.front_matter_page_count,
        statistics_page=statistics_page,
        first_included_page=first_included_page,
        last_included_page=last_included_page,
        skipped_front_matter_pages=tuple(skipped_front),
        skipped_back_matter_pages=tuple(skipped_back),
    )


def remote_ocr_budget_status(
    requested_page_count: int,
    *,
    monthly_page_budget: int = DEFAULT_REMOTE_OCR_MONTHLY_PAGE_BUDGET,
) -> str:
    return (
        "within_contract_budget"
        if requested_page_count <= monthly_page_budget
        else "over_contract_budget_requires_manual_approval"
    )


def _is_in_processing_window(
    page_number: int,
    window: MagazineProcessingWindow,
) -> bool:
    if page_number in window.skipped_front_matter_pages:
        return False
    if page_number in window.skipped_back_matter_pages:
        return False
    return True


def _first_statistics_page(pages: Sequence[PageLike]) -> int | None:
    for page in pages:
        if is_statistics_section_text(page.text.splitlines()):
            return page.page_number
    return None


def is_statistics_section_text(lines: Sequence[str]) -> bool:
    normalized = tuple(_clean_line(line) for line in lines if _clean_line(line))
    body_lines = _without_running_header(normalized)
    body_text = "\n".join(body_lines)
    body_markers = (
        "Die Woche im Überblick",
        "52-Wochen",
        "seit Jahresanfang",
        "Indizes",
    )
    marker_count = sum(1 for marker in body_markers if marker in body_text)

    return (
        "Die Woche im Überblick" in body_text
        or ("Statistik" in body_text and marker_count >= 1)
        or marker_count >= 2
    )


def _without_running_header(lines: Sequence[str]) -> tuple[str, ...]:
    if _has_running_header(lines):
        return tuple(lines[RUNNING_HEADER_LINE_COUNT:])
    return tuple(lines)


def _has_running_header(lines: Sequence[str]) -> bool:
    if len(lines) < RUNNING_HEADER_LINE_COUNT:
        return False
    section_label = lines[0] in {"Inhalt", "Statistik"}
    magazine_label = any("AKTIONÄR" in line for line in lines[1:RUNNING_HEADER_LINE_COUNT])
    return section_label and magazine_label


def _clean_line(line: str) -> str:
    cleaned = line.replace("\u2009", " ").replace("\u202f", " ").replace("\u2003", " ")
    cleaned = cleaned.replace("\ufeff", "").replace("\b", "")
    return " ".join(cleaned.split())
