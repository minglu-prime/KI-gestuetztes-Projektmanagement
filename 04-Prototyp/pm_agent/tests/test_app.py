"""The Streamlit site headless, with the agent replaced: no network, no files in data/ or logs/."""

import socket
import tomllib
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest
from test_tools import PROJECT, TEAM, plan_input

from pm_agent import agent, followup, lab_server, tracking, workbench
from pm_agent.agent import AgentError, PlanningError
from pm_agent.models import ControlReport, Plan, StatusSummary

SITE = Path(__file__).parents[1] / "app.py"
PLANUNG = "pages/planung.py"
PLAN = Plan.model_validate(plan_input())


@pytest.fixture
def local(monkeypatch, tmp_path):
    """Nothing is read from or written to the real data/ and logs/, and no lab is running."""
    monkeypatch.setattr(workbench, "load_team", lambda: list(TEAM))
    monkeypatch.setattr(workbench, "saved_runs", lambda: [])
    monkeypatch.setattr(workbench, "RUNS_CSV", tmp_path / "runs.csv")
    monkeypatch.setattr(tracking, "PROJECT_FILE", tmp_path / "projekt.json")
    monkeypatch.setattr(tracking, "LOG_DIR", tmp_path)
    with socket.socket() as probe:  # a port where nothing listens
        probe.bind(("127.0.0.1", 0))
        monkeypatch.setattr(lab_server, "PORT", probe.getsockname()[1])


@pytest.fixture
def app(local):
    """The Planung page on its own."""
    at = AppTest.from_file(str(SITE.parent / PLANUNG), default_timeout=30)
    at.run()
    return at


@pytest.fixture
def site(local):
    """The whole site, opened on the Startseite."""
    at = AppTest.from_file(str(SITE), default_timeout=30)
    at.run()
    return at


def fill_project(at):
    at.text_area(key="idea").input(PROJECT.idea)
    at.date_input(key="start").set_value(PROJECT.start_date)
    at.date_input(key="deadline").set_value(PROJECT.deadline)
    at.checkbox(key="consent").check()
    return at.run()


def button(at, label):
    return next(b for b in at.button if b.label == label)


def test_without_project_and_consent_planning_is_blocked(app):
    assert not app.exception
    assert button(app, "Plan mit Claude erstellen").disabled
    infos = [i.value for i in app.info]
    assert any("Projektidee und Deadline (Schritt 2)" in i for i in infos)
    assert any("Noch kein Plan" in i for i in infos)


def test_a_plan_from_the_agent_is_checked_shown_and_exported(app, monkeypatch):
    def fake_run(project, team, on_round=None):
        assert (project, team) == (PROJECT, TEAM)
        on_round(
            {
                "tool_results": [
                    {"tool": "submit_plan", "is_error": False, "content": "Plan angenommen."}
                ]
            }
        )
        return PLAN

    monkeypatch.setattr(agent, "run_planning", fake_run)
    at = fill_project(app)
    button(at, "Plan mit Claude erstellen").click()
    at.run()

    assert not at.exception
    metrics = {m.label: m.value for m in at.metric}
    assert metrics == {"Planende": "11.11.2026", "Fehler": "0", "Warnungen": "1"}
    assert [w.value for w in at.warning] == [
        "Task 'A' braucht 'SQL', Anna hat diese Fähigkeit nicht angegeben"
    ]
    assert not at.error

    button(at, "Erneut prüfen").click()  # unchanged table: same plan, not marked as edited
    at.run()
    assert not at.exception and not at.error
    assert "angepasst" not in " ".join(c.value for c in at.caption)


def chips(at):
    """The status strip above the steps, as plain text."""
    (strip,) = [h.value for h in at.html if 'class="chips"' in h.value]
    return strip


def test_the_status_strip_says_what_the_planning_still_needs(app, monkeypatch):
    for text in ["✓ Team: 1 Person<", "○ Zustimmung<", "○ Projekt<", "○ Plan offen<"]:
        assert text in chips(app)

    monkeypatch.setattr(agent, "run_planning", planned)
    at = fill_project(app)
    button(at, "Plan mit Claude erstellen").click()
    at.run()

    for text in ["✓ Zustimmung<", "✓ Projekt<", "✓ Plan geprüft, 1 Warnung<"]:
        assert text in chips(at)


def test_the_buttons_at_the_end_of_a_step_open_the_next_step(app):
    assert not button(app, "Weiter zum Projekt").disabled
    button(app, "Weiter zum Projekt").click()
    at = app.run()
    assert not at.exception
    assert at.session_state["step"] == "2 · Projekt"


def test_an_agent_error_is_shown_to_the_project_lead(app, monkeypatch):
    def failing_run(project, team, on_round=None):
        raise PlanningError("Kein Zugang zur Claude API: ANTHROPIC_API_KEY ist nicht gesetzt.")

    monkeypatch.setattr(agent, "run_planning", failing_run)
    at = fill_project(app)
    button(at, "Plan mit Claude erstellen").click()
    at.run()

    assert not at.exception
    assert [e.value for e in at.error] == [
        "Kein Zugang zur Claude API: ANTHROPIC_API_KEY ist nicht gesetzt."
    ]
    assert any("Noch kein Plan" in i.value for i in at.info)


def test_a_deadline_before_the_start_is_explained(app):
    app.text_area(key="idea").input("Idee")
    app.date_input(key="start").set_value(date(2026, 12, 1))
    app.date_input(key="deadline").set_value(date(2026, 11, 1))
    at = app.run()
    assert [e.value for e in at.error] == ["Die Deadline liegt vor dem Startdatum"]


def test_the_server_listens_only_on_this_computer():
    # With the API key loaded, anyone who can reach the port can start paid runs.
    config = tomllib.loads((SITE.parent / ".streamlit" / "config.toml").read_text("utf-8"))
    assert config["server"]["address"] == "localhost"


def planned(project, team, on_round=None):
    return PLAN


def test_every_menu_entry_opens_and_explains_its_empty_state(site):
    assert not site.exception
    assert [t.value for t in site.title] == ["Der Agent schlägt vor. *Du entscheidest.*"]
    assert any("PM-AGENT" in h.value for h in site.html)  # the top bar of every page
    assert "Noch kein Projekt übernommen." in [i.value for i in site.info]

    expected = {
        PLANUNG: ("Planung", "Für die Planung fehlt noch"),
        "pages/durchfuehrung.py": ("Durchführung", "Noch kein Projekt übernommen."),
        "pages/kontrolle.py": ("Kontrolle", "Noch kein Projekt übernommen."),
        "pages/ki_lab.py": ("KI-Lab", "Das KI-Lab läuft noch nicht."),
    }
    for path, (header, info) in expected.items():
        at = site.switch_page(path).run()
        assert not at.exception, path
        assert at.header[0].value == header
        assert any(info in i.value for i in at.info), path

    at = site.switch_page("pages/kontrolle.py").run()
    captions = [c.value for c in at.caption]
    assert "Noch keine protokollierten Läufe." in captions
    assert "Noch kein Plan exportiert." in captions
    for path, header in [("pages/ueber_uns.py", "Über uns"), ("pages/impressum.py", "Impressum")]:
        at = site.switch_page(path).run()
        assert not at.exception, path
        assert at.header[0].value == header
    assert "Angaben fehlen noch" in at.warning[0].value


def test_the_buttons_on_the_startseite_open_the_pages_they_name(site):
    button(site, "Projekt planen").click()
    at = site.run()
    assert not at.exception
    assert at.header[0].value == "Planung"


def test_startseite_and_ueber_uns_describe_all_three_agents(site):
    # Durchführung and Kontrolle have an agent too: no page may still call them "ohne LLM".
    start = " ".join(m.value for m in site.markdown)
    about = " ".join(m.value for m in site.switch_page("pages/ueber_uns.py").run().markdown)
    assert "ohne LLM" not in start and "ohne LLM" not in about
    assert "Aufwand der Agenten" in start and "Planungsagenten" not in start


def test_project_and_team_survive_a_visit_to_another_page(site):
    at = fill_project(site.switch_page(PLANUNG).run())
    # What the team editor returned after the project lead added Ben.
    edited = pd.DataFrame(
        workbench.team_rows(TEAM)
        + [{"Name": "Ben", "Skills": "SQL 3", "Stunden/Woche": 10, "Notiz": ""}],
        columns=workbench.TEAM_COLUMNS,
    )
    at.session_state["team_current"] = edited

    at = at.switch_page("pages/kontrolle.py").run()
    at = at.switch_page(PLANUNG).run()

    assert not at.exception
    assert at.text_area(key="idea").value == PROJECT.idea
    assert at.date_input(key="deadline").value == PROJECT.deadline
    assert at.checkbox(key="consent").value is True
    assert list(at.session_state["team_df"]["Name"]) == ["Anna", "Ben"]
    assert not button(at, "Plan mit Claude erstellen").disabled


def test_an_adopted_plan_is_tracked_in_durchfuehrung_and_kontrolle(site, monkeypatch):
    monkeypatch.setattr(agent, "run_planning", planned)
    at = fill_project(site.switch_page(PLANUNG).run())
    button(at, "Plan mit Claude erstellen").click()
    at.run()
    button(at, "Plan als Projekt übernehmen").click()
    at.run()

    assert not at.exception
    assert tracking.load().plan == PLAN
    assert "Übernommen. Weiter auf den Seiten Durchführung und Kontrolle." in [
        s.value for s in at.success
    ]

    at = at.switch_page("pages/durchfuehrung.py").run()
    assert not at.exception and not at.info
    assert any("# Statusbericht" in m.value for m in at.markdown)
    button(at, "Fortschritt speichern").click()
    at.run()
    assert not at.exception and not at.error
    assert any("Fortschritt gespeichert" in s.value for s in at.success)

    at = at.switch_page("pages/kontrolle.py").run()
    assert not at.exception
    metrics = {m.label: m.value for m in at.metric}
    assert (metrics["Fortschritt"], metrics["Planstunden"]) == ("0 %", "24 h")
    assert any("Noch kein Fortschritt erfasst" in i.value for i in at.info)


def test_a_plan_with_errors_cannot_be_adopted(app, monkeypatch):
    broken = Plan.model_validate(plan_input(member="Zoe"))
    monkeypatch.setattr(agent, "run_planning", lambda project, team, on_round=None: broken)
    at = fill_project(app)
    button(at, "Plan mit Claude erstellen").click()
    at.run()

    assert button(at, "Plan als Projekt übernehmen").disabled
    assert tracking.load() is None


@pytest.fixture
def tracked(site):
    """The site with an adopted project (in the temporary folder of `local`)."""
    tracking.adopt(PROJECT, TEAM, PLAN)
    return site


def test_without_a_project_durchfuehrung_and_kontrolle_lead_to_the_planung(site):
    for path in ["pages/durchfuehrung.py", "pages/kontrolle.py"]:
        at = site.switch_page(path).run()
        assert not button(at, "Zur Planung").disabled, path


def test_durchfuehrung_says_where_the_project_stands(tracked):
    # Only what does not depend on today's date: nothing is finished or started yet.
    at = tracked.switch_page("pages/durchfuehrung.py").run()
    assert not at.exception
    for text in ["○ 0 von 2 Aufgaben fertig<", "○ 0 in Arbeit<"]:
        assert text in chips(at)


def test_the_execution_agent_needs_consent_and_its_proposal_goes_into_the_report(
    tracked, monkeypatch
):
    summary = StatusSummary(
        summary="Beide Aufgaben sind im Verzug.",
        next_steps=[{"task_id": "A", "action": "Anna klärt das Schema bis Montag."}],
    )

    def proposing(adopted, today, on_round=None):
        assert adopted.plan == PLAN
        accepted = {"tool": "submit_status", "is_error": False, "content": "angenommen."}
        on_round({"tool_results": [accepted]})
        return summary

    monkeypatch.setattr(followup, "run_status_summary", proposing)
    at = tracked.switch_page("pages/durchfuehrung.py").run()
    start = "Zusammenfassung mit Claude vorschlagen"
    assert button(at, start).disabled
    assert any("Noch nicht erstellt. Der Durchführungs-Agent" in m.value for m in at.markdown)

    at.checkbox(key="consent_durchfuehrung").check()
    at.run()
    button(at, start).click()
    at.run()

    assert not at.exception and not at.error
    texts = [m.value for m in at.markdown]
    assert "Beide Aufgaben sind im Verzug." in texts
    assert "- **A:** Anna klärt das Schema bis Montag." in texts
    assert any("*Vorschlag des Durchführungs-Agenten (Claude)" in t for t in texts)


def test_the_control_agent_shows_assessment_findings_and_measures(tracked, monkeypatch):
    report = ControlReport(
        assessment="gefährdet",
        findings=[{"task_ids": ["B"], "observation": "B hat noch nicht begonnen."}],
        measures=[{"task_ids": ["B"], "action": "Anna beginnt B.", "effect": "Verzug sinkt."}],
    )
    monkeypatch.setattr(followup, "run_control_report", lambda *args, **kwargs: report)
    at = tracked.switch_page("pages/kontrolle.py").run()
    assert button(at, "Stand mit Claude bewerten").disabled

    at.checkbox(key="consent_kontrolle").check()
    at.run()
    button(at, "Stand mit Claude bewerten").click()
    at.run()

    assert not at.exception and not at.error
    assert {m.label: m.value for m in at.metric}["Bewertung"] == "gefährdet"
    assert "- **B:** B hat noch nicht begonnen." in [m.value for m in at.markdown]
    (measures,) = [d.value for d in at.dataframe if "Maßnahme" in d.value.columns]
    assert measures.to_dict("records") == [
        {"Aufgaben": "B", "Maßnahme": "Anna beginnt B.", "Erwartete Wirkung": "Verzug sinkt."}
    ]


def test_a_failing_agent_shows_the_reason_and_no_result(tracked, monkeypatch):
    def failing(adopted, today, on_round=None):
        raise AgentError("Kein Zugang zur Claude API: ANTHROPIC_API_KEY ist nicht gesetzt.")

    monkeypatch.setattr(followup, "run_control_report", failing)
    at = tracked.switch_page("pages/kontrolle.py").run()
    at.checkbox(key="consent_kontrolle").check()
    at.run()
    button(at, "Stand mit Claude bewerten").click()
    at.run()

    assert not at.exception
    assert [e.value for e in at.error] == [
        "Kein Zugang zur Claude API: ANTHROPIC_API_KEY ist nicht gesetzt."
    ]
    assert "Bewertung" not in {m.label for m in at.metric}
