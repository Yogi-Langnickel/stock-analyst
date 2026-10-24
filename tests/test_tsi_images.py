"""Synthetic local screenshot intake and OCR regressions."""
from __future__ import annotations

from hashlib import sha256
import importlib.util
from pathlib import Path
import struct
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import zlib

from stock_analyst.tsi_images import extract_image_document


def private_test_root():
    root = Path(__file__).resolve().parents[1] / "data/private"
    root.mkdir(parents=True, exist_ok=True)
    return root


def synthetic_png(path: Path, width: int = 320, height: int = 100) -> Path:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack('>I', len(payload)) + kind + payload + struct.pack('>I', zlib.crc32(kind + payload))
    raw = b''.join(b'\x00' + b'\xff\xff\xff' * width for _ in range(height))
    path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))
    return path


@unittest.skipUnless(importlib.util.find_spec('fitz'), 'optional local image decoder unavailable')
class ScreenshotIntakeTest(unittest.TestCase):
    def test_png_is_preserved_and_missing_ocr_is_explicit(self):
        with TemporaryDirectory(dir=private_test_root()) as directory:
            source = synthetic_png(Path(directory) / 'source.png')
            target = Path(directory) / 'private' / 'copy.png'
            with patch('stock_analyst.tsi_images._run_local_ocr', return_value={'status': 'unavailable', 'reason': 'local_ocr_dependency_unavailable', 'words': []}):
                doc = extract_image_document(source, stored_path=target, ingested_at='2026-10-25T00:00:00Z')
            self.assertEqual(source.read_bytes(), target.read_bytes())
            self.assertEqual(doc['sha256'], sha256(source.read_bytes()).hexdigest())
            self.assertEqual(doc['extraction_status'], 'ocr_unavailable')
            self.assertEqual(doc['pages'][0]['width'], 320)
            self.assertEqual(doc['pages'][0]['height'], 100)
            self.assertFalse(doc['observations'])
            self.assertIn('local_ocr_dependency_unavailable', str(doc['exceptions']))

    def test_crop_coordinates_ocr_confidence_and_missing_context_are_preserved(self):
        with TemporaryDirectory(dir=private_test_root()) as directory:
            source = synthetic_png(Path(directory) / 'source.png')
            words = [{'text': 'Synthetic', 'left': 3, 'top': 4, 'width': 30, 'height': 10, 'confidence': 50.0, 'block': 1, 'paragraph': 1, 'line': 1}]
            with patch('stock_analyst.tsi_images._run_local_ocr', return_value={'status': 'complete', 'words': words}):
                doc = extract_image_document(source, stored_path=Path(directory) / 'private/copy.png', ingested_at='2026-10-25T00:00:00Z', region=(10, 20, 200, 80))
            row = doc['observations'][0]
            self.assertEqual(row['evidence']['bbox'], [10.0, 20.0, 200.0, 80.0])
            self.assertEqual(doc['ocr_words'][0]['bbox'], [13.0, 24.0, 43.0, 34.0])
            self.assertIn('missing_header', row['unresolved'])
            self.assertIn('missing_publication_date', row['unresolved'])
            self.assertIn('cropped_context', row['unresolved'])
            self.assertIn('uncertain_ocr', row['unresolved'])
            self.assertEqual(row['review_status'], 'needs_review')
            self.assertFalse(row['exportable'])
            self.assertIsNone(row['instrument_id'])
            self.assertIsNone(row['transaction_effective_date'])

    def test_overlap_identifier_hints_remain_noncanonical(self):
        with TemporaryDirectory(dir=private_test_root()) as directory:
            source = synthetic_png(Path(directory) / 'source.png')
            words = [{'text': text, 'left': i * 40, 'top': 4, 'width': 30, 'height': 10, 'confidence': 95.0, 'block': 1, 'paragraph': 1, 'line': 1} for i, text in enumerate(['TSI', 'USA', 'WKN', 'A1B2C3'])]
            with patch('stock_analyst.tsi_images._run_local_ocr', return_value={'status': 'complete', 'words': words}):
                doc = extract_image_document(source, stored_path=Path(directory) / 'copy.png', ingested_at='2026-10-25')
            self.assertEqual(doc['overlap_hints']['wkn_candidates'], ['A1B2C3'])
            self.assertIsNone(doc['observations'][0]['instrument_id'])
            self.assertNotIn('wkn', doc['observations'][0]['printed_fields'])


    def test_body_only_product_mention_does_not_establish_header(self):
        with TemporaryDirectory(dir=private_test_root()) as directory:
            source = synthetic_png(Path(directory) / 'source.png')
            words = [{'text': text, 'left': i * 40, 'top': 70, 'width': 30, 'height': 10, 'confidence': 95.0, 'block': 1, 'paragraph': 1, 'line': 1} for i, text in enumerate(['TSI', 'USA'])]
            with patch('stock_analyst.tsi_images._run_local_ocr', return_value={'status': 'complete', 'words': words}):
                doc = extract_image_document(source, stored_path=Path(directory) / 'copy.png', ingested_at='2026-10-25')
            self.assertIsNone(doc['original_publication'])
            self.assertIsNone(doc['product'])
            self.assertIn('missing_header', doc['observations'][0]['unresolved'])


    def test_decoder_dependency_absence_is_explicit_and_retains_original(self):
        with TemporaryDirectory(dir=private_test_root()) as directory:
            source = synthetic_png(Path(directory) / 'source.png')
            with patch('stock_analyst.tsi_images.importlib.import_module', side_effect=ModuleNotFoundError):
                doc = extract_image_document(source, stored_path=Path(directory) / 'copy.png', ingested_at='2026-10-25')
            self.assertEqual(doc['extraction_status'], 'ocr_unavailable')
            self.assertIsNone(doc['pages'][0]['width'])
            self.assertIn('image_decoder_unavailable', str(doc['exceptions']))


    def test_invalid_crop_and_mismatched_magic_are_rejected(self):
        with TemporaryDirectory(dir=private_test_root()) as directory:
            root = Path(directory)
            source = synthetic_png(root / 'source.png')
            for region in [(0, 0, 400, 100), (-1, 0, 100, 100), (3, 4, 3, 5), (float('nan'), 0, 2, 2)]:
                with self.assertRaises(ValueError):
                    extract_image_document(source, stored_path=root / 'private/copy.png', ingested_at='2026-10-25', region=region)
            wrong = root / 'wrong.jpg'; wrong.write_bytes(source.read_bytes())
            with self.assertRaisesRegex(ValueError, 'image'):
                extract_image_document(wrong, stored_path=root / 'private/wrong.jpg', ingested_at='2026-10-25')
            corrupt = root / 'corrupt.png'; corrupt.write_bytes(b'\x89PNG\r\n\x1a\ncorrupt')
            with self.assertRaisesRegex(ValueError, 'image'):
                extract_image_document(corrupt, stored_path=root / 'private/corrupt.png', ingested_at='2026-10-25')

    def test_jpeg_decode_and_no_ocr_are_explicit(self):
        import fitz
        with TemporaryDirectory(dir=private_test_root()) as directory:
            root = Path(directory)
            source = root / 'source.jpeg'
            pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 160, 80), False)
            pix.clear_with(255); source.write_bytes(pix.tobytes('jpeg'))
            doc = extract_image_document(source, stored_path=root / 'private/copy.jpeg', ingested_at='2026-10-25', ocr=False)
            self.assertEqual(doc['media_type'], 'image/jpeg')
            self.assertEqual(doc['extraction_status'], 'ocr_not_requested')
            self.assertEqual(doc['pages'][0]['width'], 160)

    def test_source_change_does_not_overwrite_retained_original(self):
        with TemporaryDirectory(dir=private_test_root()) as directory:
            root = Path(directory)
            source = synthetic_png(root / 'source.png')
            stored = root / 'private/copy.png'; stored.parent.mkdir(); stored.write_bytes(b'existing source')
            with self.assertRaises(ValueError):
                extract_image_document(source, stored_path=stored, ingested_at='2026-10-25', ocr=False)
            self.assertEqual(stored.read_bytes(), b'existing source')


class OcrDependencyTest(unittest.TestCase):
    def test_missing_executable_is_unavailable(self):
        from stock_analyst.tsi_images import _run_local_ocr
        with patch('stock_analyst.tsi_images.shutil.which', return_value=None):
            result = _run_local_ocr(Path('/private/tmp/unused.png'))
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['words'], [])

    def test_missing_supported_language_models_is_unavailable(self):
        from stock_analyst.tsi_images import _run_local_ocr
        listed = subprocess.CompletedProcess(['tesseract', '--list-langs'], 0, 'List of available languages (1):\nosd\n', '')
        with patch('stock_analyst.tsi_images.shutil.which', return_value='/local/tesseract'), patch('stock_analyst.tsi_images.subprocess.run', return_value=listed) as runner:
            result = _run_local_ocr(Path('/private/tmp/unused.png'))
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['reason'], 'local_ocr_language_models_unavailable')
        self.assertEqual(result['words'], [])
        self.assertEqual(runner.call_count, 1)


    def test_tsv_word_coordinates_and_confidence(self):
        from stock_analyst.tsi_images import _parse_tsv
        tsv = 'level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n5\t1\t1\t1\t1\t1\t10\t20\t30\t8\t92.4\tSynthetic\n'
        words = _parse_tsv(tsv)
        self.assertEqual(words[0]['text'], 'Synthetic')
        self.assertEqual(words[0]['confidence'], 92.4)
        self.assertEqual(words[0]['left'], 10)


if __name__ == '__main__':
    unittest.main()
