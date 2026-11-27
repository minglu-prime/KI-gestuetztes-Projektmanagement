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

    def test_pilot_ratings_excluded_by_default_and_supported_for_calibration(self):
        records = [{'participant': 'PILOT-abc', 'pilot': True, 'group': 1, 'consent_at': 10, 'rounds': [
            {'rating_id': 'pm', 'case_id': 'A', 'condition': 'manual', 'status': 'submitted',
             'started_at': 10, 'ended_at': 110, 'ai_calls': []},
            {'rating_id': 'pa', 'case_id': 'B', 'condition': 'ai', 'status': 'submitted',
             'started_at': 200, 'ended_at': 280, 'ai_calls': []},
        ]}]
        ratings = [
            {'rating_id': 'pm', 'rater': 'R1', 'dependencies': 16, 'resources': 12, 'milestones': 12,
             'risk_identification': 14, 'prioritization': 10, 'measures': 10, 'severe_errors': 0},
            {'rating_id': 'pm', 'rater': 'R2', 'dependencies': 14, 'resources': 10, 'milestones': 10,
             'risk_identification': 12, 'prioritization': 10, 'measures': 10, 'severe_errors': 1},
            {'rating_id': 'pa', 'rater': 'R1', 'dependencies': 18, 'resources': 14, 'milestones': 14,
             'risk_identification': 16, 'prioritization': 12, 'measures': 12, 'severe_errors': 0},
            {'rating_id': 'pa', 'rater': 'R2', 'dependencies': 16, 'resources': 12, 'milestones': 12,
             'risk_identification': 14, 'prioritization': 12, 'measures': 12, 'severe_errors': 0},
        ]
        # Formal default still excludes pilots and rejects pilot ratings.
        formal = summarize(records)
        self.assertEqual(formal['participants'], 0)
        self.assertFalse(formal['includes_pilots'])
        with self.assertRaises(ValueError):
            summarize(records, ratings)
        # Explicit include_pilots=True enables rater calibration on pilot sessions.
        cal = summarize(records, ratings, include_pilots=True)
        self.assertTrue(cal['includes_pilots'])
        self.assertEqual(cal['participants'], 1)
        self.assertEqual(cal['complete_pairs'], 1)
        self.assertEqual(len(cal['quality_pairs']), 1)
        gaps = {d['rating_id']: d['absolute_total_gap'] for d in cal['rater_disagreements']}
        self.assertEqual(gaps, {'pa': 8, 'pm': 8})

    def test_single_rater_ratings_reported_explicitly_with_warning(self):
        records = [{'participant': 'P001', 'pilot': False, 'group': 1, 'consent_at': 1, 'rounds': [
            {'rating_id': 'm1', 'case_id': 'A', 'condition': 'manual', 'status': 'submitted',
             'started_at': 0, 'ended_at': 100, 'ai_calls': []},
            {'rating_id': 'a1', 'case_id': 'B', 'condition': 'ai', 'status': 'submitted',
             'started_at': 200, 'ended_at': 270, 'ai_calls': []},
        ]}]
        r1_only = [
            {'rating_id': 'm1', 'rater': 'R1', 'dependencies': 18, 'resources': 14, 'milestones': 12,
             'risk_identification': 14, 'prioritization': 10, 'measures': 10, 'severe_errors': 0},
            {'rating_id': 'a1', 'rater': 'R1', 'dependencies': 16, 'resources': 12, 'milestones': 12,
             'risk_identification': 16, 'prioritization': 12, 'measures': 12, 'severe_errors': 1},
        ]
        report = summarize(records, r1_only)
        self.assertEqual(report['quality_pairs'], [])
        self.assertEqual(report['single_rater_ratings'], [
            {'rating_id': 'a1', 'rater': 'R1', 'missing_rater': 'R2'},
            {'rating_id': 'm1', 'rater': 'R1', 'missing_rater': 'R2'},
        ])
        self.assertTrue(report['warnings'])
        # Passing only blank template rows also warns instead of silently returning empty quality.
        blank = [
            {'rating_id': 'm1', 'rater': 'R1', 'dependencies': None, 'resources': None, 'milestones': None,
             'risk_identification': None, 'prioritization': None, 'measures': None, 'severe_errors': None},
        ]
        blank_report = summarize(records, blank)
        self.assertEqual(blank_report['single_rater_ratings'], [])
        self.assertTrue(blank_report['warnings'])
        # Without ratings argument, no rating warning is emitted.
        self.assertEqual(summarize(records)['warnings'], [])

    def test_invited_not_started_participants_separated_from_participants(self):
        records = [
            {'participant': 'P001', 'pilot': False, 'group': 1, 'consent_at': 10, 'rounds': [
                {'rating_id': 'r1', 'case_id': 'A', 'condition': 'manual', 'status': 'submitted',
                 'started_at': 10, 'ended_at': 110, 'ai_calls': []},
                {'rating_id': 'r2', 'case_id': 'B', 'condition': 'ai', 'status': 'submitted',
                 'started_at': 200, 'ended_at': 270, 'ai_calls': []},
            ]},
            {'participant': 'P002', 'pilot': False, 'group': 2, 'consent_at': 20, 'rounds': [
                {'rating_id': 'r3', 'case_id': 'B', 'condition': 'ai', 'status': 'timed_out',
                 'started_at': 20, 'ended_at': 1520, 'ai_calls': []},
                {'rating_id': 'r4', 'case_id': 'A', 'condition': 'manual', 'status': 'ready',
                 'started_at': None, 'ended_at': None, 'ai_calls': []},
            ]},
            {'participant': 'P003', 'pilot': False, 'group': 3, 'consent_at': None, 'rounds': [
                {'rating_id': 'r5', 'case_id': 'B', 'condition': 'manual', 'status': 'ready',
                 'started_at': None, 'ended_at': None, 'ai_calls': []},
                {'rating_id': 'r6', 'case_id': 'A', 'condition': 'ai', 'status': 'ready',
                 'started_at': None, 'ended_at': None, 'ai_calls': []},
            ]},
        ]
        report = summarize(records)
        self.assertEqual(report['invited'], 3)
        self.assertEqual(report['participants'], 2)
        self.assertEqual(report['not_started_participants'], ['P003'])
        self.assertEqual(report['incomplete_participants'], ['P002'])
        self.assertEqual({o['participant'] for o in report['observations']}, {'P001', 'P002'})

    def test_descriptive_stats_range_by_case_and_by_experience(self):
        records = [
            {'participant': 'P001', 'pilot': False, 'group': 1, 'consent_at': 1,
             'experience': {'pm': 'wenig', 'ai': 'oft'}, 'rounds': [
                 {'rating_id': 'p1m', 'case_id': 'A', 'condition': 'manual', 'status': 'submitted',
                  'started_at': 0, 'ended_at': 100, 'ai_calls': []},
                 {'rating_id': 'p1a', 'case_id': 'B', 'condition': 'ai', 'status': 'submitted',
                  'started_at': 200, 'ended_at': 260, 'ai_calls': []},
             ]},
            {'participant': 'P002', 'pilot': False, 'group': 3, 'consent_at': 2,
             'experience': {'pm': 'viel', 'ai': 'selten'}, 'rounds': [
                 {'rating_id': 'p2m', 'case_id': 'B', 'condition': 'manual', 'status': 'submitted',
                  'started_at': 0, 'ended_at': 120, 'ai_calls': []},
                 {'rating_id': 'p2a', 'case_id': 'A', 'condition': 'ai', 'status': 'submitted',
                  'started_at': 200, 'ended_at': 300, 'ai_calls': []},
             ]},
        ]
        def pair_rating(rid, dep, res, mil, rsk, pri, mea, err):
            return [
                {'rating_id': rid, 'rater': rater, 'dependencies': dep, 'resources': res,
                 'milestones': mil, 'risk_identification': rsk, 'prioritization': pri,
                 'measures': mea, 'severe_errors': err}
                for rater in ('R1', 'R2')
            ]
        ratings = (
            pair_rating('p1m', 10, 10, 10, 10, 10, 10, 2)  # total 60, plan 30, risk 30, err 2
            + pair_rating('p1a', 15, 10, 15, 15, 10, 15, 0)  # total 80 (+20), plan 40 (+10), risk 40 (+10), err 0 (-2)
            + pair_rating('p2m', 18, 12, 10, 16, 12, 12, 0)  # total 80, plan 40, risk 40, err 0
            + pair_rating('p2a', 14, 12, 10, 14, 12, 12, 1)  # total 74 (-6), plan 36 (-4), risk 38 (-2), err 1 (+1)
        )
        report = summarize(records, ratings)
        # Time deltas: P001 = 60 - 100 = -40, P002 = 100 - 120 = -20
        self.assertEqual(report['time_delta_stats'], {'n': 2, 'median': -30, 'min': -40, 'max': -20})
        self.assertEqual(report['quality_delta_stats']['total'], {'n': 2, 'median': 7, 'min': -6, 'max': 20})
        self.assertEqual(report['quality_delta_stats']['errors'], {'n': 2, 'median': -0.5, 'min': -2, 'max': 1})
        # By case: Case A has P001 manual (100s, total 60) and P002 ai (100s, total 74)
        self.assertEqual(report['by_case']['A']['submitted_rounds'], 2)
        self.assertEqual(report['by_case']['A']['seconds'], {'n': 2, 'median': 100, 'min': 100, 'max': 100})
        self.assertEqual(report['by_case']['A']['total'], {'n': 2, 'median': 67, 'min': 60, 'max': 74})
        # Case B has P001 ai (60s, total 80) and P002 manual (120s, total 80)
        self.assertEqual(report['by_case']['B']['seconds'], {'n': 2, 'median': 90, 'min': 60, 'max': 120})
        self.assertEqual(report['by_case']['B']['total'], {'n': 2, 'median': 80, 'min': 80, 'max': 80})
        # By experience stratification
        self.assertEqual(report['by_experience']['pm']['wenig']['participants'], 1)
        self.assertEqual(report['by_experience']['pm']['wenig']['time_delta_stats'],
                         {'n': 1, 'median': -40, 'min': -40, 'max': -40})
        self.assertEqual(report['by_experience']['pm']['viel']['quality_delta_stats']['total'],
                         {'n': 1, 'median': -6, 'min': -6, 'max': -6})
        self.assertEqual(report['by_experience']['ai']['oft']['participants'], 1)
        self.assertEqual(report['by_experience']['ai']['selten']['participants'], 1)

if __name__ == '__main__':
    unittest.main()
