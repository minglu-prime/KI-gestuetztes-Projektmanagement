import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lab import Lab, Problem


class LabTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = 1000.0
        self.lab = Lab(Path(self.tmp.name) / 'lab.db', clock=lambda: self.now,
                       model='test-snapshot', api_key='')
        self.addCleanup(self.lab.close)

    def create(self, group=1):
        return self.lab.create(group=group, pilot=True)['token']

    def start(self, token):
        return self.lab.start(token, consent=True, pm_experience='wenig', ai_experience='oft')

    def test_cases_hidden_until_start_and_start_does_not_reset_clock(self):
        token = self.create()
        self.assertIsNone(self.lab.view(token)['case'])
        first = self.start(token)
        self.now += 30
        second = self.start(token)
        self.assertEqual(first['rounds'][0]['started_at'], second['rounds'][0]['started_at'])
        self.assertEqual(second['remaining_seconds'], 1470)

    def test_consent_required(self):
        with self.assertRaises(Problem):
            self.lab.start(self.create(), consent=False)

    def test_manual_ai_is_blocked_at_server(self):
        token = self.create()
        self.start(token)
        with self.assertRaises(Problem) as caught:
            self.lab.ask(token, 'Erstelle einen Plan')
        self.assertEqual(caught.exception.status, 403)

    def test_missing_key_is_logged_without_fake_answer(self):
        token = self.create(4)
        self.start(token)
        with self.assertRaises(Problem):
            self.lab.ask(token, 'Erstelle einen Plan')
        entry = self.lab.raw()[0]['rounds'][0]['ai_calls'][0]
        self.assertEqual(entry['status'], 'error')
        self.assertIsNone(entry['answer'])

    def test_autosave_survives_reopen(self):
        token = self.create()
        self.start(token)
        self.lab.save(token, {'plan': 'Entwurf', 'risks': ''})
        other = Lab(Path(self.tmp.name) / 'lab.db', clock=lambda: self.now)
        try:
            self.assertEqual(other.view(token)['rounds'][0]['draft']['plan'], 'Entwurf')
        finally:
            other.close()

    def test_timeout_keeps_last_saved_work_and_rejects_late_edits(self):
        token = self.create()
        self.start(token)
        self.lab.save(token, {'plan': 'Rechtzeitig', 'risks': ''})
        self.now += 1501
        with self.assertRaises(Problem):
            self.lab.save(token, {'plan': 'Zu spaet', 'risks': ''})
        row = self.lab.view(token)['rounds'][0]
        self.assertEqual(row['status'], 'timed_out')
        self.assertEqual(row['final']['plan'], 'Rechtzeitig')
        self.assertEqual(row['ended_at'], 2500)

    def test_submission_is_immutable_and_second_round_needs_explicit_start(self):
        token = self.create()
        self.start(token)
        self.lab.finish_plan(token, {'plan': 'Plan', 'risks': ''})
        self.lab.submit(token, {'plan': 'Plan', 'risks': 'Risiken'})
        with self.assertRaises(Problem):
            self.lab.save(token, {'plan': 'overwrite', 'risks': ''})
        view = self.lab.view(token)
        self.assertEqual(view['rounds'][1]['status'], 'ready')
        self.assertIsNone(view['case'])
        second = self.start(token)
        self.assertEqual(second['case']['id'], 'B')
        self.assertEqual(second['rounds'][1]['condition'], 'ai')

    def test_all_four_sequences(self):
        expected = [[('A', 'manual'), ('B', 'ai')], [('B', 'ai'), ('A', 'manual')],
                    [('B', 'manual'), ('A', 'ai')], [('A', 'ai'), ('B', 'manual')]]
        for group, sequence in enumerate(expected, 1):
            view = self.lab.view(self.create(group))
            self.assertEqual([(r['case_id'], r['condition']) for r in view['rounds']], sequence)

    def test_formal_creation_requires_frozen_protocol_and_ai(self):
        with self.assertRaises(Problem):
            self.lab.create(group=1, pilot=False)

    def test_unknown_token_rejected(self):
        with self.assertRaises(Problem) as caught:
            self.lab.view('unknown')
        self.assertEqual(caught.exception.status, 404)

    def test_ai_success_keeps_first_draft_and_model_metadata(self):
        token = self.create(4)
        self.start(token)
        with patch('lab.call_model', return_value={'text': 'KI Entwurf', 'model': 'test-snapshot',
                                                   'id': 'response-test', 'usage': {}}):
            self.lab.api_key = 'unit-test-only'
            self.lab.ask(token, 'Plan bitte')
        row = self.lab.view(token)['rounds'][0]
        self.assertEqual(row['first_ai_draft'], 'KI Entwurf')
        self.assertEqual(row['ai_calls'][0]['model_returned'], 'test-snapshot')
        self.assertEqual(row['draft']['plan'], '')

    def test_payload_validation(self):
        token = self.create()
        self.start(token)
        for payload in ({'plan': 42, 'risks': ''}, {'plan': 'a' * 50001, 'risks': ''}):
            with self.assertRaises(Problem):
                self.lab.save(token, payload)

    def test_reference_answer_hidden_until_plan_locked(self):
        token = self.create()
        initial = self.start(token)
        self.assertNotIn('reference_plan', initial['case'])
        self.assertNotIn('change', initial['case'])
        self.now += 90
        locked = self.lab.finish_plan(token, {'plan': 'Mein eigener Plan', 'risks': ''})
        self.assertIn('reference_plan', locked['case'])
        self.assertEqual(locked['remaining_seconds'], 1410)
        with self.assertRaises(Problem):
            self.lab.save(token, {'plan': 'Abgeschriebener Plan', 'risks': 'Analyse'})
        self.lab.submit(token, {'plan': 'Mein eigener Plan', 'risks': 'Analyse'})

    def test_delayed_save_cannot_cross_rounds(self):
        token = self.create()
        self.start(token)
        self.now += 1501
        self.start(token)
        with self.assertRaises(Problem):
            self.lab.save(token, {'plan':'STALE A', 'risks':''}, expected={'case_id':'A','stage':'plan'})
        self.assertEqual(self.lab.view(token)['rounds'][1]['draft']['plan'], '')

    def test_late_ai_kept_in_audit_not_applied_to_next_round(self):
        token = self.create(4)
        self.start(token)
        def provider(*args):
            self.now += 1501
            self.start(token)
            return {'text':'Late suggestion', 'model':'test-snapshot', 'id':'late', 'usage':{}}
        self.lab.api_key = 'test-only'
        with patch('lab.call_model', side_effect=provider), self.assertRaises(Problem):
            self.lab.ask(token, 'Plan')
        state = self.lab.view(token)
        self.assertEqual(state['rounds'][0]['ai_calls'][0]['status'], 'late')
        self.assertIsNone(state['rounds'][1]['first_ai_draft'])

    def test_formal_freeze_and_model_drift(self):
        self.lab.api_key = 'test-only'
        self.lab.model = 'test-2026-01-01'
        self.lab.freeze('TEST ONLY: controlled configuration attestation')
        token = self.lab.create(group=1, pilot=False, participant='P001')['token']
        self.lab.model = 'test-2026-02-01'
        with self.assertRaises(Problem):
            self.start(token)


if __name__ == '__main__':
    unittest.main()
