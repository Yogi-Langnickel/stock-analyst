"""Escaped, offline HTML reviewer preview for private local source registries."""
from __future__ import annotations

import base64
from datetime import date
from hashlib import sha256
import html
import json
import os
from pathlib import Path
import tempfile

PREVIEW_MARKER='<!-- stock-analyst-tsi-preview-v1 -->'

TABLES = (
    ('recommendation', 'Explicit publisher recommendations'),
    ('ranking', 'Rankings'),
    ('portfolio_snapshot', 'Publisher portfolio snapshots'),
    ('transaction', 'Explicit publisher transactions'),
    ('commentary', 'Commentary and strategy context'),
)

STYLE = '''
:root{font-family:system-ui,sans-serif;color:#172b3a;background:#eef2f5;line-height:1.45}
body{max-width:1600px;margin:auto;padding:24px}h1,h2,h3{line-height:1.2}h1{font-size:2rem}
.banner,.summary,article{background:white;padding:20px;margin-bottom:20px;border-radius:12px;border:1px solid #d1dce4}
.banner{border-left:6px solid #426276}.muted{color:#526777}.flag{display:inline-block;background:#fff2cf;color:#694f00;padding:3px 8px;border-radius:5px;font-size:.85rem}
.meta{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}.meta p{margin:2px 0}
table{width:100%;border-collapse:collapse;background:#fff;font-size:.9rem}th,td{text-align:left;vertical-align:top;padding:10px;border:1px solid #d5dfe6}th{background:#e8eff4;position:sticky;top:0}
.scroll{overflow:auto;max-height:760px;border:1px solid #d5dfe6;margin-bottom:24px}td.facts{min-width:230px;max-width:500px}dl{margin:0}dt{font-weight:600}dd{margin:0 0 5px;white-space:pre-wrap;overflow-wrap:anywhere}
pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:.8rem;max-height:250px;overflow:auto}details{margin:8px 0}summary{cursor:pointer;font-weight:600}a{color:#14648b}.source{max-width:100%;height:auto;border:1px solid #d5dfe6;display:block;margin:12px auto}.pages{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:14px}.page{padding:12px;border:1px solid #d1dce4;scroll-margin-top:12px}.empty{color:#526777;padding:14px;background:#f4f7f9}.small{font-size:.8rem}.status{white-space:nowrap}code{overflow-wrap:anywhere}
@media(max-width:700px){body{padding:10px}article,.banner,.summary{padding:12px}.pages{display:block}table{font-size:.8rem}}
'''


def _escape(value) -> str:
    if value is None or value == '':
        return 'Unresolved'
    if isinstance(value, (dict, list, tuple)):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return html.escape(str(value), quote=True)


def _facts(fields: dict) -> str:
    rows = []
    for key, value in fields.items():
        rendered = _escape(value)
        if isinstance(value, (dict, list, tuple)) or len(rendered) > 220:
            rendered = f'<details><summary>Show exact printed evidence</summary><pre>{rendered}</pre></details>'
        rows.append(f'<dt>{_escape(key)}</dt><dd>{rendered}</dd>')
    return '<dl>' + ''.join(rows) + '</dl>'


def _source_previews(document: dict) -> tuple[dict[int, str], str | None]:
    """Render only retained bytes whose full hash matches registry provenance."""
    from stock_analyst.tsi_registry import assert_private_output

    try:
        source = assert_private_output(Path(document['stored_path']))
        payload = source.read_bytes()
        if sha256(payload).hexdigest() != document.get('sha256'):
            return {}, 'Source bytes changed: preview withheld pending re-import.'
    except (KeyError, OSError, ValueError, TypeError):
        return {}, 'Retained private source unavailable: preview withheld.'
    try:
        import fitz
        images = {}
        media = document.get('media_type', '')
        if media.startswith('image/'):
            pix = fitz.Pixmap(payload)
            if pix.width > 1200 or pix.height > 1600:
                ratio = min(1200 / pix.width, 1600 / pix.height)
                pix = fitz.Pixmap(pix, max(1, int(pix.width * ratio)), max(1, int(pix.height * ratio)))
            images[1] = 'data:image/png;base64,' + base64.b64encode(pix.tobytes('png')).decode('ascii')
        elif media == 'application/pdf':
            with fitz.open(stream=payload, filetype='pdf') as pdf:
                # Unsupported legacy formats retain a cover preview. Supported
                # candidate pages each receive their own exact page preview.
                wanted = {1}
                wanted.update(int(item['evidence']['page']) for item in document.get('observations', []))
                wanted.update(int(item['number']) for item in document.get('pages', []) if item.get('layout_status') in {'parsed', 'exception'})
                for number in sorted(wanted):
                    if 1 <= number <= len(pdf):
                        page = pdf[number - 1]
                        scale = min(1200 / page.rect.width, 1600 / page.rect.height)
                        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                        images[number] = 'data:image/png;base64,' + base64.b64encode(pix.tobytes('png')).decode('ascii')
        else:
            return {}, 'Source media type unsupported for local preview.'
        return images, None
    except (ImportError, RuntimeError, ValueError, KeyError, TypeError):
        return {}, 'Local source rendering unavailable; retained source remains private.'


def _historical_label(document: dict) -> str:
    publication = document.get('publication_date')
    if not publication:
        return 'Publication date unresolved'
    try:
        published = date.fromisoformat(publication)
        ingested = date.fromisoformat(str(document.get('ingested_at', ''))[:10])
    except (ValueError, TypeError):
        return 'Publication date requires review'
    return 'Historical publication' if published < ingested else 'Publication date as printed'


def _row(document_id: str, record: dict) -> str:
    evidence = record.get('evidence') or {}
    page = evidence.get('page')
    source_link = f'#{document_id}-page-{page}'
    unresolved = record.get('unresolved') or []
    return (
        '<tr>'
        f'<td><code>{_escape(record.get("observation_id"))}</code><br><span class="flag">needs_review</span><br>non-exportable</td>'
        f'<td class="facts">{_facts(record.get("printed_fields") or {})}</td>'
        f'<td>Publication: {_escape(record.get("publication_date"))}<br>As of: {_escape(record.get("as_of_date"))}<br>Transaction effective: {_escape(record.get("transaction_effective_date"))}<br>Ingested: {_escape(record.get("ingested_at"))}</td>'
        f'<td>Strategy: {_escape(record.get("strategy"))}<br>Universe: {_escape(record.get("universe"))}<br>Instrument: {_escape(record.get("instrument_id"))}</td>'
        f'<td><a href="{_escape(source_link)}">Page {_escape(page)}</a><br>Region: {_escape(evidence.get("bbox"))}<br>Method: {_escape(evidence.get("extraction_method"))}<details><summary>Exact provenance</summary><pre>{_escape(evidence)}</pre></details></td>'
        f'<td>{_escape(unresolved)}<details><summary>Source text for review</summary><pre>{_escape(record.get("source_text"))}</pre></details></td>'
        '</tr>'
    )


def _document(document: dict, number: int) -> str:
    # DOM anchors use our own ordinal, never source-controlled IDs.
    anchor = f'document-{number}'
    images, rendering_exception = _source_previews(document)
    pages = document.get('pages', [])
    observations = document.get('observations', [])
    counts = {}
    for page in pages:
        status = page.get('layout_status', 'unresolved')
        counts[status] = counts.get(status, 0) + 1
    product = document.get('product') or document.get('original_publication') or 'Unresolved publication/product'
    parts = [f'<article id="{anchor}"><h2>{_escape(product)}</h2>',
             f'<div class="meta"><p><strong>{_escape(_historical_label(document))}</strong><br>Publication: {_escape(document.get("publication_date"))}<br>Ingestion: {_escape(document.get("ingested_at"))}</p>',
             f'<p>Status: {_escape(document.get("extraction_status"))}<br>Original publication: {_escape(document.get("original_publication"))}<br>Media: {_escape(document.get("media_type"))}</p>',
             f'<p>{len(pages)} pages; {len(observations)} observations; {len(document.get("exceptions", []))} extraction exceptions<br>Aliases: {len(document.get("aliases", []))}</p></div>',
             f'<details><summary>Document provenance and aliases</summary><code>SHA-256: {_escape(document.get("sha256"))}</code><pre>{_escape(document.get("aliases", []))}</pre></details>',
             f'<h3>Coverage</h3><p>{_escape(counts)}. Candidate counts are extraction inventory and require visual reconciliation.</p>']
    if document.get('possible_overlaps'):
        parts.append(f'<p class="flag">Possible screenshot/PDF overlap - review links only: {_escape(document["possible_overlaps"])}</p>')
    if rendering_exception:
        parts.append(f'<p class="flag">{_escape(rendering_exception)}</p>')
    parts.append('<details><summary>Source previews and page inventory</summary><div class="pages">')
    for page in pages:
        n = page.get('number')
        parts.append(f'<section class="page" id="{anchor}-page-{_escape(n)}"><h3>Page {_escape(n)}</h3><p>Status: {_escape(page.get("layout_status"))}; candidates: {_escape(page.get("candidate_count", 0))}</p>')
        if n in images:
            parts.append(f'<img class="source" src="{images[n]}" alt="Verified retained source page {_escape(n)}" loading="lazy">')
        elif not rendering_exception:
            parts.append('<p class="muted">Unsupported page; full original retained privately. Cover preview is shown on page 1.</p>')
        parts.append(f'<details><summary>Page extraction evidence</summary><pre>{_escape(page)}</pre></details></section>')
    parts.append('</div></details>')
    for kind, label in TABLES:
        matching = [row for row in observations if row.get('record_type') == kind]
        parts.append(f'<h3>{label} ({len(matching)})</h3>')
        if not matching:
            parts.append('<p class="empty">No extracted records of this type.</p>'); continue
        parts.append('<div class="scroll"><table><thead><tr><th>Observation / review</th><th>Printed facts</th><th>Dates</th><th>Identity and context</th><th>Source evidence</th><th>Unresolved and raw evidence</th></tr></thead><tbody>')
        parts.extend(_row(anchor, row) for row in matching)
        parts.append('</tbody></table></div>')
    parts.append('<details><summary>Extraction exceptions</summary>')
    for exception in document.get('exceptions', []):
        parts.append(f'<pre>{_escape(exception)}</pre>')
    parts.append('</details></article>')
    return ''.join(parts)


def write_preview(registry: dict, output_path: Path) -> Path:
    """Write a private self-contained reviewer artifact; return its local path."""
    from stock_analyst.tsi_registry import assert_private_output

    output_path = Path(output_path)
    resolved = assert_private_output(output_path)
    documents = sorted((registry.get('documents') or {}).values(),
                       key=lambda doc:(doc.get('publication_date') or '',doc.get('sha256') or ''),
                       reverse=True)
    if resolved.suffix.lower()!='.html':
        raise ValueError('Reviewer preview output must use .html')
    for document in documents:
        originals=[document.get('stored_path'),*document.get('aliases',[])]
        if any(value and Path(value).resolve()==resolved for value in originals):
            raise ValueError('Reviewer preview cannot replace source evidence')
        if any(value and Path(value).exists() and resolved.exists() and
               Path(value).samefile(resolved) for value in originals):
            raise ValueError('Reviewer preview cannot replace source evidence')
    if resolved.exists():
        with resolved.open('r',encoding='utf-8',errors='replace') as existing:
            if existing.read(len(PREVIEW_MARKER))!=PREVIEW_MARKER:
                raise ValueError('Existing file is not an owned reviewer preview')
    observation_count = sum(len(doc.get('observations', [])) for doc in documents)
    page_count = sum(len(doc.get('pages', [])) for doc in documents)
    parts = [PREVIEW_MARKER,'<!doctype html><html lang="en"><head><meta charset="utf-8">',
             '<meta name="viewport" content="width=device-width,initial-scale=1">',
             '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">',
             f'<title>Private TSI reviewer preview</title><style>{STYLE}</style></head><body>',
             '<header class="banner"><p class="muted">STOCK ANALYST / PRIVATE LOCAL REVIEW</p><h1>TSI source evidence</h1>',
             '<p><strong>All observations need manual review and are non-exportable.</strong> This summarizes publisher material for private review. It is not personal financial advice, a recommendation, or a suitability assessment.</p>',
             '<p>Ranking membership never implies Buy. Publisher portfolios describe publisher model portfolios. Snapshot disappearance does not establish a sale.</p></header>',
             f'<section class="summary"><h2>Import coverage</h2><p>{len(documents)} unique documents / {page_count} inventoried pages / {observation_count} observations</p><p>Publication, as-of, transaction-effective and ingestion dates remain separate. Unknown dates and identities require review.</p></section>']
    parts.append('<nav class="summary"><h2>Documents: newest publication first</h2><ul>')
    for number,doc in enumerate(documents,1):
        parts.append(f'<li><a href="#document-{number}">{_escape(doc.get("product"))} / '
                     f'{_escape(doc.get("publication_date"))}</a> / {_escape(doc.get("extraction_status"))} / '
                     f'{len(doc.get("observations",[]))} observations</li>')
    parts.append('</ul></nav>')
    parts.extend(_document(doc, number) for number, doc in enumerate(documents, 1))
    parts.append('</body></html>')
    resolved.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor,name=tempfile.mkstemp(prefix='.preview-',dir=resolved.parent)
    try:
        with os.fdopen(descriptor,'w',encoding='utf-8') as stream:
            stream.write(''.join(parts));stream.flush();os.fsync(stream.fileno())
        os.replace(name,resolved)
    finally:
        if Path(name).exists():Path(name).unlink()
    return output_path
