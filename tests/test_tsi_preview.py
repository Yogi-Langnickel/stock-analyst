"""Private offline preview regressions using synthetic observations."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from hashlib import sha256

from stock_analyst.tsi_preview import write_preview


def private_test_root():
    root = Path(__file__).resolve().parents[1] / "data/private"
    root.mkdir(parents=True, exist_ok=True)
    return root


class TsiPreviewTest(unittest.TestCase):
    def test_preview_never_overwrites_registry_source_or_unrelated_file(self):
        with TemporaryDirectory(dir=private_test_root()) as directory:
            root=Path(directory)
            for name in ('registry.json','source.png','unrelated.html'):
                target=root/name;target.write_bytes(b'preserve original bytes')
                with self.assertRaises(ValueError):
                    write_preview({'schema_version':1,'documents':{}},target)
                self.assertEqual(target.read_bytes(),b'preserve original bytes')
            alias=root/'original.html';alias.write_bytes(b'preserve alias')
            registry={'schema_version':1,'documents':{'x':{'stored_path':str(alias),'aliases':[str(alias)]}}}
            with self.assertRaises(ValueError):write_preview(registry,alias)
            self.assertEqual(alias.read_bytes(),b'preserve alias')

    def test_only_owned_preview_can_be_replaced(self):
        with TemporaryDirectory(dir=private_test_root()) as directory:
            target=Path(directory)/'preview.html'
            empty={'schema_version':1,'documents':{}}
            write_preview(empty,target)
            first=target.read_bytes()
            write_preview(empty,target)
            self.assertEqual(first,target.read_bytes())

    def test_typed_tables_dates_coverage_and_html_escaping(self):
        with TemporaryDirectory(dir=private_test_root()) as directory:
            output = Path(directory) / 'private' / 'preview.html'
            document = {'document_id':'doc1', 'sha256':'a'*64, 'original_publication':'TSI <script>bad()</script>', 'product':'USA', 'publication_date':'2017-02-06', 'ingested_at':'2026-10-25T00:00:00Z', 'extraction_status':'partial', 'aliases':['synthetic.png'], 'media_type':'image/png', 'stored_path':'/private/tmp/absent.png', 'pages':[{'number':1,'layout_status':'parsed','candidate_count':1,'observation_ids':['row1'],'exception_ids':[]}], 'observations':[{'observation_id':'row1','record_type':'ranking','printed_fields':{'name':'<img src=x onerror=alert(1)>','rank':'1','score':'99'},'publication_date':'2017-02-06','as_of_date':None,'transaction_effective_date':None,'strategy':'Synthetic strategy','universe':'Synthetic universe','review_status':'needs_review','exportable':False,'unresolved':['missing_as_of_date'],'evidence':{'page':1,'bbox':[0,0,10,10]},'source_text':'Synthetic private content'}], 'exceptions':[{'exception_id':'ex1','reason':'<script>exception</script>','page':1}]}
            returned = write_preview({'schema_version':1,'documents':{'a'*64:document}}, output)
            html = returned.read_text()
            self.assertEqual(returned, output)
            self.assertIn('Rankings', html)
            self.assertIn('Historical publication', html)
            self.assertIn('2017-02-06', html)
            self.assertIn('needs_review', html)
            self.assertIn('non-exportable', html)
            self.assertIn('Coverage', html)
            self.assertIn('&lt;script&gt;', html)
            self.assertNotIn('<script>', html)
            self.assertNotIn('src="https://', html)
            self.assertIn('missing_as_of_date', html)
            self.assertIn('Publisher portfolio snapshots', html)

    def test_output_rejects_non_private_path(self):
        with TemporaryDirectory(dir=private_test_root()) as directory:
            with self.assertRaises(ValueError):
                write_preview({'schema_version':1,'documents':{}}, Path('/private/tmp') / 'tsi-non-private-preview.html')

    def test_changed_source_bytes_are_withheld(self):
        with TemporaryDirectory(dir=private_test_root()) as directory:
            root = Path(directory); source = root / 'changed.png'
            source.write_bytes(b'changed bytes')
            doc = {'sha256':'c'*64, 'stored_path':str(source), 'media_type':'image/png', 'pages':[], 'observations':[], 'exceptions':[]}
            html = write_preview({'schema_version':1,'documents':{'c'*64:doc}}, root / 'preview.html').read_text()
            self.assertIn('Source bytes changed', html)
            self.assertNotIn('data:image/png;base64,', html)


    def test_source_preview_is_embedded_offline(self):
        import importlib.util
        if not importlib.util.find_spec('fitz'):
            self.skipTest('optional local renderer unavailable')
        import fitz
        with TemporaryDirectory(dir=private_test_root()) as directory:
            root = Path(directory); image = root / 'source.png'
            pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0,0,40,30),False); pix.clear_with(255); pix.save(image)
            doc = {'sha256':sha256(image.read_bytes()).hexdigest(),'document_id':'image1','original_publication':None,'product':None,'publication_date':None,'media_type':'image/png','stored_path':str(image),'pages':[{'number':1,'layout_status':'unsupported','candidate_count':0}],'observations':[],'exceptions':[]}
            html = write_preview({'schema_version':1,'documents':{'b'*64:doc}}, root / 'private/preview.html').read_text()
            self.assertIn('data:image/png;base64,', html)
            self.assertIn('Publication date unresolved', html)
            self.assertNotIn('file://', html)


if __name__ == '__main__':
    unittest.main()
