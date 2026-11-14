"""The KI-Lab page's helper against the real study server in 04-Prototyp/ki_lab."""

import socket
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from pm_agent import lab_server
from pm_agent.lab_server import LabError, allows_frame, health, start, stop


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_the_lab_starts_answers_allows_the_named_frame_and_stops(tmp_path):
    port = free_port()
    assert health(port) is None

    start(["http://localhost:8501"], port=port, db=tmp_path / "lab.db")
    try:
        assert lab_server.started_here()
        assert health(port)["ok"] is True
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/") as response:
            policy = response.headers["Content-Security-Policy"]
        assert "frame-ancestors http://localhost:8501;" in policy
        assert allows_frame("http://localhost:8501", port)
        assert not allows_frame("http://localhost:9999", port)
    finally:
        stop()

    assert not lab_server.started_here()
    assert health(port) is None


def test_a_lab_that_ends_during_start_reports_its_own_message(tmp_path):
    with pytest.raises(LabError, match="Nur Seiten auf diesem Rechner"):
        start(["https://evil.example"], port=free_port(), db=tmp_path / "lab.db")
    assert not lab_server.started_here()


def test_another_program_on_the_port_is_reported_not_taken_for_the_lab():
    class NotTheLab(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_error(404)

        def log_message(self, *args):
            pass

    other = HTTPServer(("127.0.0.1", 0), NotTheLab)
    threading.Thread(target=other.serve_forever, daemon=True).start()
    try:
        with pytest.raises(LabError, match="anderes Programm"):
            health(other.server_port)
    finally:
        other.shutdown()
        other.server_close()
