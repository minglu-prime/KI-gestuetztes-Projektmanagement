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

    def test_quality_pairs_report_single_criteria_beside_sums(self):
        records = [{'participant':'P001', 'pilot':False, 'group':1, 'rounds':[
            {'rating_id':'m', 'case_id':'A', 'condition':'manual', 'status':'submitted', 'started_at':0, 'ended_at':100, 'ai_calls':[]},
            {'rating_id':'a', 'case_id':'B', 'condition':'ai', 'status':'submitted', 'started_at':200, 'ended_at':270, 'ai_calls':[]}]}]
        ratings = [
            {'rating_id':'m', 'rater':'R1', 'dependencies':18, 'resources':14, 'milestones':12,
             'risk_identification':14, 'prioritization':10, 'measures':10, 'severe_errors':0},
            {'rating_id':'m', 'rater':'R2', 'dependencies':16, 'resources':12, 'milestones':12,
             'risk_identification':12, 'prioritization':10, 'measures':10, 'severe_errors':1},
            {'rating_id':'a', 'rater':'R1', 'dependencies':12, 'resources':10, 'milestones':14,
             'risk_identification':18, 'prioritization':14, 'measures':12, 'severe_errors':2},
            {'rating_id':'a', 'rater':'R2', 'dependencies':14, 'resources':8, 'milestones':14,
             'risk_identification':16, 'prioritization':12, 'measures':12, 'severe_errors':2},
        ]
        (pair,) = summarize(records, ratings)['quality_pairs']
        self.assertEqual(pair['manual']['dependencies'], 17)
        self.assertEqual(pair['ai']['dependencies'], 13)
        self.assertEqual(pair['delta_ai_minus_manual']['dependencies'], -4)
        self.assertEqual(pair['delta_ai_minus_manual']['resources'], -4)
        self.assertEqual(pair['delta_ai_minus_manual']['plan'], -6)
        self.assertEqual(pair['delta_ai_minus_manual']['risk'], 9)


    def test_the_models_that_answered_are_reported(self):
        # Without a dated snapshot the provider may answer with another model; the report
        # names every model that answered in the formal study, pilots left out.
        def call(model, status='completed'):
            return {'status': status, 'model_returned': model}
        def session(pilot, calls):
            return {'participant': 'P', 'pilot': pilot, 'group': 1, 'rounds': [
                {'rating_id': 'x', 'case_id': 'A', 'condition': 'ai', 'status': 'submitted',
                 'started_at': 0, 'ended_at': 1, 'ai_calls': calls}]}
        report = summarize([session(False, [call('gpt-6-sol'), call(None, 'error')]),
                            session(False, [call('gpt-6-sol-b')]),
                            session(True, [call('pilot-model')])])
        self.assertEqual(report['models_returned'], ['gpt-6-sol', 'gpt-6-sol-b'])
        self.assertTrue(report['model_varies'])
        self.assertEqual(summarize([])['models_returned'], [])
        self.assertFalse(summarize([])['model_varies'])

if __name__ == '__main__':
    unittest.main()
