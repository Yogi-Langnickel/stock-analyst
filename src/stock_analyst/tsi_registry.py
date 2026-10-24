"""Content-addressed private document registry with atomic local imports."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

from stock_analyst.tsi_records import review_fingerprint

PRIVATE_ROOT = Path(__file__).resolve().parents[2] / 'data' / 'private'


def assert_private_output(path: Path) -> Path:
    resolved = Path(path).resolve()
    root=PRIVATE_ROOT.resolve()
    # macOS may expose the same checkout through Coding/coding spellings.
    # Compare actual directory identity, not a case-folded prefix (which could
    # admit another directory on a case-sensitive filesystem).
    for ancestor in (resolved,*resolved.parents):
        if ancestor.exists() and root.exists() and ancestor.samefile(root):
            return root/resolved.relative_to(ancestor)
    raise ValueError('TSI artifacts must remain under repository data/private')


def _is_below(path: Path, root: Path) -> bool:
    return any(parent.exists() and root.exists() and parent.samefile(root)
               for parent in (path,*path.parents))


def _checksum(path: Path) -> str:
    digest = sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def validate_registry(registry: dict, *, verify_sources: bool = True) -> dict:
    if not isinstance(registry,dict) or registry.get('schema_version') != 1 or not isinstance(
            registry.get('documents'),dict):
        raise ValueError('Unsupported or malformed private document registry')
    for checksum, doc in registry['documents'].items():
        if not isinstance(doc,dict) or len(checksum)!=64 or doc.get('sha256')!=checksum:
            raise ValueError('Malformed private document identity')
        if not all(c in '0123456789abcdef' for c in checksum):
            raise ValueError('Malformed private document checksum')
        for key in ('aliases','observations','pages','exceptions'):
            if not isinstance(doc.get(key),list):
                raise ValueError('Malformed private document structure')
        if not all(isinstance(alias,str) for alias in doc['aliases']):
            raise ValueError('Malformed private document aliases')
        if not isinstance(doc.get('ingested_at'),str) or not isinstance(doc.get('stored_path'),str):
            raise ValueError('Missing private document provenance')
        stored = assert_private_output(Path(doc['stored_path']))
        if verify_sources and (not stored.is_file() or _checksum(stored)!=checksum):
            raise ValueError('Private source missing or changed; evidence verification failed')
        for row in doc['observations']:
            if not isinstance(row,dict) or row.get('review_status')!='needs_review' or row.get(
                    'exportable') is not False or row.get('manual_review_required') is not True:
                raise ValueError('TSI local records must remain non-exportable needs_review')
            if row.get('review_hash')!=review_fingerprint(row):
                raise ValueError('Private observation values or evidence changed')
            if row.get('document_id')!=doc.get('document_id') or row.get('evidence',{}).get(
                    'document_sha256')!=checksum:
                raise ValueError('Private observation belongs to another document')
            for key in ('product','original_publication','publication_date','ingested_at'):
                if row.get(key)!=doc.get(key):
                    raise ValueError('Private observation document context changed')
        ids=[r.get('observation_id') for r in doc['observations']]
        if len(ids)!=len(set(ids)):
            raise ValueError('Duplicate private observation identity')
        coverage=[i for p in doc['pages'] for i in p.get('observation_ids',[])]
        if sorted(ids)!=sorted(coverage):
            raise ValueError('Private page coverage does not match observations')
    return registry


def load_registry(path: Path) -> dict:
    path = assert_private_output(path)
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        raise ValueError('Private registry unavailable or malformed') from None
    return validate_registry(value)


@contextmanager
def _locked(output: Path):
    lock = output/'registry.lock'
    try:
        descriptor=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    except FileExistsError:
        raise ValueError('Private registry busy; concurrent import refused') from None
    try:
        os.close(descriptor)
        yield
    finally:
        lock.unlink()


def _save(path: Path, registry: dict) -> None:
    descriptor, name = tempfile.mkstemp(prefix='.registry-',dir=path.parent)
    try:
        with os.fdopen(descriptor,'w',encoding='utf-8') as stream:
            json.dump(registry,stream,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)
            stream.flush();os.fsync(stream.fileno())
        os.replace(name,path)
    finally:
        if Path(name).exists():
            Path(name).unlink()


def import_sources(source: Path, output: Path, *, ocr: bool = True,
                   region: tuple | None = None, reprocess: bool = False) -> dict:
    from stock_analyst.tsi_pdf import extract_pdf_document
    output = assert_private_output(output)
    output.mkdir(parents=True,exist_ok=True,mode=0o700)
    source = source.resolve()
    if not source.exists():
        raise ValueError('Local source path unavailable')
    if _is_below(source,output):
        raise ValueError('Source must be outside the generated registry directory')
    candidates = sorted([source] if source.is_file() else
                        [p for p in source.rglob('*') if p.is_file() and
                         p.suffix.lower() in {'.pdf','.png','.jpg','.jpeg'} and
                         not _is_below(p.resolve(),output)])
    with _locked(output):
        target=output/'registry.json'
        registry=load_registry(target) if target.exists() else dict(schema_version=1,documents={})
        timestamp=datetime.now(timezone.utc).isoformat()
        sources=output/'sources';sources.mkdir(exist_ok=True,mode=0o700)
        processed=set()
        for path in candidates:
            extension=path.suffix.lower()
            if extension=='.pdf':
                with path.open('rb') as candidate:
                    if candidate.read(5)!=b'%PDF-':
                        raise ValueError('Invalid local PDF source')
            else:
                from stock_analyst.tsi_images import _validated_image
                _validated_image(path)
            checksum=_checksum(path)
            alias=str(path.resolve())
            previous=registry['documents'].get(checksum)
            if previous is not None and (not reprocess or checksum in processed):
                if previous['media_type'].startswith('image/') and not reprocess:
                    previous_options=previous.get('extraction_options')
                    if previous_options is None:
                        prior_region=previous.get('image_region')
                        page=previous['pages'][0]
                        full_region=[0,0,page.get('width'),page.get('height')]
                        previous_options=dict(ocr=previous.get('ocr_status')!='not_requested',
                            region=None if prior_region==full_region else prior_region)
                    requested_options=dict(ocr=ocr,region=list(region) if region is not None else None)
                    if previous_options!=requested_options:
                        raise ValueError('Cached image options require explicit --reprocess')
                doc=registry['documents'][checksum]
                doc['aliases']=sorted(set(doc['aliases']+[alias]))
                continue
            stored=sources/(checksum+extension)
            if stored.exists() and _checksum(stored)!=checksum:
                raise ValueError('Existing private source copy conflicts; import refused')
            ingested_at=previous['ingested_at'] if previous else timestamp
            if extension=='.pdf':
                if path.read_bytes()[:5]!=b'%PDF-':
                    raise ValueError('Invalid local PDF source')
                if not stored.exists():
                    descriptor=os.open(stored,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                    with os.fdopen(descriptor,'wb') as stream, path.open('rb') as original:
                        shutil.copyfileobj(original,stream)
                try:
                    doc=extract_pdf_document(stored,stored_path=stored,ingested_at=ingested_at)
                except Exception:
                    raise ValueError('Local PDF extraction failed; registry unchanged') from None
            else:
                from stock_analyst.tsi_images import extract_image_document
                doc=extract_image_document(path,stored_path=stored,ingested_at=ingested_at,
                                           region=region,ocr=ocr)
                doc['extraction_options']=dict(ocr=ocr,region=list(region) if region is not None else None)
            doc['aliases']=sorted(set((previous['aliases'] if previous else [])+[alias]))
            registry['documents'][checksum]=doc
            processed.add(checksum)
        _link_possible_overlaps(registry)
        validate_registry(registry)
        _save(target,registry)
        return registry


def _link_possible_overlaps(registry: dict) -> None:
    """Only suggest review links; never coalesce PDF/image observations."""
    pdfs=[d for d in registry['documents'].values() if d['media_type']=='application/pdf']
    images=[d for d in registry['documents'].values() if d['media_type'].startswith('image/')]
    for image in images:
        image['possible_overlaps']=[]
        # A printed identifier/date match is a candidate, never proof of equivalence.
        identifiers={r.get('printed_fields',{}).get('wkn') for r in image['observations']}
        identifiers.discard(None)
        identifiers.update(image.get('overlap_hints',{}).get('wkn_candidates',[]))
        ocr_text='\n'.join(r.get('source_text','') for r in image['observations'])
        identifiers.update(re.findall(r'\bWKN\s*:?\s*([A-Z0-9]{6})\b',ocr_text))
        for pdf in pdfs:
            common=identifiers & {r.get('printed_fields',{}).get('wkn') for r in pdf['observations']}
            if common or (image.get('publication_date') and image.get('publication_date')==pdf.get('publication_date')
                          and image.get('product')==pdf.get('product')):
                image['possible_overlaps'].append(dict(document_id=pdf['document_id'],
                    reason='printed_identifier_or_product_date_match',review_status='needs_review'))


def registry_summary(registry: dict) -> dict:
    documents=list(registry['documents'].values())
    pages=[page for doc in documents for page in doc['pages']]
    rows=[row for doc in documents for row in doc['observations']]
    return dict(document_count=len(documents),alias_count=sum(len(d['aliases']) for d in documents),
                duplicate_alias_count=sum(max(0,len(d['aliases'])-1) for d in documents),
                page_count=len(pages),observation_count=len(rows),
                observation_types={kind:sum(r['record_type']==kind for r in rows)
                                   for kind in sorted({r['record_type'] for r in rows})},
                coverage={status:sum(p['layout_status']==status for p in pages)
                          for status in ('parsed','exception','unsupported','no_candidate')},
                exception_count=sum(len(d['exceptions']) for d in documents),
                approved_count=0,exportable_count=0,private_local_only=True)
