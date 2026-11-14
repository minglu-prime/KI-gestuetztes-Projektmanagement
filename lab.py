"""Local study service. No third-party runtime dependencies."""
import copy
import hashlib
import json
import os
import re
import secrets
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SEQUENCES = {1: [('A', 'manual'), ('B', 'ai')], 2: [('B', 'ai'), ('A', 'manual')],
             3: [('B', 'manual'), ('A', 'ai')], 4: [('A', 'ai'), ('B', 'manual')]}
LIMIT = 25 * 60


class Problem(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def call_model(api_key, model, messages):
    payload = {'model': model, 'input': messages, 'store': False, 'max_output_tokens': 3500}
    request = urllib.request.Request('https://api.openai.com/v1/responses',
        data=json.dumps(payload).encode(), headers={'Authorization': 'Bearer ' + api_key,
                                                  'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            value = json.load(response)
    except urllib.error.HTTPError as exc:
        raise Problem(f'KI-Anbieter meldet HTTP {exc.code}. Keine Antwort erzeugt.', 502) from None
    except (OSError, ValueError) as exc:
        raise Problem('KI-Verbindung fehlgeschlagen oder ungültige Antwort. Bitte erneut versuchen.', 502) from exc
    if value.get('status') != 'completed':
        raise Problem('KI-Antwort unvollständig. Sie wird nicht als Vorschlag übernommen.', 502)
    answer = '\n'.join(part.get('text', '') for item in value.get('output', [])
                       if item.get('type') == 'message' for part in item.get('content', [])
                       if part.get('type') == 'output_text')
    if not answer.strip():
        raise Problem('KI lieferte keinen verwendbaren Text.', 502)
    return {'text': answer, 'model': value.get('model'), 'id': value.get('id'), 'usage': value.get('usage')}


class Lab:
    def __init__(self, database, clock=time.time, model=None, api_key=None):
        self.path = Path(database)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, check_same_thread=False, timeout=15)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, body TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS settings (name TEXT PRIMARY KEY, body TEXT NOT NULL)')
        self.db.commit()
        self.lock = threading.RLock()
        self.clock = clock
        self.model = model if model is not None else os.environ.get('PM_MODEL', '')
        self.api_key = api_key if api_key is not None else os.environ.get('OPENAI_API_KEY', '')
        self.materials = json.loads((ROOT / 'cases.json').read_text(encoding='utf-8'))
        self.prompt = (ROOT / 'prompt.txt').read_text(encoding='utf-8')

    def close(self):
        self.db.close()

    def config(self):
        return {'case_version': self.materials['version'],
                'materials_sha256': hashlib.sha256(canonical(self.materials).encode()).hexdigest(),
                'prompt_sha256': hashlib.sha256(self.prompt.encode()).hexdigest(),
                'model': self.model, 'api': 'https://api.openai.com/v1/responses',
                'max_output_tokens': 3500, 'limit_seconds': LIMIT, 'protocol_version': '1.0'}

    def freeze(self, attestation):
        if not self.api_key or not re.search(r'\d{4}-\d{2}-\d{2}$', self.model):
            raise Problem('Für Freeze: API-Key und datierte Modell-Snapshot-ID konfigurieren.')
        if not isinstance(attestation, str) or len(attestation.strip()) < 20:
            raise Problem('Freigaben und erfolgreichen Live-Pilot schriftlich bestätigen (mind. 20 Zeichen).')
        with self.lock:
            if self.db.execute("SELECT 1 FROM settings WHERE name='freeze'").fetchone():
                raise Problem('Bereits eingefroren. Für ein neues Protokoll eine neue Datenbank verwenden.', 409)
            value = {'config': self.config(), 'at': self.clock(), 'attestation': attestation}
            self.db.execute("INSERT INTO settings VALUES ('freeze', ?)", (canonical(value),))
            self.db.commit()
            return value

    def _formal_ready(self):
        row = self.db.execute("SELECT body FROM settings WHERE name='freeze'").fetchone()
        if not row or json.loads(row[0])['config'] != self.config() or not self.api_key:
            raise Problem('Formale Studie gesperrt: Freeze, Modellkonfiguration oder API-Key prüfen.', 409)

    def create(self, group=1, pilot=True, participant=None):
        if type(group) is not int or group not in SEQUENCES:
            raise Problem('Gruppe muss 1–4 sein.')
        with self.lock:
            if not pilot:
                self._formal_ready()
                if not isinstance(participant, str) or not re.fullmatch(r'P\d{3}', participant):
                    raise Problem('Anonyme Kennung im Format P001 erforderlich.')
                if any(s['participant'] == participant for s in self.raw()):
                    raise Problem('Teilnehmerkennung bereits vorhanden.', 409)
            token = secrets.token_urlsafe(32)
            state = {'schema_version': 1, 'participant': participant or 'PILOT-' + secrets.token_hex(3),
                     'pilot': bool(pilot), 'group': group, 'created_at': self.clock(),
                     'config': self.config(), 'materials': copy.deepcopy(self.materials), 'prompt': self.prompt,
                     'consent_at': None, 'experience': {}, 'reflection': {}, 'events': [],
                     'rounds': [{'case_id': c, 'condition': mode, 'stage': 'plan', 'rating_id': 'R-' + secrets.token_hex(12), 'status': 'ready', 'started_at': None,
                                 'ended_at': None, 'draft': {'plan': '', 'risks': ''}, 'final': None,
                                 'first_ai_draft': None, 'ai_calls': [], 'revisions': []}
                                for c, mode in SEQUENCES[group]]}
            self._put(token, state)
            return {'token': token, 'participant': state['participant'], 'pilot': state['pilot']}

    def _put(self, token, state):
        self.db.execute('INSERT OR REPLACE INTO sessions VALUES (?, ?)', (token, canonical(state)))
        self.db.commit()

    def _load(self, token):
        row = self.db.execute('SELECT body FROM sessions WHERE token=?', (token,)).fetchone()
        if not row:
            raise Problem('Sitzung nicht gefunden. Einladungslink prüfen.', 404)
        state = json.loads(row[0])
        for r in state['rounds']:
            if r['status'] == 'active' and self.clock() >= r['started_at'] + LIMIT:
                r.update(status='timed_out', ended_at=r['started_at'] + LIMIT, final=copy.deepcopy(r['draft']))
                state['events'].append({'at': self.clock(), 'type': 'deadline', 'case_id': r['case_id']})
                self._put(token, state)
        return state

    def _active(self, state):
        for r in state['rounds']:
            if r['status'] == 'active':
                return r
        raise Problem('Keine aktive Runde. Beendete Runden sind schreibgeschützt.', 409)

    def view(self, token):
        with self.lock:
            state = self._load(token)
            active = next((r for r in state['rounds'] if r['status'] == 'active'), None)
            result = {k: copy.deepcopy(v) for k, v in state.items() if k not in ('materials', 'prompt')}
            result['case'] = self.visible_case(state, active) if active else None
            result['practice'] = state['materials']['practice']
            result['remaining_seconds'] = max(0, int(active['started_at'] + LIMIT - self.clock())) if active else 0
            result['server_time'] = self.clock()
            result['ai_configured'] = bool(self.api_key and self.model)
            return result

    def visible_case(self, state, current):
        case = copy.deepcopy(state['materials']['cases'][current['case_id']])
        if current['stage'] == 'plan':
            case.pop('reference_plan')
            case.pop('change')
        return case

    def _match(self, r, expected):
        if expected is not None and expected != {'case_id': r['case_id'], 'stage': r['stage']}:
            raise Problem('Veraltete Anfrage: Fall oder Aufgabenphase hat sich geändert.', 409)

    def start(self, token, consent=False, pm_experience='', ai_experience='', expected=None):
        with self.lock:
            state = self._load(token)
            target = next((r for r in state['rounds'] if r['status'] in ('active', 'ready')), None)
            if target is None:
                raise Problem('Alle Runden beendet.', 409)
            self._match(target, expected)
            if not state['consent_at']:
                if consent is not True:
                    raise Problem('Einwilligung vor Beginn erforderlich.')
                if pm_experience not in ('keine', 'wenig', 'viel') or ai_experience not in ('nie', 'selten', 'oft'):
                    raise Problem('Erfahrungsangaben auswählen.')
                state['consent_at'] = self.clock()
                state['experience'] = {'pm': pm_experience, 'ai': ai_experience}
            if not state['pilot']:
                self._formal_ready()
                if state['config'] != self.config():
                    raise Problem('Studienkonfiguration geändert.', 409)
            if not any(r['status'] == 'active' for r in state['rounds']):
                r = next((r for r in state['rounds'] if r['status'] == 'ready'), None)
                if not r:
                    raise Problem('Alle Runden beendet.', 409)
                r.update(status='active', started_at=self.clock())
            self._put(token, state)
            return self.view(token)

    def _draft(self, payload):
        if not isinstance(payload, dict):
            raise Problem('Ungültiger Entwurf.')
        result = {}
        for key in ('plan', 'risks'):
            value = payload.get(key)
            if not isinstance(value, str) or len(value) > 50000:
                raise Problem('Plan und Risiken müssen Text mit höchstens 50.000 Zeichen sein.')
            result[key] = value
        return result

    def save(self, token, payload, expected=None):
        draft = self._draft(payload)
        with self.lock:
            state = self._load(token)
            r = self._active(state)
            self._match(r, expected)
            self._stage_draft(r, draft)
            if r['draft'] != draft:
                r['draft'] = draft
                r['revisions'].append({'at': self.clock(), 'draft': copy.deepcopy(draft)})
                self._put(token, state)
            return {'saved_at': self.clock()}

    def _stage_draft(self, r, draft):
        if r['stage'] == 'plan' and draft['risks'].strip():
            raise Problem('Risikoaufgabe erst nach Abschluss des Basisplans.', 409)
        if r['stage'] == 'risks' and draft['plan'] != r['draft']['plan']:
            raise Problem('Basisplan ist bereits gesperrt.', 409)

    def finish_plan(self, token, payload, expected=None):
        draft = self._draft(payload)
        if not draft['plan'].strip():
            raise Problem('Bitte zuerst den Basisplan bearbeiten.')
        with self.lock:
            state = self._load(token)
            r = self._active(state)
            self._match(r, expected)
            if r['stage'] != 'plan':
                raise Problem('Basisplan bereits abgeschlossen.', 409)
            self._stage_draft(r, draft)
            r.update(draft=draft, stage='risks', plan_locked_at=self.clock())
            state['events'].append({'at': self.clock(), 'type': 'plan_locked', 'case_id': r['case_id']})
            self._put(token, state)
            return self.view(token)

    def submit(self, token, payload, expected=None):
        draft = self._draft(payload)
        if not draft['plan'].strip() or not draft['risks'].strip():
            raise Problem('Beide Aufgaben bearbeiten; Teilstände werden beim Zeitablauf automatisch gesichert.')
        with self.lock:
            state = self._load(token)
            r = self._active(state)
            self._match(r, expected)
            if r['stage'] != 'risks':
                raise Problem('Zuerst Basisplan abschließen, dann Risikoaufgabe bearbeiten.', 409)
            self._stage_draft(r, draft)
            r.update(draft=draft, final=copy.deepcopy(draft), status='submitted', ended_at=self.clock())
            state['events'].append({'at': self.clock(), 'type': 'submitted', 'case_id': r['case_id']})
            self._put(token, state)
            return self.view(token)

    def reflect(self, token, payload):
        if not isinstance(payload, dict) or any(not isinstance(v, str) or len(v) > 5000 for v in payload.values()):
            raise Problem('Ungültige Reflexion.')
        allowed = ('time_spent', 'trust', 'human_decisions', 'workload', 'protocol_deviations')
        with self.lock:
            state = self._load(token)
            if any(r['status'] in ('ready', 'active') for r in state['rounds']):
                raise Problem('Reflexion erst nach beiden Runden.', 409)
            state['reflection'] = {k: payload.get(k, '') for k in allowed}
            state['reflection_at'] = self.clock()
            self._put(token, state)
            return {'saved': True}

    def ask(self, token, question, expected=None):
        if not isinstance(question, str) or not 1 <= len(question.strip()) <= 4000:
            raise Problem('Frage mit 1–4.000 Zeichen eingeben.')
        with self.lock:
            state = self._load(token)
            r = self._active(state)
            self._match(r, expected)
            if r['condition'] != 'ai':
                raise Problem('KI ist in der manuellen Bedingung nicht erlaubt.', 403)
            if not state['pilot']:
                self._formal_ready()
            # Stale requests remain visible as interrupted; do not silently lose their audit trail.
            for old in r['ai_calls']:
                if old['status'] == 'pending' and self.clock() - old['started_at'] > 90:
                    old.update(status='interrupted', error='Keine bestätigte Antwort nach 90 Sekunden.')
            if any(c['status'] == 'pending' for c in r['ai_calls']):
                raise Problem('Eine KI-Anfrage läuft bereits.', 409)
            if len(r['ai_calls']) >= 12:
                raise Problem('Maximal 12 KI-Anfragen pro Runde erreicht.', 429)
            messages = [{'role': 'developer', 'content': state['prompt']},
                        {'role': 'user', 'content': 'FALLMATERIAL:\n' + canonical(self.visible_case(state, r))}]
            for previous in r['ai_calls']:
                if previous['status'] == 'completed':
                    messages.extend([{'role': 'user', 'content': previous['question']},
                                     {'role': 'assistant', 'content': previous['answer']}])
            messages.append({'role': 'user', 'content': 'AKTUELLER ENTWURF:\n' + canonical(r['draft']) + '\nFRAGE:\n' + question})
            call = {'id': secrets.token_hex(8), 'question': question, 'started_at': self.clock(),
                    'ended_at': None, 'status': 'pending', 'answer': None, 'error': None,
                    'model_requested': state['config']['model'], 'input': messages}
            r['ai_calls'].append(call)
            case_id = r['case_id']
            self._put(token, state)
        result, failure = None, None
        try:
            if not self.api_key or not state['config']['model']:
                raise Problem('KI nicht konfiguriert. Studienleitung muss API-Key und Modell setzen.', 503)
            result = call_model(self.api_key, state['config']['model'], messages)
        except Problem as exc:
            failure = exc
        except Exception:
            failure = Problem('Unerwarteter KI-Fehler. Anfrage protokolliert, keine Ersatzantwort.', 502)
        with self.lock:
            state = self._load(token)
            r = next(x for x in state['rounds'] if x['case_id'] == case_id)
            saved = next(x for x in r['ai_calls'] if x['id'] == call['id'])
            saved['ended_at'] = self.clock()
            if failure:
                saved.update(status='error', error=str(failure))
            else:
                late = r['status'] != 'active'
                saved.update(status='late' if late else 'completed', answer=result['text'],
                             model_returned=result['model'], response_id=result['id'], usage=result['usage'])
                if not late and r['first_ai_draft'] is None:
                    r['first_ai_draft'] = result['text']
                if late:
                    failure = Problem('Antwort erst nach Rundenende eingetroffen; nur im Audit gespeichert.', 409)
            self._put(token, state)
        if failure:
            raise failure
        return {'answer': result['text']}

    def raw(self):
        with self.lock:
            tokens = [r[0] for r in self.db.execute('SELECT token FROM sessions ORDER BY rowid')]
            return [self._load(t) for t in tokens]
