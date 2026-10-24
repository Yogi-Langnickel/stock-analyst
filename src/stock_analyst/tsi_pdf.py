"""Dedicated, local modern TSI USA adapter. No DA calendar or skip policy."""

from __future__ import annotations

from datetime import date
from hashlib import sha256
import re

from stock_analyst.tsi_records import make_observation, review_fingerprint

DATE = re.compile(r'(?<!\d)(\d{2})\.(\d{2})\.(20\d{2})(?!\d)')
WKN = re.compile(r'^[A-Z0-9]{6}$')


def dates_in(text: str) -> list[str]:
    result = []
    for day, month, year in DATE.findall(text):
        try:
            value = date(int(year), int(month), int(day)).isoformat()
        except ValueError:
            continue
        if value not in result:
            result.append(value)
    return result


def classify_document(cover: str, filename: str = '') -> dict:
    """Filename is deliberately not publication/date authority."""
    upper = cover.upper()
    if 'AKTIENREPORT' in upper:
        product = 'Aktienreports'
    elif 'PREMIUM' in upper and 'TSI' in upper:
        product = 'TSI Premium'
    elif ('TSI' in upper and 'USA' in upper) or 'TSI-USA.DE' in upper:
        product = 'TSI USA'
    elif 'TSI' in upper or 'TREND-SIGNAL' in upper or 'TRENDSIGNAL' in upper:
        product = 'TSI (product unresolved)'
    else:
        product = 'Unknown publication'
    header_dates = []
    for match in re.finditer(r'\d{2}\.\d{2}\.20\d{2}\s+Nr\.?\s*\d', cover):
        header_dates.extend(dates_in(match.group()))
    header_dates = list(dict.fromkeys(header_dates))
    # Older publications retain dates only when explicitly printed; no filename authority.
    dates = header_dates if product == 'TSI USA' else dates_in(cover[:500])
    publication_date = dates[0] if len(dates)==1 else None
    supported = (product == 'TSI USA' and publication_date is not None
                 and publication_date >= '2026-01-01' and 'TSI-USA.DE' in upper)
    return dict(original_publication='Aktienreports' if product == 'Aktienreports' else
                ('TSI' if product.startswith('TSI') else 'Unknown publication'),
                product=product, publication_date=publication_date, supported=supported,
                date_conflicts=dates if len(dates)>1 else [])


def _text(words: list) -> str:
    lines = {}
    for w in sorted(words, key=lambda w: (round(w[1] / 3), w[0])):
        lines.setdefault(round(w[1] / 3), []).append(w[4])
    return '\n'.join(' '.join(line) for line in lines.values())


def parse_table_rows(words: list, kind: str, boundaries: list[float], width: float,
                     *, portfolio_stop: bool = False, transaction_stop: bool = True) -> tuple:
    """Read known columns, preserving printed strings and unresolved rows."""
    scale = width / 595.276
    if kind == 'ranking':
        edges = [42, 65, 85, 195, 228, 249, 335, 378]
        keys = ['rank', 'rank_change', 'name', 'score', 'score_change',
                'last_five_issues', 'high_low_comparison']
    elif kind == 'portfolio_snapshot':
        edges = [63, 130, 170, 200, 255, 310, 360, 410, 451, 499, 553]
        keys = ['name', 'wkn', 'quantity', 'purchase_date', 'purchase_price',
                'current_price', 'position_value', 'rank', 'weight_percent', 'performance_percent']
        if portfolio_stop:
            edges = [63,130,170,200,255,298,340,389,433,461,506,553]
            keys = ['name','wkn','quantity','purchase_date','purchase_price','current_price',
                    'position_value','stop_price','rank','weight_percent','performance_percent']
    elif kind == 'transaction':
        edges = [42,92,190,237,282,340,391,439,492,553]
        keys = ['action','name','wkn','quantity','effective_date','price','stop',
                'weight_percent','performance_percent']
        if not transaction_stop:
            edges=[42,96,211,253,301,377,434,487,553]
            keys=['action','name','wkn','quantity','effective_date','price','weight_percent',
                  'performance_percent']
    elif kind == 'derivative':
        edges = [42, 100, 149, 191, 234, 276, 314, 347, 393, 423, 451, 497, 554]
        keys = ['underlying_name', 'wkn_and_alternative', 'purchase_date_and_issue',
                'purchase_price', 'current_price', 'limit_purchase_price', 'omega_or_leverage',
                'expiry', 'targets', 'stop', 'performance_percent', 'printed_status']
    else:
        edges = [42, 150, 192, 242, 280, 324, 367, 411, 452, 497, 554]
        keys = ['name', 'wkn', 'purchase_date', 'issue', 'purchase_price',
                'current_price', 'target', 'stop', 'performance_percent', 'printed_status']
    edges = [e * scale for e in edges]
    rows, exceptions = [], []
    for top, bottom in zip(boundaries, boundaries[1:]):
        selected = [w for w in words if top <= (w[1]+w[3])/2 < bottom
                    and edges[0] <= w[0] < edges[-1]]
        if not selected:
            continue
        fields = {key: _text([w for w in selected if left <= w[0] < right]).strip()
                  for key, left, right in zip(keys, edges, edges[1:])}
        raw = _text(selected)
        box = [edges[0], top, edges[-1], bottom]
        valid = (fields.get('rank', '').isdigit() and fields.get('score', '').isdigit()
                 and fields.get('name')) if kind == 'ranking' else bool(
                     fields.get('name') or fields.get('underlying_name'))
        if kind != 'ranking':
            fields['instrument_type'] = 'derivative' if kind == 'derivative' else 'stock'
            fields['currency'] = 'EUR'
            if kind == 'derivative':
                identifiers = re.findall(r'\b[A-Z0-9]{6}\b', fields['wkn_and_alternative'])
                fields['wkn'] = identifiers[0] if identifiers else None
                fields['alternative_wkn'] = identifiers[1:] if len(identifiers) > 1 else []
                valid = valid and bool(identifiers)
            else:
                valid = valid and bool(WKN.fullmatch(fields.get('wkn', '')))
        if valid:
            rows.append(dict(printed_fields=fields, bbox=box, source_text=raw))
        else:
            exceptions.append(dict(reason='unresolved_table_row', bbox=box, source_text=raw))
    return rows, exceptions


def _row_boundaries(words: list, kind: str, width: float) -> list[float]:
    scale = width / 595.276
    if kind == 'ranking':
        # Company-start positions independently inventory rows even if a rank
        # or score is malformed/missing. Such candidates become exceptions.
        anchors = [w[1] for w in words if 87*scale <= w[0] < 89*scale
                   and 130 < w[1] < 795]
    elif kind=='transaction':
        anchors=[w[1] for w in words if 42*scale<=w[0]<70*scale and w[1]>500
                 and w[4] in ('Kauf','Verkauf')]
    else:
        left, right = ((130, 170) if kind == 'portfolio_snapshot' else
                       ((100, 149) if kind == 'derivative' else (150, 192)))
        minimum = 130 if kind == 'portfolio_snapshot' else 474
        anchors = [w[1] for w in words if left*scale <= w[0] < right*scale
                   and minimum <= w[1] < 780 and WKN.fullmatch(w[4])]
        name_left=63 if kind=='portfolio_snapshot' else 45
        independent=[w[1] for w in words if name_left*scale<=w[0]<(name_left+2)*scale
                     and minimum<=w[1]< (375 if kind=='portfolio_snapshot' else 755)]
        if independent:
            anchors=independent
        # Alternative warrants are evidence within the same printed row.
        if kind != 'ranking':
            grouped = []
            for anchor in sorted(anchors):
                if not grouped or anchor-grouped[-1] > 15:
                    grouped.append(anchor)
            anchors = grouped
    anchors = sorted(set(round(y, 2) for y in anchors))
    if not anchors:
        return []
    # Rows can have wrapped company names above the identifier baseline.
    margin = 5 if kind == 'ranking' else 10
    return [anchors[0]-margin] + [(a+b)/2+3 for a,b in zip(anchors,anchors[1:])] + [anchors[-1]+17]


def _as_of_date(text: str) -> str | None:
    matches=[]
    for match in re.finditer(r'Stand\s*:?\s*\d{2}\.\d{2}\.20\d{2}',text,re.I):
        matches.extend(dates_in(match.group()))
    matches=list(dict.fromkeys(matches))
    return matches[0] if len(matches)==1 else None


def _top_tip_rows(page) -> list[dict]:
    import fitz
    words=page.get_text('words')
    header=[w for w in words if w[4] in ('OS','Aktie') and 90<w[1]<150 and w[0]>430]
    if len(header)!=2:
        return []
    labels={'WKN':'wkn','Kurs':'price','Ziel':'target','Stopp':'stop',
            'Kauf-Limit':'limit_purchase_price','Omega':'omega','Laufzeit':'expiry',
            'Ersatzschein':'alternative_wkn'}
    company=page.get_text(clip=fitz.Rect(399,80,553,105)).strip()
    result=[]
    for instrument,left,right in [('derivative',450,502),('stock',502,554)]:
        fields=dict(name=company,instrument_type=instrument,currency='EUR')
        for label in [w for w in words if 399<w[0]<450 and 120<w[1]<325]:
            if label[4] not in labels:
                continue
            key=labels[label[4]]
            if key=='target':
                number=' '.join(w[4] for w in words if 399<w[0]<450 and abs(w[1]-label[1])<3)
                key='target_2' if '2' in number else 'target_1'
            value=_text([w for w in words if left<=w[0]<right and abs(w[1]-label[1])<4])
            fields[key]=value
        if WKN.fullmatch(fields.get('wkn','')):
            bbox=[left,105,right,325]
            raw=page.get_text(clip=fitz.Rect(399,80,554,325))
            result.append(dict(printed_fields=fields,bbox=bbox,source_text=raw))
    return result


def extract_pdf_document(path, *, stored_path, ingested_at: str) -> dict:
    try:
        import fitz
    except ImportError:
        raise RuntimeError('Local PDF extraction dependency unavailable') from None
    checksum = sha256(path.read_bytes()).hexdigest()
    with fitz.open(path) as pdf:
        cover = pdf[0].get_text() if len(pdf) else ''
        identity = classify_document(cover, path.name)
        if identity['product']=='Unknown publication':
            printed_headers='\n'.join(p.get_text(clip=fitz.Rect(0,0,p.rect.width,110)) for p in pdf)
            if 'AKTIENREPORT' in printed_headers.upper():
                identity.update(original_publication='Aktienreports',product='Aktienreports')
        document = dict(document_id='doc_'+checksum, sha256=checksum, aliases=[str(path.resolve())],
                        media_type='application/pdf', stored_path=str(stored_path.resolve()),
                        ingested_at=ingested_at, **{k:v for k,v in identity.items() if k!='supported'},
                        extraction_status='parsed' if identity['supported'] else 'unsupported',
                        pages=[], observations=[], exceptions=[])
        document['document_kind']=('special_report' if document['product']=='Aktienreports' else
            ('transaction_notice' if len(pdf)==1 and 'TRANSAKTION' in cover.upper() else 'issue'))
        universe = None
        for number, page in enumerate(pdf, 1):
            text = page.get_text(); words = page.get_text('words')
            box = [0, 0, float(page.rect.width), float(page.rect.height)]
            source_header = page.get_text(clip=fitz.Rect(0,0,page.rect.width,70))
            source_date = classify_document(source_header)['publication_date']
            source_date_conflict = bool(source_date and source_date!=document['publication_date'])
            inventory = dict(number=number, width=page.rect.width, height=page.rect.height,
                             extraction_method='embedded_text', layout_status='unsupported',
                             printed_publication_date=source_date,
                             candidate_count=0, observation_count=0, observation_ids=[], exception_ids=[])
            document['pages'].append(inventory)

            def exception(reason, bbox=box, source_text=text):
                item = dict(exception_id='exception_'+sha256(
                    f'{checksum}:{number}:{bbox}:{reason}'.encode()).hexdigest(),
                            page=number, bbox=list(bbox), reason=reason, source_text=source_text,
                            document_sha256=checksum)
                document['exceptions'].append(item)
                inventory['exception_ids'].append(item['exception_id'])

            def record(kind, bbox, fields, raw, **kwargs):
                fields=dict(fields)
                if source_date:
                    fields['source_page_publication_date']=source_date
                if source_date_conflict:
                    kwargs['unresolved']=list(kwargs.get('unresolved',[]))+[
                        'source_page_publication_date_conflict']
                row = make_observation(document, kind, number, bbox, fields,
                                       source_text=raw, **kwargs)
                document['observations'].append(row)
                inventory['observation_ids'].append(row['observation_id'])

            if not identity['supported']:
                exception('unsupported_source_format')
                continue
            if source_date_conflict:
                exception('source_page_publication_date_conflict',[0,0,page.rect.width,70],source_header)
            if not text.strip():
                inventory['layout_status'] = 'exception'
                exception('embedded_text_unavailable')
                continue
            header_text = page.get_text(clip=fitz.Rect(0,0,page.rect.width,110))
            header = header_text.upper()
            if 'TSI-RANGLISTEN' in header or 'TSI-RANGLISTE' in header:
                kind = 'ranking'
                for match in re.finditer(r'(?:TSI-Rangliste\s+)(Big Caps|Mid Caps|Small Caps|Micro Caps)', header_text, re.I):
                    universe = match.group(1).title()
            elif 'TSI-USA-Depot' in text and 'Stückzahl' in text and 'Kaufdatum' in text:
                kind = 'portfolio_snapshot'
            elif 'EMPFEHLUNGSLISTE' in header and 'Ersatzschein' in text:
                kind = 'derivative'
            elif 'EMPFEHLUNGSLISTE' in header and 'Kaufdatum' in text and 'WKN' in text:
                kind = 'recommendation'
            else:
                kind = None
            if kind:
                boundaries = _row_boundaries(words, kind, page.rect.width)
                parsed, errors = parse_table_rows(words, kind, boundaries, page.rect.width,
                    portfolio_stop=kind=='portfolio_snapshot' and 'Stoppkurs' in text)
                for item in parsed:
                    unresolved = []
                    if kind == 'recommendation' or kind == 'derivative':
                        unresolved.append('action_not_explicit_in_table')
                    if kind == 'ranking' and universe is None:
                        unresolved.append('ranking_universe_unresolved')
                    if kind == 'ranking':
                        unresolved.extend(['visual_history_markers_require_review',
                                           'rank_direction_graphics_require_review',
                                           'high_low_bar_requires_review'])
                    if kind == 'portfolio_snapshot':
                        unresolved.append('portfolio_category_band_requires_review')
                    record('recommendation' if kind=='derivative' else kind,
                           item['bbox'], item['printed_fields'], item['source_text'],
                           as_of_date=_as_of_date(text),
                           strategy='TSI USA', universe=universe if kind=='ranking' else None,
                           unresolved=unresolved)
                for item in errors:
                    exception(**item)
                inventory['candidate_count'] += len(parsed)+len(errors)
                if not boundaries:
                    exception('unsupported_table_layout')
                # Preserve all surrounding context, aggregate rows, disclaimers,
                # table captions and sidebar strategy text without trade inference.
                table_top = boundaries[0] if boundaries else page.rect.height
                table_bottom = boundaries[-1] if boundaries else 0
                context_words = [w for w in words if w[1]<table_top or w[1]>table_bottom
                                 or (kind=='ranking' and w[0]>378)]
                context = _text(context_words)
                if context.strip():
                    record('commentary', box, {'context_kind':'table_context'}, context,
                           strategy='TSI USA')
            else:
                record('commentary', box, {'context_kind':'publisher_commentary'}, text,
                       strategy='TSI USA')
                # Explicit cover top-tip evidence is separate from ranking membership.
                if number == 1 and 'Top-Tipp:' in text:
                    record('recommendation', box, {'label':'Top-Tipp', 'instrument_type':'stock'},
                           text, strategy='TSI USA', unresolved=['structured_tip_fields_unresolved'])
                if 'NEUAUFNAHME' in header and re.search(r'\bKAUF\b', text):
                    fields={'action':'Kauf','instrument_type':'stock'}
                    for label,key,pattern in [('WKN','wkn',r'[A-Z0-9]{6}'),
                        ('KAUFKURS','purchase_price',r'[\d.,]+\s*€?'),
                        ('STOPPKURS','stop_price',r'[\d.,]+\s*€?'),
                        ('KAUFDATUM','purchase_date',r'\d{2}\.\d{2}\.20\d{2}')]:
                        match=re.search(label+r'\s*:?\s*('+pattern+r')',text,re.I)
                        if match:fields[key]=match.group(1).strip()
                    title=page.get_text(clip=fitz.Rect(42,72,380,105)).strip()
                    if title:fields['name']=title
                    record('recommendation', box, fields, text, strategy='TSI USA',
                           unresolved=['printed_purchase_date_requires_execution_review'])
                # Detail tip tables require explicit evidence review rather than mixing
                # stock and warrant values into a single instrument record.
                if number == 2 and 'Ersatzschein' in text:
                    tip_rows = _top_tip_rows(page)
                    for item in tip_rows:
                        record('recommendation',item['bbox'],item['printed_fields'],
                               item['source_text'],strategy='TSI USA',
                               unresolved=['action_not_explicit_in_tip_table'])
                    if not tip_rows:
                        exception('top_tip_stock_derivative_columns_require_review')
                    inventory['candidate_count'] += max(1,len(tip_rows))
                if number == 1:
                    for block in page.get_text('blocks'):
                        raw = block[4]
                        if re.search(r'\b(?:Verkauf|Kauf)\s*:', raw):
                            record('transaction', list(block[:4]), {'printed_transaction_summary':raw},
                                   raw, strategy='TSI USA',
                                   unresolved=['transaction_effective_date_unresolved',
                                               'transaction_instruments_require_review'])
                if not (number in (1,2) or 'NEUAUFNAHME' in header or
                        'DEPOTENTWICKLUNG' in header or 'IMPRESSUM' in header or 'REGELWERK' in header):
                    exception('unsupported_modern_page_layout')
            if 'Transaktionsübersicht' in text:
                boundaries=_row_boundaries(words,'transaction',page.rect.width)
                parsed,errors=parse_table_rows(words,'transaction',boundaries,page.rect.width,
                    transaction_stop=any(w[4]=='Stoppkurs' and w[1]>500 for w in words))
                for item in parsed:
                    effective=dates_in(item['printed_fields'].get('effective_date',''))
                    record('transaction',item['bbox'],item['printed_fields'],item['source_text'],
                           strategy='TSI USA',transaction_effective_date=effective[0] if len(effective)==1 else None,
                           unresolved=[] if len(effective)==1 else ['transaction_effective_date_unresolved'])
                for item in errors:exception(**item)
                if not boundaries:exception('unsupported_transaction_table_layout')
            if 'Depotgewichtung' in text:
                sidebar_count=0
                for weight in [w for w in words if w[0]>520 and 100<w[1]<600 and '%' in w[4]]:
                    row_words=[w for w in words if 399<w[0]<554 and abs(w[1]-weight[1])<3]
                    name=_text([w for w in row_words if 419<w[0]<520])
                    if not name:name=_text([w for w in row_words if w[0]<520])
                    if not re.search(r'[A-Za-zÄÖÜäöüß]',name) or name.strip()=='Bar':continue
                    sidebar_count+=1
                    record('portfolio_snapshot',[399,weight[1]-3,554,weight[3]+3],
                           {'name':name,'weight_percent':weight[4],'snapshot_variant':'allocation_sidebar'},
                           _text(row_words),strategy='TSI USA',as_of_date=_as_of_date(text),
                           unresolved=['instrument_identity_not_printed_in_sidebar'])
                if sidebar_count<10:
                    region=[399,100,554,600]
                    exception('allocation_sidebar_alignment_requires_review',region,
                              page.get_text(clip=fitz.Rect(region)))
                    document['exceptions'][-1]['unresolved_candidate_count']=max(1,10-sidebar_count)
            inventory['observation_count']=len(inventory['observation_ids'])
            inventory['candidate_count']=sum(row['record_type']!='commentary'
                for row in document['observations'] if row['evidence']['page']==number)+sum(
                e.get('unresolved_candidate_count',1) if e['reason']!='source_page_publication_date_conflict' else 0
                for e in document['exceptions']
                if e['page']==number)
            inventory['layout_status'] = ('exception' if inventory['exception_ids'] else
                ('no_candidate' if inventory['candidate_count']==0 else 'parsed'))
        _flag_evidence_conflicts(document)
        return document


def _flag_evidence_conflicts(document: dict) -> None:
    """Keep competing publisher values; compare printed date year suffixes only."""
    grouped={}
    for row in document['observations']:
        fields=row['printed_fields'];wkn=fields.get('wkn')
        if wkn and fields.get('expiry'):
            grouped.setdefault(wkn,[]).append(row)
    document['possible_evidence_conflicts']=[]
    for rows in grouped.values():
        values={re.sub(r'(?<=\.)20(?=\d{2}\b)','',r['printed_fields']['expiry']).strip().lower()
                for r in rows}
        if len(values)>1:
            document['possible_evidence_conflicts'].append(dict(
                field='expiry',observation_ids=[r['observation_id'] for r in rows],
                review_status='needs_review'))
            for row in rows:
                row['unresolved'].append('conflicting_publisher_expiry_evidence')
                row['review_hash']=review_fingerprint(row)
