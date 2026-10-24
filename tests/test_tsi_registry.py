import json
from pathlib import Path
import tempfile
import unittest

from stock_analyst.tsi_registry import (
    _link_possible_overlaps, assert_private_output, import_sources, load_registry,
)


class TsiRegistryTests(unittest.TestCase):
    def test_private_guard_rejects_repo_docs_even_named_private(self):
        with self.assertRaises(ValueError):
            assert_private_output(Path('docs/private/registry.json'))

    def test_malformed_registry_is_not_overwritten(self):
        root = Path('data/private'); root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as directory:
            output = Path(directory); registry = output/'registry.json'
            registry.write_text('{"schema_version":999,"documents":{}}')
            with self.assertRaises(ValueError):
                load_registry(registry)
            self.assertEqual(json.loads(registry.read_text())['schema_version'], 999)

    def test_duplicate_aliases_and_ingestion_are_stable(self):
        try:
            import fitz
        except ImportError:
            self.skipTest('optional local PDF dependency unavailable')
        root = Path('data/private'); root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as directory:
            folder = Path(directory); source=folder/'input';source.mkdir()
            with fitz.open() as pdf:
                page=pdf.new_page();page.insert_text((50,50),'Synthetic unsupported source')
                pdf.save(source/'one.pdf')
            (source/'two.pdf').write_bytes((source/'one.pdf').read_bytes())
            first=import_sources(source,folder/'output')
            doc=next(iter(first['documents'].values()))
            self.assertEqual(len(doc['aliases']),2)
            second=import_sources(source,folder/'output')
            self.assertEqual(first,second)
            self.assertEqual(doc['ingested_at'],next(iter(second['documents'].values()))['ingested_at'])
            reprocessed=import_sources(source,folder/'output',reprocess=True)
            self.assertEqual(first,reprocessed)

    def test_screenshot_overlap_is_link_only_and_not_name_merge(self):
        pdf=dict(document_id='pdf',media_type='application/pdf',publication_date=None,
                 observations=[{'printed_fields':{'wkn':'SYN123'}}])
        image=dict(document_id='image',media_type='image/png',publication_date=None,
                   observations=[{'source_text':'WKN SYN123','printed_fields':{}}])
        unrelated=dict(document_id='other',media_type='image/png',publication_date=None,
                       observations=[{'source_text':'Synthetic Corp','printed_fields':{}}])
        registry={'documents':{'p':pdf,'i':image,'u':unrelated}}
        _link_possible_overlaps(registry)
        self.assertEqual(image['possible_overlaps'][0]['document_id'],'pdf')
        self.assertEqual(image['possible_overlaps'][0]['review_status'],'needs_review')
        self.assertEqual(unrelated['possible_overlaps'],[])
        self.assertEqual(len(registry['documents']),3)

    def test_duplicate_alias_extension_is_validated_before_skip(self):
        try:import fitz
        except ImportError:self.skipTest('optional local decoder unavailable')
        root=Path('data/private');root.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as directory:
            folder=Path(directory);sources=folder/'input';sources.mkdir()
            image=sources/'one.png'
            pix=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,10,10),False)
            pix.clear_with(255);pix.save(image)
            import_sources(image,folder/'output',ocr=False)
            original=load_registry(folder/'output/registry.json')
            repeated=import_sources(image,folder/'output',ocr=False)
            self.assertEqual(original,repeated)
            (sources/'alias.png').write_bytes(image.read_bytes())
            aliased=import_sources(sources,folder/'output',ocr=False)
            self.assertEqual(len(next(iter(aliased['documents'].values()))['aliases']),2)
            self.assertEqual(aliased,import_sources(sources,folder/'output',ocr=False,reprocess=True))
            (sources/'two.jpg').write_bytes(image.read_bytes())
            before=(folder/'output/registry.json').read_bytes()
            with self.assertRaises(ValueError):import_sources(sources,folder/'output')
            self.assertEqual(before,(folder/'output/registry.json').read_bytes())


if __name__ == '__main__':
    unittest.main()
