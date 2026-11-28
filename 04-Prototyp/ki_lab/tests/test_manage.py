"""CLI tests for manage.py: calibration, multi-file ratings, not-started counts, and deletion."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import manage
from lab import Lab


class ManageCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.db = self.folder / 'lab.db'
        self.env = {'OPENAI_API_KEY': 'test-only', 'PM_MODEL': 'gpt-6-sol', 'PM_LAB_MATERIALS': ''}

    def run_cli(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        code = 0
        with patch.dict(os.environ, self.env, clear=False), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                manage.main(['--db', str(self.db), *args])
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else 1
        return code, stdout.getvalue(), stderr.getvalue()

    def _complete_session(self, token):
        now = [1000.0]
        lab = Lab(self.db, clock=lambda: now[0], model='gpt-6-sol', api_key='test-only')
        try:
            lab.start(token, consent=True, pm_experience='wenig', ai_experience='oft')
            now[0] += 100
            lab.finish_plan(token, {'plan': 'Basis 1', 'risks': ''})
            now[0] += 50
            lab.submit(token, {'plan': 'Basis 1', 'risks': 'Risiken 1'})
            now[0] += 60
            lab.start(token)
            now[0] += 80
            lab.finish_plan(token, {'plan': 'Basis 2', 'risks': ''})
            now[0] += 40
            lab.submit(token, {'plan': 'Basis 2', 'risks': 'Risiken 2'})
        finally:
            lab.close()

    def _fill_ratings(self, path, base=12, errors=0):
        rows = json.loads(path.read_text(encoding='utf-8'))
        for row in rows:
            for key in ('dependencies', 'resources', 'milestones',
                        'risk_identification', 'prioritization', 'measures'):
                row[key] = base
            row['severe_errors'] = errors
        path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')

    def test_analyze_merges_multiple_rating_files_and_warns_on_single_rater(self):
        code, _, err = self.run_cli('freeze', '--attestation', 'TEST ONLY: controlled configuration attestation')
        self.assertEqual(code, 0, err)
        code, _, err = self.run_cli('enroll', '--count', '2')
        self.assertEqual(code, 0, err)
        invitations = json.loads((self.folder / 'invitations-001.json').read_text(encoding='utf-8'))
        token1 = invitations[0]['url'].split('#session=')[1]
        self._complete_session(token1)  # P002 stays invited / not started

        export_dir = self.folder / 'export'
        code, _, err = self.run_cli('export', '--out', str(export_dir))
        self.assertEqual(code, 0, err)
        r1 = export_dir / 'R1' / 'ratings.json'
        r2 = export_dir / 'R2' / 'ratings.json'
        self._fill_ratings(r1, base=14, errors=0)
        self._fill_ratings(r2, base=12, errors=1)

        # Single --ratings file stays backward-compatible and warns explicitly (no silent empty quality).
        out_single = self.folder / 'single.json'
        code, out, err = self.run_cli('analyze', '--ratings', str(r1), '--out', str(out_single))
        self.assertEqual(code, 0, err)
        self.assertIn('Warnung', err)
        single = json.loads(out_single.read_text(encoding='utf-8'))
        self.assertEqual(single['invited'], 2)
        self.assertEqual(single['participants'], 1)
        self.assertEqual(single['not_started_participants'], ['P002'])
        self.assertEqual(single['quality_pairs'], [])
        self.assertEqual(len(single['single_rater_ratings']), 2)
        self.assertTrue(single['warnings'])

        # Repeated --ratings flags merge both raters cleanly.
        out_repeat = self.folder / 'repeat.json'
        code, out, err = self.run_cli('analyze', '--ratings', str(r1), '--ratings', str(r2), '--out', str(out_repeat))
        self.assertEqual(code, 0, err)
        self.assertEqual(err, '')
        merged = json.loads(out_repeat.read_text(encoding='utf-8'))
        self.assertEqual(len(merged['quality_pairs']), 1)
        self.assertEqual(merged['single_rater_ratings'], [])
        self.assertEqual(merged['warnings'], [])
        self.assertIn('1 Qualitätspaar.', out)

        # Multiple paths after one --ratings flag also work.
        out_multi = self.folder / 'multi.json'
        code, _, err = self.run_cli('analyze', '--ratings', str(r1), str(r2), '--out', str(out_multi))
        self.assertEqual(code, 0, err)
        self.assertEqual(len(json.loads(out_multi.read_text(encoding='utf-8'))['quality_pairs']), 1)

        # Passing the same rater file twice is rejected clearly.
        code, _, err = self.run_cli('analyze', '--ratings', str(r1), str(r1), '--out', str(out_multi))
        self.assertNotEqual(code, 0)
        self.assertIn('Doppelte Bewertung', err)

        # Missing ratings file produces a clear German CLI error.
        code, _, err = self.run_cli('analyze', '--ratings', str(self.folder / 'fehlt.json'), '--out', str(out_multi))
        self.assertNotEqual(code, 0)
        self.assertIn('nicht gefunden', err)

    def test_analyze_include_pilots_flag_enables_pilot_calibration(self):
        lab = Lab(self.db, model='gpt-6-sol', api_key='test-only')
        try:
            token = lab.create(group=1, pilot=True)['token']
        finally:
            lab.close()
        self._complete_session(token)

        export_dir = self.folder / 'pilot_export'
        code, _, err = self.run_cli('export', '--out', str(export_dir), '--include-pilots')
        self.assertEqual(code, 0, err)
        r1 = export_dir / 'R1' / 'ratings.json'
        r2 = export_dir / 'R2' / 'ratings.json'
        self._fill_ratings(r1, base=15, errors=0)
        self._fill_ratings(r2, base=13, errors=1)

        # Without --include-pilots, pilot ratings are rejected to protect formal analysis.
        out_formal = self.folder / 'formal.json'
        code, _, err = self.run_cli('analyze', '--ratings', str(r1), str(r2), '--out', str(out_formal))
        self.assertNotEqual(code, 0)
        self.assertIn('Unbekannte Bewertungs-ID', err)

        # With --include-pilots, calibration succeeds and marks the report as including pilots.
        out_pilot = self.folder / 'pilot.json'
        code, out, err = self.run_cli('analyze', '--include-pilots', '--ratings', str(r1), str(r2), '--out', str(out_pilot))
        self.assertEqual(code, 0, err)
        self.assertIn('inkl. Piloten', out)
        report = json.loads(out_pilot.read_text(encoding='utf-8'))
        self.assertTrue(report['includes_pilots'])
        self.assertEqual(report['participants'], 1)
        self.assertEqual(len(report['quality_pairs']), 1)
        self.assertEqual(len(report['rater_disagreements']), 2)

    def test_delete_requires_confirm_and_deletes_participant(self):
        code, _, err = self.run_cli('freeze', '--attestation', 'TEST ONLY: controlled configuration attestation')
        self.assertEqual(code, 0, err)
        code, _, err = self.run_cli('enroll', '--count', '2')
        self.assertEqual(code, 0, err)

        # Without --confirm, nothing is deleted and CLI exits with error.
        code, _, err = self.run_cli('delete', 'P001')
        self.assertNotEqual(code, 0)
        self.assertIn('--confirm', err)
        lab = Lab(self.db, model='gpt-6-sol', api_key='test-only')
        try:
            self.assertEqual([s['participant'] for s in lab.raw()], ['P001', 'P002'])
        finally:
            lab.close()

        # With --confirm, P001 is deleted cleanly while P002 stays.
        code, out, err = self.run_cli('delete', 'P001', '--confirm')
        self.assertEqual(code, 0, err)
        self.assertIn('P001', out)
        lab = Lab(self.db, model='gpt-6-sol', api_key='test-only')
        try:
            self.assertEqual([s['participant'] for s in lab.raw()], ['P002'])
        finally:
            lab.close()

        # Deleting an unknown ID exits non-zero with a clear German error.
        code, _, err = self.run_cli('delete', 'P999', '--confirm')
        self.assertNotEqual(code, 0)
        self.assertIn('nicht gefunden', err)

        # If a concurrent WAL reader prevents compaction, delete still succeeds and warns on stderr.
        import sqlite3
        real_connect = sqlite3.connect
        reader = real_connect(self.db, isolation_level=None)
        self.addCleanup(reader.close)
        reader.execute('BEGIN')
        reader.execute('SELECT count(*) FROM sessions').fetchone()
        try:
            with patch('lab.sqlite3.connect', side_effect=lambda *a, **kw: real_connect(*a, **{**kw, 'timeout': 0.1})):
                code, out, err = self.run_cli('delete', 'P002', '--confirm')
            self.assertEqual(code, 0, err)
            self.assertIn('P002', out)
            self.assertIn('Warnung', err)
        finally:
            reader.execute('ROLLBACK')


if __name__ == '__main__':
    unittest.main()
