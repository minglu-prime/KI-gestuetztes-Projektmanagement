"""Loopback-only participant server; operator functions are CLI-only."""
import argparse
import json
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from lab import ROOT, Lab, Problem


class LocalServer(ThreadingHTTPServer):
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def make_server(lab, port=8874):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass  # Do not log bearer tokens or participant content.

        def send(self, status, value, content_type='application/json; charset=utf-8'):
            body = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            self.end_headers()
            self.wfile.write(body)

        def gate(self):
            host = self.headers.get('Host', '')
            if host not in (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'):
                raise Problem('Host nicht erlaubt.', 403)
            origin = self.headers.get('Origin')
            if origin and origin != 'http://' + host:
                raise Problem('Anfrage von fremder Website nicht erlaubt.', 403)

        def token(self):
            header = self.headers.get('Authorization', '')
            if not header.startswith('Bearer ') or len(header) < 20:
                raise Problem('Sitzungsschlüssel fehlt.', 401)
            return header[7:]

        def do_GET(self):
            try:
                self.gate()
                path = urlsplit(self.path).path
                static = {'/': ('index.html', 'text/html'), '/app.js': ('app.js', 'text/javascript'),
                          '/style.css': ('style.css', 'text/css')}
                if path in static:
                    name, mime = static[path]
                    self.send(200, (ROOT / 'web' / name).read_bytes(), mime + '; charset=utf-8')
                elif path == '/api/health':
                    self.send(200, {'ok': True, 'ai_configured': bool(lab.api_key and lab.model),
                                    'model': lab.model, 'case_version': lab.materials['version']})
                elif path in ('/api/session', '/api/export'):
                    self.send(200, lab.view(self.token()))
                else:
                    raise Problem('Nicht gefunden.', 404)
            except Problem as exc:
                self.send(exc.status, {'error': str(exc)})

        def do_POST(self):
            try:
                self.gate()
                if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    raise Problem('JSON erforderlich.', 415)
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                except ValueError:
                    raise Problem('Ungültige Länge.') from None
                if not 0 < length <= 250000:
                    raise Problem('Anfrage zu groß oder leer.', 413)
                try:
                    payload = json.loads(self.rfile.read(length))
                except (ValueError, UnicodeDecodeError):
                    raise Problem('Ungültiges JSON.') from None
                if not isinstance(payload, dict):
                    raise Problem('JSON-Objekt erforderlich.')
                path = urlsplit(self.path).path
                if path == '/api/pilot':
                    self.send(201, lab.create(group=payload.get('group', 1), pilot=True))
                    return
                if path not in ('/api/start', '/api/save', '/api/plan', '/api/submit', '/api/ai', '/api/reflect'):
                    raise Problem('Nicht gefunden.', 404)
                token = self.token()
                expected = payload.get('_context')
                if path != '/api/reflect' and (not isinstance(expected, dict) or set(expected) != {'case_id', 'stage'}):
                    raise Problem('Fall- und Phasenkontext fehlt.')
                if path == '/api/start':
                    value = lab.start(token, payload.get('consent'), payload.get('pm_experience'), payload.get('ai_experience'), expected)
                elif path == '/api/save':
                    value = lab.save(token, payload, expected)
                elif path == '/api/submit':
                    value = lab.submit(token, payload, expected)
                elif path == '/api/plan':
                    value = lab.finish_plan(token, payload, expected)
                elif path == '/api/ai':
                    value = lab.ask(token, payload.get('question'), expected)
                else:
                    value = lab.reflect(token, payload)
                self.send(200, value)
            except Problem as exc:
                self.send(exc.status, {'error': str(exc)})

    return LocalServer(('127.0.0.1', port), Handler)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='KI · PM Lab — lokaler Studienserver')
    parser.add_argument('--port', type=int, default=8874)
    parser.add_argument('--db', default=str(ROOT / 'data' / 'lab.db'))
    args = parser.parse_args()
    lab = Lab(args.db)
    server = make_server(lab, args.port)
    print(f'KI · PM Lab: http://127.0.0.1:{server.server_port}', flush=True)
    print('KI konfiguriert: ' + ('ja' if lab.api_key and lab.model else 'nein — ehrlicher Fehlerpfad, keine Demo-Antworten'), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        lab.close()
