import tempfile
import unittest
from pathlib import Path

from analysis import export_bundle, summarize
from lab import Lab


class AnalysisTests(unittest.TestCase):
    def test_blinded_export_hides_condition_and_pilot_excluded(self):
        with tempfile.TemporaryDirectory() as folder:
            lab = Lab(Path(folder) / 'db')
            try:
                token = lab.create(group=1)['token']
                lab.start(token, True, 'wenig', 'oft')
                lab.finish_plan(token, {'plan':'Basis', 'risks':''})
                lab.submit(token, {'plan':'Basis', 'risks':'Risiken'})
                bundle = export_bundle(lab.raw(), include_pilots=True)
                answer = bundle['blinded'][0]
                self.assertEqual(set(answer), {'rating_id', 'case_id', 'plan', 'risks'})
                self.assertNotIn('participant', answer)
                self.assertEqual(len(export_bundle(lab.raw())['blinded']), 0)
            finally:
                lab.close()

    def test_pair_difference_and_timeout_not_counted_as_fast_success(self):
        records = [{'participant':'P001', 'pilot':False, 'group':1, 'rounds':[
            {'rating_id':'x', 'case_id':'A', 'condition':'manual', 'status':'submitted', 'started_at':0, 'ended_at':100, 'ai_calls':[]},
            {'rating_id':'y', 'case_id':'B', 'condition':'ai', 'status':'submitted', 'started_at':200, 'ended_at':270, 'ai_calls':[]}]},
            {'participant':'P002', 'pilot':False, 'group':2, 'rounds':[
            {'rating_id':'z', 'case_id':'B', 'condition':'ai', 'status':'timed_out', 'started_at':0, 'ended_at':1500, 'ai_calls':[]}]}]
        report = summarize(records)
        self.assertEqual(report['complete_pairs'], 1)
        self.assertEqual(report['pairs'][0]['time_delta_ai_minus_manual'], -30)
        self.assertEqual(report['timeouts'], 1)
        self.assertEqual(report['incomplete_participants'], ['P002'])

    def test_missing_scores_not_zero_and_duplicate_ratings_rejected(self):
        self.assertEqual(summarize([])['quality_pairs'], [])
        with self.assertRaises(ValueError):
            summarize([], ratings=[{'rating_id':'X', 'rater':'R1'}, {'rating_id':'X', 'rater':'R1'}])


if __name__ == '__main__':
    unittest.main()
