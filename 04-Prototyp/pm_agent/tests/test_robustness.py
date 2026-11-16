"""Files that cannot be opened, a damaged team file, and the KI-Lab child process: the site
says what went wrong and loses nothing on its own."""

from datetime import date

import pytest
from streamlit.testing.v1 import AppTest
from test_app import PLAN, PLANUNG, SITE, button, local, site  # noqa: F401 (fixtures)
from test_tools import PROJECT, TEAM

from pm_agent import lab_server, tracking, workbench
from pm_agent.lab_server import LabError
from pm_agent.workbench import InputError


def test_a_file_that_cannot_be_opened_is_reported_like_a_damaged_one(tmp_path):
    # A folder where the file should be: reading it fails with an OSError, not a ValueError.
    folder = tmp_path / "team.json"
    folder.mkdir()
    with pytest.raises(InputError, match="team.json konnte nicht gelesen werden"):
        workbench.load_team(folder)
    with pytest.raises(InputError, match="team.json konnte nicht gelesen werden"):
        tracking.load(folder)


def test_logged_runs_that_cannot_be_read_are_said_not_thrown(local, monkeypatch):  # noqa: F811
    def locked():
        raise PermissionError(13, "Zugriff verweigert")

    monkeypatch.setattr(workbench, "saved_runs", locked)
    at = AppTest.from_file(str(SITE.parent / PLANUNG), default_timeout=30).run()
    assert not at.exception
    assert any("Protokolle in logs/ konnten nicht gelesen werden" in e.value for e in at.error)


def test_a_damaged_team_file_is_replaced_only_when_confirmed(local, monkeypatch):  # noqa: F811
    def damaged():
        raise InputError("team.json ist beschädigt: Zeile 3")

    saved = []
    monkeypatch.setattr(workbench, "load_team", damaged)
    monkeypatch.setattr(workbench, "save_team", lambda team: saved.append(team))
    at = AppTest.from_file(str(SITE.parent / PLANUNG), default_timeout=30).run()
    at.session_state["team_editor_0"] = {
        "edited_rows": {},
        "added_rows": [{"Name": "Anna", "Skills": "Python 4", "Stunden/Woche": 40}],
        "deleted_rows": [],
    }
    at.run()
    assert not at.exception
    assert button(at, "Team lokal speichern").disabled

    at.checkbox(key="team_replace_damaged").check().run()
    button(at, "Team lokal speichern").click()
    at.run()
    assert not at.exception and len(saved) == 1


def test_kontrolle_does_not_promise_that_finished_work_is_lost(site):  # noqa: F811
    # Since the work done so far can be kept, the button text must not say it goes.
    open_end = PROJECT.model_copy(update={"deadline": date.max})
    tracking.adopt(open_end, TEAM, PLAN)
    tracking.save(tracking.apply_rows(tracking.load(), [{"ID": "A", "Status": "fertig"}]))
    at = site.switch_page("views/kontrolle.py").run()
    assert not at.exception
    texts = " ".join(c.value for c in at.caption)
    assert "Lädt die unfertigen Aufgaben" in texts
    assert "gehören dann nicht mehr dazu" not in texts


def test_a_lab_that_cannot_be_run_at_all_is_a_lab_error(tmp_path, monkeypatch):
    monkeypatch.setattr(lab_server, "KI_LAB_DIR", tmp_path / "fehlt")
    with pytest.raises(LabError, match="konnte nicht gestartet werden"):
        lab_server.start(["http://localhost:8501"], port=8999, db=tmp_path / "lab.db")
    assert not lab_server.started_here()


def test_the_running_lab_writes_its_messages_to_no_pipe_that_fills_up(tmp_path):
    # Nobody reads a pipe once the lab runs: a few tracebacks of aborted connections would
    # fill it and block the lab.
    from test_lab_server import free_port

    lab_server.start(["http://localhost:8501"], port=free_port(), db=tmp_path / "lab.db")
    try:
        assert lab_server._process.stderr is None
    finally:
        lab_server.stop()
