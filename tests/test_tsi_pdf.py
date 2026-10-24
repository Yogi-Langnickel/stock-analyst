import unittest
from pathlib import Path
import tempfile

from stock_analyst.tsi_pdf import (
    _row_boundaries, classify_document, extract_pdf_document, parse_table_rows,
)


def word(x, y, text):
    return [x, y, x+10, y+7, text]


class TsiPdfTests(unittest.TestCase):
    def test_product_and_date_are_source_specific(self):
        doc = classify_document('TSI USA www.tsi-usa.de 02.01.2026 Nr. 01/26', '')
        self.assertEqual(doc['product'], 'TSI USA')
        self.assertTrue(doc['supported'])
        old = classify_document('TSI PREMIUM 01.01.2014', 'TSI-USA-2026.pdf')
        self.assertEqual(old['product'], 'TSI Premium')
        self.assertFalse(old['supported'])
        special = classify_document('AKTIENREPORTS 24. September 2026', '')
        self.assertEqual(special['product'], 'Aktienreports')
        self.assertFalse(special['supported'])
        self.assertIsNone(classify_document('unknown', 'TSI-USA-2026-01-01.pdf')['publication_date'])

    def test_ranking_membership_is_never_recommendation(self):
        words = [word(45, 140, '1'), word(70, 140, '+2'),
                 word(90, 140, 'Synthetic'), word(145, 140, 'Corp'),
                 word(213, 140, '99'), word(240, 140, '+1')]
        rows, exceptions = parse_table_rows(words, 'ranking', [130, 154], 595)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['printed_fields']['rank'], '1')
        self.assertEqual(rows[0]['printed_fields']['score'], '99')
        self.assertNotIn('action', rows[0]['printed_fields'])
        self.assertEqual(exceptions, [])

    def test_malformed_candidate_is_exception_and_raw_values_survive(self):
        words = [word(45, 140, '1'), word(90, 140, 'Synthetic')]
        rows, exceptions = parse_table_rows(words, 'ranking', [130, 154], 595)
        self.assertEqual(rows, [])
        self.assertEqual(len(exceptions), 1)
        self.assertIn('Synthetic', exceptions[0]['source_text'])

    def test_header_date_excludes_strategy_inception_and_conflicts_fail_closed(self):
        result=classify_document('seit 02.03.2016 TSI USA www.tsi-usa.de '
                                 '02.01.2026 Nr. 01/26 Stand 01.01.2026', '')
        self.assertEqual(result['publication_date'],'2026-01-02')
        self.assertEqual(result['date_conflicts'],[])
        result=classify_document('TSI USA www.tsi-usa.de 02.01.2026 Nr. 01/26 '
                                 '03.01.2026 Nr. 02/26','')
        self.assertIsNone(result['publication_date'])
        self.assertFalse(result['supported'])

    def test_portfolio_stop_layout_keeps_all_columns(self):
        xs=[65,140,180,215,270,310,355,399,443,479,529]
        values=['Synthetic','SYN123','2','01.01.2020','1,23','2,34','4,68',
                '1,10','7','8','+9']
        words=[word(x,140,v) for x,v in zip(xs,values)]
        rows,errors=parse_table_rows(words,'portfolio_snapshot',[130,160],595.276,
                                     portfolio_stop=True)
        self.assertEqual(errors,[])
        fields=rows[0]['printed_fields']
        self.assertEqual(fields['stop_price'],'1,10')
        self.assertEqual(fields['rank'],'7')
        self.assertEqual(fields['weight_percent'],'8')
        self.assertEqual(fields['performance_percent'],'+9')

    def test_candidate_inventory_does_not_require_valid_rank(self):
        words=[word(45,140,'?'),word(87.9,140,'Synthetic'),word(213,140,'99')]
        boundaries=_row_boundaries(words,'ranking',595.276)
        self.assertEqual(len(boundaries),2)
        rows,errors=parse_table_rows(words,'ranking',boundaries,595.276)
        self.assertEqual(rows,[])
        self.assertEqual(len(errors),1)

    def test_explicit_transaction_columns_keep_effective_date_and_approximations(self):
        words=[word(x,660,v) for x,v in zip(
            [45,97,204,258,300,361,405,466,520],
            ['Verkauf','Synthetic','SYN123','2','03.01.2026','ca.1,23','-','ca.7','+8'])]
        rows,errors=parse_table_rows(words,'transaction',[650,675],595.276)
        self.assertEqual(errors,[])
        self.assertEqual(rows[0]['printed_fields']['action'],'Verkauf')
        self.assertEqual(rows[0]['printed_fields']['effective_date'],'03.01.2026')
        self.assertEqual(rows[0]['printed_fields']['price'],'ca.1,23')

    def test_derivative_full_date_never_enters_omega(self):
        words=[word(x,490,v) for x,v in zip([45,110,160,205,245,285,325,350.1,402,430,470],
            ['Synthetic','SYN123','01.01.2026','1,00','2,00','0,90','4,0','16.06.2027','3,00','0,50','+2'])]
        rows,errors=parse_table_rows(words,'derivative',[475,510],595.276)
        self.assertEqual(errors,[])
        self.assertEqual(rows[0]['printed_fields']['expiry'],'16.06.2027')
        self.assertEqual(rows[0]['printed_fields']['omega_or_leverage'],'4,0')

    def test_transaction_table_without_stop_keeps_eight_columns(self):
        words=[word(x,660,v) for x,v in zip([45,100,220,264,325,397,450,505],
            ['Kauf','Synthetic','SYN123','2','03.01.2026','1,23','7','+8'])]
        rows,errors=parse_table_rows(words,'transaction',[650,675],595.276,transaction_stop=False)
        self.assertEqual(errors,[])
        self.assertEqual(rows[0]['printed_fields']['weight_percent'],'7')
        self.assertNotIn('stop',rows[0]['printed_fields'])

    def test_pdf_pipeline_retains_tip_instruments_and_header_conflict(self):
        try:import fitz
        except ImportError:self.skipTest('optional local PDF dependency unavailable')
        root=Path('data/private');root.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as directory:
            path=Path(directory)/'synthetic.pdf'
            with fitz.open() as pdf:
                cover=pdf.new_page(width=595.276,height=841.89)
                cover.insert_text((43,50),'TSI USA www.tsi-usa.de 02.01.2026 Nr. 01/26',fontsize=8)
                cover.insert_text((43,250),'Top-Tipp: Synthetic Corp',fontsize=10)
                cover.insert_text((400,350),'Kauf: Synthetic Corp',fontsize=8)
                page=pdf.new_page(width=595.276,height=841.89)
                page.insert_text((43,50),'TSI USA 03.01.2026 Nr. 01/26',fontsize=8)
                page.insert_text((400,100),'Synthetic Corp',fontsize=8)
                page.insert_text((470,115),'OS',fontsize=8)
                page.insert_text((515,115),'Aktie',fontsize=8)
                for y,label,derivative,stock in [(140,'WKN','SYN456','SYN123'),
                    (160,'Kurs','1,00','2,00'),(180,'Stopp','0,50','1,50'),
                    (200,'Laufzeit','16.06.27','-'),(220,'Ersatzschein','ALT456','-')]:
                    page.insert_text((405,y),label,fontsize=7)
                    page.insert_text((465,y),derivative,fontsize=7)
                    page.insert_text((515,y),stock,fontsize=7)
                pdf.save(path)
            doc=extract_pdf_document(path,stored_path=path,ingested_at='2026-01-04T00:00:00Z')
            tips=[r for r in doc['observations'] if r['record_type']=='recommendation'
                  and r['evidence']['page']==2]
            self.assertEqual(len(tips),2)
            self.assertEqual({r['printed_fields']['instrument_type'] for r in tips},{'stock','derivative'})
            self.assertNotEqual(tips[0]['instrument_id'],tips[1]['instrument_id'])
            self.assertTrue(all('source_page_publication_date_conflict' in r['unresolved'] for r in tips))
            self.assertEqual(sum(r['record_type']=='transaction' for r in doc['observations']),1)


if __name__ == '__main__':
    unittest.main()
