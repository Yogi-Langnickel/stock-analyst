import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from stock_analyst.cli import run_visual_ocr_review
from stock_analyst.visual_ocr import (
    LocalVisualError,
    RenderedPageImage,
    build_visual_ocr_bundle,
    parse_page_selection,
)


def write_pdf(path: Path) -> Path:
    path.write_bytes(b"%PDF-1.7\nprivate synthetic fixture")
    return path


class StubRenderer:
    renderer_name = "stub_renderer"

    def count_pages(self, _pdf_path: Path) -> int:
        return 3

    def render_page(
        self,
        _pdf_path: Path,
        *,
        page_number: int,
        output_dir: Path,
        dpi: int,
    ) -> RenderedPageImage:
        output_dir.mkdir(parents=True, exist_ok=True)
        image_path = output_dir / f"page-{page_number:03}.png"
        image_path.write_bytes(f"page={page_number};dpi={dpi}".encode("utf-8"))
        return RenderedPageImage(
            page_number=page_number,
            image_path=image_path,
            width_pixels=1200,
            height_pixels=1800,
            dpi=dpi,
        )


class FailingRenderer:
    renderer_name = "failing_renderer"

    def count_pages(self, _pdf_path: Path) -> int:
        raise LocalVisualError("synthetic renderer unavailable")

    def render_page(
        self,
        _pdf_path: Path,
        *,
        page_number: int,
        output_dir: Path,
        dpi: int,
    ) -> RenderedPageImage:
        raise LocalVisualError("synthetic renderer unavailable")


class StubOcrRunner:
    runner_name = "stub_ocr"

    def extract_text(self, _image_path: Path, *, language: str) -> str:
        return f"Banco Sabadell OCR fixture text {language}"


class VisualOcrTest(unittest.TestCase):
    def test_parse_page_selection_accepts_ranges_and_dedupes(self) -> None:
        self.assertEqual(parse_page_selection("22,62-63,22"), (22, 62, 63))
        self.assertIsNone(parse_page_selection(None))

    def test_render_and_ocr_write_private_artifacts_without_returning_ocr_text(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            pdf = write_pdf(root / "DA_2026_03.pdf")
            output_dir = root / "private" / "visual-ocr"
            bundle = build_visual_ocr_bundle(
                pdf,
                pages=(2,),
                output_dir=output_dir,
                dpi=150,
                run_ocr=True,
                write_ocr_text=True,
                renderer=StubRenderer(),
                ocr_runner=StubOcrRunner(),
            )

            payload = bundle.to_dict()
            image_path = Path(str(payload["pages"][0]["imagePath"]))
            text_path = Path(str(payload["pages"][0]["ocrTextPath"]))

            self.assertTrue(image_path.exists())
            self.assertTrue(text_path.exists())
            self.assertEqual(payload["status"], "ready")
            self.assertEqual(payload["renderedPageCount"], 1)
            self.assertEqual(payload["ocrPageCount"], 1)
            self.assertEqual(payload["pages"][0]["renderStatus"], "rendered")
            self.assertEqual(payload["pages"][0]["ocrStatus"], "extracted")
            self.assertEqual(payload["pages"][0]["ocrCharCount"], 39)
            self.assertNotIn("Banco Sabadell", json.dumps(payload))
            self.assertIn("Banco Sabadell", text_path.read_text(encoding="utf-8"))

    def test_dependency_failure_is_reported_without_raising(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            pdf = write_pdf(root / "DA_2026_03.pdf")
            bundle = build_visual_ocr_bundle(
                pdf,
                output_dir=root / "private",
                renderer=FailingRenderer(),
            )

        self.assertEqual(bundle.status, "dependency_unavailable")
        self.assertEqual(bundle.failure_reason, "synthetic renderer unavailable")
        self.assertEqual(bundle.pages, ())

    def test_cli_visual_ocr_review_renders_selected_pages(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            pdf = write_pdf(root / "DA_2026_03.pdf")
            result = run_visual_ocr_review(
                pdf,
                pages=(1,),
                output_dir=root / "private" / "visual-ocr",
                ocr=False,
            )

        self.assertIn("status", result)
        self.assertFalse(result["externalServicesEnabled"])


if __name__ == "__main__":
    unittest.main()
