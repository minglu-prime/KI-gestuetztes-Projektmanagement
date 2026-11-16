"""The Streamlit site headless, with the agent replaced: no network, no files in data/ or logs/."""

import datetime
import json
import re
import socket
import tomllib
from datetime import date
from pathlib import Path
from unittest.mock import Mock

import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest
from test_tools import PROJECT, TEAM, plan_input

from pm_agent import agent, followup, lab_server, lifecycle, tracking, ui, workbench
from pm_agent.agent import AgentError, PlanningError
from pm_agent.models import (
    Absence,
    Charter,
    ControlReport,
    Criterion,
    Plan,
    Requirement,
    Requirements,
    StatusSummary,
)

SITE = Path(__file__).parents[1] / "app.py"
PAGES = "views"
PLANUNG = f"{PAGES}/planung.py"
PLAN = Plan.model_validate(plan_input())


@pytest.fixture
def local(monkeypatch, tmp_path):
    """Nothing is read from or written to the real data/ and logs/, and no lab is running."""
    monkeypatch.setattr(workbench, "load_team", lambda: list(TEAM))
    monkeypatch.setattr(workbench, "saved_runs", lambda: [])
    monkeypatch.setattr(workbench, "RUNS_CSV", tmp_path / "runs.csv")
    monkeypatch.setattr(tracking, "PROJECT_FILE", tmp_path / "projekt.json")
    monkeypatch.setattr(tracking, "LOG_DIR", tmp_path)
    monkeypatch.setattr(lifecycle, "FILE", tmp_path / "vorhaben.json")
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


def test_a_link_to_a_page_as_first_visit_goes_through_the_menu(local):
    # While a folder named pages/ sits next to app.py, a fresh Streamlit server works in its
    # old multipage mode until app.py has run once: a link to /kontrolle as the first request
    # ran that page alone, without menu, style and the state the pages share.
    at = AppTest.from_file(str(SITE), default_timeout=30)
    at.switch_page(f"{PAGES}/kontrolle.py").run()
    assert not at.exception
    assert "page" in at.session_state and at.session_state["page"] == "kontrolle"


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
    strip = next(h.value for h in at.html if 'class="chips"' in h.value)  # first of the page
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


def now(at):
    """The line "Jetzt dran" of the Planung."""
    return next(m.value for m in at.markdown if "Jetzt dran" in m.value)


def test_the_planung_says_what_is_next_and_opens_that_step(app, monkeypatch):
    # The team is there, the consent is not.
    assert "Zustimmung" in now(app) and "Schritt 1" in now(app)
    app.checkbox(key="consent").check()
    at = app.run()
    assert "Projektidee und Deadline" in now(at) and "Schritt 2" in now(at)
    button(at, "Zu Schritt 2").click()
    at = at.run()
    assert at.session_state["step"] == "2 · Projekt"

    at = fill_project(at)
    assert "Schritt 3" in now(at)
    monkeypatch.setattr(agent, "run_planning", planned)
    button(at, "Plan mit Claude erstellen").click()
    at = at.run()
    assert "übernimm" in now(at) and "Schritt 6" in now(at)


WISH = "Das Datenmodell dauert doppelt so lange."


@pytest.fixture
def with_plan(app, monkeypatch):
    """The Planung page with a plan from the agent, and an agent that doubles task A on request."""
    monkeypatch.setattr(agent, "run_planning", planned)
    at = fill_project(app)
    button(at, "Plan mit Claude erstellen").click()
    at.run()

    def replanned(project, team, plan, wish, on_round=None):
        assert (project, team, plan, wish) == (PROJECT, TEAM, PLAN, WISH)
        accepted = {"tool": "submit_plan", "is_error": False, "content": "Plan angenommen."}
        on_round(
            {
                "text": "Ich verdopple die Schätzung.",
                "tool_calls": [{"name": "submit_plan", "input": plan_input(hours=16)}],
                "tool_results": [accepted],
            }
        )
        return Plan.model_validate(plan_input(hours=16))

    monkeypatch.setattr(agent, "run_replanning", replanned)
    return at


def test_a_task_is_explained_in_the_result(with_plan):
    # Opens on the first task: Anna does A although she has not named SQL.
    texts = [m.value for m in with_plan.markdown]
    assert "**Warum Anna?**" in texts and "kennt die Raumdaten" in texts
    assert "- SQL: bei Anna nicht angegeben" in texts
    assert "- B · API" in texts  # B waits for it
    (details,) = [h.value for h in with_plan.html if "Kein Puffer" in h.value]
    assert "8 h" in details and "09.11. – 09.11.2026" in details
    # Anna is the only person in the team: nobody else could take it.
    assert any("Niemand sonst im Team" in c.value for c in with_plan.caption)

    at = with_plan.selectbox[0].select("B").run()
    assert not at.exception
    assert "- A · Datenmodell" in [m.value for m in at.markdown]


def test_a_wish_left_over_from_another_plan_is_not_asked_for_a_reopened_run(
    with_plan, monkeypatch, tmp_path
):
    # A wish is waiting, then the project lead opens a logged run instead.
    log = tmp_path / "run-20261109-120000.json"
    record = {
        "project": PROJECT.model_dump(mode="json"),
        "team": [m.model_dump(mode="json") for m in TEAM],
        "plan": PLAN.model_dump(mode="json"),
        "rounds": [],
    }
    log.write_text(json.dumps(record), encoding="utf-8")
    monkeypatch.setattr(workbench, "saved_runs", lambda: [log])
    at = with_plan.run()
    at.session_state["asked"] = WISH
    button(at, "Lauf öffnen").click()
    at.run()

    assert not at.exception
    assert at.session_state["source"] == f"Protokoll {log.name}"
    assert "asked" not in at.session_state
    assert at.session_state["proposal"] is None  # Claude was not asked


def test_a_change_asked_from_claude_is_shown_as_differences_before_it_counts(with_plan):
    at = with_plan.chat_input(key="wish").set_value(WISH).run()

    assert not at.exception and not at.error
    texts = " ".join(m.value for m in at.markdown)
    assert "A · Datenmodell: 8 h → 16 h" in texts
    assert "Planende: 11.11.2026 → 12.11.2026 (1 Arbeitstag später)" in texts
    # The round is shown while Claude works: its words and what it changed in the plan.
    assert "Claude: Ich verdopple die Schätzung." in [c.value for c in at.caption]
    assert {m.label: m.value for m in at.metric}["Planende"] == "11.11.2026"  # not taken yet
    assert at.chat_input(key="wish").disabled  # decide on the open proposal first

    button(at, "Übernehmen").click()
    at.run()
    assert not at.exception
    assert {m.label: m.value for m in at.metric}["Planende"] == "12.11.2026"
    (turn,) = at.session_state["chat"]
    assert turn["accepted"] is True and turn["wish"] == WISH
    assert not at.chat_input(key="wish").disabled  # ready for the next wish


def test_a_suggested_wish_is_asked_with_one_click(with_plan, monkeypatch):
    asked = []

    def replanned(project, team, plan, wish, on_round=None):
        asked.append(wish)
        return Plan.model_validate(plan_input(hours=16))

    monkeypatch.setattr(agent, "run_replanning", replanned)
    suggestion = "Was, wenn B (API) doppelt so lange dauert?"
    button(with_plan, suggestion).click()
    at = with_plan.run()

    assert not at.exception and not at.error
    assert asked == [suggestion]
    assert at.session_state["proposal"]["wish"] == suggestion
    assert suggestion not in [b.label for b in at.button]  # decide on the proposal first


def test_claude_is_not_asked_while_the_table_holds_edits_that_were_not_checked(with_plan):
    # The table as after the project lead changed the hours of A by hand, without "Erneut
    # prüfen": the current plan still says 8 h. (AppTest cannot type into the editor.)
    rows = workbench.plan_rows(PLAN)
    rows[0]["Stunden"] = 40
    with_plan.session_state["plan_df"] = pd.DataFrame(rows, columns=workbench.PLAN_COLUMNS)
    with_plan.session_state["asked"] = WISH  # a wish typed in the same moment
    at = with_plan.run()

    assert not at.exception
    assert at.chat_input(key="wish").disabled
    assert any("noch nicht geprüft" in w.value for w in at.warning)
    # Claude was not called: it would have got the plan without the edit, and taking its
    # proposal would have overwritten the table.
    assert at.session_state["proposal"] is None
    assert at.session_state["plan"] == PLAN
    assert "Tabelle zurücksetzen" in [b.label for b in at.button]


def test_a_proposal_cannot_be_taken_over_edits_that_were_not_checked(with_plan):
    at = with_plan.chat_input(key="wish").set_value(WISH).run()
    assert not button(at, "Übernehmen").disabled
    # While the proposal is open, the project lead changes the hours of B in the table.
    rows = workbench.plan_rows(PLAN)
    rows[1]["Stunden"] = 80
    at.session_state["plan_df"] = pd.DataFrame(rows, columns=workbench.PLAN_COLUMNS)
    at = at.run()

    assert not at.exception
    # Taking the proposal would replace the table and lose the 80 h without a word.
    assert button(at, "Übernehmen").disabled
    assert any("noch nicht geprüft" in w.value for w in at.warning)


def test_a_table_nobody_touched_never_counts_as_edited(app, monkeypatch):
    # Claude lists the assignments in another order than the tasks; the table sorts them.
    data = plan_input()
    data["assignments"].reverse()
    shuffled = Plan.model_validate(data)
    monkeypatch.setattr(agent, "run_planning", lambda project, team, on_round=None: shuffled)
    at = fill_project(app)
    button(at, "Plan mit Claude erstellen").click()
    at.run()
    at = at.run()  # the table has been drawn once

    assert not at.exception
    assert not at.chat_input(key="wish").disabled
    assert not any("noch nicht geprüft" in w.value for w in at.warning)
    button(at, "Erneut prüfen").click()
    at.run()
    assert at.session_state["plan"] == PLAN  # as the table writes it
    assert at.session_state["hand_edited"] is False  # runs.csv: nobody changed the plan


def test_checking_an_untouched_table_keeps_an_open_proposal(app, monkeypatch):
    # The plan's assignments are in another order than its tasks, so "Erneut prüfen" writes
    # the plan anew in the form of the table. Nobody changed it: the proposal still fits.
    data = plan_input()
    data["assignments"].reverse()
    shuffled = Plan.model_validate(data)
    doubled = Plan.model_validate(plan_input(hours=16))
    monkeypatch.setattr(agent, "run_planning", lambda project, team, on_round=None: shuffled)
    monkeypatch.setattr(
        agent, "run_replanning", lambda project, team, plan, wish, on_round=None: doubled
    )
    at = fill_project(app)
    button(at, "Plan mit Claude erstellen").click()
    at.run()
    at = at.chat_input(key="wish").set_value(WISH).run()
    assert at.session_state["proposal"] is not None
    button(at, "Erneut prüfen").click()
    at = at.run()

    assert not at.exception
    assert at.session_state["proposal"] is not None
    assert not button(at, "Übernehmen").disabled


def test_an_export_writes_one_line_into_the_record(with_plan):
    # runs.csv is the data of the before/after comparison. The page writes it from the
    # callback of the download buttons; `local` points the file into the temporary folder.
    record = workbench.RUNS_CSV
    assert not record.exists()
    next(b for b in with_plan.download_button if b.label == "Als CSV herunterladen").click()
    at = with_plan.run()

    assert not at.exception
    (line,) = pd.read_csv(record).to_dict("records")
    assert (line["quelle"], line["format"], line["tasks"]) == ("Agent", "csv", 2)
    assert (line["runden"], line["angepasst"], line["fehler"]) == (0, False, 0)


def test_an_export_that_cannot_be_recorded_says_so(with_plan):
    # Something sits where the record should be and cannot be written to: here a folder.
    workbench.RUNS_CSV.mkdir()
    next(b for b in with_plan.download_button if b.label == "Als CSV herunterladen").click()
    at = with_plan.run()

    assert not at.exception  # the page is still there
    # (In the test the record lies in a temporary folder, not in logs/.)
    assert any("heruntergeladen, aber nicht in" in e.value for e in at.error)
    assert any("/runs.csv vermerkt: " in e.value for e in at.error)
    assert [b.label for b in at.download_button] == [
        "Als Markdown herunterladen",
        "Als CSV herunterladen",
    ]


def test_taking_a_change_keeps_what_the_export_record_needs(with_plan):
    # As after 3 rounds and 90 s of planning and a hand edit confirmed with "Erneut prüfen".
    with_plan.session_state["agent_seconds"] = 90.0
    with_plan.session_state["round_count"] = 3
    with_plan.session_state["hand_edited"] = True
    shown_at = with_plan.session_state["shown_at"]
    at = with_plan.chat_input(key="wish").set_value(WISH).run()
    button(at, "Übernehmen").click()
    at.run()

    assert not at.exception
    # runs.csv is the data of the before/after comparison: the change by Claude adds to the
    # agent's time and rounds, and does not erase that the lead edited the plan by hand or
    # when the review began.
    assert at.session_state["agent_seconds"] >= 90.0
    assert at.session_state["round_count"] == 4
    assert at.session_state["hand_edited"] is True
    assert at.session_state["shown_at"] == shown_at


def test_a_dropped_proposal_leaves_the_plan_as_it_was(with_plan):
    at = with_plan.chat_input(key="wish").set_value(WISH).run()
    button(at, "Verwerfen").click()
    at.run()

    assert not at.exception
    assert {m.label: m.value for m in at.metric}["Planende"] == "11.11.2026"
    assert at.session_state["plan"] == PLAN
    assert at.session_state["chat"][0]["accepted"] is False
    assert "**Verworfen**" in [m.value for m in at.markdown]


def test_without_consent_claude_is_not_asked_to_change_the_plan(with_plan):
    with_plan.checkbox(key="consent").uncheck()
    at = with_plan.run()
    assert at.chat_input(key="wish").disabled
    assert any("die Zustimmung des Teams (Schritt 1)" in c.value for c in at.caption)


def test_a_failing_change_shows_the_reason_and_no_proposal(with_plan, monkeypatch):
    def failing(project, team, plan, wish, on_round=None):
        raise PlanningError("Claude hat nach 10 Runden noch keinen gültigen Plan.")

    monkeypatch.setattr(agent, "run_replanning", failing)
    at = with_plan.chat_input(key="wish").set_value(WISH).run()

    assert not at.exception
    assert [e.value for e in at.error] == ["Claude hat nach 10 Runden noch keinen gültigen Plan."]
    assert at.session_state["proposal"] is None
    assert "Übernehmen" not in [b.label for b in at.button]


def test_an_absence_in_the_team_table_moves_the_plan(local, monkeypatch):
    monday = Absence(first=date(2026, 11, 9), last=date(2026, 11, 9))
    away = TEAM[0].model_copy(update={"absences": [monday]})
    monkeypatch.setattr(workbench, "load_team", lambda: [away])
    monkeypatch.setattr(agent, "run_planning", lambda project, team, on_round=None: PLAN)
    at = AppTest.from_file(str(SITE.parent / PLANUNG), default_timeout=30).run()
    at = fill_project(at)
    button(at, "Plan mit Claude erstellen").click()
    at.run()

    assert not at.exception
    assert at.session_state["team_df"]["Abwesend"].tolist() == ["09.11.2026"]
    # Without the absence the plan ends on 11.11.: the work starts a day later.
    assert {m.label: m.value for m in at.metric}["Planende"] == "12.11.2026"


def test_free_days_of_the_project_move_the_plan(app, monkeypatch):
    monkeypatch.setattr(agent, "run_planning", lambda project, team, on_round=None: PLAN)
    at = fill_project(app)
    at.text_input(key="free_days").input("09.11.2026").run()
    button(at, "Plan mit Claude erstellen").click()
    at.run()

    assert not at.exception
    # Without the free Monday the plan ends on 11.11.
    assert {m.label: m.value for m in at.metric}["Planende"] == "12.11.2026"

    # Not readable: the project is not complete, and the page says what is wrong.
    at.text_input(key="free_days").input("Weihnachten").run()
    assert not at.exception
    assert any("'Weihnachten' nicht lesbar" in e.value for e in at.error)
    assert button(at, "Plan mit Claude erstellen").disabled
    # Step 3 says what is in the way, not that idea and deadline were missing.
    assert any("lesbare freie Tage (Schritt 2)" in i.value for i in at.info)


def test_a_team_or_project_that_cannot_be_saved_is_said_not_thrown(with_plan, monkeypatch):
    def locked(*args, **kwargs):
        raise PermissionError(13, "Zugriff verweigert")

    monkeypatch.setattr(workbench, "save_team", locked)
    monkeypatch.setattr(tracking, "adopt", locked)
    button(with_plan, "Team lokal speichern").click()
    at = with_plan.run()
    assert not at.exception
    assert any("team.json konnte nicht gespeichert werden" in e.value for e in at.error)
    button(at, "Plan als Projekt übernehmen").click()
    at = at.run()
    assert not at.exception
    assert any("projekt.json konnte nicht gespeichert werden" in e.value for e in at.error)
    assert not any("Übernommen" in s.value for s in at.success)


def test_an_agent_error_is_shown_to_the_project_lead(app, monkeypatch):
    def failing_run(project, team, on_round=None):
        raise PlanningError("Kein Zugang zur Claude API: ANTHROPIC_API_KEY ist nicht gesetzt.")

    monkeypatch.setattr(agent, "run_planning", failing_run)
    at = fill_project(app)
    button(at, "Plan mit Claude erstellen").click()
    at.run()

    assert not at.exception
    assert [e.value for e in at.error] == [
        # Shown as written: the underscores would set "API" in italics.
        ui.as_text("Kein Zugang zur Claude API: ANTHROPIC_API_KEY ist nicht gesetzt.")
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


def test_the_site_says_that_it_is_german(site):
    # Streamlit serves its page as English. A browser then offers to translate the German
    # texts, and a screen reader reads them with English sounds.
    assert any('document.documentElement.lang = "de"' in h.value for h in site.html)


def test_the_startseite_introduces_the_roles_the_agent_pages_mark(site):
    flow = next(h.value for h in site.html if 'class="flow"' in h.value)
    # The same chips as on the agent pages, in the order of the work.
    marks = ['class="role claude"', 'class="role python"', 'class="role du"']
    assert all(m in flow for m in marks)
    assert flow.index(marks[0]) < flow.index(marks[1]) < flow.index(marks[2])


def test_every_menu_entry_opens_and_explains_its_empty_state(site):
    assert not site.exception
    assert [t.value for t in site.title] == ["Der Agent schlägt vor. *Du entscheidest.*"]
    assert any("PM-AGENT" in h.value for h in site.html)  # the top bar of every page
    assert "Noch kein Projekt übernommen." in [i.value for i in site.info]

    expected = {
        PLANUNG: ("Planung", "Für die Planung fehlt noch"),
        "views/durchfuehrung.py": ("Durchführung", "Noch kein Projekt übernommen."),
        "views/kontrolle.py": ("Kontrolle", "Noch kein Projekt übernommen."),
        "views/ki_lab.py": ("KI-Lab", "Das KI-Lab läuft noch nicht."),
        "views/auftrag.py": ("Projektauftrag", "Noch kein Projektauftrag."),
        "views/anforderungen.py": ("Anforderungen", "Noch keine Anforderungen."),
    }
    for path, (header, info) in expected.items():
        at = site.switch_page(path).run()
        assert not at.exception, path
        assert at.header[0].value == header
        assert any(info in i.value for i in at.info), path

    at = site.switch_page("views/kontrolle.py").run()
    captions = [c.value for c in at.caption]
    assert "Noch keine protokollierten Läufe." in captions
    assert "Noch kein Plan exportiert." in captions
    for path, header in [("views/ueber_uns.py", "Über uns"), ("views/impressum.py", "Impressum")]:
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
    about = " ".join(m.value for m in site.switch_page("views/ueber_uns.py").run().markdown)
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

    at = at.switch_page("views/kontrolle.py").run()
    at = at.switch_page(PLANUNG).run()

    assert not at.exception
    assert at.text_area(key="idea").value == PROJECT.idea
    assert at.date_input(key="deadline").value == PROJECT.deadline
    assert at.checkbox(key="consent").value is True
    assert list(at.session_state["team_df"]["Name"]) == ["Anna", "Ben"]
    assert not button(at, "Plan mit Claude erstellen").disabled


@pytest.fixture
def flow_site(site, monkeypatch):
    """Fix business evaluations, not the wall clock; keep real pages, storage and calculations."""
    evaluate = tracking.evaluate
    download_button = st.download_button
    downloads = {}

    def on_test_day(project, today):
        return evaluate(project, date(2026, 11, 12))

    def unexpected_provider(*args, **kwargs):
        pytest.fail("The business-flow regression must not call an AI provider")

    def capture_download(label, data, **kwargs):
        downloads[label] = data
        return download_button(label, data, **kwargs)

    # AppTest executes each page's imports after this patch. date.today() itself,
    # adoption timestamps and download filenames are deliberately not frozen.
    monkeypatch.setattr(tracking, "evaluate", on_test_day)
    monkeypatch.setattr(agent, "Anthropic", unexpected_provider)
    monkeypatch.setattr(agent, "run_planning", planned)
    monkeypatch.setattr(followup, "run_status_summary", unexpected_provider)
    monkeypatch.setattr(followup, "run_control_report", unexpected_provider)
    monkeypatch.setattr(st, "download_button", capture_download)
    return site, downloads


def adopt_from_planning(at):
    at = fill_project(at.switch_page(PLANUNG).run())
    button(at, "Plan mit Claude erstellen").click()
    at.run()
    button(at, "Plan als Projekt übernehmen").click()
    at.run()
    assert not at.exception
    assert tracking.load().plan == PLAN
    return at


def edit_progress(at, edits):
    return edit_table(at, "progress_editor_", edits)


def edit_table(at, prefix, edits, deleted=()):
    # AppTest has no canvas cell editor. Submit its documented edit-state payload;
    # st.data_editor still applies the edits and the page's real save handler runs.
    (editor,) = [frame for frame in at.dataframe if frame.key and frame.key.startswith(prefix)]
    at.session_state[editor.key] = {
        "edited_rows": edits,
        "added_rows": [],
        "deleted_rows": list(deleted),
    }
    return at.run()


def progress_editor(at):
    (frame,) = [f for f in at.dataframe if f.key and f.key.startswith("progress_editor_")]
    return frame.value


def test_unsaved_progress_survives_a_visit_to_another_page(flow_site):
    at, _ = flow_site
    at = adopt_from_planning(at)
    at = at.switch_page("views/durchfuehrung.py").run()
    at = edit_progress(at, {0: {"Status": "in Arbeit", "Ist (h)": 3, "Notiz": "läuft"}})
    before = tracking.PROJECT_FILE.read_bytes()

    at = at.switch_page("views/kontrolle.py").run()
    at = at.switch_page("views/durchfuehrung.py").run()

    assert not at.exception
    row = progress_editor(at).iloc[0]
    assert (row["Status"], row["Ist (h)"], row["Notiz"]) == ("in Arbeit", 3, "läuft")
    assert tracking.PROJECT_FILE.read_bytes() == before  # still not saved
    # A further edit after the return keeps the restored ones.
    # (AppTest shows the editor's input data, not its edits: the save shows both.)
    at = edit_progress(at, {1: {"Notiz": "wartet"}})
    button(at, "Fortschritt speichern").click()
    at.run()
    stored = tracking.load().progress
    assert (stored["A"].status, stored["A"].actual_hours, stored["B"].note) == (
        "in Arbeit",
        3,
        "wartet",
    )


def test_unsaved_progress_is_dropped_when_the_project_changed_meanwhile(flow_site):
    at, _ = flow_site
    at = adopt_from_planning(at)
    at = at.switch_page("views/durchfuehrung.py").run()
    at = edit_progress(at, {0: {"Notiz": "alt"}})
    at = at.switch_page("views/kontrolle.py").run()
    tracking.save(tracking.apply_rows(tracking.load(), [{"ID": "A", "Notiz": "neu"}]))

    at = at.switch_page("views/durchfuehrung.py").run()

    assert not at.exception
    assert progress_editor(at).iloc[0]["Notiz"] == "neu"


@pytest.mark.parametrize("host_day", [date(2000, 1, 1), date(2099, 12, 31)])
def test_flow_pages_use_fixed_evaluation_date_despite_host_today(flow_site, monkeypatch, host_day):
    at, downloads = flow_site
    baseline = tracking.adopt(PROJECT, TEAM, PLAN)
    saved = tracking.apply_rows(
        baseline,
        [
            {"ID": "A", "Status": "fertig", "Ist (h)": 10},
            {"ID": "B", "Status": "in Arbeit", "Ist (h)": 4},
        ],
    )
    tracking.save(saved)

    class HostDate(date):
        @classmethod
        def today(cls):
            return cls(host_day.year, host_day.month, host_day.day)

    monkeypatch.setattr(datetime, "date", HostDate)
    evaluate = Mock(wraps=tracking.evaluate)  # observe, but delegate to the existing date fixture
    monkeypatch.setattr(tracking, "evaluate", evaluate)
    for page in ("views/durchfuehrung.py", "views/kontrolle.py"):
        evaluate.reset_mock()
        at.switch_page(page).run()
        assert not at.exception
        # Each page's first evaluation receives its own date.today(), before
        # document/table helpers run. This exercises the page's imported alias.
        assert evaluate.call_args_list[0].args == (saved, host_day)
        if page == "views/durchfuehrung.py":
            assert "! 1 im Verzug<" in chips(at)
            report = downloads["Statusbericht als Markdown herunterladen"]
            assert "**Stand:** 12.11.2026" in report
        else:
            assert [w.value for w in at.warning] == [
                "Im Verzug:\n\n- B · API (Anna), geplant bis 11.11.2026, Status: in Arbeit"
            ]


def test_nonzero_progress_survives_reopen_and_reaches_control_and_documents(flow_site):
    at, downloads = flow_site
    at = adopt_from_planning(at)
    baseline = tracking.load()
    before_save = tracking.PROJECT_FILE.read_bytes()

    at = at.switch_page("views/durchfuehrung.py").run()
    at = edit_progress(
        at,
        {
            0: {"Status": "fertig", "Ist (h)": 10, "Notiz": "Schema erneut geprüft"},
            1: {"Status": "in Arbeit", "Ist (h)": 4, "Notiz": "Integration läuft"},
        },
    )
    assert not at.exception and not at.error
    assert tracking.PROJECT_FILE.read_bytes() == before_save  # edits are not autosaved
    assert "- Ist-Stunden bisher: 0 h" in downloads["Statusbericht als Markdown herunterladen"]

    button(at, "Fortschritt speichern").click()
    at.run()
    assert not at.exception and not at.error
    assert any("Fortschritt gespeichert" in s.value for s in at.success)

    after_save = tracking.PROJECT_FILE.read_bytes()
    stored = json.loads(after_save)
    assert stored["progress"] == {
        "A": {
            "status": "fertig",
            "actual_hours": 10,
            "remaining_hours": None,
            "note": "Schema erneut geprüft",
        },
        "B": {
            "status": "in Arbeit",
            "actual_hours": 4,
            "remaining_hours": None,
            "note": "Integration läuft",
        },
    }
    restored = tracking.load()
    assert (restored.project, restored.team, restored.plan) == (PROJECT, TEAM, PLAN)
    assert restored.adopted == baseline.adopted
    evaluation = tracking.evaluate(restored, date(2026, 11, 12))
    assert evaluation.today == date(2026, 11, 12)
    assert (evaluation.planned_hours, evaluation.actual_hours) == (24, 14)
    assert evaluation.progress == pytest.approx(8 / 24)
    # B's unfinished 16 h task has used 4 h: its remaining 12 h are not a saving.
    assert evaluation.finished_deviation == 2
    assert [task.id for task in evaluation.overdue] == ["B"]

    # A new AppTest has no cached page state: the page must restore the saved file.
    at = AppTest.from_file(str(SITE), default_timeout=30).run()
    at = at.switch_page("views/durchfuehrung.py").run()
    assert not at.exception
    (editor,) = [
        frame.value
        for frame in at.dataframe
        if frame.key and frame.key.startswith("progress_editor_")
    ]
    assert editor[["ID", "Status", "Ist (h)", "Notiz"]].to_dict("records") == [
        {"ID": "A", "Status": "fertig", "Ist (h)": 10, "Notiz": "Schema erneut geprüft"},
        {"ID": "B", "Status": "in Arbeit", "Ist (h)": 4, "Notiz": "Integration läuft"},
    ]
    report = downloads["Statusbericht als Markdown herunterladen"]
    assert report.strip() in [m.value for m in at.markdown]  # preview strips outer whitespace
    for text in [
        "**Stand:** 12.11.2026",
        "- Fortschritt: 33 %",
        "- Planstunden gesamt: 24 h",
        "- Ist-Stunden bisher: 14 h",
        "- Abweichung der fertigen Aufgaben: +2 h",
        "| A | Datenmodell | Anna | fertig | 8 | 10 | Schema erneut geprüft |",
        "| B | API | Anna | in Arbeit | 16 | 4 | Integration läuft |",
    ]:
        assert text in report

    next(r for r in at.radio if r.label == "Vorlage").set_value("Arbeitspaketbeschreibungen").run()
    packages = downloads["Arbeitspaketbeschreibungen als Markdown herunterladen"]
    assert packages.strip() in [m.value for m in at.markdown]
    for text in [
        "**Projekt:** Raumbuchung für Lerngruppen",
        "## A · Datenmodell",
        "## B · API",
        "| Verantwortlich | Anna |",
        "| Aufwand | 8 h |",
        "| Aufwand | 16 h |",
        "| Zeitraum | 10.11.2026 bis 11.11.2026 |",
        "| Abhängig von | A |",
        "**Begründung der Zuweisung:** kennt die Raumdaten",
    ]:
        assert text in packages

    button(at, "Weiter zur Kontrolle").click()
    at.run()
    assert not at.exception and at.header[0].value == "Kontrolle"
    metrics = {m.label: m.value for m in at.metric}
    # The metrics of the fixed evaluation day. The forecast tiles count from the real today
    # and are left out here.
    fixed = {
        "Fortschritt": "33 %",
        "Planstunden": "24 h",
        "Ist-Stunden bisher": "14 h",
        "Abweichung fertiger Aufgaben": "+2 h",
        # Earned value on 12.11.: the whole plan should be done, A (8 h) is.
        "Planwert bis heute": "24 h",
        "Fertigstellungswert": "8 h",
        "Ist-Stunden": "14 h",
        "Termin-Kennzahl (SPI)": "0,33",
        "Aufwands-Kennzahl (CPI)": "0,57",
    }
    assert {label: metrics.get(label) for label in fixed} == fixed
    (tasks,) = [d.value for d in at.dataframe if "Geplantes Ende" in d.value.columns]
    assert tasks[["ID", "Status", "Plan (h)", "Ist (h)"]].to_dict("records") == [
        {"ID": "A", "Status": "fertig", "Plan (h)": 8, "Ist (h)": 10},
        {"ID": "B", "Status": "in Arbeit", "Plan (h)": 16, "Ist (h)": 4},
    ]
    (members,) = [d.value for d in at.dataframe if "Fertig (Plan-h)" in d.value.columns]
    assert members.to_dict("records") == [
        {"Person": "Anna", "Plan (h)": 24, "Ist (h)": 14, "Fertig (Plan-h)": 8, "Erledigt": 0.33}
    ]
    assert [w.value for w in at.warning] == [
        "Im Verzug:\n\n- B · API (Anna), geplant bis 11.11.2026, Status: in Arbeit"
    ]

    # Target subsequent AppTest reruns at the page reached by the in-app button.
    at.switch_page("views/kontrolle.py")
    next(n for n in at.number_input if n.label == "Stundensatz (€)").set_value(50).run()
    assert not at.exception
    metrics = {m.label: m.value for m in at.metric}
    assert (metrics["Plankosten gesamt"], metrics["Ist-Kosten bisher"]) == (
        "1.200,00 €",
        "700,00 €",
    )
    assert tracking.PROJECT_FILE.read_bytes() == after_save


@pytest.mark.parametrize("actual_hours", [0, 4])
@pytest.mark.parametrize("rate", [None, 0, 50])
def test_control_costs_for_zero_and_nonzero_hours_and_rates(flow_site, actual_hours, rate):
    at, _ = flow_site
    baseline = tracking.adopt(PROJECT, TEAM, PLAN)
    tracking.save(
        tracking.apply_rows(baseline, [{"ID": "A", "Status": "in Arbeit", "Ist (h)": actual_hours}])
    )
    at = at.switch_page("views/kontrolle.py").run()
    if rate is not None:
        next(n for n in at.number_input if n.label == "Stundensatz (€)").set_value(rate).run()
    assert not at.exception
    metrics = {m.label: m.value for m in at.metric}
    assert (metrics["Fortschritt"], metrics["Abweichung fertiger Aufgaben"]) == ("0 %", "+0 h")
    costs = {key: value for key, value in metrics.items() if "kosten" in key.lower()}
    if rate is None:
        assert costs == {}
        assert "Ohne Stundensatz werden keine Kosten berechnet." in [c.value for c in at.caption]
    else:
        assert costs == {
            "Plankosten gesamt": tracking.euro(24 * rate),  # the German way: 1.200,00 €
            "Ist-Kosten bisher": tracking.euro(actual_hours * rate),
        }


def test_an_adopted_project_with_progress_requires_explicit_overwrite(flow_site, monkeypatch):
    at, _ = flow_site
    at = adopt_from_planning(at)
    at = at.switch_page("views/durchfuehrung.py").run()
    at = edit_progress(at, {0: {"Status": "fertig", "Ist (h)": 10, "Notiz": "Behalten"}})
    button(at, "Fortschritt speichern").click()
    at.run()
    assert not at.exception
    saved = tracking.PROJECT_FILE.read_bytes()

    at = at.switch_page(PLANUNG).run()
    replacement = Plan.model_validate(plan_input(hours=12))
    monkeypatch.setattr(agent, "run_planning", lambda *args, **kwargs: replacement)
    button(at, "Plan mit Claude erstellen").click()
    at.run()
    assert not at.exception
    assert at.session_state["plan"] == replacement
    assert tracking.load().plan == PLAN
    # Nothing is chosen for the project lead: no button before a choice.
    assert at.radio(key="adopt_progress").value is None
    assert button(at, "Plan als Projekt übernehmen").disabled
    # Keeping does not fit: A is finished and in the new plan again, it would count twice.
    at.radio(key="adopt_progress").set_value("Als frühere Arbeit behalten").run()
    assert any("Schon fertig und wieder im Plan: A" in w.value for w in at.warning)
    assert button(at, "Plan als Projekt übernehmen").disabled

    at.radio(key="adopt_progress").set_value("Verwerfen").run()
    assert at.checkbox(key="adopt_overwrite").value is False
    assert "Fortschritt verwerfen" in at.checkbox(key="adopt_overwrite").label
    assert button(at, "Plan als Projekt übernehmen").disabled
    assert tracking.PROJECT_FILE.read_bytes() == saved

    at.checkbox(key="adopt_overwrite").check().run()
    assert not button(at, "Plan als Projekt übernehmen").disabled
    assert tracking.PROJECT_FILE.read_bytes() == saved  # consent alone is not a save
    button(at, "Plan als Projekt übernehmen").click()
    at.run()
    assert not at.exception
    restored = tracking.load()
    assert restored.plan == replacement
    assert not tracking.has_progress(restored)
    assert all(
        p.status == "offen" and p.actual_hours == 0 and p.note == ""
        for p in restored.progress.values()
    )


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


def journey(at):
    """The project path above an agent page, as HTML, or None."""
    return next((h.value for h in at.html if 'class="journey"' in h.value), None)


def test_every_agent_page_shows_the_project_path_with_the_page_marked(site):
    for path, step in [
        ("views/auftrag.py", "Auftrag"),
        ("views/anforderungen.py", "Anforderungen"),
        ("views/planung.py", "Planen"),
        ("views/durchfuehrung.py", "Ausführen"),
        ("views/kontrolle.py", "Prüfen"),
    ]:
        at = site.switch_page(path).run()
        html = journey(at)
        assert html is not None, path
        assert re.search(rf'class="step[^"]*here[^"]*"[^>]*>.*?{step}', html), path
    # Not on pages that are no agent.
    assert journey(site.switch_page("views/startseite.py").run()) is None


def test_without_a_project_the_path_waits_at_planen_and_says_nothing_twice(site):
    at = site.switch_page("views/kontrolle.py").run()
    assert not at.exception
    planen = journey(at).split("Ausführen")[0]
    assert 'class="step next' in planen  # Planen comes next
    assert "als Nächstes" in planen  # in words too, not by colour alone
    # The page itself already says there is no project: no second "Jetzt dran" for it.
    assert not any("Jetzt dran" in m.value for m in at.markdown)


def test_with_a_project_the_path_says_what_is_next_and_leads_there(tracked):
    at = tracked.switch_page("views/durchfuehrung.py").run()
    assert not at.exception
    advice, where = tracking.next_step(tracking.load(), date.today())
    assert '<span class="step done' in journey(at).split("Ausführen")[0]  # Planen is done
    assert any("Jetzt dran" in m.value and advice in m.value for m in at.markdown)
    target = {"durchfuehrung": "Zur Durchführung", "kontrolle": "Zur Kontrolle"}[where]
    # A button to the page the advice points to, unless the advice is about this page.
    assert any(b.label == target for b in at.button) == (where != "durchfuehrung")
    # Otherwise the line says it is this page.
    here = any("Unten auf dieser Seite" in m.value for m in at.markdown)
    assert here == (where == "durchfuehrung")


def test_a_damaged_project_leaves_the_path_without_a_state(site):
    tracking.PROJECT_FILE.write_text("{kaputt", encoding="utf-8")
    at = site.switch_page("views/kontrolle.py").run()
    assert not at.exception
    assert any("konnte nicht gelesen werden" in e.value for e in at.error)
    # The page says the file is unreadable; the path must not say nothing was planned yet.
    states = re.findall(r'class="step([^"]*)"', journey(at))
    assert states and not any("done" in s or "next" in s for s in states)
    assert not any("Jetzt dran" in m.value for m in at.markdown)


def test_the_planung_does_not_forecast_the_adopted_project(tracked, monkeypatch):
    # The Planung shows no "Jetzt dran" from the project: it must not depend on it either.
    def unused(*args):
        raise AssertionError("next_step on the Planung")

    monkeypatch.setattr(ui, "next_step", unused)
    at = tracked.switch_page("views/planung.py").run()
    assert not at.exception
    assert '<span class="step done' in journey(at)  # Planen is still done


def test_the_advice_is_shown_as_text(tracked, monkeypatch):
    # Task IDs from the plan end up in the advice; Markdown in them stays text.
    monkeypatch.setattr(
        ui, "next_step", lambda t, d: ("Task ![x](http://e/x.png) hängt", "kontrolle")
    )
    at = tracked.switch_page("views/durchfuehrung.py").run()
    line = next(m.value for m in at.markdown if "Jetzt dran" in m.value)
    assert r"!\[x\]" in line


def test_each_part_of_an_agent_page_says_who_does_it(tracked):
    at = tracked.switch_page("views/kontrolle.py").run()
    roles = [h.value for h in at.html if 'class="roles"' in h.value]
    # The agent: Claude proposes, Python checks, the project lead decides. In that order.
    agent_roles = next(r for r in roles if "CLAUDE" in r)
    assert agent_roles.index("CLAUDE") < agent_roles.index("PYTHON") < agent_roles.index("DU")
    # The numbers are Python's alone.
    assert any("PYTHON" in r and "CLAUDE" not in r and "DU" not in r for r in roles)


def test_without_a_project_durchfuehrung_and_kontrolle_lead_to_the_planung(site):
    for path in ["views/durchfuehrung.py", "views/kontrolle.py"]:
        at = site.switch_page(path).run()
        assert not button(at, "Zur Planung").disabled, path


def test_durchfuehrung_says_where_the_project_stands(tracked):
    # Only what does not depend on today's date: nothing is finished or started yet.
    at = tracked.switch_page("views/durchfuehrung.py").run()
    assert not at.exception
    for text in ["○ 0 von 2 Aufgaben fertig<", "○ 0 in Arbeit<"]:
        assert text in chips(at)


def test_durchfuehrung_shows_who_does_what_next(tracked):
    at = tracked.switch_page("views/durchfuehrung.py").run()
    assert not at.exception
    tables = [t.value for t in at.dataframe]
    # Whatever today is: nothing is done, so both tasks are still ahead, A first.
    assert any(list(t["ID"]) == ["A", "B"] and "Beginn" in t.columns for t in tables)

    done = [{"ID": "A", "Status": "fertig"}, {"ID": "B", "Status": "fertig"}]
    tracking.save(tracking.apply_rows(tracking.load(), done))
    at = at.run()
    assert "Alle Aufgaben sind fertig: Es steht nichts mehr an." in [s.value for s in at.success]


def test_progress_that_cannot_be_saved_is_said_not_thrown(tracked, monkeypatch):
    def locked(tracking_, path=None):
        raise PermissionError(13, "Zugriff verweigert")

    monkeypatch.setattr(tracking, "save", locked)
    at = tracked.switch_page("views/durchfuehrung.py").run()
    button(at, "Fortschritt speichern").click()
    at = at.run()
    assert not at.exception
    assert any("konnte nicht gespeichert werden" in e.value for e in at.error)
    assert not at.success  # and nothing claims it was saved


WAYS_ON = ["Fortschritt erfassen", "Stand prüfen"]


def test_the_rest_of_the_project_goes_from_kontrolle_into_the_planung(site):
    # A deadline that never passes, so that this holds whatever today is.
    open_end = PROJECT.model_copy(update={"deadline": date.max})
    tracking.adopt(open_end, TEAM, PLAN)
    tracking.save(tracking.apply_rows(tracking.load(), [{"ID": "A", "Status": "fertig"}]))

    at = site.switch_page("views/kontrolle.py").run()
    button(at, "Rest mit Claude umplanen").click()
    at.run()

    assert not at.exception and not at.error
    assert at.header[0].value == "Planung"
    assert at.session_state["source"] == "Rest des übernommenen Projekts"
    assert [t.id for t in at.session_state["plan"].tasks] == ["B"]  # A is finished
    assert at.session_state["step"] == "5 · Anpassen"  # where the conversation is
    assert at.date_input(key="start").value == max(date.today(), PROJECT.start_date)
    assert list(at.session_state["team_df"]["Name"]) == ["Anna"]

    # Adopted again, the finished A stays as work of the earlier plan. (AppTest reruns the
    # page it ran, Kontrolle, not the one the script switched to.)
    at = at.switch_page(PLANUNG).run()
    assert [t.id for t in at.session_state["plan"].tasks] == ["B"]
    at.radio(key="adopt_progress").set_value("Als frühere Arbeit behalten").run()
    button(at, "Plan als Projekt übernehmen").click()
    at.run()
    assert not at.exception and not at.error
    again = tracking.load()
    assert [t.id for t in again.plan.tasks] == ["B"]
    assert [(e.id, e.finished) for e in again.history] == [("A", True)]

    at = at.switch_page("views/durchfuehrung.py").run()
    assert not at.exception
    assert "Aus früheren Plänen (1)" in [e.label for e in at.expander]


def test_kontrolle_shows_the_earned_value(tracked):
    at = tracked.switch_page("views/kontrolle.py").run()
    assert not at.exception
    labels = [m.label for m in at.metric]
    for label in [
        "Planwert bis heute",
        "Fertigstellungswert",
        "Termin-Kennzahl (SPI)",
        "Aufwands-Kennzahl (CPI)",
    ]:
        assert label in labels


def test_kontrolle_survives_a_record_it_cannot_read(tracked):
    # A line with a cell too many, as a hand edit or an old version leaves it.
    workbench.RUNS_CSV.write_bytes(b"quelle,runden\r\nagent,3\r\nagent,5,csv,x\r\n")
    (workbench.RUNS_CSV.parent / "runs-bis-20261115-120000.csv").write_bytes(b"alt\r\n1\r\n")
    at = tracked.switch_page("views/kontrolle.py").run()

    assert not at.exception
    assert any("runs.csv konnte nicht gelesen werden" in e.value for e in at.error)
    assert any("runs-bis-20261115-120000.csv" in c.value for c in at.caption)


def test_kontrolle_shows_no_table_with_cells_left_out(tracked):
    # The first data line has a cell more than the heading. Read as it is, pandas would
    # leave the surplus cells out and show the rest as if nothing were wrong.
    workbench.RUNS_CSV.write_bytes(b"quelle,runden\r\nagent,5,csv\r\nagent,3,md\r\n")
    at = tracked.switch_page("views/kontrolle.py").run()
    assert not at.exception
    assert any("runs.csv konnte nicht gelesen werden" in e.value for e in at.error)
    assert not any("quelle" in frame.value.columns for frame in at.dataframe)


def test_a_damaged_project_is_replaced_only_when_confirmed(flow_site):
    # The file may hold progress that a hand can still rescue: no silent overwrite.
    at, _ = flow_site
    tracking.PROJECT_FILE.write_text("{kaputt", encoding="utf-8")
    at = fill_project(at.switch_page(PLANUNG).run())
    button(at, "Plan mit Claude erstellen").click()
    at.run()
    assert any("konnte nicht gelesen werden" in e.value for e in at.error)
    assert button(at, "Plan als Projekt übernehmen").disabled

    at.checkbox(key="adopt_replace_damaged").check().run()
    button(at, "Plan als Projekt übernehmen").click()
    at.run()
    assert not at.exception
    assert tracking.load().plan == PLAN


def test_kontrolle_opens_before_there_is_a_logs_folder(tracked, monkeypatch, tmp_path):
    # A fresh clone: logs/ is git-ignored and made by the first run or export.
    monkeypatch.setattr(workbench, "RUNS_CSV", tmp_path / "noch-nicht-da" / "runs.csv")
    at = tracked.switch_page("views/kontrolle.py").run()
    assert not at.exception and not at.error
    assert "Noch kein Plan exportiert." in [c.value for c in at.caption]


def test_kontrolle_promises_nothing_about_a_record_it_cannot_open(tracked):
    # Not a damaged record: something that cannot be opened at all (here a folder). The
    # next export cannot open it either, so it will not put it aside.
    workbench.RUNS_CSV.mkdir()
    at = tracked.switch_page("views/kontrolle.py").run()
    assert not at.exception
    (message,) = [e.value for e in at.error if "runs.csv konnte nicht gelesen werden" in e.value]
    assert "legt sie beiseite" not in message

    workbench.RUNS_CSV.rmdir()
    workbench.RUNS_CSV.write_bytes(b"quelle,runden\r\nagent,5,csv\r\n")
    at = at.run()
    (message,) = [e.value for e in at.error if "runs.csv konnte nicht gelesen werden" in e.value]
    assert "der nächste Export legt sie beiseite" in message


def test_kontrolle_takes_an_empty_record_for_no_export_yet(tracked):
    workbench.RUNS_CSV.write_bytes(b"")
    at = tracked.switch_page("views/kontrolle.py").run()
    assert not at.exception and not at.error
    assert "Noch kein Plan exportiert." in [c.value for c in at.caption]


def test_kontrolle_offers_the_control_document(tracked):
    at = tracked.switch_page("views/kontrolle.py").run()
    assert not at.exception
    assert any(m.value.startswith("# Kontrollbericht") for m in at.markdown)


def test_the_startseite_says_where_the_project_is_heading(tracked):
    at = tracked.run()
    assert not at.exception
    said = [c.value for c in at.caption] + [w.value for w in at.warning]
    assert any(text.startswith("Prognose: Voraussichtliches Ende") for text in said)
    # And what to do about it: one of the two buttons is the recommended one.
    assert any(m.value.startswith("**Als Nächstes:** ") for m in at.markdown)
    assert sorted(b.proto.type for b in at.button if b.label in WAYS_ON) == [
        "primary",
        "secondary",
    ]


def test_kontrolle_forecasts_the_end_from_the_recorded_progress(tracked):
    # Whatever today is: with every task finished there is nothing left to forecast.
    done = [{"ID": "A", "Status": "fertig", "Ist (h)": 8}, {"ID": "B", "Status": "fertig"}]
    tracking.save(tracking.apply_rows(tracking.load(), done))
    at = tracked.switch_page("views/kontrolle.py").run()
    assert not at.exception
    assert "Alle Aufgaben sind fertig." in [s.value for s in at.success]
    assert "Voraussichtliches Ende" not in {m.label for m in at.metric}

    # Nothing done yet: the forecast names an end, and a buffer or a missed deadline.
    tracking.adopt(PROJECT, TEAM, PLAN)
    at = at.run()
    assert not at.exception
    labels = {m.label for m in at.metric}
    assert "Voraussichtliches Ende" in labels
    assert labels & {"Puffer bis zur Deadline", "Deadline verpasst um"}


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
    at = tracked.switch_page("views/durchfuehrung.py").run()
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
        measures=[
            {"task_ids": ["B"], "action": "Anna beginnt B.", "effect": "Verzug sinkt."},
            {
                "task_ids": ["B"],
                "action": "Anna übernimmt B.",
                "effect": "B wird früher fertig.",
                "reassign_to": "Anna",
            },
        ],
    )
    monkeypatch.setattr(followup, "run_control_report", lambda *args, **kwargs: report)
    at = tracked.switch_page("views/kontrolle.py").run()
    assert button(at, "Stand mit Claude bewerten").disabled

    at.checkbox(key="consent_kontrolle").check()
    at.run()
    button(at, "Stand mit Claude bewerten").click()
    at.run()

    assert not at.exception and not at.error
    assert {m.label: m.value for m in at.metric}["Bewertung"] == "gefährdet"
    assert "- **B:** B hat noch nicht begonnen." in [m.value for m in at.markdown]
    (measures,) = [d.value for d in at.dataframe if "Maßnahme" in d.value.columns]
    first, second = measures.to_dict("records")
    assert first == {
        "Aufgaben": "B",
        "Maßnahme": "Anna beginnt B.",
        "Erwartete Wirkung (Claude)": "Verzug sinkt.",
        "Nachgerechnet (Python)": "Keine Umverteilung: nicht nachrechenbar",
    }
    # B is Anna's already: Python finds that giving it to her changes nothing, whatever
    # Claude expected.
    assert second["Erwartete Wirkung (Claude)"] == "B wird früher fertig."
    assert second["Nachgerechnet (Python)"].startswith("Das voraussichtliche Ende bleibt der ")


def test_text_from_claude_shows_no_image_or_link_on_the_pages(tracked, monkeypatch):
    # Rendered as Markdown, an image would be fetched from a foreign server and a link
    # could hide where it leads.
    active = "![x](https://track.example/p.png) [hier](https://evil.example)"
    summary = StatusSummary(summary=active, next_steps=[{"task_id": "A", "action": active}])
    report = ControlReport(
        assessment="gefährdet", findings=[{"task_ids": ["B"], "observation": active}]
    )
    monkeypatch.setattr(
        followup, "run_status_summary", lambda adopted, today, on_round=None: summary
    )
    monkeypatch.setattr(followup, "run_control_report", lambda *args, **kwargs: report)
    shown = []
    for page, consent, start in [
        ("durchfuehrung", "consent_durchfuehrung", "Zusammenfassung mit Claude vorschlagen"),
        ("kontrolle", "consent_kontrolle", "Stand mit Claude bewerten"),
    ]:
        at = tracked.switch_page(f"views/{page}.py").run()
        at.checkbox(key=consent).check()
        at.run()
        button(at, start).click()
        at.run()
        assert not at.exception
        shown += [m.value for m in at.markdown] + [c.value for c in at.caption]

    assert any("track.example" in text for text in shown)
    assert not [text for text in shown if re.search(r"(?<!\\)\[", text)]


def test_a_failing_agent_shows_the_reason_and_no_result(tracked, monkeypatch):
    def failing(adopted, today, on_round=None):
        raise AgentError("Kein Zugang zur Claude API: ANTHROPIC_API_KEY ist nicht gesetzt.")

    monkeypatch.setattr(followup, "run_control_report", failing)
    at = tracked.switch_page("views/kontrolle.py").run()
    at.checkbox(key="consent_kontrolle").check()
    at.run()
    button(at, "Stand mit Claude bewerten").click()
    at.run()

    assert not at.exception
    assert [e.value for e in at.error] == [
        ui.as_text("Kein Zugang zur Claude API: ANTHROPIC_API_KEY ist nicht gesetzt.")
    ]
    assert "Bewertung" not in {m.label for m in at.metric}


CHARTER = Charter(
    goal="Lerngruppen buchen Räume online",
    benefit="Kein Weg mehr zum Infoschalter",
    in_scope=["Buchen", "Stornieren"],
    stakeholders=["Studierende"],
    success_criteria=[{"id": "K1", "text": "Eine Buchung dauert unter einer Minute"}],
)


def enter_project(at):
    at.text_area(key="auftrag_idea").input(PROJECT.idea)
    at.date_input(key="auftrag_start").set_value(PROJECT.start_date)
    at.date_input(key="auftrag_deadline").set_value(PROJECT.deadline)
    return at.run()


def test_a_charter_from_claude_is_saved_as_draft_and_approved_by_the_lead(site, monkeypatch):
    def drafted(project, on_round=None):
        assert project == PROJECT
        return CHARTER

    monkeypatch.setattr(lifecycle, "run_charter", drafted)
    at = enter_project(site.switch_page("views/auftrag.py").run())
    button(at, "Projektauftrag mit Claude entwerfen").click()
    at = at.run()
    assert not at.exception and not at.error
    saved = lifecycle.load()
    assert (saved.project, saved.charter) == (PROJECT, CHARTER)
    assert lifecycle.charter_state(saved) == "entwurf"
    # What Claude drafted is in the fields, ready to change.
    assert at.text_area(key="charter_goal").value == CHARTER.goal

    button(at, "Projektauftrag freigeben").click()
    at = at.run()
    assert lifecycle.charter_state(lifecycle.load()) == "freigegeben"
    assert "✓ Projektauftrag: freigegeben<" in chips(at)


def test_a_charter_changed_after_approval_says_so(site):
    life = lifecycle.Lifecycle(project=PROJECT, charter=CHARTER)
    lifecycle.save(lifecycle.approve_charter(life, datetime.datetime(2026, 11, 16, 10, 0)))
    at = site.switch_page("views/auftrag.py").run()
    at.text_area(key="charter_goal").input("Räume und Geräte online buchen")
    at = at.run()
    assert any("nicht gespeichert" in c.value for c in at.caption)
    assert button(at, "Projektauftrag freigeben").disabled  # unsaved edits first
    button(at, "Änderungen speichern und prüfen").click()
    at = at.run()
    assert lifecycle.load().charter.goal == "Räume und Geräte online buchen"
    assert "! Projektauftrag: seit der Freigabe geändert<" in chips(at)
    assert not button(at, "Projektauftrag freigeben").disabled


def test_a_charter_with_errors_cannot_be_approved(site):
    twice = CHARTER.model_copy(
        update={"success_criteria": [Criterion(id="K1", text="a"), Criterion(id="K1", text="b")]}
    )
    lifecycle.save(lifecycle.Lifecycle(project=PROJECT, charter=twice))
    at = site.switch_page("views/auftrag.py").run()
    assert any("'K1' ist mehrfach vergeben" in e.value for e in at.error)
    assert button(at, "Projektauftrag freigeben").disabled


def test_a_charter_written_by_hand_needs_no_claude(site):
    at = enter_project(site.switch_page("views/auftrag.py").run())
    at.text_area(key="charter_goal").input(CHARTER.goal)
    at.text_area(key="charter_benefit").input(CHARTER.benefit)
    at.text_area(key="charter_in_scope").input("Buchen\nStornieren")
    at.text_area(key="charter_criteria").input("K1: Eine Buchung dauert unter einer Minute")
    at = at.run()
    button(at, "Änderungen speichern und prüfen").click()
    at = at.run()
    assert not at.exception and not at.error
    assert lifecycle.load().charter.in_scope == ["Buchen", "Stornieren"]


def test_an_agent_error_on_the_auftrag_is_shown(site, monkeypatch):
    def failing(project, on_round=None):
        raise AgentError("Kein Zugang zur Claude API: ANTHROPIC_API_KEY ist nicht gesetzt.")

    monkeypatch.setattr(lifecycle, "run_charter", failing)
    at = enter_project(site.switch_page("views/auftrag.py").run())
    button(at, "Projektauftrag mit Claude entwerfen").click()
    at = at.run()
    assert not at.exception
    assert "ANTHROPIC_API_KEY ist nicht gesetzt" in at.error[0].value
    assert lifecycle.load() is None or lifecycle.load().charter is None


def test_a_damaged_vorhaben_file_is_said_not_thrown(site):
    lifecycle.FILE.write_text("{kaputt", encoding="utf-8")
    at = site.switch_page("views/auftrag.py").run()
    assert not at.exception
    assert any("vorhaben.json ist beschädigt" in e.value for e in at.error)
    # The damaged file is only replaced on purpose.
    assert button(at, "Neu beginnen").disabled
    at.checkbox(key="vorhaben_replace").check()
    at = at.run()
    button(at, "Neu beginnen").click()
    at = at.run()
    assert lifecycle.load() == lifecycle.Lifecycle()


NEEDS = Requirements(
    items=[
        Requirement(
            id="R1",
            title="Raum buchen",
            story="Als Studentin will ich einen Raum buchen, damit die Gruppe arbeiten kann.",
            priority="Muss",
            criteria=["Die Buchung steht sofort in der Liste"],
            sources=["K1"],
        )
    ]
)
APPROVED_AT = datetime.datetime(2026, 11, 16, 10, 0)


def with_charter(approved=True):
    life = lifecycle.Lifecycle(project=PROJECT, charter=CHARTER)
    return lifecycle.approve_charter(life, APPROVED_AT) if approved else life


def test_requirements_from_claude_are_checked_against_the_charter(site, monkeypatch):
    def drafted(project, charter, on_round=None):
        assert (project, charter) == (PROJECT, CHARTER)
        return NEEDS

    monkeypatch.setattr(lifecycle, "run_requirements", drafted)
    lifecycle.save(with_charter())
    at = site.switch_page("views/anforderungen.py").run()
    button(at, "Anforderungen mit Claude entwerfen").click()
    at = at.run()
    assert not at.exception and not at.error
    assert lifecycle.load().requirements == NEEDS
    (table,) = [f.value for f in at.dataframe if f.key and f.key.startswith("requirements_editor_")]
    assert list(table["ID"]) == ["R1"]

    button(at, "Anforderungen freigeben").click()
    at = at.run()
    assert lifecycle.approved_requirements(lifecycle.load()) == NEEDS.items
    assert "✓ Anforderungen: freigegeben<" in chips(at)


def test_requirements_edited_in_the_table_are_checked_again(site):
    lifecycle.save(with_charter().model_copy(update={"requirements": NEEDS}))
    at = site.switch_page("views/anforderungen.py").run()
    # The only Muss becomes a Kann: the check finds no Muss, and nothing can be approved.
    at = edit_table(at, "requirements_editor_", {0: {"Priorität": "Kann"}})
    assert any("nicht gespeichert" in c.value for c in at.caption)
    button(at, "Änderungen speichern und prüfen").click()
    at = at.run()
    assert lifecycle.load().requirements.items[0].priority == "Kann"
    assert any("keine Muss-Anforderung" in e.value for e in at.error)
    assert button(at, "Anforderungen freigeben").disabled


def test_a_requirement_for_an_unknown_criterion_cannot_be_approved(site):
    lifecycle.save(with_charter().model_copy(update={"requirements": NEEDS}))
    at = site.switch_page("views/anforderungen.py").run()
    at = edit_table(at, "requirements_editor_", {0: {"Erfolgskriterien": "K9"}})
    button(at, "Änderungen speichern und prüfen").click()
    at = at.run()
    errors = [e.value for e in at.error]
    assert "Anforderung 'R1' nennt das unbekannte Erfolgskriterium 'K9'" in errors
    assert button(at, "Anforderungen freigeben").disabled


def test_without_an_approved_charter_the_requirements_say_so(site, monkeypatch):
    seen = []
    monkeypatch.setattr(
        lifecycle,
        "run_requirements",
        lambda project, charter, on_round=None: seen.append(charter) or NEEDS,
    )
    lifecycle.save(with_charter(approved=False))
    at = site.switch_page("views/anforderungen.py").run()
    assert any("nicht freigegeben" in w.value for w in at.warning)
    button(at, "Anforderungen mit Claude entwerfen").click()
    at = at.run()
    # Claude works from the charter as it stands, approved or not.
    assert seen == [CHARTER]


def test_without_project_data_the_requirements_lead_to_the_auftrag(site):
    at = site.switch_page("views/anforderungen.py").run()
    assert not at.exception
    assert button(at, "Anforderungen mit Claude entwerfen").disabled
    assert any("Noch keine Anforderungen." in i.value for i in at.info)


def steps(at):
    """Each step of the project path: its name and its classes."""
    return {
        name: set(classes.split())
        for classes, name in re.findall(r'class="(step[^"]*)"[^>]*><b>[^<]*</b> (\w+)', journey(at))
    }


def test_the_path_starts_at_the_auftrag_and_ticks_what_is_approved(site):
    at = site.switch_page("views/auftrag.py").run()
    assert steps(at)["Auftrag"] >= {"here", "next"}

    lifecycle.save(with_charter())
    at = site.switch_page("views/planung.py").run()
    path = steps(at)
    assert "done" in path["Auftrag"] and "next" in path["Anforderungen"]

    approved = lifecycle.approve_requirements(
        with_charter().model_copy(update={"requirements": NEEDS}), APPROVED_AT
    )
    lifecycle.save(approved)
    at = site.switch_page("views/kontrolle.py").run()
    path = steps(at)
    assert "done" in path["Anforderungen"] and "next" in path["Planen"]


def test_a_draft_or_a_skipped_phase_is_marked_not_approved(tracked):
    # A project is adopted without charter and requirements: both were skipped.
    at = tracked.switch_page("views/kontrolle.py").run()
    path = steps(at)
    assert "warn" in path["Auftrag"] and "warn" in path["Anforderungen"]
    assert journey(at).count("nicht freigegeben") == 2
    # A draft is marked too, before any project is adopted.
    tracking.PROJECT_FILE.unlink()
    lifecycle.save(with_charter(approved=False))
    path = steps(tracked.switch_page("views/planung.py").run())
    assert "warn" in path["Auftrag"] and "warn" not in path["Anforderungen"]


def test_an_unreadable_vorhaben_is_said_on_the_agent_pages(site):
    lifecycle.FILE.write_text("{kaputt", encoding="utf-8")
    at = site.switch_page("views/durchfuehrung.py").run()
    assert not at.exception
    assert any("vorhaben.json ist beschädigt" in c.value for c in at.caption)
    assert "done" not in str(steps(at)) and "next" not in str(steps(at)["Auftrag"])


def approve_needs(needs=NEEDS):
    life = with_charter().model_copy(update={"requirements": needs})
    lifecycle.save(lifecycle.approve_requirements(life, APPROVED_AT))


def test_approved_requirements_reach_agent_and_check(app, monkeypatch):
    approve_needs()
    seen = {}

    def planning(project, team, on_round=None, **trace):
        seen.update(trace)
        return PLAN  # serves no requirement

    monkeypatch.setattr(agent, "run_planning", planning)
    at = fill_project(app.run())
    button(at, "Plan mit Claude erstellen").click()
    at = at.run()
    assert not at.exception
    assert seen == {"requirements": NEEDS.items, "covered": frozenset()}
    warnings = [w.value for w in at.warning]
    assert "Muss-Anforderung 'R1' (Raum buchen) hat keine Task" in warnings
    assert "2 Tasks dienen keiner Anforderung: A, B" in warnings
    (trace,) = [d.value for d in at.dataframe if "Anforderung" in d.value.columns]
    assert trace.to_dict("records") == [
        {"ID": "R1", "Anforderung": "Raum buchen", "Priorität": "Muss", "Aufgaben": "keine"}
    ]
    assert "✓ Anforderungen: freigegeben<" in chips(at)


def test_without_approval_the_planung_works_as_before_and_says_so(app, monkeypatch):
    lifecycle.save(with_charter().model_copy(update={"requirements": NEEDS}))  # a draft
    monkeypatch.setattr(agent, "run_planning", planned)  # the old signature
    at = fill_project(app.run())
    button(at, "Plan mit Claude erstellen").click()
    at = at.run()
    assert not at.exception and not at.error
    assert not any("Anforderung" in w.value for w in at.warning)
    assert "○ Anforderungen: Entwurf, nicht freigegeben<" in chips(at)


def test_the_auftrag_prefills_step_2(app):
    planned_until = PROJECT.model_copy(
        update={"free_days": [Absence(first=date(2026, 12, 1), last=date(2026, 12, 2))]}
    )
    lifecycle.save(lifecycle.Lifecycle(project=planned_until))
    at = app.run()
    at.text_input(key="free_days").input("24.12.2026")
    at = at.run()
    button(at, "Eckdaten aus dem Projektauftrag übernehmen").click()
    at = at.run()
    assert at.text_area(key="idea").value == PROJECT.idea
    assert at.date_input(key="deadline").value == PROJECT.deadline
    # Free days are entered here, in the Planung: taking the dates leaves them alone.
    assert at.text_input(key="free_days").value == "24.12.2026"


def test_the_rest_does_not_ask_for_requirements_that_are_done(site, monkeypatch):
    second = NEEDS.items[0].model_copy(update={"id": "R2", "title": "Stornieren"})
    needs = Requirements(items=[*NEEDS.items, second])
    approve_needs(needs)
    data = plan_input()
    data["tasks"][0]["requirement_ids"] = ["R1"]
    data["tasks"][1]["requirement_ids"] = ["R2"]
    open_end = PROJECT.model_copy(update={"deadline": date.max})
    tracking.adopt(open_end, TEAM, Plan.model_validate(data), requirements=needs.items)
    tracking.save(tracking.apply_rows(tracking.load(), [{"ID": "A", "Status": "fertig"}]))

    at = site.switch_page("views/kontrolle.py").run()
    button(at, "Rest mit Claude umplanen").click()
    at.run()
    at = at.switch_page(PLANUNG).run()
    assert at.session_state["covered"] == frozenset({"R1"})
    # R1 was served by the finished A, which is not in the rest: no warning about it.
    assert not any("'R1'" in w.value for w in at.warning)

    # A new plan for the rest still counts what finished work served.
    seen = []

    def planning(project, team, on_round=None, **trace):
        seen.append(trace["covered"])
        return at.session_state["plan"]

    monkeypatch.setattr(agent, "run_planning", planning)
    at.checkbox(key="consent").check()
    at = at.run()
    button(at, "Plan mit Claude erstellen").click()
    at = at.run()
    assert seen == [frozenset({"R1"})]
    assert at.session_state["covered"] == frozenset({"R1"})


def test_the_kontrolle_shows_progress_per_requirement(site):
    data = plan_input()
    data["tasks"][0]["requirement_ids"] = ["R1"]
    data["tasks"][1]["requirement_ids"] = ["R1"]
    tracking.adopt(PROJECT, TEAM, Plan.model_validate(data), requirements=NEEDS.items)
    tracking.save(tracking.apply_rows(tracking.load(), [{"ID": "A", "Status": "fertig"}]))
    at = site.switch_page("views/kontrolle.py").run()
    assert not at.exception
    (table,) = [d.value for d in at.dataframe if "Anforderung" in d.value.columns]
    assert table.to_dict("records") == [
        {
            "ID": "R1",
            "Anforderung": "Raum buchen",
            "Priorität": "Muss",
            "Aufgaben": "A, B",
            "Fertig": "1 von 2",
        }
    ]


def test_without_requirements_the_kontrolle_says_why_it_cannot_trace(tracked):
    at = tracked.switch_page("views/kontrolle.py").run()
    assert any("ohne freigegebene Anforderungen übernommen" in c.value for c in at.caption)


def test_an_emptied_requirements_table_cannot_be_approved_as_it_was(site):
    lifecycle.save(with_charter().model_copy(update={"requirements": NEEDS}))
    at = site.switch_page("views/anforderungen.py").run()
    at = edit_table(at, "requirements_editor_", {}, deleted=[0])
    assert any("Noch keine Anforderung" in e.value for e in at.error)
    assert button(at, "Anforderungen freigeben").disabled


def test_starting_over_clears_the_fields_too(site):
    lifecycle.save(lifecycle.Lifecycle(project=PROJECT, charter=CHARTER))
    at = site.switch_page("views/auftrag.py").run()
    assert at.text_area(key="auftrag_idea").value == PROJECT.idea
    lifecycle.FILE.write_text("{kaputt", encoding="utf-8")
    at = at.run()
    at.checkbox(key="vorhaben_replace").check()
    at = at.run()
    button(at, "Neu beginnen").click()
    at = at.run()
    at = at.run()  # the fields of the old project must not save it again
    assert lifecycle.load() == lifecycle.Lifecycle()
    assert at.text_area(key="auftrag_idea").value == ""
