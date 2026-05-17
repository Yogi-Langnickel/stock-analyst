"""Local page rendering and OCR review helpers.

This module keeps visual review work local and optional. It records private
artifact paths, hashes, and counts, but never returns OCR page text in command
output.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Protocol, Sequence

from stock_analyst.extraction import hash_text
from stock_analyst.extraction import (
    OcrStatus,
    RawTextExtractor,
    TextExtractionStatus,
    extract_pdf_text,
)
from stock_analyst.intake import assert_pdf_upload, calculate_sha256


class LocalVisualError(RuntimeError):
    """Raised when a local visual/OCR adapter cannot complete an operation."""


@dataclass(frozen=True)
class RenderedPageImage:
    page_number: int
    image_path: Path
    width_pixels: int
    height_pixels: int
    dpi: int
    image_format: str = "png"


class PageImageRenderer(Protocol):
    renderer_name: str

    def count_pages(self, pdf_path: Path) -> int:
        """Return the number of pages in a local PDF."""

    def render_page(
        self,
        pdf_path: Path,
        *,
        page_number: int,
        output_dir: Path,
        dpi: int,
    ) -> RenderedPageImage:
        """Render one 1-based page to a local image artifact."""


class PageOcrRunner(Protocol):
    runner_name: str

    def extract_text(self, image_path: Path, *, language: str) -> str:
        """Run local OCR on a rendered page image."""


class VisualReviewRenderer(Protocol):
    renderer_name: str

    def render_page(
        self,
        pdf_path: Path,
        *,
        page_number: int,
        output_path: Path,
        dpi: int,
    ) -> None:
        """Render one 1-based PDF page to a caller-selected image path."""


class VisualReviewOcrEngine(Protocol):
    engine_name: str

    def ocr_image(self, image_path: Path) -> str:
        """Return local OCR text for one rendered page image."""


class DependencyUnavailablePageImageRenderer:
    renderer_name = "dependency_unavailable"

    def count_pages(self, pdf_path: Path) -> int:
        raise LocalVisualError("local page rendering dependency is not installed")

    def render_page(
        self,
        pdf_path: Path,
        *,
        page_number: int,
        output_dir: Path,
        dpi: int,
    ) -> RenderedPageImage:
        raise LocalVisualError("local page rendering dependency is not installed")


class PyMuPdfPageImageRenderer:
    renderer_name = "pymupdf"

    def count_pages(self, pdf_path: Path) -> int:
        try:
            import fitz  # type: ignore[import-not-found]
        except ModuleNotFoundError as error:
            raise LocalVisualError(
                "local page rendering dependency is not installed"
            ) from error

        try:
            document = fitz.open(pdf_path)
        except Exception as error:  # pragma: no cover - adapter boundary
            raise LocalVisualError(str(error)) from error

        with document:
            return int(document.page_count)

    def render_page(
        self,
        pdf_path: Path,
        *,
        page_number: int,
        output_dir: Path,
        dpi: int,
    ) -> RenderedPageImage:
        try:
            import fitz  # type: ignore[import-not-found]
        except ModuleNotFoundError as error:
            raise LocalVisualError(
                "local page rendering dependency is not installed"
            ) from error

        try:
            document = fitz.open(pdf_path)
        except Exception as error:  # pragma: no cover - adapter boundary
            raise LocalVisualError(str(error)) from error

        with document:
            if page_number < 1 or page_number > document.page_count:
                raise LocalVisualError(
                    f"page {page_number} is outside PDF page range 1-{document.page_count}"
                )
            page = document.load_page(page_number - 1)
            scale = dpi / 72
            pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            output_dir.mkdir(parents=True, exist_ok=True)
            image_path = _page_image_path(pdf_path, output_dir, page_number)
            pixmap.save(str(image_path))
            return RenderedPageImage(
                page_number=page_number,
                image_path=image_path,
                width_pixels=int(pixmap.width),
                height_pixels=int(pixmap.height),
                dpi=dpi,
            )


class DependencyUnavailablePageOcrRunner:
    runner_name = "dependency_unavailable"

    def extract_text(self, image_path: Path, *, language: str) -> str:
        raise LocalVisualError("local OCR dependency is not installed")


class TesseractPageOcrRunner:
    runner_name = "tesseract"

    def extract_text(self, image_path: Path, *, language: str) -> str:
        try:
            import pytesseract  # type: ignore[import-not-found]
            from PIL import Image  # type: ignore[import-not-found]
        except ModuleNotFoundError as error:
            raise LocalVisualError("local OCR dependency is not installed") from error

        try:
            with Image.open(image_path) as image:
                return str(pytesseract.image_to_string(image, lang=language)).strip()
        except Exception as error:  # pragma: no cover - adapter boundary
            if error.__class__.__name__ == "TesseractNotFoundError":
                raise LocalVisualError("local tesseract binary is not installed") from error
            raise LocalVisualError(str(error)) from error


class PyMuPdfVisualReviewRenderer:
    renderer_name = "pymupdf"

    def render_page(
        self,
        pdf_path: Path,
        *,
        page_number: int,
        output_path: Path,
        dpi: int,
    ) -> None:
        try:
            import fitz  # type: ignore[import-not-found]
        except ModuleNotFoundError as error:
            raise LocalVisualError(
                "local page rendering dependency is not installed"
            ) from error

        try:
            document = fitz.open(pdf_path)
        except Exception as error:  # pragma: no cover - adapter boundary
            raise LocalVisualError(str(error)) from error

        with document:
            if page_number < 1 or page_number > document.page_count:
                raise LocalVisualError(
                    f"page {page_number} is outside PDF page range 1-{document.page_count}"
                )
            page = document.load_page(page_number - 1)
            scale = dpi / 72
            pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            pixmap.save(str(output_path))


class TesseractVisualReviewOcrEngine:
    engine_name = "tesseract"

    def ocr_image(self, image_path: Path) -> str:
        return TesseractPageOcrRunner().extract_text(image_path, language="deu+eng")


@dataclass(frozen=True)
class VisualOcrReviewPage:
    page_number: int
    ocr_queued: bool
    render_status: str
    ocr_status: str
    render_path: Path | None = None
    ocr_text_path: Path | None = None
    ocr_text_hash: str | None = None
    ocr_char_count: int | None = None
    failure_reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "page": self.page_number,
            "ocrQueued": self.ocr_queued,
            "renderStatus": self.render_status,
            "ocrStatus": self.ocr_status,
        }
        if self.render_path is not None:
            result["renderPath"] = str(self.render_path)
        if self.ocr_text_path is not None:
            result["ocrTextPath"] = str(self.ocr_text_path)
        if self.ocr_text_hash is not None:
            result["ocrTextHash"] = self.ocr_text_hash
        if self.ocr_char_count is not None:
            result["ocrCharCount"] = self.ocr_char_count
        if self.failure_reason is not None:
            result["failureReason"] = self.failure_reason
        return result


@dataclass(frozen=True)
class VisualOcrReviewPlan:
    pdf_path: Path
    checksum_sha256: str
    requested_pages: tuple[int, ...]
    render_enabled: bool
    ocr_enabled: bool
    write_ocr_text: bool
    output_dir: Path
    dpi: int
    extractor: str
    renderer: str | None
    ocr_engine: str | None
    external_services_enabled: bool
    pages: tuple[VisualOcrReviewPage, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "pdfPath": str(self.pdf_path),
            "checksumSha256": self.checksum_sha256,
            "requestedPages": list(self.requested_pages),
            "renderEnabled": self.render_enabled,
            "ocrEnabled": self.ocr_enabled,
            "writeOcrText": self.write_ocr_text,
            "outputDir": str(self.output_dir),
            "dpi": self.dpi,
            "extractor": self.extractor,
            "renderer": self.renderer,
            "ocrEngine": self.ocr_engine,
            "externalServicesEnabled": self.external_services_enabled,
            "networkAccess": False,
            "pages": [page.to_dict() for page in self.pages],
        }


def build_visual_ocr_review_plan(
    pdf_path: Path,
    *,
    pages: Sequence[int] = (),
    render: bool = False,
    ocr: bool = False,
    write_ocr_text: bool = False,
    output_dir: Path = Path("data/private/visual-ocr"),
    dpi: int = 200,
    min_embedded_chars: int = 40,
    extractor: RawTextExtractor | None = None,
    renderer: VisualReviewRenderer | None = None,
    ocr_engine: VisualReviewOcrEngine | None = None,
) -> VisualOcrReviewPlan:
    """Plan or run local page rendering/OCR without exposing page text."""

    if dpi < 72 or dpi > 400:
        raise ValueError("dpi must be between 72 and 400")

    assert_pdf_upload(pdf_path)
    checksum = calculate_sha256(pdf_path)
    extraction = extract_pdf_text(
        pdf_path,
        extractor=extractor,
        min_embedded_chars=min_embedded_chars,
    )
    selected_pages = _explicit_or_ocr_needed_pages(pages, extraction.pages)
    selected_renderer = renderer or (PyMuPdfVisualReviewRenderer() if render else None)
    selected_ocr_engine = ocr_engine or (TesseractVisualReviewOcrEngine() if ocr else None)

    review_pages = tuple(
        _build_visual_ocr_review_page(
            pdf_path,
            page_number=page_number,
            ocr_queued=_page_needs_ocr(page_number, extraction.pages),
            render=render,
            ocr=ocr,
            write_ocr_text=write_ocr_text,
            output_dir=output_dir,
            dpi=dpi,
            renderer=selected_renderer,
            ocr_engine=selected_ocr_engine,
        )
        for page_number in selected_pages
    )

    return VisualOcrReviewPlan(
        pdf_path=pdf_path,
        checksum_sha256=checksum,
        requested_pages=selected_pages,
        render_enabled=render,
        ocr_enabled=ocr,
        write_ocr_text=write_ocr_text,
        output_dir=output_dir,
        dpi=dpi,
        extractor=extraction.extractor,
        renderer=selected_renderer.renderer_name if selected_renderer else None,
        ocr_engine=selected_ocr_engine.engine_name if selected_ocr_engine else None,
        external_services_enabled=False,
        pages=review_pages,
    )


@dataclass(frozen=True)
class VisualOcrPage:
    page_number: int
    render_status: str
    ocr_status: str
    image_path: Path | None = None
    width_pixels: int | None = None
    height_pixels: int | None = None
    dpi: int | None = None
    image_format: str | None = None
    ocr_text_path: Path | None = None
    ocr_text_hash: str | None = None
    ocr_char_count: int | None = None
    failure_reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "page": self.page_number,
            "renderStatus": self.render_status,
            "ocrStatus": self.ocr_status,
        }
        if self.image_path is not None:
            result["imagePath"] = str(self.image_path)
        if self.width_pixels is not None:
            result["widthPixels"] = self.width_pixels
        if self.height_pixels is not None:
            result["heightPixels"] = self.height_pixels
        if self.dpi is not None:
            result["dpi"] = self.dpi
        if self.image_format is not None:
            result["imageFormat"] = self.image_format
        if self.ocr_text_path is not None:
            result["ocrTextPath"] = str(self.ocr_text_path)
        if self.ocr_text_hash is not None:
            result["ocrTextHash"] = self.ocr_text_hash
        if self.ocr_char_count is not None:
            result["ocrCharCount"] = self.ocr_char_count
        if self.failure_reason is not None:
            result["failureReason"] = self.failure_reason
        return result


@dataclass(frozen=True)
class VisualOcrBundle:
    pdf_path: Path
    checksum_sha256: str
    output_dir: Path
    page_count: int
    selected_page_count: int
    rendered_page_count: int
    ocr_page_count: int
    status: str
    renderer: str
    ocr_runner: str | None
    external_services_enabled: bool
    pages: tuple[VisualOcrPage, ...]
    failure_reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "pdfPath": str(self.pdf_path),
            "checksumSha256": self.checksum_sha256,
            "outputDir": str(self.output_dir),
            "pageCount": self.page_count,
            "selectedPageCount": self.selected_page_count,
            "renderedPageCount": self.rendered_page_count,
            "ocrPageCount": self.ocr_page_count,
            "status": self.status,
            "renderer": self.renderer,
            "ocrRunner": self.ocr_runner,
            "externalServicesEnabled": self.external_services_enabled,
            "networkAccess": False,
            "pages": [page.to_dict() for page in self.pages],
        }
        if self.failure_reason is not None:
            result["failureReason"] = self.failure_reason
        return result


def default_page_image_renderer() -> PageImageRenderer:
    try:
        import fitz  # type: ignore[import-not-found]  # noqa: F401
    except ModuleNotFoundError:
        return DependencyUnavailablePageImageRenderer()
    return PyMuPdfPageImageRenderer()


def default_page_ocr_runner() -> PageOcrRunner:
    try:
        import pytesseract  # type: ignore[import-not-found]  # noqa: F401
        import PIL  # type: ignore[import-not-found]  # noqa: F401
    except ModuleNotFoundError:
        return DependencyUnavailablePageOcrRunner()
    return TesseractPageOcrRunner()


def build_visual_ocr_bundle(
    pdf_path: Path,
    *,
    output_dir: Path,
    pages: Sequence[int] | None = None,
    dpi: int = 180,
    run_ocr: bool = False,
    write_ocr_text: bool = False,
    ocr_language: str = "deu+eng",
    renderer: PageImageRenderer | None = None,
    ocr_runner: PageOcrRunner | None = None,
) -> VisualOcrBundle:
    """Render local page images and optionally run local OCR for private review."""

    if dpi < 72 or dpi > 400:
        raise ValueError("dpi must be between 72 and 400")

    assert_pdf_upload(pdf_path)
    checksum = calculate_sha256(pdf_path)
    selected_renderer = renderer or default_page_image_renderer()
    selected_ocr_runner = ocr_runner or (default_page_ocr_runner() if run_ocr else None)

    try:
        page_count = selected_renderer.count_pages(pdf_path)
    except LocalVisualError as error:
        return VisualOcrBundle(
            pdf_path=pdf_path,
            checksum_sha256=checksum,
            output_dir=output_dir,
            page_count=0,
            selected_page_count=0,
            rendered_page_count=0,
            ocr_page_count=0,
            status="dependency_unavailable",
            renderer=selected_renderer.renderer_name,
            ocr_runner=selected_ocr_runner.runner_name if selected_ocr_runner else None,
            external_services_enabled=False,
            pages=(),
            failure_reason=str(error),
        )

    selected_pages = _validated_pages(pages, page_count)
    review_pages: list[VisualOcrPage] = []
    for page_number in selected_pages:
        review_pages.append(
            _build_visual_ocr_page(
                pdf_path,
                page_number=page_number,
                output_dir=output_dir,
                dpi=dpi,
                run_ocr=run_ocr,
                write_ocr_text=write_ocr_text,
                ocr_language=ocr_language,
                renderer=selected_renderer,
                ocr_runner=selected_ocr_runner,
            )
        )

    rendered_count = sum(1 for page in review_pages if page.render_status == "rendered")
    ocr_count = sum(1 for page in review_pages if page.ocr_status == "extracted")
    status = "ready"
    if rendered_count != len(review_pages):
        status = "needs_review"
    elif run_ocr and ocr_count != len(review_pages):
        status = "needs_review"

    return VisualOcrBundle(
        pdf_path=pdf_path,
        checksum_sha256=checksum,
        output_dir=output_dir,
        page_count=page_count,
        selected_page_count=len(selected_pages),
        rendered_page_count=rendered_count,
        ocr_page_count=ocr_count,
        status=status,
        renderer=selected_renderer.renderer_name,
        ocr_runner=selected_ocr_runner.runner_name if selected_ocr_runner else None,
        external_services_enabled=False,
        pages=tuple(review_pages),
    )


def parse_page_selection(value: str | None) -> tuple[int, ...] | None:
    """Parse comma-separated 1-based page numbers and ranges."""

    if value is None or not value.strip():
        return None

    selected: list[int] = []
    for part in value.split(","):
        token = part.strip()
        if not token:
            continue
        if "-" in token:
            start_text, end_text = token.split("-", 1)
            start = _parse_positive_page(start_text)
            end = _parse_positive_page(end_text)
            if end < start:
                raise ValueError(f"invalid descending page range: {token}")
            selected.extend(range(start, end + 1))
        else:
            selected.append(_parse_positive_page(token))

    return tuple(dict.fromkeys(selected))


def _build_visual_ocr_page(
    pdf_path: Path,
    *,
    page_number: int,
    output_dir: Path,
    dpi: int,
    run_ocr: bool,
    write_ocr_text: bool,
    ocr_language: str,
    renderer: PageImageRenderer,
    ocr_runner: PageOcrRunner | None,
) -> VisualOcrPage:
    try:
        image = renderer.render_page(
            pdf_path,
            page_number=page_number,
            output_dir=output_dir,
            dpi=dpi,
        )
    except LocalVisualError as error:
        return VisualOcrPage(
            page_number=page_number,
            render_status="render_failed",
            ocr_status="not_run",
            failure_reason=str(error),
        )

    ocr_status = "not_requested"
    ocr_text_hash = None
    ocr_char_count = None
    ocr_text_path = None
    failure_reason = None

    if run_ocr:
        if ocr_runner is None:
            ocr_status = "dependency_unavailable"
            failure_reason = "local OCR runner is not configured"
        else:
            try:
                ocr_text = ocr_runner.extract_text(image.image_path, language=ocr_language)
            except LocalVisualError as error:
                ocr_status = "ocr_failed"
                failure_reason = str(error)
            else:
                ocr_status = "extracted" if ocr_text else "empty"
                ocr_text_hash = hash_text(ocr_text)
                ocr_char_count = len(ocr_text)
                if write_ocr_text:
                    ocr_text_path = _ocr_text_path(pdf_path, output_dir, page_number)
                    ocr_text_path.write_text(ocr_text, encoding="utf-8")

    return VisualOcrPage(
        page_number=page_number,
        render_status="rendered",
        ocr_status=ocr_status,
        image_path=image.image_path,
        width_pixels=image.width_pixels,
        height_pixels=image.height_pixels,
        dpi=image.dpi,
        image_format=image.image_format,
        ocr_text_path=ocr_text_path,
        ocr_text_hash=ocr_text_hash,
        ocr_char_count=ocr_char_count,
        failure_reason=failure_reason,
    )


def _build_visual_ocr_review_page(
    pdf_path: Path,
    *,
    page_number: int,
    ocr_queued: bool,
    render: bool,
    ocr: bool,
    write_ocr_text: bool,
    output_dir: Path,
    dpi: int,
    renderer: VisualReviewRenderer | None,
    ocr_engine: VisualReviewOcrEngine | None,
) -> VisualOcrReviewPage:
    render_path = _page_image_path(pdf_path, output_dir, page_number)
    ocr_text_path = None
    ocr_text_hash = None
    ocr_char_count = None
    failure_reason = None

    if not render:
        return VisualOcrReviewPage(
            page_number=page_number,
            ocr_queued=ocr_queued,
            render_status="not_requested",
            ocr_status="not_requested",
        )

    if renderer is None:
        return VisualOcrReviewPage(
            page_number=page_number,
            ocr_queued=ocr_queued,
            render_status="dependency_unavailable",
            ocr_status="not_run",
            render_path=render_path,
            failure_reason="local page renderer is not configured",
        )

    try:
        renderer.render_page(
            pdf_path,
            page_number=page_number,
            output_path=render_path,
            dpi=dpi,
        )
    except LocalVisualError as error:
        return VisualOcrReviewPage(
            page_number=page_number,
            ocr_queued=ocr_queued,
            render_status="render_failed",
            ocr_status="not_run",
            render_path=render_path,
            failure_reason=str(error),
        )

    ocr_status = "not_requested"
    if ocr:
        if ocr_engine is None:
            ocr_status = "dependency_unavailable"
            failure_reason = "local OCR engine is not configured"
        else:
            try:
                ocr_text = ocr_engine.ocr_image(render_path).strip()
            except LocalVisualError as error:
                ocr_status = "ocr_failed"
                failure_reason = str(error)
            else:
                ocr_status = "extracted" if ocr_text else "empty"
                ocr_text_hash = hash_text(ocr_text)
                ocr_char_count = len(ocr_text)
                if write_ocr_text:
                    ocr_text_path = _ocr_text_path(pdf_path, output_dir, page_number)
                    ocr_text_path.write_text(ocr_text, encoding="utf-8")

    return VisualOcrReviewPage(
        page_number=page_number,
        ocr_queued=ocr_queued,
        render_status="rendered",
        ocr_status=ocr_status,
        render_path=render_path,
        ocr_text_path=ocr_text_path,
        ocr_text_hash=ocr_text_hash,
        ocr_char_count=ocr_char_count,
        failure_reason=failure_reason,
    )


def _validated_pages(pages: Sequence[int] | None, page_count: int) -> tuple[int, ...]:
    selected = tuple(range(1, page_count + 1)) if pages is None else tuple(pages)
    for page_number in selected:
        if page_number < 1 or page_number > page_count:
            raise ValueError(f"page {page_number} is outside PDF page range 1-{page_count}")
    return tuple(dict.fromkeys(selected))


def _explicit_or_ocr_needed_pages(
    pages: Sequence[int],
    extracted_pages: Sequence[object],
) -> tuple[int, ...]:
    if pages:
        return tuple(dict.fromkeys(pages))

    selected = [
        page.page_number
        for page in extracted_pages
        if getattr(page, "ocr_status", None) == OcrStatus.NEEDED
        or getattr(page, "embedded_text_status", None) == TextExtractionStatus.NEEDS_REVIEW
    ]
    return tuple(dict.fromkeys(selected))


def _page_needs_ocr(page_number: int, extracted_pages: Sequence[object]) -> bool:
    for page in extracted_pages:
        if getattr(page, "page_number", None) == page_number:
            return (
                getattr(page, "ocr_status", None) == OcrStatus.NEEDED
                or getattr(page, "embedded_text_status", None)
                == TextExtractionStatus.NEEDS_REVIEW
            )
    return True


def _parse_positive_page(value: str) -> int:
    try:
        page = int(value.strip())
    except ValueError as error:
        raise ValueError(f"invalid page number: {value}") from error
    if page < 1:
        raise ValueError(f"page must be 1 or greater: {value}")
    return page


def _page_image_path(pdf_path: Path, output_dir: Path, page_number: int) -> Path:
    digest = sha256(str(pdf_path.name).encode("utf-8")).hexdigest()[:8]
    return output_dir / f"{pdf_path.stem}-{digest}-p{page_number:03d}.png"


def _ocr_text_path(pdf_path: Path, output_dir: Path, page_number: int) -> Path:
    digest = sha256(str(pdf_path.name).encode("utf-8")).hexdigest()[:8]
    return output_dir / f"{pdf_path.stem}-{digest}-p{page_number:03d}.ocr.txt"
