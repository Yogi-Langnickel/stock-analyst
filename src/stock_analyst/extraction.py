"""Local-only PDF text extraction scaffolding.

The public helpers in this module do not require a live provider or network
access. Real PDF reader libraries are optional adapters; tests can inject a
deterministic extractor.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from pathlib import Path
import shutil
import subprocess
from typing import Protocol, Sequence

from stock_analyst.intake import assert_pdf_upload, calculate_sha256


class TextExtractionStatus(str, Enum):
    EXTRACTED = "extracted"
    NEEDS_REVIEW = "needs_review"
    EXTRACTION_FAILED = "extraction_failed"


class OcrStatus(str, Enum):
    NOT_REQUIRED = "not_required"
    NEEDED = "ocr_needed"
    NOT_RUN = "not_run"


class PdfTextExtractionError(RuntimeError):
    """Raised when a local PDF text adapter cannot extract a document."""


@dataclass(frozen=True)
class RawPageText:
    page_number: int
    text: str
    source: str = "embedded"
    layout_text: str | None = None


class RawTextExtractor(Protocol):
    extractor_name: str

    def extract_pages(self, pdf_path: Path) -> Sequence[RawPageText]:
        """Return page-level embedded text with 1-based page numbers."""


@dataclass(frozen=True)
class PageTextExtraction:
    page_number: int
    text: str
    text_hash: str
    embedded_text_status: TextExtractionStatus
    ocr_status: OcrStatus
    source: str
    reading_order_start: int
    failure_reason: str | None = None
    layout_text: str | None = None


@dataclass(frozen=True)
class PdfTextExtractionResult:
    checksum_sha256: str
    page_count: int
    status: TextExtractionStatus
    pages: tuple[PageTextExtraction, ...]
    extractor: str
    external_services_enabled: bool
    failure_reason: str | None = None


class DependencyUnavailableTextExtractor:
    extractor_name = "dependency_unavailable"

    def extract_pages(self, pdf_path: Path) -> Sequence[RawPageText]:
        raise PdfTextExtractionError(
            "local PDF text extraction dependency is not installed"
        )


class PyMuPdfTextExtractor:
    extractor_name = "pymupdf"

    def extract_pages(self, pdf_path: Path) -> Sequence[RawPageText]:
        try:
            import fitz  # type: ignore[import-not-found]
        except ModuleNotFoundError as error:
            raise PdfTextExtractionError(
                "local PDF text extraction dependency is not installed"
            ) from error

        try:
            document = fitz.open(pdf_path)
        except Exception as error:  # pragma: no cover - adapter boundary
            raise PdfTextExtractionError(str(error)) from error

        with document:
            return tuple(
                RawPageText(
                    page_number=index + 1,
                    text=page.get_text("text"),
                    source="embedded",
                )
                for index, page in enumerate(document)
            )


class PopplerTextExtractor:
    """Local Poppler fallback with reading-order text plus table layout.

    ``pdftotext`` provides the regular embedded reading order. A separate
    layout pass preserves wide recommendation-table rows without replacing
    that normal text.
    """

    extractor_name = "poppler_pdftotext_layout"

    def extract_pages(self, pdf_path: Path) -> Sequence[RawPageText]:
        reading_order_pages = self._run(pdf_path, layout=False)
        layout_pages = self._run(pdf_path, layout=True)
        return tuple(
            RawPageText(
                page_number=index + 1,
                text=reading_order_pages[index],
                source="embedded",
                layout_text=(layout_pages[index] if index < len(layout_pages) else None),
            )
            for index in range(len(reading_order_pages))
        )

    def _run(self, pdf_path: Path, *, layout: bool) -> list[str]:
        command = ["pdftotext"]
        if layout:
            command.append("-layout")
        command.extend((str(pdf_path), "-"))
        try:
            result = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except (OSError, subprocess.CalledProcessError) as error:
            raise PdfTextExtractionError(
                "local Poppler text extraction failed"
            ) from error

        pages = result.stdout.split("\f")
        if pages and not pages[-1].strip():
            pages.pop()
        return pages


class AugmentedTextExtractor:
    """Retain a primary extractor's text while adding optional table layouts."""

    extractor_name = "augmented_embedded_and_layout"

    def __init__(
        self,
        primary: RawTextExtractor,
        layout_extractor: PopplerTextExtractor,
    ) -> None:
        self._primary = primary
        self._layout_extractor = layout_extractor

    def extract_pages(self, pdf_path: Path) -> Sequence[RawPageText]:
        primary_pages = tuple(self._primary.extract_pages(pdf_path))
        try:
            layout_pages = tuple(self._layout_extractor.extract_pages(pdf_path))
        except PdfTextExtractionError:
            return primary_pages
        layout_by_page = {
            page.page_number: page.layout_text or page.text for page in layout_pages
        }
        return tuple(
            RawPageText(
                page_number=page.page_number,
                text=page.text,
                source=page.source,
                layout_text=layout_by_page.get(page.page_number),
            )
            for page in primary_pages
        )


def default_text_extractor() -> RawTextExtractor:
    try:
        import fitz  # type: ignore[import-not-found]  # noqa: F401
    except ModuleNotFoundError:
        if shutil.which("pdftotext"):
            return PopplerTextExtractor()
        return DependencyUnavailableTextExtractor()
    primary = PyMuPdfTextExtractor()
    if shutil.which("pdftotext"):
        return AugmentedTextExtractor(primary, PopplerTextExtractor())
    return primary


def hash_text(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def extract_pdf_text(
    pdf_path: Path,
    *,
    extractor: RawTextExtractor | None = None,
    min_embedded_chars: int = 40,
) -> PdfTextExtractionResult:
    """Extract embedded page text and mark OCR needs without running OCR."""

    assert_pdf_upload(pdf_path)
    checksum = calculate_sha256(pdf_path)
    selected_extractor = extractor or default_text_extractor()

    try:
        raw_pages = tuple(selected_extractor.extract_pages(pdf_path))
    except PdfTextExtractionError as error:
        return PdfTextExtractionResult(
            checksum_sha256=checksum,
            page_count=0,
            status=TextExtractionStatus.NEEDS_REVIEW,
            pages=(),
            extractor=selected_extractor.extractor_name,
            external_services_enabled=False,
            failure_reason=str(error),
        )

    if not raw_pages:
        return PdfTextExtractionResult(
            checksum_sha256=checksum,
            page_count=0,
            status=TextExtractionStatus.NEEDS_REVIEW,
            pages=(),
            extractor=selected_extractor.extractor_name,
            external_services_enabled=False,
            failure_reason="no pages were returned by the local extractor",
        )

    pages: list[PageTextExtraction] = []
    any_needs_ocr = False

    for index, raw_page in enumerate(raw_pages):
        text = raw_page.text.strip()
        needs_ocr = len(text) < min_embedded_chars
        any_needs_ocr = any_needs_ocr or needs_ocr
        pages.append(
            PageTextExtraction(
                page_number=raw_page.page_number,
                text=text,
                text_hash=hash_text(text),
                embedded_text_status=(
                    TextExtractionStatus.NEEDS_REVIEW
                    if needs_ocr
                    else TextExtractionStatus.EXTRACTED
                ),
                ocr_status=OcrStatus.NEEDED if needs_ocr else OcrStatus.NOT_REQUIRED,
                source=raw_page.source,
                reading_order_start=index,
                failure_reason=(
                    "embedded text below local threshold; OCR should be queued"
                    if needs_ocr
                    else None
                ),
                layout_text=raw_page.layout_text,
            )
        )

    return PdfTextExtractionResult(
        checksum_sha256=checksum,
        page_count=len(pages),
        status=TextExtractionStatus.NEEDS_REVIEW
        if any_needs_ocr
        else TextExtractionStatus.EXTRACTED,
        pages=tuple(pages),
        extractor=selected_extractor.extractor_name,
        external_services_enabled=False,
    )
