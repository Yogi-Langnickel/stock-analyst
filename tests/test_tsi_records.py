import copy
import unittest

from stock_analyst.tsi_records import make_observation, review_decision_matches


class TsiRecordTests(unittest.TestCase):
    def document(self):
        return dict(document_id='doc_'+'a'*64, sha256='a'*64,
                    original_publication='TSI', product='TSI USA',
                    publication_date='2026-01-02', ingested_at='2026-01-03T00:00:00Z')

    def test_exact_review_identity_and_no_automatic_approval(self):
        row = make_observation(self.document(), 'ranking', 1, [1, 2, 3, 4],
                               {'name': 'Synthetic Corp', 'rank': '1', 'score': '99'},
                               universe='Big Caps', source_text='synthetic evidence')
        self.assertEqual(row['review_status'], 'needs_review')
        self.assertFalse(row['exportable'])
        self.assertIsNone(row['instrument_id'])
        decision = {'review_hash': row['review_hash']}
        self.assertTrue(review_decision_matches(row, decision))
        changes = [('publication_date', '2026-02-02'), ('product', 'TSI Premium'),
                   ('record_type', 'recommendation'), ('universe', 'Small Caps'),
                   ('instrument_id', 'instrument_x'), ('strategy', 'other'),
                   ('as_of_date','2026-01-01'),('transaction_effective_date','2026-01-02'),
                   ('ingested_at','2026-01-04T00:00:00Z')]
        for key, value in changes:
            changed = copy.deepcopy(row); changed[key] = value
            self.assertFalse(review_decision_matches(changed, decision), key)
        for key, value in [('page', 2), ('bbox', [2, 3, 4, 5]),
                           ('document_sha256', 'b'*64), ('extraction_version', 'other')]:
            changed = copy.deepcopy(row); changed['evidence'][key] = value
            self.assertFalse(review_decision_matches(changed, decision), key)

    def test_same_instrument_distinct_observations_and_dates(self):
        doc = self.document()
        first = make_observation(doc, 'portfolio_snapshot', 1, [1, 2, 3, 4],
                                 {'wkn': 'SYN123', 'purchase_date': '01.01.2020'},
                                 as_of_date='2026-01-02')
        second = make_observation(doc, 'ranking', 2, [1, 2, 3, 4],
                                  {'wkn': 'SYN123'}, universe='Big Caps')
        self.assertEqual(first['instrument_id'], second['instrument_id'])
        self.assertNotEqual(first['observation_id'], second['observation_id'])
        self.assertIsNone(first['transaction_effective_date'])


if __name__ == '__main__':
    unittest.main()
