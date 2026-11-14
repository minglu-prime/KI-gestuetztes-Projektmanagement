import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from lab import Lab
from server import make_server


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lab = Lab(Path(self.tmp.name) / 'db', api_key='')
        self.server = make_server(self.lab, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = 'http://127.0.0.1:' + str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.lab.close()
        self.tmp.cleanup()

    def request(self, path, body=None, token='', **headers):
        if body is not None and path in ('/api/start','/api/save','/api/plan','/api/submit','/api/ai') and '_context' not in body:
            view = self.lab.view(token)
            target = next(r for r in view['rounds'] if r['status'] in ('ready','active'))
            body = {**body, '_context':{'case_id':target['case_id'],'stage':target['stage']}}
        request = urllib.request.Request(self.url + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token, **headers})
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    def test_participant_flow_and_download(self):
        status, body = self.request('/api/pilot', {'group': 1, 'pilot': False})
        self.assertEqual(status, 201)
        token = json.loads(body)['token']
        status, body = self.request('/api/session', token=token)
        self.assertTrue(json.loads(body)['pilot'])
        self.assertIsNone(json.loads(body)['case'])
        self.assertEqual(self.request('/api/start', {'consent': True, 'pm_experience': 'keine', 'ai_experience': 'nie'}, token)[0], 200)
        self.assertEqual(self.request('/api/ai', {'question': 'Plan'}, token)[0], 403)
        self.assertEqual(self.request('/api/plan', {'plan': 'Basis', 'risks': ''}, token)[0], 200)
        self.assertEqual(self.request('/api/submit', {'plan': 'Basis', 'risks': 'Analyse'}, token)[0], 200)
        status, body = self.request('/api/export', token=token)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['rounds'][0]['final']['plan'], 'Basis')

    def test_no_private_files_or_bulk_export(self):
        for path in ('/lab.py', '/cases.json', '/prompt.txt', '/data/lab.db', '/docs/scoring.md', '/api/admin', '/../../lab.py'):
            self.assertEqual(self.request(path)[0], 404, path)
        self.assertEqual(self.request('/api/session')[0], 401)

    def test_cross_origin_mutation_rejected(self):
        self.assertEqual(self.request('/api/pilot', {'group': 1}, Origin='https://evil.example')[0], 403)

    def test_malformed_json_is_400(self):
        request = urllib.request.Request(self.url + '/api/pilot', data=b'{bad', headers={'Content-Type':'application/json'})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request)
        self.assertEqual(caught.exception.code, 400)

    def test_second_server_cannot_share_study_port(self):
        duplicate = None
        try:
            with self.assertRaises(OSError):
                duplicate = make_server(self.lab, port=self.server.server_port)
        finally:
            if duplicate:
                duplicate.server_close()


if __name__ == '__main__':
    unittest.main()
