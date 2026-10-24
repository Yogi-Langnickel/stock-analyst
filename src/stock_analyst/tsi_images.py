"""Validated, private screenshot intake and local-only OCR.

OCR is evidence for manual review. It never infers an instrument, trade, approval,
or personal holding. Optional dependency failures are explicit data statuses.
"""
from __future__ import annotations

import csv
from hashlib import sha256
import importlib
import io
import math
from pathlib import Path
import re
import shutil
import subprocess
from tempfile import TemporaryDirectory

MAX_IMAGE_PIXELS = 40_000_000
MAX_IMAGE_BYTES = 40 * 1024 * 1024
OCR_VERSION = 'tsi-local-tesseract-tsv-v1'


def _parse_tsv(payload: str) -> list[dict]:
    words = []
    try:
        rows = csv.DictReader(io.StringIO(payload), delimiter='\t', quoting=csv.QUOTE_NONE)
        for row in rows:
            if row.get('level') != '5' or not row.get('text', '').strip():
                continue
            word = {
                'text': row['text'].strip(), 'left': int(row['left']),
                'top': int(row['top']), 'width': int(row['width']),
                'height': int(row['height']), 'confidence': float(row['conf']),
                'block': int(row['block_num']), 'paragraph': int(row['par_num']),
                'line': int(row['line_num']),
            }
            if not math.isfinite(word['confidence']) or not 0 <= word['confidence'] <= 100 or min(word['left'], word['top']) < 0 or min(word['width'], word['height']) <= 0:
                raise ValueError('invalid OCR coordinates')
            words.append(word)
    except (KeyError, TypeError, ValueError, csv.Error) as error:
        raise ValueError('local_ocr_invalid_response') from error
    return words


def _run_local_ocr(image_path: Path) -> dict:
    """Capture local Tesseract TSV without placing source text in logs."""
    executable = shutil.which('tesseract')
    if executable is None:
        return {'status': 'unavailable', 'reason': 'local_ocr_dependency_unavailable', 'words': []}
    try:
        # Tesseract's normal German model is preferred; eng is an explicit local
        # fallback, retaining the language in extraction provenance.
        listed = subprocess.run([executable, '--list-langs'], capture_output=True, text=True, timeout=10, check=False)
        languages = set(listed.stdout.splitlines())
        if listed.returncode != 0 or not languages.intersection({'deu', 'eng'}):
            return {'status': 'unavailable', 'reason': 'local_ocr_language_models_unavailable', 'words': []}
        language = 'deu+eng' if {'deu', 'eng'} <= languages else ('deu' if 'deu' in languages else 'eng')
        result = subprocess.run([executable, str(image_path), 'stdout', '-l', language, '--psm', '6', 'tsv'], capture_output=True, text=True, timeout=60, check=False)
        if result.returncode != 0:
            return {'status': 'failed', 'reason': 'local_ocr_failed', 'words': [], 'language': language}
        return {'status': 'complete', 'words': _parse_tsv(result.stdout), 'language': language}
    except (FileNotFoundError, ModuleNotFoundError):
        return {'status': 'unavailable', 'reason': 'local_ocr_dependency_unavailable', 'words': []}
    except (OSError, subprocess.TimeoutExpired, UnicodeError, ValueError):
        return {'status': 'failed', 'reason': 'local_ocr_failed', 'words': []}


def _validated_image(path: Path):
    suffix = path.suffix.lower()
    if suffix not in {'.png', '.jpg', '.jpeg'}:
        raise ValueError('image must be PNG or JPEG')
    try:
        if not path.is_file() or path.stat().st_size > MAX_IMAGE_BYTES:
            raise ValueError('image missing or exceeds local size limit')
        payload = path.read_bytes()
    except OSError as error:
        raise ValueError('image cannot be read') from error
    valid = payload.startswith(b'\x89PNG\r\n\x1a\n') if suffix == '.png' else payload.startswith(b'\xff\xd8\xff')
    if not valid:
        raise ValueError('image extension and content do not match')
    try:
        fitz = importlib.import_module('fitz')
    except ModuleNotFoundError:
        return payload, None, 'image_decoder_unavailable'
    try:
        # Reading dimensions before a full pixel decode bounds decompression.
        image = fitz.open(stream=payload, filetype='png' if suffix == '.png' else 'jpeg')
        with image:
            info = image[0].get_image_info()
            width = int(info[0]['width']) if info else 0
            height = int(info[0]['height']) if info else 0
        if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
            raise ValueError('image dimensions invalid or exceed local limit')
        pix = fitz.Pixmap(payload)
        if pix.width != width or pix.height != height:
            raise ValueError('image dimensions inconsistent')
        return payload, pix, None
    except Exception as error:
        raise ValueError('image cannot be decoded or exceeds local dimensions') from error


def _crop_region(region, width: int, height: int) -> list[float]:
    if region is None:
        return [0.0, 0.0, float(width), float(height)]
    try:
        values = [float(value) for value in region]
    except (TypeError, ValueError) as error:
        raise ValueError('image crop coordinates invalid') from error
    if len(values) != 4 or not all(math.isfinite(value) for value in values):
        raise ValueError('image crop coordinates invalid')
    left, top, right, bottom = values
    if not (0 <= left < right <= width and 0 <= top < bottom <= height):
        raise ValueError('image crop coordinates outside original dimensions')
    if any(value != int(value) for value in values):
        raise ValueError('image crop coordinates must be whole pixels')
    return values


def _screenshot_exception(document_hash: str, reason: str, bbox: list | None) -> dict:
    key = sha256(f'{document_hash}:{reason}:{bbox}'.encode()).hexdigest()
    return {'exception_id': f'ex_{key}', 'page': 1, 'bbox': bbox, 'reason': reason, 'status': 'unresolved'}


def extract_image_document(path: Path, *, stored_path: Path, ingested_at: str,
                           region: tuple | None = None, ocr: bool = True) -> dict:
    """Retain a validated original and derive uncertain local OCR evidence."""
    from stock_analyst.tsi_registry import assert_private_output
    from stock_analyst.tsi_records import make_observation

    path = Path(path)
    stored_path = assert_private_output(Path(stored_path))
    payload, pix, unavailable = _validated_image(path)
    checksum = sha256(payload).hexdigest()
    width, height = (pix.width, pix.height) if pix is not None else (None, None)
    crop = _crop_region(region, width, height) if pix is not None else None
    if region is not None and pix is None:
        raise ValueError('image crop cannot be validated without local decoder')
    if stored_path.exists() and stored_path.read_bytes() != payload:
        raise ValueError('retained original image differs; refusing overwrite')
    stored_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not stored_path.exists():
        stored_path.write_bytes(payload)
        stored_path.chmod(0o600)
    doc = {
        'document_id': f'doc_{checksum}', 'sha256': checksum,
        'aliases': [str(path.resolve())], 'media_type': 'image/png' if path.suffix.lower() == '.png' else 'image/jpeg',
        'original_publication': None, 'product': None, 'publication_date': None,
        'ingested_at': ingested_at, 'stored_path': str(stored_path),
        'extraction_status': 'ocr_pending', 'parser_version': OCR_VERSION,
        'pages': [], 'observations': [], 'exceptions': [], 'ocr_words': [],
        'image_region': crop, 'possible_overlaps': [], 'overlap_hints': {},
        'context_flags': ['screenshot_context_unverified'],
    }
    page = {'number': 1, 'width': width, 'height': height,
            'extraction_method': 'local_tesseract_tsv', 'layout_status': 'exception',
            'candidate_count': 0, 'observation_ids': [], 'exception_ids': []}
    doc['pages'].append(page)
    if unavailable:
        result = {'status': 'unavailable', 'reason': unavailable, 'words': []}
    elif not ocr:
        result = {'status': 'not_requested', 'reason': 'ocr_not_requested', 'words': []}
    else:
        import fitz
        left, top, right, bottom = map(int, crop)
        # Render the exact pixel crop rather than image-page coordinates (which
        # are affected by DPI metadata in PDFs produced from images).
        rgb = fitz.Pixmap(fitz.csRGB, pix) if pix.colorspace is None or pix.colorspace.n != 3 else pix
        if rgb.alpha:
            rgb = fitz.Pixmap(rgb, 0)
        crop_rect = fitz.IRect(left, top, right, bottom)
        cropped = fitz.Pixmap(fitz.csRGB, crop_rect, False)
        cropped.copy(rgb, crop_rect)
        cropped.set_origin(0, 0)
        with TemporaryDirectory(prefix='tsi-local-ocr-') as temp:
            temporary_image = Path(temp) / 'region.png'
            cropped.save(str(temporary_image))
            result = _run_local_ocr(temporary_image)
    doc['ocr_status'] = result['status']
    doc['ocr_language'] = result.get('language')
    if result['status'] != 'complete':
        doc['extraction_status'] = ('ocr_unavailable' if result['status'] == 'unavailable' else result['reason'])
        exception = _screenshot_exception(checksum, result.get('reason', 'local_ocr_failed'), crop)
        doc['exceptions'].append(exception); page['exception_ids'].append(exception['exception_id'])
        return doc
    unresolved = ['ocr_requires_manual_verification', 'screenshot_record_type_unresolved', 'missing_as_of_date', 'screenshot_context_unverified']
    left, top = crop[:2]
    lines = {}
    for word in result.get('words', []):
        x, y, w, h = (word[key] for key in ['left', 'top', 'width', 'height'])
        if x < 0 or y < 0 or x + w > crop[2] - left or y + h > crop[3] - top:
            unresolved.append('invalid_ocr_region'); continue
        retained = dict(word)
        retained['bbox'] = [left + x, top + y, left + x + w, top + y + h]
        doc['ocr_words'].append(retained)
        lines.setdefault((word['block'], word['paragraph'], word['line']), []).append(word['text'])
    source_text = '\n'.join(' '.join(words) for words in lines.values())
    if not source_text:
        exception = _screenshot_exception(checksum, 'ocr_no_text', crop)
        doc['exceptions'].append(exception); page['exception_ids'].append(exception['exception_id'])
        doc['extraction_status'] = 'ocr_no_text'
        return doc
    # Product/header evidence must occur near the top of the original image.
    # A body mention cannot restore context that a screenshot cropped away.
    header_text = ' '.join(word['text'] for word in doc['ocr_words']
                           if word['bbox'][1] < height * 0.25)
    if re.search(r'\bTSI\b', header_text, re.I):
        unresolved.append('header_requires_manual_verification')
        doc['original_publication'] = 'TSI'
        if re.search(r'\bUSA\b', header_text, re.I):
            doc['product'] = 'TSI USA'
        elif re.search(r'\bPremium\b', header_text, re.I):
            doc['product'] = 'TSI Premium'
        else:
            unresolved.append('missing_product')
    else:
        unresolved.extend(['missing_header', 'missing_product'])
    # A screenshot may show several dates with unknown roles. Preserve all
    # strings as printed rather than choosing a publication date from OCR.
    date_candidates = re.findall(r'\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b', source_text)
    unresolved.append('publication_date_role_unresolved' if date_candidates else 'missing_publication_date')
    doc['overlap_hints'] = {
        'wkn_candidates': sorted(set(re.findall(r'\bWKN\s*[:#-]?\s*([A-Z0-9]{6})\b', source_text, re.I))),
        'isin_candidates': sorted(set(re.findall(r'\b[A-Z]{2}[A-Z0-9]{9}[0-9]\b', source_text))),
        'date_candidates': date_candidates,
    }
    if region is not None:
        unresolved.append('cropped_context')
    if any(word['confidence'] < 85 for word in doc['ocr_words']):
        unresolved.append('uncertain_ocr')
    printed = {'ocr_text': source_text, 'date_candidates': date_candidates,
               'ocr_language': result.get('language'), 'ocr_words': doc['ocr_words'],
               'ocr_version': OCR_VERSION, 'ocr_identifier_candidates': doc['overlap_hints']}
    doc['context_flags'] = sorted(set(unresolved))
    observation = make_observation(doc, 'commentary', 1, crop, printed,
                                   source_text=source_text, extraction_method='local_tesseract_tsv',
                                   unresolved=sorted(set(unresolved)))
    doc['observations'].append(observation)
    doc['extraction_status'] = 'ocr_needs_review'
    page.update(layout_status='parsed', candidate_count=1, observation_ids=[observation['observation_id']])
    return doc
