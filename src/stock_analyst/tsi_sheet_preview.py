"""Bounded private TSI Google Sheets presentation; no shared-view integration.

The source registry remains the evidence ledger. This module projects a labelled
subset into one explicitly authorized private reviewer tab, never approvals.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from hashlib import sha256
import argparse
import json
import os
from pathlib import Path
import tempfile
from zoneinfo import ZoneInfo

from stock_analyst.tsi_registry import assert_private_output, load_registry, validate_registry

SHEET_TITLE = 'TSI'
OWNER_KEY = 'stock_analyst_tsi_preview_v1'
OWNER_NAME = 'stock_analyst_tsi_private_presentation'
SCHEMA_VERSION = 1
WIDTH = 17
TAIL = ['Publication date', 'As-of date', 'Transaction effective', 'Import date (UTC)',
        'Source', 'Review status / notes']
HEADERS = {
    'stock': ['WKN','Company','Publisher action','Source price','Target(s)','Stop',
              'Purchase / limit price','Publisher status','Leverage / Omega','Expiry',
              'Printed purchase date',*TAIL],
    'derivative': ['WKN','Underlying / company','Publisher action','Source price',
                   'Target(s)','Stop','Limit price','Alternative WKN','Leverage / Omega',
                   'Expiry','Publisher status',*TAIL],
    'portfolio_snapshot': ['WKN','Company','Snapshot variant','Quantity','Purchase price',
                           'Source price','Position value','Portfolio weight (%)','Stop',
                           'Printed performance (%)','Printed purchase date',*TAIL],
    'transaction': ['WKN','Company','Publisher transaction','Quantity','Printed price',
                    'Stop','Portfolio weight (%)','Printed performance (%)',
                    'Printed effective date','','',*TAIL],
    'ranking': ['WKN','Company','Universe','Rank','TSI score','Rank change','Score change',
                'High/low comparison','','','',*TAIL],
}
TITLES = {'stock':'Publisher stock recommendations',
          'derivative':'Publisher derivative recommendations',
          'portfolio_snapshot':'Publisher model portfolio snapshot',
          'transaction':'Latest available explicit publisher transactions',
          'ranking':'Ranking sample - membership is not a Buy action'}
WIDTHS = [110,220,155,125,125,115,145,155,125,125,155,125,125,145,135,210,330]


def _digest(value) -> str:
    return sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,
                             separators=(',',':'),allow_nan=False).encode()).hexdigest()


def _string(value) -> str:
    if value is None:return ''
    if isinstance(value,list):return ' / '.join(str(v) for v in value)
    if isinstance(value,(dict,tuple)):return json.dumps(value,ensure_ascii=False,sort_keys=True)
    return str(value)


def _valid_date(value) -> str | None:
    try:return date.fromisoformat(value).isoformat()
    except (TypeError,ValueError):return None


def _import_date(value: str) -> str:
    parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
    if parsed.tzinfo is None:raise ValueError('Ingestion time must include timezone')
    return parsed.astimezone(timezone.utc).date().isoformat()


def _eligible(row: dict) -> str | None:
    fields=row['printed_fields'];kind=row['record_type']
    if kind=='commentary':return 'commentary_withheld'
    if not _valid_date(row.get('publication_date')):return 'undated_or_invalid_source_date'
    if kind=='transaction' and not(fields.get('wkn') and fields.get('action') and fields.get('name')):
        return 'summary_only_transactions'
    if kind=='recommendation' and not(fields.get('wkn') and (fields.get('name') or fields.get('underlying_name'))):
        return 'unstructured_recommendations'
    if kind=='ranking' and not str(fields.get('rank','')).isdigit():return 'unresolved_ranking_position'
    return None


def _group(row: dict) -> tuple:
    fields=row['printed_fields']
    return (row.get('product'),row.get('strategy'),row['record_type'],
            fields.get('instrument_type') if row['record_type']=='recommendation' else None,
            row.get('universe'),fields.get('context_kind'),fields.get('snapshot_variant'))


def _notes(row: dict,today: date,*,currency_unresolved: bool=False) -> str:
    flags=row.get('unresolved',[])
    notes=['needs_review']
    if date.fromisoformat(row['publication_date'])<today:notes.append('Historical publisher evidence')
    if row['record_type']=='recommendation' and not row['printed_fields'].get('action'):
        notes.append('Publisher action not explicit')
    if any('conflict' in value for value in flags):notes.append('Conflicting source evidence: manual review')
    if any('graph' in value or 'category_band' in value for value in flags):
        notes.append('Graphical/source category needs review')
    if row['record_type']=='portfolio_snapshot':notes.append('Publisher portfolio, not personal holdings')
    if row['record_type']=='ranking':notes.append('Ranking only; no action inferred')
    if currency_unresolved:notes.append('Source currency unresolved')
    return ' | '.join(notes)


def _money(value,currency) -> str:
    """Attach the explicit source unit without parsing or changing its literal."""
    text=_string(value)
    if text.strip() in ('','-','—','–','n.v.','n. v.'):return text
    return text+(' '+_string(currency) if currency else ' (currency unresolved)')


def _display_row(row: dict,today: date) -> dict:
    f=row['printed_fields'];kind=row['record_type']
    table=f.get('instrument_type','stock') if kind=='recommendation' else kind
    if table not in HEADERS:raise ValueError('Unsupported presentation observation type')
    values=[f.get('wkn'),f.get('name') or f.get('underlying_name')]
    if kind=='recommendation':
        targets=f.get('target') or f.get('targets')
        if not targets:
            targets=' / '.join(_string(f[k]) for k in ('target_1','target_2') if f.get(k))
        values += [f.get('action'), f.get('current_price') or f.get('price'),targets,f.get('stop'),
                   f.get('limit_purchase_price') or (f.get('purchase_price') if table=='stock' else None)]
        if table=='derivative':
            values += [f.get('alternative_wkn'),f.get('omega_or_leverage') or f.get('leverage') or f.get('omega'),
                       f.get('expiry'),f.get('printed_status')]
        else:
            values += [f.get('printed_status'),f.get('leverage') or f.get('omega'),f.get('expiry'),f.get('purchase_date')]
    elif kind=='portfolio_snapshot':
        values += [f.get('snapshot_variant') or 'full portfolio table',f.get('quantity'),f.get('purchase_price'),
                   f.get('current_price'),f.get('position_value'),f.get('weight_percent'),
                   f.get('stop_price'),f.get('performance_percent'),f.get('purchase_date')]
    elif kind=='transaction':
        values += [f.get('action'),f.get('quantity'),f.get('price'),f.get('stop'),f.get('weight_percent'),
                   f.get('performance_percent'),f.get('effective_date'),'','']
    else:
        values += [row.get('universe'),f.get('rank'),f.get('score'),f.get('rank_change'),f.get('score_change'),
                   f.get('high_low_comparison'),'','','']
    monetary_indexes=({'stock':(3,4,5,6),'derivative':(3,4,5,6),
                       'portfolio_snapshot':(4,5,6,8),'transaction':(4,5)}).get(table,())
    currency_unresolved=not f.get('currency') and any(_string(values[i]).strip() not in ('','-','—','–','n.v.','n. v.') for i in monetary_indexes)
    for index in monetary_indexes:values[index]=_money(values[index],f.get('currency'))
    source=f"{row.get('product') or 'Unresolved product'} | p.{row['evidence']['page']}"
    values += [row['publication_date'],row.get('as_of_date'),row.get('transaction_effective_date'),
               _import_date(row['ingested_at']),source,_notes(row,today,currency_unresolved=currency_unresolved)]
    if len(values)!=WIDTH:raise ValueError('Presentation row width mismatch')
    return dict(values=[_string(v) for v in values],observation_id=row['observation_id'],
                review_hash=row['review_hash'],binding={
                    key:row.get(key) for key in ('document_id','record_type','product','strategy','universe',
                        'publication_date','as_of_date','transaction_effective_date','ingested_at',
                        'instrument_id','printed_fields','evidence','unresolved')})


def build_preview_plan(registry: dict,*,today: date | None=None,ranking_limit: int=5) -> dict:
    """Select an explicit subset; never coalesce observations by instrument."""
    validate_registry(registry,verify_sources=False)
    today=today or datetime.now(ZoneInfo('Australia/Melbourne')).date()
    if not isinstance(today,date) or not 1<=ranking_limit<=20:raise ValueError('Invalid preview options')
    groups=defaultdict(list);dispositions=Counter()
    all_rows=[row for doc in registry['documents'].values() for row in doc['observations']]
    for row in all_rows:
        reason=_eligible(row)
        if reason:dispositions[reason]+=1
        else:groups[_group(row)].append(row)
    sections=[]
    for group,rows in sorted(groups.items(),key=lambda item:tuple(_string(v) for v in item[0])):
        newest=max(row['publication_date'] for row in rows)
        latest=[row for row in rows if row['publication_date']==newest]
        dispositions['older_source_observations']+=len(rows)-len(latest)
        kind=group[2];table=group[3] if kind=='recommendation' else kind
        if table not in HEADERS:
            dispositions['unsupported_instrument_type']+=len(latest);continue
        latest.sort(key=lambda row:(int(row['printed_fields']['rank']) if kind=='ranking' else row['evidence']['page'],row['observation_id']))
        selected=latest[:ranking_limit] if kind=='ranking' else latest
        dispositions['ranking_sample_omissions']+=len(latest)-len(selected)
        subtitle=f"{group[0] or 'Unresolved product'} | {group[1] or 'Unresolved strategy'} | source {newest}"
        if group[4]:subtitle+=f' | {group[4]}'
        if group[6]:subtitle+=f' | {group[6]}'
        if kind=='transaction':subtitle+=' | historical transactions, not current trade instructions'
        sections.append(dict(record_type=kind,table_type=table,title=TITLES[table],subtitle=subtitle,
                             source_group=list(group),publication_date=newest,headers=HEADERS[table],
                             available_count=len(latest),shown_count=len(selected),
                             omitted_count=len(latest)-len(selected),
                             rows=[_display_row(row,today) for row in selected]))
    order={'stock':0,'derivative':1,'portfolio_snapshot':2,'transaction':3,'ranking':4}
    sections.sort(key=lambda s:(order[s['table_type']],s['subtitle']))
    coverage=[]
    for doc in sorted(registry['documents'].values(),key=lambda d:(d.get('publication_date') or '',d['sha256']),reverse=True):
        coverage.append(dict(product=doc.get('product'),publication_date=doc.get('publication_date'),
                             status=doc['extraction_status'],page_count=len(doc['pages']),
                             observation_count=len(doc['observations']),exception_count=len(doc['exceptions'])))
    source_coverage=dict(supported_document_count=sum(d['status']!='unsupported' for d in coverage),
                         unsupported_document_count=sum(d['status']=='unsupported' for d in coverage),
                         unsupported_page_count=sum(d['page_count'] for d in coverage if d['status']=='unsupported'),
                         supported_exception_count=sum(d['exception_count'] for d in coverage if d['status']!='unsupported'),
                         total_exception_count=sum(d['exception_count'] for d in coverage))
    plan=dict(plan_kind=OWNER_NAME,schema_version=SCHEMA_VERSION,sheet_title=SHEET_TITLE,privateDraftReviewOnly=True,
              familyVisibleSafe=False,approvedCount=0,preview_date=today.isoformat(),
              ranking_limit=ranking_limit,source_registry_hash=_digest(registry),
              total_observation_count=len(all_rows),shown_observation_count=sum(s['shown_count'] for s in sections),
              dispositions=dict(dispositions),sections=sections,coverage=coverage,source_coverage=source_coverage)
    if plan['shown_observation_count']+sum(dispositions.values())!=len(all_rows):
        raise ValueError('Presentation coverage accounting failed')
    plan['plan_hash']=_digest(plan)
    return plan


def validate_preview_plan(plan: dict,registry: dict) -> dict:
    expected=build_preview_plan(registry,today=date.fromisoformat(plan['preview_date']),
                                ranking_limit=plan['ranking_limit'])
    if plan!=expected:raise ValueError('Private preview plan is stale or modified')
    return plan


def _padded(values) -> list[str]:
    if len(values)>WIDTH:raise ValueError('Presentation width exceeded')
    return [_string(v) for v in values]+['']*(WIDTH-len(values))


def _banner(label: str,detail: str) -> list[str]:
    values=['']*WIDTH;values[0]=label;values[3]=detail;return values


def build_values(plan: dict) -> list[list[str]]:
    """Only selected printed facts and redacted coverage enter Google cells."""
    latest=max((s['publication_date'] for s in plan['sections']),default='Unresolved')
    values=[_banner('TSI','Dated publisher evidence | presentation preview'),
            _banner('PRIVATE DRAFT','All rows needs_review | no financial approval / family publication'),
            _banner('SOURCE DATES',f"Latest available source: {latest} | Preview date: {plan['preview_date']} | Irregular updates"),
            _banner('PREVIEW COVERAGE',f"Showing {plan['shown_observation_count']} of {plan['total_observation_count']} observations | historical printed values, not live prices"),
            _banner('SOURCE CONTEXT','Blank values are unresolved. Rankings are not Buy actions; publisher portfolios are not personal holdings.'),
            _banner('COMPLEMENTARY VIEWS','Proposed: Search matches company/WKN with TSI source dates; Aktuell gets a separate dated TSI panel after design review.'),_padded([])]
    for section in plan['sections']:
        values.append(_banner(section['title'],section['subtitle']))
        values.append(_banner(f"Showing {section['shown_count']} of {section['available_count']}",
                              'One row per source observation; differing publisher evidence is retained separately.'))
        values.append(list(section['headers']))
        values.extend(row['values'] for row in section['rows'])
        values.append(_padded([]))
    c=plan['source_coverage']
    values += [_banner('Coverage and omitted evidence',
                       f"{c['supported_exception_count']} supported-source exception regions; "
                       f"{c['unsupported_document_count']} unsupported documents / {c['unsupported_page_count']} unsupported pages. "
                       'Expected graphical review flags are not additional parse failures.'),
               _padded(['Disposition','Count'])]
    values.extend(_padded([key.replace('_',' '),count]) for key,count in sorted(plan['dispositions'].items()) if count)
    values.append(_padded(['Source documents: unsupported layouts remain explicit']))
    values.append(_padded(['Product','Publication date','Extraction status','Pages','Observations','Exceptions']))
    values.extend(_padded([d['product'],d['publication_date'],d['status'],d['page_count'],d['observation_count'],d['exception_count']]) for d in plan['coverage'])
    values.append(_padded(['This summarizes publisher evidence for private review. It is not personal financial advice.']))
    return values


def format_requests(plan: dict,sheet_id: int) -> list[dict]:
    values=build_values(plan);end=len(values)
    dark={'red':0.10,'green':0.22,'blue':0.29};blue={'red':0.85,'green':0.91,'blue':0.95}
    requests=[{'updateSheetProperties':{'properties':{'sheetId':sheet_id,'gridProperties':{'rowCount':max(end,150),'columnCount':WIDTH,'frozenRowCount':6,'frozenColumnCount':3},'tabColorStyle':{'rgbColor':{'red':0.10,'green':0.48,'blue':0.59}}},'fields':'gridProperties,tabColorStyle'}},
              {'repeatCell':{'range':{'sheetId':sheet_id,'startRowIndex':0,'endRowIndex':max(end,150),'startColumnIndex':0,'endColumnIndex':WIDTH},'cell':{'userEnteredFormat':{'backgroundColor':{'red':1,'green':1,'blue':1},'textFormat':{'fontFamily':'Arial','fontSize':10,'foregroundColor':dark},'wrapStrategy':'WRAP','verticalAlignment':'TOP'}},'fields':'userEnteredFormat'}},
              {'updateDimensionProperties':{'range':{'sheetId':sheet_id,'dimension':'ROWS','startIndex':0,'endIndex':end},'properties':{'pixelSize':56},'fields':'pixelSize'}}]
    for column,width in enumerate(WIDTHS):
        requests.append({'updateDimensionProperties':{'range':{'sheetId':sheet_id,'dimension':'COLUMNS','startIndex':column,'endIndex':column+1},'properties':{'pixelSize':width},'fields':'pixelSize'}})
    def merges(index):
        for left,right in ((0,3),(3,WIDTH)):
            requests.append({'mergeCells':{'range':{'sheetId':sheet_id,'startRowIndex':index,'endRowIndex':index+1,'startColumnIndex':left,'endColumnIndex':right},'mergeType':'MERGE_ALL'}})
    def bar(index,color=dark,size=11):
        merges(index)
        requests.append({'repeatCell':{'range':{'sheetId':sheet_id,'startRowIndex':index,'endRowIndex':index+1,'startColumnIndex':0,'endColumnIndex':WIDTH},'cell':{'userEnteredFormat':{'backgroundColor':color,'textFormat':{'bold':True,'fontSize':size,'foregroundColor':{'red':1,'green':1,'blue':1}}}},'fields':'userEnteredFormat.backgroundColor,userEnteredFormat.textFormat'}})
    for index in range(6):bar(index,dark if index<2 else {'red':0.25,'green':0.36,'blue':0.42},16 if index==0 else 10)
    offset=7
    for section in plan['sections']:
        bar(offset)
        merges(offset+1)
        requests.append({'repeatCell':{'range':{'sheetId':sheet_id,'startRowIndex':offset+2,'endRowIndex':offset+3,'startColumnIndex':0,'endColumnIndex':WIDTH},'cell':{'userEnteredFormat':{'backgroundColor':blue,'textFormat':{'bold':True}}},'fields':'userEnteredFormat.backgroundColor,userEnteredFormat.textFormat.bold'}})
        offset+=4+len(section['rows'])
    return requests


def validate_owner(sheet: dict,sheet_id: int,*,phase: str='committed') -> dict:
    markers=[item for item in sheet.get('developerMetadata',[]) if item.get('metadataKey')==OWNER_KEY]
    if len(markers)!=1:raise ValueError('Existing TSI tab is not owned by this preview')
    marker=markers[0]
    try:value=json.loads(marker['metadataValue'])
    except (KeyError,TypeError,ValueError):raise ValueError('Malformed TSI ownership metadata') from None
    if (sheet.get('properties',{}).get('sheetId')!=sheet_id or sheet['properties'].get('title')!=SHEET_TITLE
        or marker.get('location',{}).get('sheetId')!=sheet_id or value.get('sheet_id')!=sheet_id
        or value.get('owner')!=OWNER_NAME or value.get('schema_version')!=SCHEMA_VERSION
        or value.get('privateDraftReviewOnly') is not True or value.get('familyVisibleSafe') is not False
        or value.get('phase')!=phase
        or not isinstance(value.get('plan_hash' if phase=='committed' else 'requested_plan_hash'),str)
        or len(value['plan_hash' if phase=='committed' else 'requested_plan_hash'])!=64
        or not isinstance(value.get('payload_hash'),str) or len(value['payload_hash'])!=64):
        raise ValueError('TSI ownership metadata does not match this private preview')
    return marker


def _owner_value(sheet_id: int,plan: dict,*,phase: str) -> str:
    value=dict(owner=OWNER_NAME,schema_version=SCHEMA_VERSION,sheet_id=sheet_id,
               phase=phase,payload_hash=_digest(build_values(plan)),
               privateDraftReviewOnly=True,familyVisibleSafe=False)
    value['plan_hash' if phase=='committed' else 'requested_plan_hash']=plan['plan_hash']
    return json.dumps(value,sort_keys=True)


def apply_preview(config,plan: dict,registry: dict,*,sheets_service_factory=None) -> dict:
    """Explicit live boundary: only the configured workbook's owned TSI tab."""
    validate_registry(registry,verify_sources=True);validate_preview_plan(plan,registry)
    if sheets_service_factory is None:
        from stock_analyst.google_access import _google_service_factories
        _,sheets_service_factory=_google_service_factories(config)
    sheets=sheets_service_factory();book=sheets.spreadsheets();spreadsheet_id=config.sheets_spreadsheet_id
    response=book.get(spreadsheetId=spreadsheet_id,fields='sheets(properties(sheetId,title),developerMetadata)').execute()
    existing=[s for s in response.get('sheets',[]) if s.get('properties',{}).get('title')==SHEET_TITLE]
    if len(existing)>1:raise ValueError('Ambiguous TSI destination')
    created=not existing;values=build_values(plan)
    target="'TSI'!A1:Q";values_api=book.values()
    receipt=dict(ok=True,sheetTitle=SHEET_TITLE,tabCreated=created,privateDraftReviewOnly=True,
                 familyVisibleSafe=False,approvedCount=0,shownObservationCount=plan['shown_observation_count'],
                 valuesVerified=True,planHash=plan['plan_hash'])
    if existing:
        sheet_id=existing[0]['properties']['sheetId'];marker=validate_owner(existing[0],sheet_id)
        owner=json.loads(marker['metadataValue'])
        if owner['plan_hash']!=plan['plan_hash'] or owner['payload_hash']!=_digest(values):
            raise ValueError('Existing TSI preview differs; replacement is not authorized by this presentation command')
        actual=values_api.get(spreadsheetId=spreadsheet_id,range=target,valueRenderOption='FORMULA').execute().get('values',[])
        if [_padded(row) for row in actual]!=values:
            raise ValueError('Existing TSI values changed; preserving user content')
        return dict(receipt,noOp=True)
    # The explicit ID lets creation and its initializing ownership marker be
    # atomic. A concurrent title/ID collision fails without editing another tab.
    used={s.get('properties',{}).get('sheetId') for s in response.get('sheets',[])}
    sheet_id=1
    while sheet_id in used:sheet_id+=1
    initial={'metadataKey':OWNER_KEY,'metadataValue':_owner_value(sheet_id,plan,phase='initializing'),
             'location':{'sheetId':sheet_id},'visibility':'DOCUMENT'}
    result=book.batchUpdate(spreadsheetId=spreadsheet_id,body={'requests':[
        {'addSheet':{'properties':{'sheetId':sheet_id,'title':SHEET_TITLE,'index':2,
                                 'gridProperties':{'rowCount':max(150,len(values)),'columnCount':WIDTH}}}},
        {'createDeveloperMetadata':{'developerMetadata':initial}}]}).execute()
    marker=result['replies'][1]['createDeveloperMetadata']['developerMetadata']
    validate_owner({'properties':{'sheetId':sheet_id,'title':SHEET_TITLE},
                    'developerMetadata':[marker]},sheet_id,phase='initializing')
    # Reversible write/readback is restricted to the new, empty tab only.
    probe='TSI private reviewer connection check'
    try:
        values_api.update(spreadsheetId=spreadsheet_id,range="'TSI'!A1",valueInputOption='RAW',body={'values':[[probe]]}).execute()
        read=values_api.get(spreadsheetId=spreadsheet_id,range="'TSI'!A1",valueRenderOption='FORMULA').execute().get('values',[])
        if read!=[[probe]]:raise ValueError('Private TSI reversible write/readback failed')
    finally:
        values_api.clear(spreadsheetId=spreadsheet_id,range="'TSI'!A1",body={}).execute()
    if values_api.get(spreadsheetId=spreadsheet_id,range="'TSI'!A1",valueRenderOption='FORMULA').execute().get('values',[]):
        raise ValueError('Private TSI probe restoration failed')
    requests=format_requests(plan,sheet_id)
    requests.append({'addProtectedRange':{'protectedRange':{'range':{'sheetId':sheet_id},'description':OWNER_KEY,'warningOnly':False,'editors':{'users':[config.service_account_email]}}}})
    book.batchUpdate(spreadsheetId=spreadsheet_id,body={'requests':requests}).execute()
    values_api.update(spreadsheetId=spreadsheet_id,range=f"'TSI'!A1:Q{len(values)}",valueInputOption='RAW',body={'values':values}).execute()
    actual=values_api.get(spreadsheetId=spreadsheet_id,range=f"'TSI'!A1:Q{len(values)}",valueRenderOption='FORMULA').execute().get('values',[])
    normalized=[_padded(row) for row in actual]
    if normalized!=values:raise ValueError('Private TSI exact value readback mismatch')
    book.batchUpdate(spreadsheetId=spreadsheet_id,body={'requests':[
        {'updateDeveloperMetadata':{'dataFilters':[{'developerMetadataLookup':{'metadataId':marker['metadataId']}}],
                                    'developerMetadata':{'metadataValue':_owner_value(sheet_id,plan,phase='committed')},
                                    'fields':'metadataValue'}}]}).execute()
    return dict(receipt,noOp=False)


def write_private_plan(plan: dict,path: Path) -> Path:
    if path.is_symlink():raise ValueError('Private plan output must not be a symlink')
    path=assert_private_output(path)
    if path.suffix.lower()!='.json':raise ValueError('Private preview plan output must use JSON')
    if path.exists():
        try:existing=json.loads(path.read_text(encoding='utf-8'))
        except (OSError,ValueError):raise ValueError('Existing output is not an owned preview plan') from None
        if not isinstance(existing,dict) or existing.get('plan_kind')!=OWNER_NAME:
            raise ValueError('Existing output is not an owned preview plan')
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    descriptor,name=tempfile.mkstemp(prefix='.tsi-sheet-plan-',dir=path.parent)
    try:
        with os.fdopen(descriptor,'w',encoding='utf-8') as stream:
            json.dump(plan,stream,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)
            stream.flush();os.fsync(stream.fileno())
        os.replace(name,path)
    finally:
        if Path(name).exists():Path(name).unlink()
    return path


def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description='Private TSI presentation preview')
    parser.add_argument('--registry',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--expected-plan-hash',help='Required with --apply: exact reviewed private plan hash.')
    parser.add_argument('--env-file',type=Path,default=Path('.env'))
    args=parser.parse_args(argv)
    try:
        registry=load_registry(args.registry)
        if args.apply:
            if not args.expected_plan_hash:raise ValueError('Apply requires the reviewed plan hash')
            plan_path=assert_private_output(args.output)
            plan=json.loads(plan_path.read_text(encoding='utf-8'))
            validate_preview_plan(plan,registry)
            if args.expected_plan_hash!=plan['plan_hash']:raise ValueError('Reviewed plan hash changed')
        else:
            plan=build_preview_plan(registry);write_private_plan(plan,args.output)
        result=dict(ok=True,privateDraftReviewOnly=True,familyVisibleSafe=False,approvedCount=0,
                    shownObservationCount=plan['shown_observation_count'],sectionCount=len(plan['sections']),planHash=plan['plan_hash'])
        if args.apply:
            from stock_analyst.google_access import load_google_access_config
            result=apply_preview(load_google_access_config(env_file=args.env_file),plan,registry)
    except Exception:
        parser.exit(2,'error: private TSI presentation failed; inspect private source/plan and destination ownership\n')
    print(json.dumps(result,sort_keys=True));return 0


if __name__=='__main__':raise SystemExit(main())
