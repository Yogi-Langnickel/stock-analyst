"""Synthetic regressions for the bounded private TSI sheet presentation."""

from copy import deepcopy
from datetime import date
from hashlib import sha256
from pathlib import Path
import tempfile
import unittest

from stock_analyst.tsi_records import make_observation
from stock_analyst.tsi_sheet_preview import (
    OWNER_KEY, OWNER_NAME, apply_preview, build_preview_plan, build_values, format_requests,
    validate_preview_plan, validate_owner, write_private_plan,
)
from unittest.mock import patch
from types import SimpleNamespace
import json


def registry_with(specs):
    documents = {}
    for index, spec in enumerate(specs):
        product, published, kind, fields, strategy, universe, effective = spec
        checksum = sha256(str(index).encode()).hexdigest()
        doc = dict(document_id='doc_'+checksum, sha256=checksum,
                   aliases=['synthetic.pdf'], stored_path=str(Path('data/private/synthetic.pdf').resolve()),
                   media_type='application/pdf', original_publication='TSI', product=product,
                   publication_date=published, ingested_at='2026-10-25T00:00:00+00:00',
                   extraction_status='parsed', exceptions=[], pages=[], observations=[])
        row = make_observation(doc, kind, 1, [0, 0, 100, 20], fields,
                               strategy=strategy, universe=universe,
                               transaction_effective_date=effective,
                               source_text='Synthetic evidence')
        doc['observations'] = [row]
        doc['pages'] = [dict(number=1, width=595, height=842, layout_status='parsed',
                            candidate_count=1, observation_ids=[row['observation_id']], exception_ids=[])]
        documents[checksum] = doc
    return dict(schema_version=1, documents=documents)


def spec(published, kind='recommendation', fields=None, product='TSI USA',
         strategy='Synthetic strategy', universe=None, effective=None):
    return (product, published, kind,
            fields or dict(name='Synthetic Corp', wkn='SYN123', instrument_type='stock', current_price='1,23',currency='EUR'),
            strategy, universe, effective)


class TsiSheetPlanTests(unittest.TestCase):
    def test_latest_selection_is_per_product_strategy_type_and_universe(self):
        registry = registry_with([
            spec('2026-10-01'), spec('2026-09-01'),
            spec('2026-08-01', product='TSI Premium'),
            spec('2026-07-01', strategy='Other strategy'),
            spec('2026-10-01', 'ranking', dict(name='Big', rank='1', score='99'), universe='Big Caps'),
            spec('2026-09-01', 'ranking', dict(name='Small', rank='1', score='98'), universe='Small Caps'),
        ])
        plan = build_preview_plan(registry, today=date(2026, 10, 25))
        shown = [row for section in plan['sections'] for row in section['rows']]
        self.assertEqual(len(shown), 5)
        self.assertEqual({row['binding']['universe'] for row in shown if row['binding']['record_type']=='ranking'}, {'Big Caps','Small Caps'})
        self.assertEqual(plan['dispositions']['older_source_observations'], 1)
        self.assertEqual(plan['shown_observation_count'] + sum(plan['dispositions'].values()), 6)

    def test_historical_transactions_are_independent_and_summary_is_omitted(self):
        registry = registry_with([
            spec('2026-10-01'),
            spec('2026-09-01', 'transaction', dict(name='Synthetic', wkn='SYN123', action='Verkauf', price='2,34'), effective='2026-08-31'),
            spec('2026-10-01', 'transaction', dict(printed_transaction_summary='Synthetic summary only')),
        ])
        plan = build_preview_plan(registry, today=date(2026,10,25))
        section = next(s for s in plan['sections'] if s['record_type']=='transaction')
        self.assertEqual(section['publication_date'], '2026-09-01')
        self.assertEqual(section['rows'][0]['values'][13], '2026-08-31')
        self.assertEqual(plan['dispositions']['summary_only_transactions'], 1)
        self.assertIn('historical', section['subtitle'].lower())

    def test_rankings_and_snapshots_never_infer_an_action(self):
        registry = registry_with([
            spec('2026-10-01', 'ranking', dict(name='Synthetic', rank='1', score='99'), universe='Big Caps'),
            spec('2026-10-01', 'portfolio_snapshot', dict(name='Synthetic', wkn='SYN123', quantity='10', purchase_date='2020-01-01')),
            spec('2026-10-01', fields=dict(name='Synthetic',wkn='SYN123',instrument_type='stock',printed_status='Ausgestoppt')),
        ])
        plan = build_preview_plan(registry, today=date(2026,10,25))
        for section in plan['sections']:
            for row in section['rows']:
                self.assertNotIn(row['values'][2], ['Buy','Sell','Kauf','Verkauf'])
        rec = next(s for s in plan['sections'] if s['record_type']=='recommendation')['rows'][0]
        self.assertEqual(rec['values'][7], 'Ausgestoppt')
        self.assertEqual(rec['values'][2], '')

    def test_same_instrument_differing_evidence_is_not_merged(self):
        registry = registry_with([spec('2026-10-01'), spec('2026-10-01',fields=dict(name='Synthetic Corp',wkn='SYN123',instrument_type='stock',current_price='9,87',currency='EUR'))])
        plan = build_preview_plan(registry, today=date(2026,10,25))
        rows = [r for s in plan['sections'] for r in s['rows']]
        self.assertEqual(len(rows), 2)
        self.assertEqual({r['values'][3] for r in rows},{'1,23 EUR','9,87 EUR'})
        self.assertEqual(len({r['observation_id'] for r in rows}),2)
        self.assertTrue(all(r['review_hash'] for r in rows))

    def test_mixed_source_currencies_are_visible_without_conversion_or_defaults(self):
        registry=registry_with([spec('2026-10-01',fields=dict(name='USD',wkn='USD123',instrument_type='stock',currency='USD',current_price='1,23',target='ca. 2,50',stop='0,50')),
                                spec('2026-10-01',fields=dict(name='CHF',wkn='CHF123',instrument_type='stock',currency='CHF',current_price='9.87')),
                                spec('2026-10-01',fields=dict(name='Unknown',wkn='UNK123',instrument_type='stock',current_price='7,65'))])
        plan=build_preview_plan(registry,today=date(2026,10,25))
        rows={r['values'][0]:r for s in plan['sections'] for r in s['rows']}
        self.assertEqual(rows['USD123']['values'][3:6],['1,23 USD','ca. 2,50 USD','0,50 USD'])
        self.assertEqual(rows['CHF123']['values'][3],'9.87 CHF')
        self.assertEqual(rows['UNK123']['values'][3],'7,65 (currency unresolved)')
        self.assertEqual(rows['USD123']['binding']['printed_fields']['current_price'],'1,23')

    def test_unknown_dates_and_article_text_are_not_exported(self):
        registry = registry_with([spec(None), spec('2026-10-01','commentary',dict(context_kind='publisher_commentary'))])
        plan = build_preview_plan(registry,today=date(2026,10,25))
        self.assertEqual(plan['shown_observation_count'],0)
        self.assertEqual(sum(plan['dispositions'].values()),2)
        self.assertNotIn('Synthetic evidence', str(build_values(plan)))
        self.assertNotIn('synthetic.pdf', str(build_values(plan)))

    def test_formula_like_values_are_literal_strings_and_scoped_formatting(self):
        registry=registry_with([spec('2026-10-01',fields=dict(name='=IMPORTXML("https://invalid")',wkn='SYN123',instrument_type='stock'))])
        plan=build_preview_plan(registry,today=date(2026,10,25))
        values=build_values(plan)
        self.assertIn('=IMPORTXML("https://invalid")',[cell for row in values for cell in row])
        self.assertTrue(all(len(row)==17 for row in values))
        for request in format_requests(plan,123):
            body=next(iter(request.values()))
            if 'range' in body:self.assertEqual(body['range']['sheetId'],123)
            if 'properties' in body and 'sheetId' in body['properties']:self.assertEqual(body['properties']['sheetId'],123)
            if 'mergeCells' in request:
                self.assertFalse(body['range']['startColumnIndex'] < 3 < body['range']['endColumnIndex'])
        self.assertTrue(plan['privateDraftReviewOnly'])
        self.assertFalse(plan['familyVisibleSafe'])
        self.assertEqual(plan['approvedCount'],0)

    def test_plan_tampering_and_wrong_owner_refuse(self):
        registry=registry_with([spec('2026-10-01')])
        plan=build_preview_plan(registry,today=date(2026,10,25))
        changed=deepcopy(plan);changed['sections'][0]['rows'][0]['values'][3]='999'
        with self.assertRaises(ValueError):validate_preview_plan(changed,registry)
        with self.assertRaises(ValueError):validate_owner({'properties':{'sheetId':123,'title':'TSI'}},123)
        metadata={'metadataKey':OWNER_KEY,'metadataValue':'{}','location':{'sheetId':999}}
        with self.assertRaises(ValueError):validate_owner({'properties':{'sheetId':123,'title':'TSI'},'developerMetadata':[metadata]},123)

    def test_existing_different_or_modified_preview_refuses_before_mutation(self):
        registry=registry_with([spec('2026-10-01')]);plan=build_preview_plan(registry,today=date(2026,10,25))
        values=build_values(plan)
        for mutate in ('different_plan','modified_values','initializing'):
            fake=FakeSheets()
            marker=dict(owner=OWNER_NAME,schema_version=1,sheet_id=123,phase='committed',
                        plan_hash=plan['plan_hash'],payload_hash=sha256(json.dumps(values,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest(),
                        privateDraftReviewOnly=True,familyVisibleSafe=False)
            if mutate=='different_plan':marker['plan_hash']='a'*64
            if mutate=='initializing':marker['phase']='initializing'
            fake.sheet={'properties':{'sheetId':123,'title':'TSI'},'developerMetadata':[dict(metadataKey=OWNER_KEY,metadataValue=json.dumps(marker),metadataId=1,location={'sheetId':123})]}
            fake.values_data=deepcopy(values)
            if mutate=='modified_values':fake.values_data[0][0]='User content'
            with patch('stock_analyst.tsi_sheet_preview.validate_registry'):
                with self.assertRaises(ValueError):apply_preview(SimpleNamespace(sheets_spreadsheet_id='synthetic',service_account_email='test@example.invalid'),plan,registry,sheets_service_factory=lambda:fake)
            self.assertEqual(fake.mutations,[])

    def test_same_owned_exact_preview_is_a_noop(self):
        registry=registry_with([spec('2026-10-01')]);plan=build_preview_plan(registry,today=date(2026,10,25));values=build_values(plan)
        marker=dict(owner=OWNER_NAME,schema_version=1,sheet_id=123,phase='committed',plan_hash=plan['plan_hash'],
                    payload_hash=sha256(json.dumps(values,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest(),
                    privateDraftReviewOnly=True,familyVisibleSafe=False)
        fake=FakeSheets();fake.values_data=values
        fake.sheet={'properties':{'sheetId':123,'title':'TSI'},'developerMetadata':[dict(metadataKey=OWNER_KEY,metadataValue=json.dumps(marker),metadataId=1,location={'sheetId':123})]}
        with patch('stock_analyst.tsi_sheet_preview.validate_registry'):
            result=apply_preview(SimpleNamespace(sheets_spreadsheet_id='synthetic',service_account_email='test@example.invalid'),plan,registry,sheets_service_factory=lambda:fake)
        self.assertTrue(result['noOp']);self.assertEqual(fake.mutations,[])

    def test_fresh_publish_uses_raw_tsi_only_probe_and_commits_after_readback(self):
        registry=registry_with([spec('2026-10-01')]);plan=build_preview_plan(registry,today=date(2026,10,25))
        fake=FakeSheets()
        with patch('stock_analyst.tsi_sheet_preview.validate_registry'):
            result=apply_preview(SimpleNamespace(sheets_spreadsheet_id='synthetic',service_account_email='test@example.invalid'),plan,registry,sheets_service_factory=lambda:fake)
        self.assertTrue(result['valuesVerified']);self.assertFalse(result['noOp'])
        self.assertEqual(fake.values_data,build_values(plan))
        self.assertEqual(fake.protection_count,1)
        owner=json.loads(fake.sheet['developerMetadata'][0]['metadataValue'])
        self.assertEqual(owner['phase'],'committed');self.assertEqual(owner['plan_hash'],plan['plan_hash'])
        for call in fake.mutations:
            if 'range' in call:self.assertTrue(call['range'].startswith("'TSI'!"))
            if 'valueInputOption' in call:self.assertEqual(call['valueInputOption'],'RAW')
        initial=json.loads(fake.mutations[0]['body']['requests'][1]['createDeveloperMetadata']['developerMetadata']['metadataValue'])
        self.assertEqual(initial['phase'],'initializing');self.assertNotIn('plan_hash',initial)

    def test_failed_probe_is_restored_and_does_not_commit(self):
        registry=registry_with([spec('2026-10-01')]);plan=build_preview_plan(registry,today=date(2026,10,25))
        fake=FakeSheets();fake.probe_mismatch=True
        with patch('stock_analyst.tsi_sheet_preview.validate_registry'):
            with self.assertRaises(ValueError):apply_preview(SimpleNamespace(sheets_spreadsheet_id='synthetic',service_account_email='test@example.invalid'),plan,registry,sheets_service_factory=lambda:fake)
        self.assertEqual(fake.values_data,[])
        self.assertEqual(json.loads(fake.sheet['developerMetadata'][0]['metadataValue'])['phase'],'initializing')
        self.assertEqual(fake.protection_count,0)

    def test_plan_output_does_not_overwrite_unowned_registry(self):
        root=Path('data/private');root.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as directory:
            path=Path(directory)/'registry.json';path.write_text('{"schema_version":1,"documents":{}}')
            original=path.read_bytes();plan=build_preview_plan(registry_with([]),today=date(2026,10,25))
            with self.assertRaises(ValueError):write_private_plan(plan,path)
            self.assertEqual(path.read_bytes(),original)


class FakeResult:
    def __init__(self,value):self.value=value
    def execute(self):return self.value


class FakeSheets:
    def __init__(self):self.sheet=None;self.values_data=[];self.mutations=[];self.protection_count=0;self.probe_mismatch=False
    def spreadsheets(self):return self
    def values(self):return FakeValues(self)
    def get(self,**kwargs):return FakeResult({'sheets':[self.sheet] if self.sheet else []})
    def batchUpdate(self,**kwargs):
        self.mutations.append(deepcopy(kwargs));replies=[]
        for request in kwargs['body']['requests']:
            if 'addSheet' in request:
                self.sheet=dict(properties=deepcopy(request['addSheet']['properties']),developerMetadata=[])
                replies.append({'addSheet':{'properties':self.sheet['properties']}})
            elif 'createDeveloperMetadata' in request:
                value=deepcopy(request['createDeveloperMetadata']['developerMetadata']);value['metadataId']=1
                self.sheet['developerMetadata'].append(value)
                replies.append({'createDeveloperMetadata':{'developerMetadata':deepcopy(value)}})
            elif 'updateDeveloperMetadata' in request:
                self.sheet['developerMetadata'][0]['metadataValue']=request['updateDeveloperMetadata']['developerMetadata']['metadataValue'];replies.append({})
            else:
                if 'addProtectedRange' in request:self.protection_count+=1
                replies.append({})
        return FakeResult({'replies':replies})


class FakeValues:
    def __init__(self,parent):self.parent=parent
    def get(self,**kwargs):
        if self.parent.probe_mismatch and kwargs['range']=="'TSI'!A1":return FakeResult({'values':[['Incorrect probe']]})
        return FakeResult({'values':self.parent.values_data})
    def update(self,**kwargs):self.parent.mutations.append(deepcopy(kwargs));self.parent.values_data=deepcopy(kwargs['body']['values']);return FakeResult({})
    def clear(self,**kwargs):self.parent.mutations.append(kwargs);self.parent.values_data=[];return FakeResult({})


if __name__=='__main__':unittest.main()
