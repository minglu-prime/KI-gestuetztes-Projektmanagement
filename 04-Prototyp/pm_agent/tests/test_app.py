"""The Streamlit site headless, with the agent replaced: no network, no files in data/ or logs/."""

import dataclasses
import datetime
import json
import re
import socket
import tomllib
from datetime import date
from html import unescape
from pathlib import Path
from unittest.mock import Mock

import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest
from test_tools import PROJECT, TEAM, plan_input

from pm_agent import agent, comparison, followup, lab_server, lifecycle, tracking, ui, workbench
from pm_agent.agent import AgentError, PlanningError, Replan
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
    monkeypatch.setattr(comparison, "COMPARISON_CSV", tmp_path / "agent_vergleich.csv")
    monkeypatch.setattr(tracking, "PROJECT_FILE", tmp_path / "projekt.json")
    monkeypatch.setattr(agent, "LOG_DIR", tmp_path)
    monkeypatch.setattr(lifecycle, "FILE", tmp_path / "vorhaben.json")
    with socket.socket() as probe:  # a port where nothing listens
        probe.bind(("127.0.0.1", 0))
        monkeypatch.setattr(lab_server, "PORT", probe.getsockname()[1])


def test_no_test_reaches_the_real_data_or_logs():
    # A test saved its team into the real data/team.json: `local` replaced load_team but
    # not the file, and "Team lokal speichern" wrote there (Codex test run, 25.11.2026).
    # Every test runs with every file of the site in its own temporary folder (conftest).
    real = [SITE.parent / "data", SITE.parent / "logs"]
    used = [
        tracking.PROJECT_FILE,
        lifecycle.FILE,
        workbench.DATA_DIR,
        workbench.TEAM_FILE,
        workbench.RUNS_CSV,
        comparison.COMPARISON_CSV,
        agent.LOG_DIR,
    ]
    assert [p for p in used if any(p == r or r in p.parents for r in real)] == []


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


def test_the_consent_names_the_service_the_data_really_goes_to(site, monkeypatch):
    # The pages said "an die OpenAI API"; with OPENAI_BASE_URL the data go to another service
    # (the school's endpoint). Consent has to name the one that receives them.
    monkeypatch.setenv("OPENAI_BASE_URL", "https://ki.beispiel.test/v1")
    for path, key in [(PLANUNG, "consent"), ("views/auftrag.py", "charter_consent")]:
        label = site.switch_page(path).run().checkbox(key=key).label
        assert "ki.beispiel.test" in label and "OpenAI" not in label, path
    monkeypatch.delenv("OPENAI_BASE_URL")
    assert "api.openai.com" in site.switch_page(PLANUNG).run().checkbox(key="consent").label


def test_without_project_and_consent_planning_is_blocked(app):
    assert not app.exception
    assert button(app, "Plan mit dem Agenten erstellen").disabled
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
    button(at, "Plan mit dem Agenten erstellen").click()
    at.run()

    assert not at.exception
    metrics = {m.label: m.value for m in at.metric}
    assert metrics == {"Planende": "11.11.2026", "Fehler": "0", "Warnungen": "1"}
    # The result in one line above them: one warning to decide on.
    assert 'class="verdict warn"' in verdict(at) and "1 Warnung: Task" in verdict(at)
    # Said in full there, so not again below the chart.
    assert said_once(at, "Task 'A' braucht 'SQL', Anna hat diese Fähigkeit nicht angegeben")
    assert not at.error

    button(at, "Erneut prüfen").click()  # unchanged table: same plan, not marked as edited
    at.run()
    assert not at.exception and not at.error
    assert "angepasst" not in " ".join(c.value for c in at.caption)


def test_the_rounds_of_a_run_are_shown_once(app, monkeypatch):
    # The status box of the run listed the rounds, and an open box below listed them again.
    def one_round(project, team, on_round=None):
        accepted = {"tool": "submit_plan", "is_error": False, "content": "Plan angenommen."}
        on_round({"tool_results": [accepted]})
        return PLAN

    monkeypatch.setattr(agent, "run_planning", one_round)
    at = fill_project(app)
    button(at, "Plan mit dem Agenten erstellen").click()
    at.run()
    assert not at.exception
    logs = [e for e in at.expander if e.label.startswith("So ist der Plan entstanden")]
    assert logs == []
    # On the next run the status box is gone: the rounds stay at hand, folded.
    at.run()
    (log,) = [e for e in at.expander if e.label.startswith("So ist der Plan entstanden")]
    assert not log.proto.expanded


def lane(at):
    """The runner's lane of an agent run: its state and how each of the ten rounds ended."""
    run = next(m.value for m in at.markdown if 'class="run ' in m.value)
    return re.search(r'class="run run-(\w+)"', run)[1], re.findall(r'class="lap ?(\w*)"', run)


def test_a_runner_shows_each_round_of_the_run(app, monkeypatch):
    # While the agent works, a runner moves one lap per round. A gold dot marks a round in
    # which Python sent the agent back; once a plan is accepted the runner reaches the flag.
    found = json.dumps({"errors": [], "warnings": ["Kein Puffer"]})

    def four_rounds(project, team, on_round=None):
        on_round({"tool_results": [{"tool": "check_plan", "is_error": False, "content": found}]})
        on_round({"tool_results": [{"tool": "set_absence", "is_error": False, "content": "OK"}]})
        rejected = {"tool": "submit_plan", "is_error": True, "content": "Plan abgelehnt."}
        on_round({"tool_results": [rejected]})
        accepted = {"tool": "submit_plan", "is_error": False, "content": "Plan angenommen."}
        on_round({"tool_results": [accepted]})
        return PLAN

    monkeypatch.setattr(agent, "run_planning", four_rounds)
    at = fill_project(app)
    button(at, "Plan mit dem Agenten erstellen").click()
    at.run()
    assert not at.exception
    assert lane(at) == ("done", ["found", "ok", "found", "ok"] + [""] * 6)
    assert any("Jetzt entscheidest du" in m.value for m in at.markdown)


def test_a_failed_run_stops_the_runner(app, monkeypatch):
    def gives_up(project, team, on_round=None):
        rejected = {"tool": "submit_plan", "is_error": True, "content": "Plan abgelehnt."}
        on_round({"tool_results": [rejected]})
        raise AgentError("Kein Plan nach 1 Runde.")

    monkeypatch.setattr(agent, "run_planning", gives_up)
    at = fill_project(app)
    button(at, "Plan mit dem Agenten erstellen").click()
    at.run()
    assert not at.exception
    assert lane(at) == ("failed", ["found"] + [""] * 9)


def test_a_change_proposal_shows_its_changes_without_the_rounds(with_plan):
    at = with_plan.chat_input(key="wish").set_value(WISH).run()
    assert not at.exception
    assert not [e for e in at.expander if e.label.startswith("So ist der Agent vorgegangen")]


def chips(at):
    """The status strip above the steps, as plain text."""
    strip = next(h.value for h in at.html if 'class="chips"' in h.value)  # first of the page
    return strip


def test_the_status_strip_says_what_the_planning_still_needs(app, monkeypatch):
    for text in ["✓ Team: 1 Person<", "○ Zustimmung<", "○ Projekt<", "○ Plan offen<"]:
        assert text in chips(app)

    monkeypatch.setattr(agent, "run_planning", planned)
    at = fill_project(app)
    button(at, "Plan mit dem Agenten erstellen").click()
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
    button(at, "Plan mit dem Agenten erstellen").click()
    at = at.run()
    assert "übernimm" in now(at) and "Schritt 6" in now(at)


WISH = "Das Datenmodell dauert doppelt so lange."


@pytest.fixture
def with_plan(app, monkeypatch):
    """The Planung page with a plan from the agent, and an agent that doubles task A on request."""
    monkeypatch.setattr(agent, "run_planning", planned)
    at = fill_project(app)
    button(at, "Plan mit dem Agenten erstellen").click()
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
        return Replan(Plan.model_validate(plan_input(hours=16)), [])

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
    assert at.session_state["proposal"] is None  # the agent was not asked


def test_a_change_asked_from_claude_is_shown_as_differences_before_it_counts(with_plan):
    at = with_plan.chat_input(key="wish").set_value(WISH).run()

    assert not at.exception and not at.error
    texts = " ".join(m.value for m in at.markdown)
    assert "A · Datenmodell: 8 h → 16 h" in texts
    assert "Planende: 11.11.2026 → 12.11.2026 (1 Arbeitstag später)" in texts
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
        return Replan(Plan.model_validate(plan_input(hours=16)), [])

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
    # The agent was not called: it would have got the plan without the edit, and taking its
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
    # The agent lists the assignments in another order than the tasks; the table sorts them.
    data = plan_input()
    data["assignments"].reverse()
    shuffled = Plan.model_validate(data)
    monkeypatch.setattr(agent, "run_planning", lambda project, team, on_round=None: shuffled)
    at = fill_project(app)
    button(at, "Plan mit dem Agenten erstellen").click()
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
        agent,
        "run_replanning",
        lambda project, team, plan, wish, on_round=None: Replan(doubled, []),
    )
    at = fill_project(app)
    button(at, "Plan mit dem Agenten erstellen").click()
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
    # runs.csv is the data of the before/after comparison: the change by the agent adds to the
    # agent's time and rounds, and does not erase that the lead edited the plan by hand or
    # when the review began.
    assert at.session_state["agent_seconds"] >= 90.0
    assert at.session_state["round_count"] == 4
    assert at.session_state["hand_edited"] is True
    assert at.session_state["shown_at"] == shown_at


def away_on_monday_and_tuesday(monkeypatch):
    from pm_agent.models import MemberAbsence

    away = MemberAbsence(member="Anna", first=date(2026, 11, 9), last=date(2026, 11, 10))
    monkeypatch.setattr(
        agent,
        "run_replanning",
        lambda project, team, plan, wish, on_round=None: Replan(PLAN, [away]),
    )


def test_an_absence_from_a_wish_is_shown_and_goes_into_the_team_with_the_plan(
    with_plan, monkeypatch
):
    # The wish names an absence. The agent sets it, the check counts it, the lead takes both.
    away_on_monday_and_tuesday(monkeypatch)
    at = with_plan.chat_input(key="wish").set_value("Anna fehlt am 9. und 10.11.").run()
    shown = " ".join(m.value for m in at.markdown)
    assert "Abwesenheit neu: Anna 09.11.2026–10.11.2026" in shown
    assert not button(at, "Übernehmen").disabled  # an absence alone is a change
    button(at, "Übernehmen").click()
    at = at.run()

    assert not at.exception
    assert list(at.session_state["team_df"]["Abwesend"]) == ["09.11.2026–10.11.2026"]
    assert {m.label: m.value for m in at.metric}["Planende"] == "13.11.2026"


def test_a_dropped_absence_stays_out_of_the_team(with_plan, monkeypatch):
    away_on_monday_and_tuesday(monkeypatch)
    at = with_plan.chat_input(key="wish").set_value("Anna fehlt am 9. und 10.11.").run()
    button(at, "Verwerfen").click()
    at = at.run()

    assert list(at.session_state["team_df"]["Abwesend"]) == [""]
    assert {m.label: m.value for m in at.metric}["Planende"] == "11.11.2026"


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
        raise PlanningError("Der Agent hat nach 10 Runden noch keinen gültigen Plan.")

    monkeypatch.setattr(agent, "run_replanning", failing)
    at = with_plan.chat_input(key="wish").set_value(WISH).run()

    assert not at.exception
    assert [e.value for e in at.error] == [
        "Der Agent hat nach 10 Runden noch keinen gültigen Plan."
    ]
    assert at.session_state["proposal"] is None
    assert "Übernehmen" not in [b.label for b in at.button]


def test_an_absence_in_the_team_table_moves_the_plan(local, monkeypatch):
    monday = Absence(first=date(2026, 11, 9), last=date(2026, 11, 9))
    away = TEAM[0].model_copy(update={"absences": [monday]})
    monkeypatch.setattr(workbench, "load_team", lambda: [away])
    monkeypatch.setattr(agent, "run_planning", lambda project, team, on_round=None: PLAN)
    at = AppTest.from_file(str(SITE.parent / PLANUNG), default_timeout=30).run()
    at = fill_project(at)
    button(at, "Plan mit dem Agenten erstellen").click()
    at.run()

    assert not at.exception
    assert at.session_state["team_df"]["Abwesend"].tolist() == ["09.11.2026"]
    # Without the absence the plan ends on 11.11.: the work starts a day later.
    assert {m.label: m.value for m in at.metric}["Planende"] == "12.11.2026"


def test_free_days_of_the_project_move_the_plan(app, monkeypatch):
    monkeypatch.setattr(agent, "run_planning", lambda project, team, on_round=None: PLAN)
    at = fill_project(app)
    at.text_input(key="free_days").input("09.11.2026").run()
    button(at, "Plan mit dem Agenten erstellen").click()
    at.run()

    assert not at.exception
    # Without the free Monday the plan ends on 11.11.
    assert {m.label: m.value for m in at.metric}["Planende"] == "12.11.2026"

    # Not readable: the project is not complete, and the page says what is wrong.
    at.text_input(key="free_days").input("Weihnachten").run()
    assert not at.exception
    assert any("'Weihnachten' nicht lesbar" in e.value for e in at.error)
    assert button(at, "Plan mit dem Agenten erstellen").disabled
    # Step 3 says what is in the way, not that idea and deadline were missing.
    assert any("lesbare freie Tage (Schritt 2)" in i.value for i in at.info)


def test_details_that_cannot_be_saved_are_said_not_thrown(site, monkeypatch):
    def locked(*args, **kwargs):
        raise PermissionError(13, "Zugriff verweigert")

    monkeypatch.setattr(workbench, "save_team", locked)
    at = as_member(site)
    button(at, "Speichern").click()
    at = at.run()
    assert not at.exception
    assert any("team.json konnte nicht gespeichert werden" in e.value for e in at.error)
    assert not notices(at)  # and nothing claims it was saved


def test_a_project_that_cannot_be_saved_is_said_not_thrown(with_plan, monkeypatch):
    def locked(*args, **kwargs):
        raise PermissionError(13, "Zugriff verweigert")

    monkeypatch.setattr(tracking, "adopt", locked)
    at = with_plan
    button(at, "Plan als Projekt übernehmen").click()
    at = at.run()
    assert not at.exception
    assert any("projekt.json konnte nicht gespeichert werden" in e.value for e in at.error)
    assert not any("Übernommen" in s.value for s in at.success)


def test_an_agent_error_is_shown_to_the_project_lead(app, monkeypatch):
    def failing_run(project, team, on_round=None):
        raise PlanningError("Kein Zugang zur OpenAI API: OPENAI_API_KEY ist nicht gesetzt.")

    monkeypatch.setattr(agent, "run_planning", failing_run)
    at = fill_project(app)
    button(at, "Plan mit dem Agenten erstellen").click()
    at.run()

    assert not at.exception
    assert [e.value for e in at.error] == [
        # Shown as written: the underscores would set "API" in italics.
        ui.as_text("Kein Zugang zur OpenAI API: OPENAI_API_KEY ist nicht gesetzt.")
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
    marks = ['class="role agent"', 'class="role python"', 'class="role du"']
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
        "views/anforderungen.py": ("Anforderungen", "Noch keine Projektidee mit Terminen."),
    }
    for path, (header, info) in expected.items():
        at = site.switch_page(path).run()
        assert not at.exception, path
        assert at.header[0].value == header
        assert any(info in i.value for i in at.info), path

    at = site.switch_page("views/kontrolle.py").run()
    assert not at.tabs  # without a project nothing to sort: the agents' effort alone
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


def test_the_startseite_shows_the_whole_lifecycle_in_order(site):
    from pm_agent.ui import JOURNEY

    links = [link.proto.page for link in site.page_link]  # the URL path, the file's name
    phases = [key for key, _, _ in JOURNEY]
    assert any(links[i : i + len(phases)] == phases for i in range(len(links)))
    lead = " ".join(h.value for h in site.html if 'class="lead"' in h.value)
    assert "Projektauftrag" in lead and "Iteration" in lead


def test_startseite_and_ueber_uns_describe_all_three_agents(site):
    # Durchführung and Kontrolle have an agent too: no page may still call them "ohne LLM".
    start = " ".join(m.value for m in site.markdown)
    # Each step says who acts in it, Kontrolle included.
    tiles = [c.value for c in site.caption]
    about = " ".join(m.value for m in site.switch_page("views/ueber_uns.py").run().markdown)
    assert "ohne LLM" not in start and "ohne LLM" not in about
    assert "Planungsagenten" not in start
    assert "Python rechnet, der Agent bewertet" in tiles


def test_project_and_team_survive_a_visit_to_another_page(site, monkeypatch):
    monkeypatch.setattr(workbench, "load_team", REAL_LOAD_TEAM)
    workbench.save_team(TEAM)
    at = fill_project(site.switch_page(PLANUNG).run())
    # While the project lead visits Kontrolle, Ben joins via team.json.
    at = at.switch_page("views/kontrolle.py").run()
    ben = workbench.Member(name="Ben", skills={"SQL": 3}, hours_per_week=10)
    workbench.save_team([*TEAM, ben])
    at = at.switch_page(PLANUNG).run()

    assert not at.exception
    assert at.text_area(key="idea").value == PROJECT.idea
    assert at.date_input(key="deadline").value == PROJECT.deadline
    assert at.checkbox(key="consent").value is True
    assert list(at.session_state["team_df"]["Name"]) == ["Anna", "Ben"]
    assert not button(at, "Plan mit dem Agenten erstellen").disabled


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
    monkeypatch.setattr(agent, "OpenAI", unexpected_provider)
    monkeypatch.setattr(agent, "run_planning", planned)
    monkeypatch.setattr(followup, "run_status_summary", unexpected_provider)
    monkeypatch.setattr(followup, "run_control_report", unexpected_provider)
    monkeypatch.setattr(st, "download_button", capture_download)
    return site, downloads


def adopt_from_planning(at):
    at = fill_project(at.switch_page(PLANUNG).run())
    button(at, "Plan mit dem Agenten erstellen").click()
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


MEIN_BEREICH = f"{PAGES}/mein_bereich.py"


def as_member(at, name="Anna"):
    """The view Team as `name`, on Mein Bereich: where a member records their progress."""
    at.radio(key="role").set_value("Team").run()
    at.selectbox(key="me").set_value(name).run()
    return at.switch_page(MEIN_BEREICH).run()


def as_lead(at):
    """Back to the view of the project lead."""
    return at.radio(key="role").set_value("Leitung").run()


def test_unsaved_progress_survives_a_visit_to_another_page(flow_site):
    at, _ = flow_site
    at = adopt_from_planning(at)
    at = as_member(at)
    at = edit_progress(at, {0: {"Status": "in Arbeit", "Ist (h)": 3, "Notiz": "läuft"}})
    before = tracking.PROJECT_FILE.read_bytes()

    at = at.switch_page(f"{PAGES}/projektstand.py").run()
    at = at.switch_page(MEIN_BEREICH).run()

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
    at = as_member(at)
    at = edit_progress(at, {0: {"Notiz": "alt"}})
    at = at.switch_page(f"{PAGES}/projektstand.py").run()
    tracking.save(tracking.apply_rows(tracking.load(), [{"ID": "A", "Notiz": "neu"}]))

    at = at.switch_page(MEIN_BEREICH).run()

    assert not at.exception
    assert progress_editor(at).iloc[0]["Notiz"] == "neu"


def test_the_lead_sees_team_and_progress_without_changing_them(tracked):
    # Each member keeps their own skills, hours and progress; the project lead plans with
    # them but does not change them.
    at = tracked.switch_page(PLANUNG).run()
    assert not at.exception
    (team,) = [f for f in at.dataframe if f.key and f.key.startswith("team_editor_")]
    assert team.proto.disabled
    assert not [b for b in at.button if b.label == "Team lokal speichern"]
    at = at.switch_page("views/durchfuehrung.py").run()
    assert not at.exception
    assert not [b for b in at.button if b.label == "Fortschritt speichern"]
    assert not [f for f in at.dataframe if f.key and f.key.startswith("progress_editor_")]


def test_a_member_keeps_their_details_and_the_planung_plans_with_them(site, monkeypatch):
    monkeypatch.setattr(workbench, "load_team", REAL_LOAD_TEAM)
    workbench.save_team(TEAM)
    at = site.switch_page(PLANUNG).run()  # the project lead had the Planung open
    at = as_member(at)
    assert at.header[0].value == "Mein Bereich · Anna"
    next(n for n in at.number_input if n.label == "Stunden pro Woche").set_value(30)
    button(at, "Speichern").click()
    at = at.run()
    assert not at.exception and not at.error
    assert notices(at) == ["Deine Angaben sind gespeichert (lokal in data/team.json)."]
    assert [m.hours_per_week for m in REAL_LOAD_TEAM()] == [30]

    at = as_lead(at).switch_page(PLANUNG).run()
    assert not at.exception
    assert list(at.session_state["team_df"]["Stunden/Woche"]) == [30]


def test_someone_new_joins_the_team_on_mein_bereich(site, monkeypatch):
    monkeypatch.setattr(workbench, "load_team", REAL_LOAD_TEAM)
    workbench.save_team(TEAM)
    at = as_member(site, ui.NEW_MEMBER)
    assert at.header[0].value == "Mein Bereich"
    button(at, "Speichern").click()
    at = at.run()
    assert [e.value for e in at.error] == ["Bitte deinen Namen eintragen."]

    next(t for t in at.text_input if t.label == "Name").input("Anna")
    button(at, "Speichern").click()
    at = at.run()
    assert any("Anna gibt es im Team schon" in e.value for e in at.error)

    next(t for t in at.text_input if t.label == "Name").input("Ben")
    button(at, "Speichern").click()
    at = at.run()
    assert not at.exception and not at.error
    assert [m.name for m in REAL_LOAD_TEAM()] == ["Anna", "Ben"]
    assert at.selectbox(key="me").value == "Ben"  # and the sidebar says who is here now
    assert at.header[0].value == "Mein Bereich · Ben"


def test_mein_bereich_says_when_there_is_nothing_to_record(site, monkeypatch):
    monkeypatch.setattr(workbench, "load_team", REAL_LOAD_TEAM)
    workbench.save_team([*TEAM, workbench.Member(name="Ben", hours_per_week=10)])
    at = as_member(site)
    assert not at.exception
    assert "Noch kein Plan übernommen. Dann stehen deine Aufgaben hier." in [
        c.value for c in at.caption
    ]
    assert not [b for b in at.button if b.label == "Fortschritt speichern"]

    tracking.adopt(PROJECT, TEAM, PLAN)  # every task is Anna's
    at = as_member(at, "Ben")
    assert not at.exception
    assert "Im übernommenen Plan hat Ben keine Aufgabe." in [c.value for c in at.caption]
    assert not [b for b in at.button if b.label == "Fortschritt speichern"]


def test_the_projektstand_shows_every_member_where_the_project_stands(site):
    at = as_member(site).switch_page(f"{PAGES}/projektstand.py").run()
    assert not at.exception
    assert any("Noch kein Projekt übernommen" in i.value for i in at.info)

    tracking.adopt(PROJECT, TEAM, PLAN)
    at = at.run()
    assert not at.exception and not at.error
    assert {m.label: m.value for m in at.metric}["Aufgaben"] == "2"
    assert any("Wer wie weit ist" in m.value for m in at.markdown)

    tracking.PROJECT_FILE.write_text("{kaputt", encoding="utf-8")
    at = at.run()
    assert not at.exception
    assert any("konnte nicht gelesen werden" in e.value for e in at.error)


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
            assert not at.warning  # the late task stands in a table, not a box
            assert [(r["ID"], r["Geplant bis"], r["Status"]) for r in overdue_table(at)] == [
                ("B", "11.11.2026", "in Arbeit")
            ]


def test_nonzero_progress_survives_reopen_and_reaches_control_and_documents(flow_site):
    at, downloads = flow_site
    at = adopt_from_planning(at)
    baseline = tracking.load()
    before_save = tracking.PROJECT_FILE.read_bytes()

    # The status report counts only saved progress.
    at = at.switch_page("views/durchfuehrung.py").run()
    assert "- Ist-Stunden bisher: 0 h" in downloads["Statusbericht als Markdown herunterladen"]
    at = as_member(at)
    at = edit_progress(
        at,
        {
            0: {"Status": "fertig", "Ist (h)": 10, "Notiz": "Schema erneut geprüft"},
            1: {"Status": "in Arbeit", "Ist (h)": 4, "Notiz": "Integration läuft"},
        },
    )
    assert not at.exception and not at.error
    assert tracking.PROJECT_FILE.read_bytes() == before_save  # edits are not autosaved

    button(at, "Fortschritt speichern").click()
    at.run()
    assert not at.exception and not at.error
    assert any("Fortschritt gespeichert" in text for text in notices(at))

    after_save = tracking.PROJECT_FILE.read_bytes()
    stored = json.loads(after_save)
    assert stored["progress"] == {
        "A": {
            "status": "fertig",
            "actual_hours": 10,
            "remaining_hours": None,
            "note": "Schema erneut geprüft",
            "finished_on": date.today().isoformat(),  # set on saving
        },
        "B": {
            "status": "in Arbeit",
            "actual_hours": 4,
            "remaining_hours": None,
            "note": "Integration läuft",
            "finished_on": None,
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
    at = as_member(AppTest.from_file(str(SITE), default_timeout=30).run())
    assert not at.exception
    saved_rows = [
        {"ID": "A", "Status": "fertig", "Ist (h)": 10, "Notiz": "Schema erneut geprüft"},
        {"ID": "B", "Status": "in Arbeit", "Ist (h)": 4, "Notiz": "Integration läuft"},
    ]
    editor = progress_editor(at)
    assert editor[["ID", "Status", "Ist (h)", "Notiz"]].to_dict("records") == saved_rows
    # The project lead sees the same, read-only.
    at = as_lead(at).switch_page("views/durchfuehrung.py").run()
    assert not at.exception
    shown = next(f.value for f in at.dataframe if "Prognose Ende" in f.value.columns)
    assert shown[["ID", "Status", "Ist (h)", "Notiz"]].to_dict("records") == saved_rows
    report = downloads["Statusbericht als Markdown herunterladen"]
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
    assert not at.warning  # the late task stands in a table, not a box
    assert [(r["ID"], r["Geplant bis"], r["Status"]) for r in overdue_table(at)] == [
        ("B", "11.11.2026", "in Arbeit")
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
    at = as_member(at)
    at = edit_progress(at, {0: {"Status": "fertig", "Ist (h)": 10, "Notiz": "Behalten"}})
    button(at, "Fortschritt speichern").click()
    at.run()
    assert not at.exception
    saved = tracking.PROJECT_FILE.read_bytes()

    at = as_lead(at).switch_page(PLANUNG).run()
    replacement = Plan.model_validate(plan_input(hours=12))
    monkeypatch.setattr(agent, "run_planning", lambda *args, **kwargs: replacement)
    button(at, "Plan mit dem Agenten erstellen").click()
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
    button(at, "Plan mit dem Agenten erstellen").click()
    at.run()

    assert button(at, "Plan als Projekt übernehmen").disabled
    assert tracking.load() is None


@pytest.fixture
def tracked(site):
    """The site with an adopted project (in the temporary folder of `local`)."""
    tracking.adopt(PROJECT, TEAM, PLAN)
    return site


def verdict(at) -> str:
    """The verdict line on top of a page (ui.verdict), as HTML; empty without one."""
    return next((h.value for h in at.html if 'class="verdict' in h.value), "")


def said_once(at, finding: str) -> bool:
    """The finding stands in the verdict line, and in no box below it (ui.said_in_full)."""
    boxes = [m.value for m in [*at.error, *at.warning]]
    return finding in unescape(verdict(at)) and not any(finding in box for box in boxes)


def test_the_pages_of_a_project_open_with_its_forecast(tracked):
    # The answer to "Do we make it?" stood in the middle of the Kontrolle, below four metrics.
    for page in ("durchfuehrung", "kontrolle"):
        at = tracked.switch_page(f"views/{page}.py").run()
        assert not at.exception, page
        assert "Prognose: Voraussichtliches Ende" in verdict(at), page


def lines(boxes) -> list[str]:
    """The messages in alert boxes: several of one kind share a box as a list (ui.messages)."""
    return [line.removeprefix("- ") for box in boxes for line in box.value.splitlines()]


def journey(at):
    """The project path above an agent page, as HTML, or None."""
    return next((h.value for h in at.html if 'class="journey"' in h.value), None)


def test_a_page_of_a_group_links_the_other_pages_of_its_group_as_tabs(site):
    # Only the first page of a group is in the menu; the rest are reached by these tabs.
    for path, here, others in [
        ("views/entwurf.py", "Entwurf", ["auftrag", "anforderungen", "testplan"]),
        ("views/testlauf.py", "Test", ["kontrolle"]),
        ("views/impressum.py", "Impressum", ["ueber_uns"]),
    ]:
        at = site.switch_page(path).run()
        assert not at.exception, path
        assert [link.proto.page for link in at.page_link][: len(others)] == others, path
        tabs = next(h.value for h in at.html if 'class="group-tab here"' in h.value)
        assert f'aria-current="page">{here}<' in tabs, path
        assert f'[data-testid="stSidebarNavLink"][href$="/{others[0]}"]' in tabs, path
    # A page outside the groups has no tabs.
    at = site.switch_page(PLANUNG).run()
    assert not any('class="group-tab' in h.value for h in at.html)


def test_every_agent_page_shows_the_project_path_with_the_page_marked(site):
    for path, step in [
        ("views/auftrag.py", "Projektauftrag"),
        ("views/anforderungen.py", "Anforderungen"),
        ("views/planung.py", "Planung"),
        ("views/durchfuehrung.py", "Durchführung"),
        ("views/kontrolle.py", "Kontrolle"),
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
    planen = journey(at).split("Durchführung")[0]
    assert 'class="step next' in planen  # Planung comes next
    assert "als Nächstes" in planen  # in words too, not by colour alone
    # The page itself already says there is no project: no second "Jetzt dran" for it.
    assert not any("Jetzt dran" in m.value for m in at.markdown)


def test_with_a_project_the_path_says_what_is_next_and_leads_there(tracked):
    at = tracked.switch_page("views/durchfuehrung.py").run()
    assert not at.exception
    # The Durchführung shows the forecast: the line says what to do, not the forecast again.
    advice, where = tracking.next_step(tracking.load(), date.today(), forecast_shown=True)
    assert where == "kontrolle"  # two tasks are late
    assert '<span class="step done' in journey(at).split("Durchführung")[0]  # Planung is done
    assert any("Jetzt dran" in m.value and advice in m.value for m in at.markdown)
    # Said once on screen: by that line. In the path only for screen readers, else the
    # words push the last step onto a second row.
    assert "<em class=sr>als Nächstes</em>" in journey(at)
    assert "Zur Kontrolle" in labels(at)


def test_on_the_page_it_points_to_the_path_needs_no_line(tracked):
    # "Jetzt dran … ↓ Unten auf dieser Seite" repeated the verdict line below it (project
    # lead, 25.11.2026). On its own page the path marks the step in words, and that is all.
    at = tracked.switch_page("views/kontrolle.py").run()
    assert not at.exception
    assert tracking.next_step(tracking.load(), date.today())[1] == "kontrolle"
    assert not any("Jetzt dran" in m.value for m in at.markdown)
    assert "<em>als Nächstes</em>" in journey(at)


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
    assert '<span class="step done' in journey(at)  # Planung is still done


def test_the_advice_is_shown_as_text(tracked, monkeypatch):
    # Task IDs from the plan end up in the advice; Markdown in them stays text.
    monkeypatch.setattr(
        ui, "next_step", lambda t, d, **_: ("Task ![x](http://e/x.png) hängt", "kontrolle")
    )
    at = tracked.switch_page("views/durchfuehrung.py").run()
    line = next(m.value for m in at.markdown if "Jetzt dran" in m.value)
    assert r"!\[x\]" in line


def test_each_part_of_an_agent_page_says_who_does_it(tracked):
    at = tracked.switch_page("views/kontrolle.py").run()
    roles = [h.value for h in at.html if 'class="roles"' in h.value]
    # The agent proposes, Python checks, the project lead decides. In that order.
    agent_roles = next(r for r in roles if "AGENT" in r)
    assert agent_roles.index("AGENT") < agent_roles.index("PYTHON") < agent_roles.index("DU")
    # The numbers are Python's alone.
    assert any("PYTHON" in r and "AGENT" not in r and "DU" not in r for r in roles)


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
    at = as_member(tracked)
    button(at, "Fortschritt speichern").click()
    at = at.run()
    assert not at.exception
    assert any("konnte nicht gespeichert werden" in e.value for e in at.error)
    assert not at.success  # and nothing claims it was saved


WAYS_ON = ["Fortschritt ansehen", "Stand prüfen"]


def test_the_rest_of_the_project_goes_from_kontrolle_into_the_planung(site):
    # A deadline that never passes, so that this holds whatever today is.
    open_end = PROJECT.model_copy(update={"deadline": date.max})
    tracking.adopt(open_end, TEAM, PLAN)
    tracking.save(tracking.apply_rows(tracking.load(), [{"ID": "A", "Status": "fertig"}]))

    at = site.switch_page("views/kontrolle.py").run()
    button(at, "Rest mit dem Agenten umplanen").click()
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
    button(at, "Plan mit dem Agenten erstellen").click()
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


@pytest.fixture
def downloads(monkeypatch):
    """What each download button of a page hands out, by its label."""
    download_button, handed = st.download_button, {}

    def capture(label, data, **kwargs):
        handed[label] = data
        return download_button(label, data, **kwargs)

    monkeypatch.setattr(st, "download_button", capture)
    return handed


def test_kontrolle_offers_the_control_document(tracked, downloads):
    at = tracked.switch_page("views/kontrolle.py").run()
    assert not at.exception
    assert downloads["Kontrollbericht als Markdown herunterladen"].startswith("# Kontrollbericht")


def test_the_startseite_says_the_forecast_without_an_alarm_box(tracked):
    # The red forecast box on the Startseite was too loud (project lead, 25.11.2026). The end
    # stands as a tile beside the others; the line below says what it means and what to do.
    at = tracked.run()
    assert not at.exception
    assert verdict(at) == ""
    outlook = tracking.forecast(tracking.load(), date.today())
    assert {m.label: m.value for m in at.metric}["Voraussichtliches Ende"] == (
        f"{outlook.end:%d.%m.%Y}"
    )
    advice, _ = tracking.next_step(tracking.load(), date.today())  # with its reason
    assert f"**Als Nächstes:** {ui.as_text(advice)}" in [m.value for m in at.markdown]


def test_the_startseite_says_where_the_project_is_heading(tracked):
    at = tracked.run()
    assert not at.exception
    assert "Voraussichtliches Ende" in {m.label for m in at.metric}
    # And what to do about it: one of the two buttons is the recommended one (the line
    # "Als Nächstes": test_the_startseite_says_what_is_next_with_its_reason).
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
    # Said by the verdict line on top, not again in a green box.
    assert "Alle Aufgaben sind fertig." in verdict(at) and not at.success
    assert "Voraussichtliches Ende" not in {m.label for m in at.metric}

    # Nothing done yet: the forecast names an end, and a buffer or a missed deadline.
    tracking.adopt(PROJECT, TEAM, PLAN)
    at = at.run()
    assert not at.exception
    labels = {m.label for m in at.metric}
    assert "Voraussichtliches Ende" in labels
    assert labels & {"Puffer bis zur Deadline", "Deadline verpasst um"}


def test_the_execution_agent_needs_consent_and_its_proposal_goes_into_the_report(
    tracked, monkeypatch, downloads
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
    start = "Zusammenfassung mit dem Agenten vorschlagen"
    assert button(at, start).disabled
    report = "Statusbericht als Markdown herunterladen"
    assert "Noch nicht erstellt. Der Durchführungs-Agent" in downloads[report]

    at.checkbox(key="consent_durchfuehrung").check()
    at.run()
    button(at, start).click()
    at.run()

    assert not at.exception and not at.error
    texts = [m.value for m in at.markdown]
    assert "Beide Aufgaben sind im Verzug." in texts
    assert "- **A:** Anna klärt das Schema bis Montag." in texts
    assert "*Vorschlag des Durchführungs-Agenten" in downloads[report]


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
    assert button(at, "Stand mit dem Agenten bewerten").disabled

    at.checkbox(key="consent_kontrolle").check()
    at.run()
    button(at, "Stand mit dem Agenten bewerten").click()
    at.run()

    assert not at.exception and not at.error
    assert {m.label: m.value for m in at.metric}["Bewertung"] == "gefährdet"
    assert "- **B:** B hat noch nicht begonnen." in [m.value for m in at.markdown]
    (measures,) = [d.value for d in at.dataframe if "Maßnahme" in d.value.columns]
    first, second = measures.to_dict("records")
    assert first == {
        "Aufgaben": "B",
        "Maßnahme": "Anna beginnt B.",
        "Erwartete Wirkung (Agent)": "Verzug sinkt.",
        "Nachgerechnet (Python)": "Keine Umverteilung: nicht nachrechenbar",
    }
    # B is Anna's already: Python finds that giving it to her changes nothing, whatever
    # the agent expected.
    assert second["Erwartete Wirkung (Agent)"] == "B wird früher fertig."
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
        ("durchfuehrung", "consent_durchfuehrung", "Zusammenfassung mit dem Agenten vorschlagen"),
        ("kontrolle", "consent_kontrolle", "Stand mit dem Agenten bewerten"),
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


def test_an_error_quoting_a_cell_shows_no_link(app):
    # The message quotes the cell. Rendered as Markdown, the link hid where it leads.
    at = edit_table(app, "team_editor_", {0: {"Skills": "[hier](https://evil.example)"}})
    errors = [e.value for e in at.error]
    assert any("evil.example" in text for text in errors)
    assert not [text for text in errors if re.search(r"(?<!\\)\[", text)]


REAL_LOAD_TEAM = workbench.load_team  # bound before the local fixture replaces it


def test_a_damaged_team_file_shows_no_link(local, monkeypatch, tmp_path):
    # The reason names the place of the error, and a skill name is a place.
    path = tmp_path / "team.json"
    path.write_text(
        '[{"name": "Anna", "skills": {"[hier](https://evil.example)": 9}, "hours_per_week": 10}]',
        encoding="utf-8",
    )
    monkeypatch.setattr(workbench, "load_team", lambda: REAL_LOAD_TEAM(path))
    at = AppTest.from_file(str(SITE.parent / PLANUNG), default_timeout=30).run()
    errors = [e.value for e in at.error]
    assert any("evil.example" in text for text in errors)
    assert not [text for text in errors if re.search(r"(?<!\\)\[", text)]


def test_a_failing_agent_shows_the_reason_and_no_result(tracked, monkeypatch):
    def failing(adopted, today, on_round=None):
        raise AgentError("Kein Zugang zur OpenAI API: OPENAI_API_KEY ist nicht gesetzt.")

    monkeypatch.setattr(followup, "run_control_report", failing)
    at = tracked.switch_page("views/kontrolle.py").run()
    at.checkbox(key="consent_kontrolle").check()
    at.run()
    button(at, "Stand mit dem Agenten bewerten").click()
    at.run()

    assert not at.exception
    assert [e.value for e in at.error] == [
        ui.as_text("Kein Zugang zur OpenAI API: OPENAI_API_KEY ist nicht gesetzt.")
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
    at.checkbox(key="charter_consent").check().run()
    button(at, "Projektauftrag mit dem Agenten entwerfen").click()
    at = at.run()
    assert not at.exception and not at.error
    saved = lifecycle.load()
    assert (saved.project, saved.charter) == (PROJECT, CHARTER)
    assert lifecycle.charter_state(saved) == "entwurf"
    # What the agent drafted is in the fields, ready to change.
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
    # Approved: the button comes back once the change is saved, and the caption says so.
    assert "Projektauftrag freigeben" not in [b.label for b in at.button]
    assert any("Erst speichern, dann freigeben" in c.value for c in at.caption)
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
    assert said_once(at, "'K1' ist mehrfach vergeben")
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
        raise AgentError("Kein Zugang zur OpenAI API: OPENAI_API_KEY ist nicht gesetzt.")

    monkeypatch.setattr(lifecycle, "run_charter", failing)
    at = enter_project(site.switch_page("views/auftrag.py").run())
    at.checkbox(key="charter_consent").check().run()
    button(at, "Projektauftrag mit dem Agenten entwerfen").click()
    at = at.run()
    assert not at.exception
    # Unescaped for the page: the underscores may come escaped for Markdown.
    assert "OPENAI_API_KEY ist nicht gesetzt" in at.error[0].value.replace("\\_", "_")
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
    at.checkbox(key="requirements_consent").check().run()
    button(at, "Anforderungen mit dem Agenten entwerfen").click()
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
    assert said_once(at, "keine Muss-Anforderung")
    assert button(at, "Anforderungen freigeben").disabled


def requirements_table(at):
    (frame,) = [f for f in at.dataframe if f.key and f.key.startswith("requirements_editor_")]
    return frame.value


def test_unsaved_requirements_survive_a_visit_to_another_page(site):
    lifecycle.save(with_charter().model_copy(update={"requirements": NEEDS}))
    at = site.switch_page("views/anforderungen.py").run()
    at = edit_table(at, "requirements_editor_", {0: {"Priorität": "Kann"}})

    at = at.switch_page("views/auftrag.py").run()
    at = at.switch_page("views/anforderungen.py").run()

    assert not at.exception
    assert requirements_table(at).iloc[0]["Priorität"] == "Kann"
    assert any("nicht gespeichert" in c.value for c in at.caption)
    assert lifecycle.load().requirements == NEEDS  # still not saved
    button(at, "Änderungen speichern und prüfen").click()
    at = at.run()
    assert lifecycle.load().requirements.items[0].priority == "Kann"


def test_a_used_restore_does_not_come_back_when_the_saved_data_returns(site):
    lifecycle.save(with_charter().model_copy(update={"requirements": NEEDS}))
    at = site.switch_page("views/anforderungen.py").run()
    at = edit_table(at, "requirements_editor_", {0: {"Priorität": "Kann"}})
    at = at.switch_page("views/auftrag.py").run()
    at = at.switch_page("views/anforderungen.py").run()
    button(at, "Änderungen speichern und prüfen").click()
    at = at.run()
    assert lifecycle.load().requirements.items[0].priority == "Kann"

    at = edit_table(at, "requirements_editor_", {0: {"Priorität": "Muss"}})
    button(at, "Änderungen speichern und prüfen").click()
    at = at.run()

    assert lifecycle.load().requirements == NEEDS
    assert requirements_table(at).iloc[0]["Priorität"] == "Muss"
    assert not any("nicht gespeichert" in c.value for c in at.caption)


def test_unsaved_requirements_are_dropped_when_the_saved_ones_changed_meanwhile(site):
    lifecycle.save(with_charter().model_copy(update={"requirements": NEEDS}))
    at = site.switch_page("views/anforderungen.py").run()
    at = edit_table(at, "requirements_editor_", {0: {"Priorität": "Kann"}})
    at = at.switch_page("views/auftrag.py").run()
    changed = NEEDS.model_copy(
        update={"items": [NEEDS.items[0].model_copy(update={"priority": "Soll"})]}
    )
    lifecycle.save(lifecycle.load().model_copy(update={"requirements": changed}))

    at = at.switch_page("views/anforderungen.py").run()

    assert not at.exception
    assert requirements_table(at).iloc[0]["Priorität"] == "Soll"


def test_a_requirement_for_an_unknown_criterion_cannot_be_approved(site):
    lifecycle.save(with_charter().model_copy(update={"requirements": NEEDS}))
    at = site.switch_page("views/anforderungen.py").run()
    at = edit_table(at, "requirements_editor_", {0: {"Erfolgskriterien": "K9"}})
    button(at, "Änderungen speichern und prüfen").click()
    at = at.run()
    errors = lines(at.error)
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
    at.checkbox(key="requirements_consent").check().run()
    button(at, "Anforderungen mit dem Agenten entwerfen").click()
    at = at.run()
    # The agent works from the charter as it stands, approved or not.
    assert seen == [CHARTER]


def test_without_project_data_the_requirements_lead_to_the_auftrag(site):
    at = site.switch_page("views/anforderungen.py").run()
    assert not at.exception
    assert button(at, "Anforderungen mit dem Agenten entwerfen").disabled
    # The top says what is missing: the idea. No box below offers the switched-off draft.
    assert any("Noch keine Projektidee" in i.value for i in at.info)


def steps(at):
    """Each step of the project path: its name and its classes."""
    return {
        name: set(classes.split())
        for classes, name in re.findall(r'class="(step[^"]*)"[^>]*><b>[^<]*</b> (\w+)', journey(at))
    }


def test_the_path_starts_at_the_auftrag_and_ticks_what_is_approved(site):
    at = site.switch_page("views/auftrag.py").run()
    assert steps(at)["Projektauftrag"] >= {"here", "next"}

    lifecycle.save(with_charter())
    at = site.switch_page("views/planung.py").run()
    path = steps(at)
    assert "done" in path["Projektauftrag"] and "next" in path["Anforderungen"]

    approved = lifecycle.approve_requirements(
        with_charter().model_copy(update={"requirements": NEEDS}), APPROVED_AT
    )
    lifecycle.save(approved)
    at = site.switch_page("views/kontrolle.py").run()
    path = steps(at)
    assert "done" in path["Anforderungen"] and "next" in path["Entwurf"]


def test_a_draft_or_a_skipped_phase_is_marked_not_approved(tracked):
    # A project is adopted without charter and requirements: both were skipped.
    at = tracked.switch_page("views/kontrolle.py").run()
    path = steps(at)
    skipped = ["Projektauftrag", "Anforderungen", "Entwurf", "Testplan"]
    assert all("warn" in path[name] for name in skipped)
    assert journey(at).count("nicht freigegeben") == 4
    # A draft is marked too, before any project is adopted.
    tracking.PROJECT_FILE.unlink()
    lifecycle.save(with_charter(approved=False))
    path = steps(tracked.switch_page("views/planung.py").run())
    assert "warn" in path["Projektauftrag"] and "warn" not in path["Anforderungen"]


def test_an_unreadable_vorhaben_is_said_on_the_agent_pages(site):
    lifecycle.FILE.write_text("{kaputt", encoding="utf-8")
    at = site.switch_page("views/durchfuehrung.py").run()
    assert not at.exception
    assert any("vorhaben.json ist beschädigt" in c.value for c in at.caption)
    assert "done" not in str(steps(at)) and "next" not in str(steps(at)["Projektauftrag"])


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
    button(at, "Plan mit dem Agenten erstellen").click()
    at = at.run()
    assert not at.exception
    assert seen == {"requirements": NEEDS.items, "covered": frozenset()}
    warnings = lines(at.warning)
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
    button(at, "Plan mit dem Agenten erstellen").click()
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
    assert at.text_area(key="idea").value == PROJECT.idea
    assert at.date_input(key="deadline").value == PROJECT.deadline
    # Free days are entered here, in the Planung: taking the dates leaves them alone.
    assert at.text_input(key="free_days").value == "24.12.2026"


def test_the_rest_does_not_ask_for_requirements_that_are_done(site, monkeypatch):
    first = NEEDS.items[0].model_dump()
    first["criteria"] = [c["text"] for c in first["criteria"]]  # numbered for R2 anew
    second = Requirement.model_validate({**first, "id": "R2", "title": "Stornieren"})
    needs = Requirements(items=[*NEEDS.items, second])
    approve_needs(needs)
    data = plan_input()
    data["tasks"][0]["requirement_ids"] = ["R1"]
    data["tasks"][1]["requirement_ids"] = ["R2"]
    open_end = PROJECT.model_copy(update={"deadline": date.max})
    tracking.adopt(open_end, TEAM, Plan.model_validate(data), requirements=needs.items)
    tracking.save(tracking.apply_rows(tracking.load(), [{"ID": "A", "Status": "fertig"}]))

    at = site.switch_page("views/kontrolle.py").run()
    button(at, "Rest mit dem Agenten umplanen").click()
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
    button(at, "Plan mit dem Agenten erstellen").click()
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


def test_a_priority_is_coloured_wherever_a_table_shows_it(site):
    # Muss, Soll and Kann were grey text: hard to scan (project lead, 25.11.2026). Read-only
    # tables colour the cell like the verdict line; the word stays, colour is no only cue.
    data = plan_input()
    data["tasks"][0]["requirement_ids"] = ["R1"]
    tracking.adopt(PROJECT, TEAM, Plan.model_validate(data), requirements=NEEDS.items)
    for page in ("views/kontrolle.py", "views/abschluss.py"):
        at = site.switch_page(page).run()
        assert not at.exception
        (frame,) = [d for d in at.dataframe if "Priorität" in d.value.columns]
        assert frame.value["Priorität"].tolist() == ["Muss"]
        assert "#fdecea" in frame.proto.arrow_data.styler.styles  # the red of "Achtung"
    # The editor cannot style a cell: a coloured mark before the word, the value stays.
    lifecycle.save(with_charter().model_copy(update={"requirements": NEEDS}))
    at = site.switch_page("views/anforderungen.py").run()
    column = json.loads(requirements_table_proto(at).columns)["Priorität"]
    assert column["type_config"]["options"] == [
        {"value": "Muss", "label": "🔴 Muss"},
        {"value": "Soll", "label": "🟡 Soll"},
        {"value": "Kann", "label": "🟢 Kann"},
    ]
    assert requirements_table(at).iloc[0]["Priorität"] == "Muss"


def requirements_table_proto(at):
    (frame,) = [f for f in at.dataframe if f.key and f.key.startswith("requirements_editor_")]
    return frame.proto


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


def test_the_overdue_list_on_the_kontrolle_shows_no_link(site):
    # The plan of 9.11. is long past: both tasks are overdue whenever the test runs.
    tasks = [t.model_copy(update={"title": "[hier](https://evil.example)"}) for t in PLAN.tasks]
    tracking.adopt(PROJECT, TEAM, PLAN.model_copy(update={"tasks": tasks}))
    at = site.switch_page("views/kontrolle.py").run()
    assert not at.exception
    # A table cell is text, never Markdown: the title stands as written.
    assert [r["Aufgabe"] for r in overdue_table(at)] == ["[hier](https://evil.example)"] * 2


def design_tables(at):
    return {
        f.key.split("_")[1]: f.value
        for f in at.dataframe
        if f.key and f.key.startswith("design_") and f.key.endswith(tuple("0123456789"))
    }


def test_without_requirements_the_design_page_leads_to_them(site):
    at = site.switch_page("views/entwurf.py").run()
    assert not at.exception
    assert button(at, "Entwurf mit dem Agenten entwerfen").disabled
    lifecycle.save(with_charter())
    at = site.switch_page("views/entwurf.py").run()
    assert any("Noch keine Anforderungen" in i.value for i in at.info)
    at.checkbox(key="design_consent").check().run()
    assert not button(at, "Entwurf mit dem Agenten entwerfen").disabled


def test_a_design_from_claude_is_drawn_checked_and_approved(site, monkeypatch):
    from test_lifecycle import design

    def drafted(project, charter, requirements, on_round=None):
        assert (project, charter, requirements) == (PROJECT, CHARTER, NEEDS)
        return design()

    monkeypatch.setattr(lifecycle, "run_design", drafted)
    approve_needs()
    at = site.switch_page("views/entwurf.py").run()
    at.checkbox(key="design_consent").check().run()
    button(at, "Entwurf mit dem Agenten entwerfen").click()
    at = at.run()
    assert not at.exception and not at.error
    assert lifecycle.load().design == design()
    tables = design_tables(at)
    assert sorted(tables) == ["components", "flows", "interfaces", "steps"]
    assert list(tables["steps"]["Von"]) == ["B1", "B2", "B3"]
    assert any("<svg" in m.value and "Buchung anlegen" in m.value for m in at.markdown)

    button(at, "Entwurf freigeben").click()
    at = at.run()
    assert lifecycle.approved_design(lifecycle.load()) == design()
    assert "✓ Entwurf: freigegeben<" in chips(at)
    assert steps(at)["Entwurf"] >= {"done", "here"}


def test_a_step_against_the_contract_blocks_the_approval(site):
    from test_lifecycle import design

    approve_needs()
    lifecycle.save(lifecycle.load().model_copy(update={"design": design()}))
    at = site.switch_page("views/entwurf.py").run()
    at = edit_table(at, "design_steps_", {1: {"Von": "B3", "An": "B2"}})
    button(at, "Änderungen speichern und prüfen").click()
    at = at.run()
    assert said_once(at, "ein Aufruf von 'S1' geht von B2 an B3")
    assert button(at, "Entwurf freigeben").disabled


def test_the_planner_gets_the_design_only_while_it_is_approved(app, monkeypatch):
    from test_lifecycle import design

    approve_needs()
    life = lifecycle.load().model_copy(update={"design": design()})
    lifecycle.save(lifecycle.approve_design(life, APPROVED_AT))
    seen = []

    def planning(project, team, on_round=None, **context):
        seen.append(context.get("design"))
        return PLAN

    monkeypatch.setattr(agent, "run_planning", planning)
    at = fill_project(app.run())
    button(at, "Plan mit dem Agenten erstellen").click()
    at = at.run()
    assert "✓ Entwurf: freigegeben<" in chips(at)

    # The requirements change after the approval: the design no longer counts.
    changed = NEEDS.model_copy(
        update={"items": [NEEDS.items[0].model_copy(update={"title": "Neu"})]}
    )
    lifecycle.save(lifecycle.load().model_copy(update={"requirements": changed}))
    at = at.run()
    button(at, "Plan mit dem Agenten erstellen").click()
    at = at.run()
    assert not at.exception
    assert seen == [design(), None]
    assert "! Entwurf: seit der Freigabe geändert<" in chips(at)


def test_check_messages_on_the_lifecycle_pages_show_no_link(site):
    # A message quotes what the lead or the agent wrote; rendered as Markdown, a link in it
    # would hide where it leads.
    criteria = [*CHARTER.success_criteria, Criterion(id="K9", text="[hier](https://evil.example)")]
    charter = CHARTER.model_copy(update={"success_criteria": criteria})
    life = lifecycle.Lifecycle(project=PROJECT, charter=charter, requirements=NEEDS)
    lifecycle.save(life)
    shown, lines = [], []
    for page in ["auftrag", "anforderungen"]:
        at = site.switch_page(f"views/{page}.py").run()
        assert not at.exception
        shown += [e.value for e in at.error] + [w.value for w in at.warning]
        lines.append(verdict(at))  # a finding said in full stands only there (said_in_full)
    assert any("evil.example" in text for text in shown + lines)
    assert not [text for text in shown if re.search(r"(?<!\\)\[", text)]
    assert not [line for line in lines if "<a " in line]  # escaped HTML: no link either


def test_the_planung_shows_the_demos_of_the_plan(app, monkeypatch):
    with_demo = Plan.model_validate(
        {**PLAN.model_dump(), "demos": [{"week": 1, "title": "API zeigen", "task_ids": ["A"]}]}
    )
    monkeypatch.setattr(agent, "run_planning", lambda *args, **kwargs: with_demo)
    at = fill_project(app.run())
    button(at, "Plan mit dem Agenten erstellen").click()
    at = at.run()
    assert not at.exception
    (demos,) = [d.value for d in at.dataframe if "Demo" in d.value.columns]
    assert list(demos["Demo"]) == ["API zeigen"]
    assert "✓ Wochen-Demos: 1<" in chips(at)


DEMO_PLAN = Plan.model_validate(
    {
        **PLAN.model_dump(),
        "demos": [
            {"week": 1, "title": "Modell zeigen", "task_ids": ["A"]},
            {"week": 2, "title": "API zeigen", "task_ids": ["B"]},
        ],
    }
)


def test_the_weekly_retro_needs_a_measure_for_a_missed_demo(site):
    tracking.adopt(PROJECT, TEAM, DEMO_PLAN)
    at = site.switch_page("views/kontrolle.py").run()
    assert not at.exception
    (status,) = [d.value for d in at.dataframe if "Gezeigt" in d.value.columns]
    assert list(status["Demo"]) == ["Modell zeigen", "API zeigen"]

    at.selectbox(key="retro_week").set_value(2).run()
    at.radio(key="retro_shown_2").set_value("nein").run()
    at.text_input(key="retro_wrong_2").input("B nicht fertig").run()
    button(at, "Rückblick speichern").click()
    at = at.run()
    assert any("es fehlt eine Maßnahme" in e.value for e in at.error)
    assert tracking.load().retros == []

    at.text_input(key="retro_measure_2").input("Schema zuerst klären").run()
    button(at, "Rückblick speichern").click()
    at = at.run()
    (retro,) = tracking.load().retros
    assert (retro.monday, retro.shown, retro.measure) == (
        datetime.date(2026, 11, 16),
        "nein",
        "Schema zuerst klären",
    )
    assert any("Schema zuerst klären" in c.label for c in at.checkbox)

    at.checkbox(key="measure_done_20261116").check().run()
    assert tracking.load().retros[0].measure_done is True


def test_without_demos_the_retro_says_how_to_get_them(tracked):
    at = tracked.switch_page("views/kontrolle.py").run()
    assert not at.exception
    assert any("keine Wochen-Demos" in c.value for c in at.caption)


def test_a_new_measure_for_the_same_week_starts_open(site):
    tracking.adopt(PROJECT, TEAM, DEMO_PLAN)
    at = site.switch_page("views/kontrolle.py").run()
    at.selectbox(key="retro_week").set_value(2).run()
    at.radio(key="retro_shown_2").set_value("nein").run()
    at.text_input(key="retro_measure_2").input("Erste Maßnahme").run()
    button(at, "Rückblick speichern").click()
    at = at.run()
    at.checkbox(key="measure_done_20261116").check().run()
    at.text_input(key="retro_measure_2").input("Zweite Maßnahme").run()
    button(at, "Rückblick speichern").click()
    at = at.run()
    assert not at.exception
    (retro,) = tracking.load().retros
    assert (retro.measure, retro.measure_done) == ("Zweite Maßnahme", False)


def test_test_cases_from_claude_are_checked_and_approved(site, monkeypatch):
    from test_lifecycle import design
    from test_testplan import cases

    def drafted(project, requirements, the_design, on_round=None):
        assert (project, requirements, the_design) == (PROJECT, NEEDS, design())
        return cases()

    monkeypatch.setattr(lifecycle, "run_cases", drafted)
    approve_needs()
    lifecycle.save(lifecycle.load().model_copy(update={"design": design()}))
    at = site.switch_page("views/testplan.py").run()
    at.checkbox(key="cases_consent").check().run()
    button(at, "Testfälle mit dem Agenten entwerfen").click()
    at = at.run()
    assert not at.exception and not at.error
    assert lifecycle.load().cases == cases()

    # A case for an unknown criterion blocks the approval.
    at = edit_table(at, "cases_editor_", {0: {"Kriterien": "R9.1"}})
    button(at, "Änderungen speichern und prüfen").click()
    at = at.run()
    assert any("unbekannte Akzeptanzkriterium 'R9.1'" in e.value for e in at.error)
    assert button(at, "Testplan freigeben").disabled

    at = edit_table(at, "cases_editor_", {0: {"Kriterien": "R1.1"}})
    button(at, "Änderungen speichern und prüfen").click()
    at = at.run()
    button(at, "Testplan freigeben").click()
    at = at.run()
    assert lifecycle.approved_cases(lifecycle.load()) == cases()
    assert "✓ Testplan: freigegeben<" in chips(at)


def test_a_failed_case_needs_a_defect_which_can_reopen_its_task(tracked):
    from test_lifecycle import design
    from test_testplan import cases

    lifecycle.save(
        lifecycle.Lifecycle(project=PROJECT, requirements=NEEDS, design=design(), cases=cases())
    )
    at = tracked.switch_page("views/testlauf.py").run()
    assert not at.exception
    # Said quietly below the verdict, not as a box above it (project lead, 25.11.2026).
    assert any("nicht freigegeben" in c.value for c in at.caption) and not at.warning

    at.selectbox(key="test_case").set_value("T2").run()
    at.radio(key="test_result").set_value("fehlgeschlagen").run()
    button(at, "Ergebnis speichern").click()
    at = at.run()
    assert [(r.case_id, r.result) for r in tracking.load().results] == [("T2", "fehlgeschlagen")]
    assert said_once(at, "keinen Fehlereintrag")

    at.selectbox(key="defect_case").set_value("T2").run()
    at.radio(key="defect_severity").set_value("schwer").run()
    button(at, "Fehler erfassen").click()
    at = at.run()
    assert any("braucht eine Aufgabe" in e.value for e in at.error)
    assert tracking.load().defects == []

    at.text_input(key="defect_cause").input("Schema fehlt").run()
    at.selectbox(key="defect_task").set_value("B").run()
    button(at, "Fehler erfassen").click()
    at = at.run()
    (defect,) = tracking.load().defects
    assert (defect.id, defect.task_id, defect.status) == ("F1", "B", "offen")
    # The fields are empty again: a second click does not record the same defect twice.
    assert at.text_input(key="defect_cause").value == ""
    assert not any("keinen Fehlereintrag" in e.value for e in at.error)
    assert "keinen Fehlereintrag" not in verdict(at)

    button(at, "F1: Aufgabe B wieder öffnen").click()
    at = at.run()
    assert tracking.load().progress["B"].status == "in Arbeit"
    button(at, "F1: behoben").click()
    at = at.run()
    assert tracking.load().defects[0].status == "behoben"
    assert tracking.load().defects[0].fixed_on == date.today()

    # A fixed defect can be reopened, and an existing defect can be edited in place.
    button(at, "F1: wieder öffnen").click()
    at = at.run()
    assert tracking.load().defects[0].status == "offen"
    assert tracking.load().defects[0].fixed_on is None
    at.selectbox(key="defect_id").set_value("F1").run()
    at.radio(key="defect_severity").set_value("leicht").run()
    at.text_input(key="defect_cause").input("Nur Tippfehler").run()
    button(at, "Fehler erfassen").click()
    at = at.run()
    (edited_defect,) = tracking.load().defects
    assert (edited_defect.id, edited_defect.severity, edited_defect.cause) == (
        "F1",
        "leicht",
        "Nur Tippfehler",
    )

    # Choosing an entry fills the form with it; saving keeps its status and date of the fix.
    button(at, "F1: behoben").click()
    at = at.run()
    at.selectbox(key="defect_id").set_value("F1").run()
    assert at.text_input(key="defect_cause").value == "Nur Tippfehler"
    assert at.radio(key="defect_severity").value == "leicht"
    assert at.selectbox(key="defect_task").value == "B"
    at.text_input(key="defect_cause").input("Tippfehler im Titel").run()
    button(at, "Fehler erfassen").click()
    at = at.run()
    (edited_defect,) = tracking.load().defects
    assert (edited_defect.cause, edited_defect.status, edited_defect.fixed_on) == (
        "Tippfehler im Titel",
        "behoben",
        date.today(),
    )
    # "Neuer Fehler" empties the form again.
    at.selectbox(key="defect_id").set_value("F1").run()
    at.selectbox(key="defect_id").set_value("").run()
    assert at.text_input(key="defect_cause").value == ""


def test_without_a_test_plan_the_test_page_leads_to_it(tracked):
    at = tracked.switch_page("views/testlauf.py").run()
    assert not at.exception
    assert any("Noch kein Testplan" in i.value for i in at.info)


def test_the_closing_page_takes_decisions_and_lessons(site, monkeypatch):
    from pm_agent import closing
    from pm_agent.models import Lessons

    tracking.adopt(PROJECT, TEAM, PLAN, requirements=NEEDS.items)
    drafted = Lessons.model_validate({"items": [{"observation": "a", "advice": "b"}]})
    monkeypatch.setattr(closing, "run_lessons", lambda tracking, today, on_round=None: drafted)
    at = site.switch_page("views/abschluss.py").run()
    assert not at.exception
    assert said_once(at, "Muss-Anforderung 'R1'")

    at.radio(key="signoff_decision").set_value("zurückgestellt").run()
    button(at, "Entscheidung speichern").click()
    at = at.run()
    assert any("braucht einen Grund" in e.value for e in at.error)
    at.text_input(key="signoff_reason").input("keine Zeit").run()
    button(at, "Entscheidung speichern").click()
    at = at.run()
    (signoff,) = tracking.load().signoffs
    assert (signoff.requirement_id, signoff.decision, signoff.reason) == (
        "R1",
        "zurückgestellt",
        "keine Zeit",
    )
    assert at.text_input(key="signoff_reason").value == ""
    assert "lässt sich abschließen" in verdict(at) and 'class="verdict ok"' in verdict(at)

    at.checkbox(key="consent_abschluss").check().run()
    button(at, "Lessons Learned mit dem Agenten entwerfen").click()
    at = at.run()
    assert tracking.load().lessons == drafted.items
    assert not at.exception


def frame(at, prefix):
    (editor,) = [f for f in at.dataframe if f.key and f.key.startswith(prefix)]
    return editor.value


def test_unsaved_design_lessons_and_handbook_survive_a_visit_to_another_page(tracked):
    from test_lifecycle import design

    from pm_agent.models import Lesson

    approve_needs()
    lifecycle.save(lifecycle.load().model_copy(update={"design": design()}))
    lesson = Lesson(observation="a", advice="b")
    tracking.save(tracking.load().model_copy(update={"lessons": [lesson]}))
    saved = (lifecycle.load(), tracking.load())
    edits = [
        ("views/entwurf.py", "design_steps_", {1: {"Von": "B3"}}, "Von", "B3"),
        ("views/abschluss.py", "lessons_editor_", {0: {"Empfehlung": "neu"}}, "Empfehlung", "neu"),
        (
            "views/abschluss.py",
            "operations_editor",
            {0: {"Verantwortlich": "Team"}},
            "Verantwortlich",
            "Team",
        ),
    ]
    at = tracked
    for page, prefix, edit, column, value in edits:
        at = edit_table(at.switch_page(page).run(), prefix, edit)
        at = at.switch_page("views/startseite.py").run()
        at = at.switch_page(page).run()
        assert not at.exception, page
        assert frame(at, prefix).iloc[next(iter(edit))][column] == value, page
    assert (lifecycle.load(), tracking.load()) == saved  # nothing saved


def test_unsaved_test_cases_survive_a_visit_to_another_page(site):
    from test_lifecycle import design
    from test_testplan import cases

    approve_needs()
    lifecycle.save(lifecycle.load().model_copy(update={"design": design(), "cases": cases()}))
    saved = lifecycle.load()
    at = edit_table(
        site.switch_page("views/testplan.py").run(), "cases_editor_", {0: {"Titel": "neu"}}
    )
    at = at.switch_page("views/startseite.py").run().switch_page("views/testplan.py").run()
    assert not at.exception
    assert frame(at, "cases_editor_").iloc[0]["Titel"] == "neu"
    assert lifecycle.load() == saved  # nothing saved


def test_the_operations_page_checks_the_handbook_and_records_incidents(tracked):
    from test_lifecycle import design

    lifecycle.save(lifecycle.Lifecycle(project=PROJECT, design=design()))
    at = tracked.switch_page("views/abschluss.py").run()
    assert not at.exception
    assert any("keine Verantwortlichen" in e.value for e in at.error)

    at = edit_table(
        at,
        "operations_editor",
        {
            0: {"Verantwortlich": "Frontend-Team", "Überwachung": "Fehler zählen"},
            1: {"Verantwortlich": "Backend-Team", "Überwachung": "Health-Check"},
        },
    )
    button(at, "Betriebshandbuch speichern").click()
    at = at.run()
    assert [o.owner for o in tracking.load().operations] == ["Frontend-Team", "Backend-Team"]
    assert not at.error
    assert not [w.value for w in at.warning if "inzwischen geändert" in w.value]

    at.text_input(key="incident_impact").input("Buchen geht nicht").run()
    button(at, "Störung erfassen").click()
    at = at.run()
    assert notices(at) == ["Störung ST1 erfasst."]
    (incident,) = tracking.load().incidents
    assert (incident.id, incident.component_id) == ("ST1", "B1")
    incidents_table = next(f.value for f in at.dataframe if "Auswirkung" in f.value.columns)
    assert list(incidents_table.columns) == [
        "ID",
        "Datum",
        "Baustein",
        "Auswirkung",
        "Ursache",
        "Maßnahme",
        "Status",
    ]
    assert incidents_table.iloc[0]["Datum"] == f"{incident.on:%d.%m.%Y}"
    assert at.text_input(key="incident_impact").value == ""
    button(at, "ST1: behoben").click()
    at = at.run()
    assert tracking.load().incidents[0].status == "behoben"
    assert notices(at) == ["Störung ST1 ist behoben."]
    button(at, "ST1: wieder öffnen").click()
    at = at.run()
    assert tracking.load().incidents[0].status == "offen"
    assert notices(at) == ["Störung ST1 ist wieder offen."]
    at.selectbox(key="incident_id").set_value("ST1").run()
    at.text_input(key="incident_impact").input("Buchen langsam").run()
    button(at, "Störung erfassen").click()
    at = at.run()
    (edited_incident,) = tracking.load().incidents
    assert (edited_incident.id, edited_incident.impact) == ("ST1", "Buchen langsam")

    # Editing a fixed incident keeps its status and the day it happened.
    button(at, "ST1: behoben").click()
    at = at.run()
    saved = tracking.load()
    earlier = date(2026, 1, 5)
    tracking.save(
        saved.model_copy(
            update={"incidents": [saved.incidents[0].model_copy(update={"on": earlier})]}
        )
    )
    at = at.run()
    at.selectbox(key="incident_id").set_value("ST1").run()
    assert at.text_input(key="incident_impact").value == "Buchen langsam"
    at.text_input(key="incident_cause").input("Index fehlt").run()
    button(at, "Störung erfassen").click()
    at = at.run()
    (edited_incident,) = tracking.load().incidents
    assert (edited_incident.cause, edited_incident.status, edited_incident.on) == (
        "Index fehlt",
        "behoben",
        earlier,
    )


def test_a_new_run_starts_from_the_backlog(site, monkeypatch, tmp_path):
    from pm_agent import closing, workbench
    from pm_agent.tracking import Signoff

    monkeypatch.setattr(workbench, "DATA_DIR", tmp_path)
    adopted = tracking.adopt(PROJECT, TEAM, PLAN, requirements=NEEDS.items)
    tracking.save(
        closing.record_signoff(
            adopted, Signoff(requirement_id="R1", decision="zurückgestellt", reason="keine Zeit")
        )
    )
    lifecycle.save(lifecycle.Lifecycle(project=PROJECT))
    at = site.switch_page("views/abschluss.py").run()
    assert not at.exception
    (backlog,) = [d.value for d in at.dataframe if "Herkunft" in d.value.columns]
    assert list(backlog["Herkunft"]) == ["R1 zurückgestellt"]
    assert button(at, "Neuen Durchlauf beginnen").disabled

    at.checkbox(key="next_run_sure").check().run()
    button(at, "Neuen Durchlauf beginnen").click()
    at = at.run()
    assert not at.exception and not at.error
    assert tracking.load() is None
    assert [b.origin for b in lifecycle.load().backlog] == ["R1 zurückgestellt"]
    at = at.switch_page("views/anforderungen.py").run()
    assert any("Offen aus dem letzten Durchlauf" in m.value for m in at.markdown)


def test_one_project_goes_from_the_auftrag_to_the_next_run(site, monkeypatch, tmp_path):
    # Every other test seeds the files of the phase before it. Here one project passes all
    # nine steps through the pages only, so each hand-over between phases is exercised:
    # what one page approves is what the next page and its agent get.
    from test_lifecycle import design
    from test_testplan import cases

    from pm_agent import closing
    from pm_agent.models import Lessons

    linked = plan_input()
    for task in linked["tasks"]:
        task["requirement_ids"] = ["R1"]
    linked_plan = Plan.model_validate(linked)
    lessons = Lessons.model_validate({"items": [{"observation": "a", "advice": "b"}]})
    seen = {}

    def charter(project, on_round=None):
        seen["charter"] = project
        return CHARTER

    def requirements(project, charter, on_round=None):
        seen["requirements"] = charter
        return NEEDS

    def drafted_design(project, charter, requirements, on_round=None):
        seen["design"] = requirements
        return design()

    def drafted_cases(project, requirements, the_design, on_round=None):
        seen["cases"] = (requirements, the_design)
        return cases()

    def planning(project, team, on_round=None, **context):
        seen["planning"] = (project, context)
        return linked_plan

    monkeypatch.setattr(lifecycle, "run_charter", charter)
    monkeypatch.setattr(lifecycle, "run_requirements", requirements)
    monkeypatch.setattr(lifecycle, "run_design", drafted_design)
    monkeypatch.setattr(lifecycle, "run_cases", drafted_cases)
    monkeypatch.setattr(agent, "run_planning", planning)
    monkeypatch.setattr(closing, "run_lessons", lambda tracking, today, on_round=None: lessons)
    monkeypatch.setattr(agent, "OpenAI", lambda *a, **k: pytest.fail("no provider call"))
    monkeypatch.setattr(workbench, "DATA_DIR", tmp_path)

    def draft_and_approve(at, page, consent, draft, approve):
        at = at.switch_page(f"views/{page}.py").run()
        at.checkbox(key=consent).check().run()
        button(at, draft).click()
        at = at.run()
        assert not at.exception and not at.error, page
        button(at, approve).click()
        at = at.run()
        assert not at.exception and not at.error, page
        return at

    # 1-4 Vorbereiten: each draft is approved before the next phase drafts from it.
    at = enter_project(site.switch_page("views/auftrag.py").run())
    at = draft_and_approve(
        at,
        "auftrag",
        "charter_consent",
        "Projektauftrag mit dem Agenten entwerfen",
        "Projektauftrag freigeben",
    )
    at = draft_and_approve(
        at,
        "anforderungen",
        "requirements_consent",
        "Anforderungen mit dem Agenten entwerfen",
        "Anforderungen freigeben",
    )
    at = draft_and_approve(
        at, "entwurf", "design_consent", "Entwurf mit dem Agenten entwerfen", "Entwurf freigeben"
    )
    at = draft_and_approve(
        at,
        "testplan",
        "cases_consent",
        "Testfälle mit dem Agenten entwerfen",
        "Testplan freigeben",
    )
    assert seen["charter"] == PROJECT
    assert seen["requirements"] == CHARTER
    assert seen["design"] == NEEDS
    assert seen["cases"] == (NEEDS, design())
    life = lifecycle.load()
    assert [
        lifecycle.charter_state(life),
        lifecycle.requirements_state(life),
        lifecycle.design_state(life),
        lifecycle.cases_state(life),
    ] == ["freigegeben"] * 4

    # 5 Planung: the dates come from the Auftrag, the agent gets requirements and design.
    at = at.switch_page(PLANUNG).run()
    assert at.text_area(key="idea").value == PROJECT.idea  # taken over by itself
    at.checkbox(key="consent").check().run()
    button(at, "Plan mit dem Agenten erstellen").click()
    at = at.run()
    assert not at.exception and not at.error
    project, context = seen["planning"]
    assert project == PROJECT
    assert (context["requirements"], context["design"]) == (NEEDS.items, design())
    button(at, "Plan als Projekt übernehmen").click()
    at = at.run()
    assert not at.exception and not at.error
    adopted = tracking.load()
    assert (adopted.plan, adopted.requirements) == (linked_plan, NEEDS.items)

    # 6 Durchführung: Anna records both tasks as done, in her own view.
    at = as_member(at)
    at = edit_progress(
        at, {0: {"Status": "fertig", "Ist (h)": 8}, 1: {"Status": "fertig", "Ist (h)": 16}}
    )
    button(at, "Fortschritt speichern").click()
    at = at.run()
    assert not at.exception and not at.error
    assert {t: p.status for t, p in tracking.load().progress.items()} == {
        "A": "fertig",
        "B": "fertig",
    }

    # 7 Kontrolle: the requirement is traced to the finished tasks.
    at = as_lead(at).switch_page("views/kontrolle.py").run()
    assert not at.exception
    (trace,) = [d.value for d in at.dataframe if "Anforderung" in d.value.columns]
    assert trace[["ID", "Aufgaben", "Fertig"]].to_dict("records") == [
        {"ID": "R1", "Aufgaben": "A, B", "Fertig": "2 von 2"}
    ]

    # 8 Test: every case of the approved test plan passes.
    at = at.switch_page("views/testlauf.py").run()
    assert not at.exception
    # Said once: by the verdict line; the table lists the cases, the panel of defects is quiet.
    assert "3 Testfälle ohne Ergebnis: T1, T2, T3" in verdict(at) and not at.warning
    for case in [c.id for c in cases().cases]:
        at.selectbox(key="test_case").set_value(case).run()
        at.radio(key="test_result").set_value("bestanden").run()
        button(at, "Ergebnis speichern").click()
        at = at.run()
        assert not at.exception and not at.error, case
    assert {r.case_id: r.result for r in tracking.load().results} == dict.fromkeys(
        [c.id for c in cases().cases], "bestanden"
    )

    # 9 Abschluss: sign-off, handbook and lessons, then the next run.
    at = at.switch_page("views/abschluss.py").run()
    assert not at.exception
    signoff = next(f.value for f in at.dataframe if "Vorschlag" in f.value.columns)
    assert list(signoff["Vorschlag"]) == ["abnehmbar"]
    at.radio(key="signoff_decision").set_value("abgenommen").run()
    button(at, "Entscheidung speichern").click()
    at = at.run()
    at = edit_table(
        at,
        "operations_editor",
        {
            0: {"Verantwortlich": "Team", "Überwachung": "Fehler zählen"},
            1: {"Verantwortlich": "Team", "Überwachung": "Health-Check"},
        },
    )
    button(at, "Betriebshandbuch speichern").click()
    at = at.run()
    at.checkbox(key="consent_abschluss").check().run()
    button(at, "Lessons Learned mit dem Agenten entwerfen").click()
    at = at.run()
    assert not at.exception and not at.error
    closed = tracking.load()
    assert [(s.requirement_id, s.decision) for s in closed.signoffs] == [("R1", "abgenommen")]
    assert closed.lessons == lessons.items
    assert "lässt sich abschließen" in verdict(at) and 'class="verdict ok"' in verdict(at)

    at.checkbox(key="next_run_sure").check().run()
    button(at, "Neuen Durchlauf beginnen").click()
    at = at.run()
    assert not at.exception and not at.error
    assert tracking.load() is None
    assert lifecycle.load() == lifecycle.Lifecycle()  # nothing left over for the next run
    (archived,) = (tmp_path / "archiv").iterdir()
    assert sorted(p.name for p in archived.iterdir()) == ["projekt.json", "vorhaben.json"]
    assert tracking.load(archived / "projekt.json") == closed


def test_the_operations_step_is_done_only_when_the_handbook_passes(tracked):
    from test_lifecycle import design

    from pm_agent.tracking import Operation

    lifecycle.save(lifecycle.Lifecycle(project=PROJECT, design=design()))
    empty = [Operation(component_id="B2"), Operation(component_id="B3")]
    tracking.save(tracking.load().model_copy(update={"operations": empty}))
    at = tracked.switch_page("views/abschluss.py").run()
    assert any("keine Verantwortlichen" in e.value for e in at.error)
    full = [
        Operation(component_id=c, owner="Team", monitoring="Health-Check") for c in ["B2", "B3"]
    ]
    tracking.save(tracking.load().model_copy(update={"operations": full}))
    at = tracked.switch_page("views/abschluss.py").run()
    assert not any("keine Verantwortlichen" in e.value for e in at.error)


def test_without_requirements_the_closing_page_does_not_call_the_project_closable(tracked):
    at = tracked.switch_page("views/abschluss.py").run()
    assert not at.exception
    assert "lässt sich abschließen" not in verdict(at)
    assert "nichts abzunehmen" in verdict(at)


def test_a_finding_the_verdict_says_in_full_is_not_repeated_below(tracked):
    # The one open finding stood in the verdict line and again in a box below the table
    # (project lead, 25.11.2026). Said in full on top, it is not said again.
    at = tracked.switch_page("views/abschluss.py").run()
    assert not at.exception
    assert "1 Warnung: " in verdict(at) and "nichts abzunehmen" in verdict(at)
    assert not any("nichts abzunehmen" in w.value for w in at.warning)


def test_the_consent_for_lessons_names_what_is_sent(tracked):
    at = tracked.switch_page("views/abschluss.py").run()
    label = at.checkbox(key="consent_abschluss").label
    assert "Wochenrückblicke" in label and "Skills" not in label


def test_the_startseite_leads_to_the_test_page_for_open_defects(tracked):
    from pm_agent.tracking import Defect, record_defect

    done = tracking.apply_rows(
        tracking.load(), [{"ID": "A", "Status": "fertig"}, {"ID": "B", "Status": "fertig"}]
    )
    tracking.save(record_defect(done, Defect(case_id="T1", severity="mittel", cause="x")))
    at = tracked.switch_page("views/startseite.py").run()
    assert not at.exception
    assert button(at, "Fehler beheben").proto.type == "primary"


@pytest.mark.parametrize(
    ("page", "label", "key"),
    [
        ("auftrag", "Projektauftrag mit dem Agenten entwerfen", "charter_consent"),
        ("anforderungen", "Anforderungen mit dem Agenten entwerfen", "requirements_consent"),
        ("entwurf", "Entwurf mit dem Agenten entwerfen", "design_consent"),
        ("testplan", "Testfälle mit dem Agenten entwerfen", "cases_consent"),
    ],
)
def test_lifecycle_drafting_requires_transfer_confirmation(site, page, label, key):
    lifecycle.save(lifecycle.Lifecycle(project=PROJECT))
    at = site.switch_page(f"views/{page}.py").run()
    assert button(at, label).disabled
    at.checkbox(key=key).check().run()
    assert not button(at, label).disabled


def test_draft_cannot_overwrite_a_project_changed_during_the_call(site, monkeypatch):
    before = with_charter()
    newer = before.model_copy(update={"project": PROJECT.model_copy(update={"idea": "Neu"})})
    lifecycle.save(before)

    def draft(project, charter, on_round=None):
        lifecycle.save(newer)
        return NEEDS

    monkeypatch.setattr(lifecycle, "run_requirements", draft)
    at = site.switch_page("views/anforderungen.py").run()
    at.checkbox(key="requirements_consent").check().run()
    button(at, "Anforderungen mit dem Agenten entwerfen").click()
    at = at.run()
    assert not at.exception
    assert lifecycle.load() == newer
    assert any("inzwischen geändert" in error.value for error in at.error)


def test_a_failed_lifecycle_write_leaves_the_error_and_edit_visible(site, monkeypatch):
    approve_needs()
    at = site.switch_page("views/anforderungen.py").run()
    at = edit_table(at, "requirements_editor_", {0: {"Titel": "Neuer Titel"}})

    def blocked(_life):
        raise PermissionError("Datei gesperrt")

    monkeypatch.setattr(lifecycle, "save", blocked)
    button(at, "Änderungen speichern und prüfen").click()
    at = at.run()
    assert not at.exception
    assert lifecycle.load().requirements == NEEDS
    assert any("Datei gesperrt" in error.value for error in at.error)
    assert not button(at, "Änderungen speichern und prüfen").disabled


@pytest.mark.parametrize("severe", [False, True])
def test_iteration_cannot_archive_a_project_with_blocking_closing_errors(
    site, monkeypatch, tmp_path, severe
):
    from pm_agent import closing

    monkeypatch.setattr(workbench, "DATA_DIR", tmp_path)
    adopted = tracking.adopt(PROJECT, TEAM, PLAN, requirements=NEEDS.items)
    if severe:
        adopted = closing.record_signoff(
            adopted, tracking.Signoff(requirement_id="R1", decision="abgenommen")
        )
        adopted = tracking.record_defect(
            adopted, tracking.Defect(case_id="T1", severity="schwer", cause="offen", task_id="A")
        )
        tracking.save(adopted)
    at = site.switch_page("views/abschluss.py").run()
    assert not at.exception
    at.checkbox(key="next_run_sure").check().run()
    assert button(at, "Neuen Durchlauf beginnen").disabled
    assert tracking.load() == adopted
    assert not (tmp_path / "archiv").exists()


def test_revised_test_case_requires_new_evidence_across_pages(site):
    from test_lifecycle import design
    from test_testplan import cases

    approve_needs()
    life = lifecycle.load().model_copy(update={"design": design(), "cases": cases()})
    lifecycle.save(lifecycle.approve_cases(life, APPROVED_AT))
    tracking.adopt(PROJECT, TEAM, PLAN, requirements=NEEDS.items)

    test = site.switch_page("views/testlauf.py").run()
    button(test, "Ergebnis speichern").click().run()
    test.selectbox(key="test_case").set_value("T2").run()
    button(test, "Ergebnis speichern").click().run()
    control = test.switch_page("views/kontrolle.py").run()
    assert next(m.value for m in control.metric if m.label == "Bestanden") == "2"

    plan = control.switch_page("views/testplan.py").run()
    plan = edit_table(plan, "cases_editor_", {0: {"Erwartet": "Neue verbindliche Erwartung"}})
    button(plan, "Änderungen speichern und prüfen").click().run()
    button(plan, "Testplan freigeben").click().run()
    assert lifecycle.cases_state(lifecycle.load()) == "freigegeben"

    test = plan.switch_page("views/testlauf.py").run()
    results = next(f.value for f in test.dataframe if "Ergebnis" in f.value.columns)
    assert results.set_index("ID").loc["T1", "Ergebnis"] != "bestanden"
    assert results.set_index("ID").loc["T2", "Ergebnis"] == "bestanden"
    control = test.switch_page("views/kontrolle.py").run()
    assert next(m.value for m in control.metric if m.label == "Bestanden") == "1"
    end = control.switch_page("views/abschluss.py").run()
    signoff = next(f.value for f in end.dataframe if "Vorschlag" in f.value.columns)
    assert signoff.iloc[0]["Vorschlag"] != "abnehmbar"


def test_another_tabs_archive_does_not_recreate_old_project_details(site, tmp_path):
    from pm_agent import closing

    lifecycle.save(with_charter())
    active = tracking.adopt(PROJECT, TEAM, PLAN)
    at = site.switch_page("views/auftrag.py").run()
    assert at.text_area(key="auftrag_idea").value == PROJECT.idea

    closing.start_next_run(active, APPROVED_AT, tmp_path / "archiv")
    at.checkbox(key="charter_consent").check().run()
    assert not at.exception
    assert lifecycle.load().project is None
    assert not at.text_area(key="auftrag_idea").value


def test_progress_save_after_archiving_cannot_recreate_the_project(site, tmp_path, monkeypatch):
    from pm_agent import closing

    active = tracking.adopt(PROJECT, TEAM, PLAN)
    lifecycle.save(with_charter())
    apply = tracking.apply_rows

    def save_after_archiving(old, rows):
        closing.start_next_run(active, APPROVED_AT, tmp_path / "archiv")
        return apply(old, rows)

    monkeypatch.setattr(tracking, "apply_rows", save_after_archiving)
    at = as_member(site)
    button(at, "Fortschritt speichern").click().run()
    assert not at.exception
    assert tracking.load() is None
    assert any("inzwischen geändert" in error.value for error in at.error)


def test_slow_lessons_draft_preserves_newer_manual_notes(site, monkeypatch):
    from pm_agent import closing
    from pm_agent.models import Lesson, Lessons

    tracking.adopt(PROJECT, TEAM, PLAN)
    newer = Lesson(observation="Neu gespeichert", advice="Behalten")
    drafted = Lessons(items=[Lesson(observation="Alter Entwurf", advice="Ersetzen")])

    def propose(old, today, on_round=None):
        tracking.save(old.model_copy(update={"lessons": [newer]}))
        return drafted

    monkeypatch.setattr(closing, "run_lessons", propose)
    at = site.switch_page("views/abschluss.py").run()
    at.checkbox(key="consent_abschluss").check().run()
    button(at, "Lessons Learned mit dem Agenten entwerfen").click().run()
    assert not at.exception
    assert tracking.load().lessons == [newer]
    assert any("inzwischen geändert" in error.value for error in at.error)


def test_progress_edit_does_not_move_to_another_task_after_reordering(site):
    tracking.adopt(PROJECT, TEAM, PLAN)
    at = as_member(site)
    at = edit_progress(at, {0: {"Status": "in Arbeit", "Ist (h)": 1, "Notiz": "Aufgabe A"}})
    reordered = PLAN.model_copy(update={"tasks": list(reversed(PLAN.tasks))})
    current = tracking.adopt(PROJECT, TEAM, reordered)

    button(at, "Fortschritt speichern").click().run()
    assert not at.exception
    assert tracking.load() == current
    assert progress_editor(at).iloc[0]["ID"] == "B"
    assert any("inzwischen geändert" in warning.value for warning in at.warning)
    assert not any("Fortschritt gespeichert" in text for text in notices(at))


def test_iteration_confirmation_cannot_archive_a_replacement_project(site, tmp_path, monkeypatch):
    monkeypatch.setattr(workbench, "DATA_DIR", tmp_path)
    lifecycle.save(with_charter())
    tracking.adopt(PROJECT, TEAM, PLAN)
    at = site.switch_page("views/abschluss.py").run()
    at.checkbox(key="next_run_sure").check().run()
    assert not button(at, "Neuen Durchlauf beginnen").disabled
    current = tracking.adopt(PROJECT.model_copy(update={"idea": "Neues Vorhaben"}), TEAM, PLAN)

    button(at, "Neuen Durchlauf beginnen").click().run()
    assert not at.exception
    assert tracking.load() == current
    assert not (tmp_path / "archiv").exists()
    assert not at.checkbox(key="next_run_sure").value


def test_the_reports_are_downloads_and_not_shown_again_on_the_page(tracked):
    # A preview repeated the tables above it and doubled the length of the page.
    for page, title in [("durchfuehrung", "Statusbericht"), ("kontrolle", "Kontrollbericht")]:
        at = tracked.switch_page(f"views/{page}.py").run()
        assert not at.exception
        assert not [e for e in at.expander if e.label.startswith("Vorschau")], page
        assert not any(m.value.startswith(f"# {title}") for m in at.markdown), page


def test_the_startseite_shows_the_progress_once(tracked):
    # A bar beside the metric "Fortschritt" said the same number twice.
    at = tracked.switch_page("views/startseite.py").run()
    assert not at.exception
    assert any(m.label == "Fortschritt" for m in at.metric)
    assert not at.get("progress")


def test_without_a_project_idea_no_page_offers_the_claude_draft(site):
    # Its button is off without the idea: the page says once, at the top, what is missing.
    for page in ("anforderungen", "entwurf", "testplan"):
        at = site.switch_page(f"views/{page}.py").run()
        assert not at.exception
        infos = [i.value for i in at.info]
        assert any("Noch keine Projektidee" in i for i in infos), page
        assert not any("vom Agenten entwerfen" in i for i in infos), page


def test_with_an_adopted_project_the_planung_does_not_call_the_plan_open(tracked):
    # The path ticks "Planung" for it: "Plan offen" beside the tick said the opposite.
    at = tracked.switch_page("views/planung.py").run()
    assert not at.exception
    assert "Plan offen" not in chips(at)
    assert "✓ Plan übernommen<" in chips(at)


def in_order(node, out=None):
    """The texts of headers and Markdown of a page, top to bottom."""
    out = [] if out is None else out
    for child in getattr(node, "children", {}).values():
        if getattr(child, "type", "") in ("header", "markdown"):
            out.append(child.value)
        in_order(child, out)
    return out


def test_what_is_next_sits_right_below_the_path_on_every_page(tracked):
    # Above the title on the pages after the plan, below it on the Planung: the title moved.
    for page, title in [("planung", "Planung"), ("durchfuehrung", "Durchführung")]:
        texts = in_order(tracked.switch_page(f"views/{page}.py").run().main)
        line = next(i for i, t in enumerate(texts) if "Jetzt dran" in t)
        assert line < texts.index(title), page


def test_the_iteration_points_to_the_abschluss_instead_of_repeating_it(site, monkeypatch, tmp_path):
    # The list of open requirements stood on the Abschluss and again here, below a green
    # "Nichts offen" that meant only the backlog.
    monkeypatch.setattr(workbench, "DATA_DIR", tmp_path)
    tracking.adopt(PROJECT, TEAM, PLAN, requirements=NEEDS.items)
    lifecycle.save(lifecycle.Lifecycle(project=PROJECT))
    at = site.switch_page("views/abschluss.py").run()
    assert not at.exception
    errors = [e.value for e in at.error]
    (pointer,) = [e for e in errors if e.startswith("Der Abschluss ist nicht fertig")]
    assert "R1" not in pointer and "Reiter" in pointer
    assert said_once(at, "Muss-Anforderung 'R1'")  # once: the verdict says it in full
    assert not any("Nichts offen" in i.value for i in at.info)


@pytest.mark.parametrize("where", ["kontrolle", "durchfuehrung"])
def test_the_startseite_says_what_is_next_with_its_reason(tracked, monkeypatch, where):
    # Without the forecast box (project lead, 25.11.2026) only this line says what the
    # forecast means, "Deadline verpasst" included: for every page it points to.
    monkeypatch.setattr(tracking, "next_step", lambda *_, **__: ("Grund. Rat.", where))
    at = tracked.run()
    assert not at.exception
    assert "**Als Nächstes:** Grund. Rat." in [m.value for m in at.markdown]


def overdue_table(at):
    (table,) = [d.value for d in at.dataframe if "Hält auf" in d.value.columns]
    return table.to_dict("records")


def test_the_kontrolle_names_each_late_task_once(tracked):
    # A yellow box listed the late tasks, and the forecast listed most of them again as
    # "Verspätet und halten andere auf" (project lead, 25.11.2026). One table says both.
    at = tracked.switch_page("views/kontrolle.py").run()
    assert not at.exception
    assert overdue_table(at) == [
        {
            "ID": "A",
            "Aufgabe": "Datenmodell",
            "Person": "Anna",
            "Geplant bis": "09.11.2026",
            "Status": "offen",
            "Hält auf": "B",
        },
        {
            "ID": "B",
            "Aufgabe": "API",
            "Person": "Anna",
            "Geplant bis": "11.11.2026",
            "Status": "offen",
            "Hält auf": "",
        },
    ]
    assert not at.warning and not at.info and not at.success
    assert not any("halten andere auf" in m.value for m in at.markdown)
    # Nothing recorded yet: said once, quietly, where the progress is.
    assert any("Noch kein Fortschritt erfasst" in c.value for c in at.caption)


KONTROLLE_TABS = ["Stand", "Prognose", "Plan und Ist", "Kennzahlen", "Demos", "Agent und Bericht"]


def test_the_kontrolle_opens_the_tab_its_verdict_is_about(tracked, monkeypatch):
    # Thirteen panels stood below each other (project lead, 25.11.2026). Now six tabs, and
    # arriving opens the one that explains the verdict line.
    real, late = tracking.forecast, {"deadline_gap": 3, "shift": 2}
    monkeypatch.setattr(tracking, "forecast", lambda t, d: dataclasses.replace(real(t, d), **late))
    at = tracked.switch_page("views/kontrolle.py").run()
    assert not at.exception
    assert [t.label for t in at.tabs] == KONTROLLE_TABS
    assert at.session_state["kontrolle_tab"] == "Prognose"

    late.update(deadline_gap=-5, shift=-1)  # in time: the state is what to look at
    at = at.switch_page("views/durchfuehrung.py").run().switch_page("views/kontrolle.py").run()
    assert at.session_state["kontrolle_tab"] == "Stand"


def test_the_kontrolle_keeps_the_chosen_tab_after_a_save(site):
    tracking.adopt(PROJECT, TEAM, DEMO_PLAN)
    at = site.switch_page("views/kontrolle.py").run()
    at.session_state["kontrolle_tab"] = "Demos"  # what a click on the tab sets
    at.text_input(key="retro_measure_1").input("Früher testen").run()
    button(at, "Rückblick speichern").click()
    at = at.run()
    assert not at.exception
    assert tracking.load().retros[0].measure == "Früher testen"
    assert at.session_state["kontrolle_tab"] == "Demos"

    at.checkbox(key=f"measure_done_{tracking.load().retros[0].monday:%Y%m%d}").check().run()
    assert at.session_state["kontrolle_tab"] == "Demos"


def test_the_forecast_lists_only_late_tasks_that_hold_others(tracked):
    # A late task holding nothing was the box "Im Verzug" once more, as "hält auf: keine
    # weitere Aufgabe".
    at = tracked.switch_page("views/kontrolle.py").run()
    assert not at.exception
    assert not any("keine weitere Aufgabe" in m.value for m in at.markdown)


def test_betrieb_and_the_next_run_are_parts_of_the_abschluss(tracked):
    # Two pages of their own: one optional, one a table and a button. The path had eleven
    # steps for it and the menu seven entries under "Agenten".
    from pm_agent.ui import JOURNEY, PAGES

    assert [slug for slug, _, _ in JOURNEY][-1] == "abschluss" and len(JOURNEY) == 9
    assert "betrieb" not in PAGES and "iteration" not in PAGES
    at = tracked.switch_page("views/abschluss.py").run()
    assert not at.exception
    assert [t.label for t in at.tabs] == ["Abnahme und Lehren", "Betrieb", "Nächster Durchlauf"]
    for label in ["Lessons Learned speichern", "Neuen Durchlauf beginnen"]:
        button(at, label)  # raises if the part is missing
    assert any("kein Betriebshandbuch" in i.value for i in at.info)  # no design in this project


def test_the_step_that_adopts_the_plan_says_so_in_its_tab(app, monkeypatch):
    # The button "Plan als Projekt übernehmen" sat in a tab named "6 · Export": a tester
    # looked for it in "4 · Ergebnis" and did not find it.
    monkeypatch.setattr(agent, "run_planning", planned)
    at = fill_project(app.run())
    button(at, "Plan mit dem Agenten erstellen").click()
    at = at.run()
    (tab,) = [t for t in at.tabs if any(b.label == "Plan als Projekt übernehmen" for b in t.button)]
    assert "Übernehmen" in tab.label


FUTURE = PROJECT.model_copy(update={"start_date": date(2099, 1, 5), "deadline": date(2099, 12, 31)})


def test_the_startseite_says_when_finished_work_took_more_hours(site):
    # Its verdict box said so; without it (project lead, 25.11.2026) a quiet line does,
    # else the page would read "im Plan" alone.
    adopted = tracking.adopt(FUTURE, TEAM, PLAN)
    tracking.save(tracking.apply_rows(adopted, [{"ID": "A", "Status": "fertig", "Ist (h)": 10}]))
    at = site.run()
    assert not at.exception and verdict(at) == ""
    over = "Fertige Aufgaben brauchten 25 % mehr Stunden als geplant (+2 h)."
    assert over in [c.value for c in at.caption]

    tracking.save(tracking.apply_rows(adopted, [{"ID": "A", "Status": "fertig", "Ist (h)": 8}]))
    assert not any("mehr Stunden" in c.value for c in at.run().caption)


@pytest.mark.parametrize("page", ["kontrolle", "durchfuehrung"])
def test_the_verdict_says_when_finished_work_took_more_hours(site, page):
    # The verdict read "In Ordnung" from the forecast alone while finished work had taken a
    # quarter more hours than planned (CPI 0,50 on the same page).
    adopted = tracking.adopt(FUTURE, TEAM, PLAN)
    tracking.save(tracking.apply_rows(adopted, [{"ID": "A", "Status": "fertig", "Ist (h)": 10}]))
    at = site.switch_page(f"views/{page}.py").run()
    assert not at.exception
    shown = verdict(at)
    assert 'class="verdict warn"' in shown, shown
    assert "25 % mehr Stunden als geplant (+2 h)" in shown

    # Within the tolerance the forecast alone decides.
    tracking.save(tracking.apply_rows(adopted, [{"ID": "A", "Status": "fertig", "Ist (h)": 8}]))
    shown = verdict(at.run())
    assert 'class="verdict ok"' in shown and "mehr Stunden" not in shown


def test_the_closing_verdict_names_an_unfinished_handbook(site):
    # "Das Projekt lässt sich abschließen" stood in green above a Betrieb tab with four
    # errors in the handbook.
    from test_lifecycle import design

    from pm_agent import closing

    lifecycle.save(lifecycle.Lifecycle(project=PROJECT, design=design()))
    adopted = tracking.adopt(PROJECT, TEAM, PLAN, requirements=NEEDS.items)
    tracking.save(
        closing.record_signoff(
            adopted, tracking.Signoff(requirement_id="R1", decision="abgenommen")
        )
    )
    at = site.switch_page("views/abschluss.py").run()
    assert not at.exception
    shown = verdict(at)
    # One warning of the sign-off (no test case) and four of the handbook.
    assert 'class="verdict warn"' in shown and "5 Warnungen" in shown, shown
    # The handbook does not block the next run; only closing errors do.
    at.checkbox(key="next_run_sure").check().run()
    assert not button(at, "Neuen Durchlauf beginnen").disabled


def test_the_handbook_warnings_stay_out_of_the_signoff_list(site):
    # PR 82 put the handbook into the verdict by adding it to `warnings`, which the sign-off
    # panel lists too: every "Betrieb: …" line showed twice, once beside the sign-off.
    from test_lifecycle import design

    lifecycle.save(lifecycle.Lifecycle(project=PROJECT, design=design()))
    tracking.adopt(PROJECT, TEAM, PLAN, requirements=NEEDS.items)
    at = site.switch_page("views/abschluss.py").run()
    assert not at.exception
    assert not [w.value for w in at.warning if "Betrieb:" in w.value]


def test_saving_an_edited_table_does_not_warn_that_the_saved_state_changed(site):
    from test_lifecycle import design
    from test_testplan import cases

    from pm_agent.models import Lesson

    lifecycle.save(
        lifecycle.Lifecycle(
            project=PROJECT, charter=CHARTER, requirements=NEEDS, design=design(), cases=cases()
        )
    )
    adopted = tracking.adopt(PROJECT, TEAM, PLAN, requirements=NEEDS.items)
    tracking.save(
        adopted.model_copy(
            update={"lessons": [Lesson(observation="Spät getestet", advice="Früh testen")]}
        )
    )

    for page, editor, change_row, save_label in [
        (
            "anforderungen",
            "requirements_editor_",
            {0: {"Titel": "Raum online buchen"}},
            "Änderungen speichern und prüfen",
        ),
        (
            "entwurf",
            "design_components_",
            {0: {"Name": "Buchungs-Web"}},
            "Änderungen speichern und prüfen",
        ),
        (
            "testplan",
            "cases_editor_",
            {0: {"Erwartet": "Buchung erscheint"}},
            "Änderungen speichern und prüfen",
        ),
        (
            "abschluss",
            "lessons_editor_",
            {0: {"Empfehlung": "Ab Tag 1 testen"}},
            "Lessons Learned speichern",
        ),
    ]:
        at = site.switch_page(f"views/{page}.py").run()
        at = edit_table(at, editor, change_row)
        button(at, save_label).click()
        at = at.run()
        assert not at.exception, page
        assert not [w.value for w in at.warning if "inzwischen geändert" in w.value], page


def notices(at) -> list[str]:
    """The short notices of this run (ui.notify), as the toasts show them."""
    return [toast.value for toast in at.toast]


def test_saving_and_approving_answer_and_an_approved_phase_offers_no_approval(site):
    # A save reran the page without a word, and "freigeben" stayed on the page, greyed out,
    # under the green box that said it was approved.
    lifecycle.save(lifecycle.Lifecycle(project=PROJECT, charter=CHARTER))
    at = site.switch_page("views/auftrag.py").run()
    at.text_area(key="charter_goal").input("Räume online buchen")
    at = at.run()
    button(at, "Änderungen speichern und prüfen").click()
    at = at.run()
    assert notices(at) == ["Projektauftrag gespeichert."]
    button(at, "Projektauftrag freigeben").click()
    at = at.run()
    assert notices(at) == ["Projektauftrag freigegeben."]
    assert "Projektauftrag freigeben" not in [b.label for b in at.button]
    assert notices(at.run()) == []  # shown once


def test_every_entry_of_the_test_page_answers(tracked):
    from test_lifecycle import design
    from test_testplan import cases

    lifecycle.save(
        lifecycle.Lifecycle(project=PROJECT, requirements=NEEDS, design=design(), cases=cases())
    )
    at = tracked.switch_page("views/testlauf.py").run()
    at.selectbox(key="test_case").set_value("T2").run()
    at.radio(key="test_result").set_value("fehlgeschlagen").run()
    button(at, "Ergebnis speichern").click()
    at = at.run()
    assert notices(at) == ["Ergebnis gespeichert: T2 fehlgeschlagen."]
    at.text_input(key="defect_cause").input("Schema fehlt").run()
    at.selectbox(key="defect_task").set_value("B").run()
    button(at, "Fehler erfassen").click()
    at = at.run()
    assert notices(at) == ["Fehler F1 erfasst."]
    button(at, "F1: Aufgabe B wieder öffnen").click()
    assert notices(at.run()) == ["Aufgabe B ist wieder in Arbeit."]
    button(at, "F1: behoben").click()
    assert notices(at.run()) == ["Fehler F1 ist behoben."]
    button(at, "F1: wieder öffnen").click()
    assert notices(at.run()) == ["Fehler F1 ist wieder offen."]


def test_progress_team_retro_and_signoff_answer_the_same_way(site):
    tracking.adopt(PROJECT, TEAM, DEMO_PLAN, requirements=NEEDS.items)
    at = as_member(site)
    button(at, "Fortschritt speichern").click()
    at = at.run()
    assert notices(at) == ["Fortschritt gespeichert (lokal in data/projekt.json)."]
    assert not at.success  # the box above the table pushed it down

    at = as_lead(at).switch_page("views/kontrolle.py").run()
    at.selectbox(key="retro_week").set_value(2).run()
    at.radio(key="retro_shown_2").set_value("nein").run()
    at.text_input(key="retro_measure_2").input("Schema zuerst klären").run()
    button(at, "Rückblick speichern").click()
    assert notices(at.run()) == ["Rückblick für Woche 2 gespeichert."]

    at = at.switch_page("views/abschluss.py").run()
    at.radio(key="signoff_decision").set_value("zurückgestellt").run()
    at.text_input(key="signoff_reason").input("keine Zeit").run()
    button(at, "Entscheidung speichern").click()
    assert notices(at.run()) == ["Entscheidung für R1 gespeichert: zurückgestellt."]

    at = as_member(at)
    button(at, "Speichern").click()
    assert notices(at.run()) == ["Deine Angaben sind gespeichert (lokal in data/team.json)."]


def test_a_measure_ticked_as_done_can_be_opened_again(site):
    # Ticking a measure saved it as done and took it off the page: a slip could not be undone.
    tracking.adopt(PROJECT, TEAM, DEMO_PLAN)
    at = site.switch_page("views/kontrolle.py").run()
    at.selectbox(key="retro_week").set_value(2).run()
    at.radio(key="retro_shown_2").set_value("nein").run()
    at.text_input(key="retro_measure_2").input("Schema zuerst klären").run()
    button(at, "Rückblick speichern").click()
    at = at.run()
    at = at.checkbox(key="measure_done_20261116").check().run()
    assert tracking.load().retros[0].measure_done is True
    assert notices(at) == ["Maßnahme erledigt: Schema zuerst klären."]
    assert at.checkbox(key="measure_done_20261116").value is True  # still there, ticked
    at = at.checkbox(key="measure_done_20261116").uncheck().run()
    assert tracking.load().retros[0].measure_done is False
    assert notices(at) == ["Maßnahme wieder offen: Schema zuerst klären."]


def test_a_notice_shows_what_was_typed_as_written(site):
    # A measure written as a Markdown link became a link in the notice (review of PR 99).
    tracking.adopt(PROJECT, TEAM, DEMO_PLAN)
    at = site.switch_page("views/kontrolle.py").run()
    at.selectbox(key="retro_week").set_value(2).run()
    at.radio(key="retro_shown_2").set_value("nein").run()
    at.text_input(key="retro_measure_2").input("[Plan](https://x.test) *jetzt*").run()
    button(at, "Rückblick speichern").click()
    at = at.run()
    at = at.checkbox(key="measure_done_20261116").check().run()
    assert notices(at) == [ui.as_text("Maßnahme erledigt: [Plan](https://x.test) *jetzt*.")]


def labels(at) -> list[str]:
    return [b.label for b in at.button]


def test_the_planung_takes_idea_and_dates_from_the_auftrag_by_itself(site):
    # Step 2 stood empty although the Projektauftrag held idea, start and deadline; a button
    # had to copy them over.
    lifecycle.save(lifecycle.Lifecycle(project=PROJECT))
    at = site.switch_page(PLANUNG).run()
    assert at.text_area(key="idea").value == PROJECT.idea
    assert at.date_input(key="start").value == PROJECT.start_date
    assert at.date_input(key="deadline").value == PROJECT.deadline
    assert "Eckdaten aus dem Projektauftrag übernehmen" not in labels(at)
    # Changed here, the button offers the Auftrag again; nothing is overwritten by itself.
    at = at.text_area(key="idea").input("Nur die Raumliste").run()
    assert at.text_area(key="idea").value == "Nur die Raumliste"
    assert "Eckdaten aus dem Projektauftrag übernehmen" in labels(at)


def test_the_planung_of_an_adopted_project_leads_on_instead_of_asking_for_consent(tracked):
    at = tracked.switch_page(PLANUNG).run()
    (line,) = [m.value for m in at.markdown if "Jetzt dran" in m.value]
    assert "als Projekt übernommen" in line and "Zustimmung" not in line
    # Where the Startseite leads too (review of PR 2): a late project goes to the Kontrolle.
    advice, where = tracking.next_step(tracking.load(), date.today())
    assert ui.as_text(advice) in line
    assert ui.PAGES[where][1] in labels(at)


def test_the_rest_of_the_project_to_plan_again_is_not_taken_as_adopted(tracked):
    # Without progress the rest is the same plan, from today (review of PR 2): the line
    # said "übernommen" and led away from the planning that had just begun.
    at = tracked.switch_page("views/kontrolle.py").run()
    at.session_state["rest_requested"] = True
    at = at.switch_page(PLANUNG).run()
    (line,) = [m.value for m in at.markdown if "Jetzt dran" in m.value]
    assert "übernommen" not in line


def test_the_test_page_moves_on_to_the_next_case_and_the_defect_of_a_failure(tracked):
    from test_lifecycle import design
    from test_testplan import cases

    lifecycle.save(
        lifecycle.Lifecycle(project=PROJECT, requirements=NEEDS, design=design(), cases=cases())
    )
    at = tracked.switch_page("views/testlauf.py").run()
    assert at.selectbox(key="test_case").value == "T1"
    button(at, "Ergebnis speichern").click()
    at = at.run()
    assert at.selectbox(key="test_case").value == "T2"  # the next one without a result
    at.radio(key="test_result").set_value("fehlgeschlagen").run()
    button(at, "Ergebnis speichern").click()
    at = at.run()
    assert at.selectbox(key="test_case").value == "T3"
    # The defect form starts on the case that failed and has no defect yet.
    assert at.selectbox(key="defect_case").value == "T2"
    at = tracked.switch_page("views/startseite.py").run().switch_page("views/testlauf.py").run()
    assert at.selectbox(key="defect_case").value == "T2"
    assert at.selectbox(key="test_case").value == "T3"  # back on the page: the next open one
    # A failure of a case whose defect is still open does not pull the form to it again.
    at.text_input(key="defect_cause").input("Schema fehlt").run()
    at.selectbox(key="defect_task").set_value("B").run()
    button(at, "Fehler erfassen").click()
    at = at.run()
    at.selectbox(key="defect_case").set_value("T1").run()
    at.selectbox(key="test_case").set_value("T2").run()
    at.radio(key="test_result").set_value("fehlgeschlagen").run()
    button(at, "Ergebnis speichern").click()
    at = at.run()
    assert at.selectbox(key="defect_case").value == "T1"


def test_the_next_case_counts_results_of_the_cases_as_they_are_when_saving(tracked):
    # The form moved on with the test plan of the page: a case changed meanwhile kept its old
    # result and was skipped (review of PR 2).
    from test_lifecycle import design
    from test_testplan import cases

    from pm_agent.tracking import CaseResult, record_result, save

    lifecycle.save(
        lifecycle.Lifecycle(project=PROJECT, requirements=NEEDS, design=design(), cases=cases())
    )
    plan = lifecycle.case_plan(lifecycle.load())
    passed = CaseResult(case_id="T2", result="bestanden", on=date.today())
    save(record_result(tracking.load(), passed, plan))
    at = tracked.switch_page("views/testlauf.py").run()
    assert at.selectbox(key="test_case").value == "T1"
    changed = cases().model_copy(deep=True)
    changed.cases[1].expected = "Eine andere Antwort"
    lifecycle.save(lifecycle.load().model_copy(update={"cases": changed}))
    button(at, "Ergebnis speichern").click()
    at = at.run()
    assert at.selectbox(key="test_case").value == "T2"


def test_the_closing_page_presets_what_python_proposes_and_moves_on(site):
    from test_lifecycle import design
    from test_testplan import cases

    from pm_agent.tracking import CaseResult, record_result, save

    two = NEEDS.model_copy(
        update={"items": [*NEEDS.items, NEEDS.items[0].model_copy(update={"id": "R2"})]}
    )
    lifecycle.save(
        lifecycle.Lifecycle(project=PROJECT, requirements=two, design=design(), cases=cases())
    )
    adopted = tracking.adopt(PROJECT, TEAM, PLAN, requirements=two.items)
    plan = lifecycle.case_plan(lifecycle.load())
    for case in ["T1", "T2", "T3"]:
        result = CaseResult(case_id=case, result="bestanden", on=date.today())
        adopted = record_result(adopted, result, plan)
    save(adopted)
    at = site.switch_page("views/abschluss.py").run()
    # R1 is "abnehmbar": accepting it is preset. R2 has no case: the lead chooses.
    assert at.selectbox(key="signoff_req").value == "R1"
    assert at.radio(key="signoff_decision").value == "abgenommen"
    button(at, "Entscheidung speichern").click()
    at = at.run()
    assert at.selectbox(key="signoff_req").value == "R2"
    assert at.radio(key="signoff_decision").value is None
    button(at, "Entscheidung speichern").click()
    at = at.run()
    assert any("abgenommen" in e.value and "zurückgestellt" in e.value for e in at.error)
    assert [s.requirement_id for s in tracking.load().signoffs] == ["R1"]


def test_a_preset_acceptance_goes_when_the_evidence_changes(site):
    # The radio kept "abgenommen" after the case of an "abnehmbar" requirement failed
    # (review of PR 2): one click accepted what Python no longer proposes.
    from test_lifecycle import design
    from test_testplan import cases

    from pm_agent.tracking import CaseResult, record_result, save

    lifecycle.save(
        lifecycle.Lifecycle(project=PROJECT, requirements=NEEDS, design=design(), cases=cases())
    )
    adopted = tracking.adopt(PROJECT, TEAM, PLAN, requirements=NEEDS.items)
    plan = lifecycle.case_plan(lifecycle.load())
    for case in ["T1", "T2", "T3"]:
        adopted = record_result(
            adopted, CaseResult(case_id=case, result="bestanden", on=date.today()), plan
        )
    save(adopted)
    at = site.switch_page("views/abschluss.py").run()
    assert at.radio(key="signoff_decision").value == "abgenommen"
    failed = CaseResult(case_id="T1", result="fehlgeschlagen", on=date.today())
    save(record_result(tracking.load(), failed, plan))
    at = at.run()
    assert at.radio(key="signoff_decision").value is None


def test_the_startseite_has_one_primary_button(tracked):
    at = tracked.switch_page("views/startseite.py").run()
    primary = [b.label for b in at.button if b.proto.type == "primary"]
    assert primary == ["Stand prüfen"]


def test_efficiency_comparison_works_on_all_four_core_pages_and_keeps_draft_across_pages(tracked):
    from test_comparison import sample_answers

    # Partial draft on Planung survives switching to Kontrolle and back.
    at = tracked.switch_page(PLANUNG).run()
    assert not at.exception and not at.error
    for q in comparison.questions_for("planung"):
        assert at.radio(key=f"cmp_planung_{q.id}").value is None
    at.radio(key="cmp_planung_mode").set_value(comparison.COMMON_QUESTIONS[0].options[0])
    at.text_input(key="cmp_planung_note").input("Zwischenstand")
    at = at.run()
    at = at.switch_page("views/kontrolle.py").run()
    at = at.switch_page(PLANUNG).run()
    assert at.radio(key="cmp_planung_mode").value == comparison.COMMON_QUESTIONS[0].options[0]
    assert at.text_input(key="cmp_planung_note").value == "Zwischenstand"

    for phase, page, manual in [
        ("planung", PLANUNG, False),
        ("durchfuehrung", "views/durchfuehrung.py", False),
        ("kontrolle", "views/kontrolle.py", True),
        ("abschluss", "views/abschluss.py", False),
    ]:
        at = at.switch_page(page).run()
        assert not at.exception and not at.error
        for qid, val in sample_answers(phase, manual=manual).items():
            at.radio(key=f"cmp_{phase}_{qid}").set_value(val)
        at.text_input(key=f"cmp_{phase}_note").input(f"=Notiz {phase}")
        at.button(key=f"cmp_{phase}_submit").click().run()
        assert not at.exception and not at.error
        assert any("Bewertung gespeichert" in s.value for s in at.success)

    saved = comparison.read_comparisons()
    assert [row["phase"] for row in saved] == ["planung", "durchfuehrung", "kontrolle", "abschluss"]


def test_kontrolle_shows_efficiency_summary_download_and_empty_or_damaged_states(
    tracked, downloads, monkeypatch, tmp_path
):
    from test_comparison import make_entry

    # Missing logs folder -> clean empty state without error.
    monkeypatch.setattr(
        comparison, "COMPARISON_CSV", tmp_path / "noch-nicht-da" / "agent_vergleich.csv"
    )
    at = tracked.switch_page("views/kontrolle.py").run()
    assert not at.exception and not at.error
    assert "Noch keine Effizienz-Bewertungen erfasst." in [c.value for c in at.caption]

    # Normal state -> summary table and German Excel CSV download with formula protection.
    csv_path = tmp_path / "agent_vergleich.csv"
    monkeypatch.setattr(comparison, "COMPARISON_CSV", csv_path)
    comparison.record_comparison(
        make_entry("planung", note="=SUMME(A1)", agent_seconds=11.5, agent_rounds=2)
    )
    comparison.record_comparison(make_entry("kontrolle", manual=True))
    at = tracked.switch_page("views/kontrolle.py").run()
    assert not at.exception and not at.error
    assert any("Phase" in frame.value.columns for frame in at.dataframe)
    exported = downloads["Effizienzvergleich als CSV herunterladen"]
    assert exported.startswith("\ufeff") and ";11,5;" in exported and "'=SUMME(A1)" in exported

    # Damaged CSV + put-aside file -> explicit error, no broken table, archive named.
    csv_path.write_bytes(b"phase,notiz\r\nplanung,a,b\r\n")
    (tmp_path / "agent_vergleich-bis-20261127-120000.csv").write_bytes(b"alt\r\n1\r\n")
    at = at.run()
    assert not at.exception
    (message,) = [
        e.value for e in at.error if "agent_vergleich.csv konnte nicht gelesen werden" in e.value
    ]
    assert "die nächste Bewertung legt sie beiseite" in message
    assert not any("Phase" in frame.value.columns for frame in at.dataframe)
    assert any(ui.as_text("agent_vergleich-bis-20261127-120000.csv") in c.value for c in at.caption)

    # Unopenable directory -> error without promising put-aside.
    csv_path.unlink()
    csv_path.mkdir()
    at = at.run()
    (message,) = [
        e.value for e in at.error if "agent_vergleich.csv konnte nicht gelesen werden" in e.value
    ]
    assert "legt sie beiseite" not in message


def _real_team(monkeypatch, members=TEAM, *, adopt_plan=None, project=PROJECT):
    monkeypatch.setattr(workbench, "load_team", REAL_LOAD_TEAM)
    workbench.save_team(members)
    if adopt_plan is not None:
        tracking.adopt(project, members, adopt_plan)


def _two_member_setup(monkeypatch):
    ben = workbench.Member(name="Ben", skills={"Python": 4}, hours_per_week=40)
    data = plan_input()
    data["assignments"][1]["member"] = "Ben"
    _real_team(monkeypatch, [*TEAM, ben], adopt_plan=Plan.model_validate(data))


def test_switching_member_in_mein_bereich_does_not_leak_unsaved_edits(site, monkeypatch):
    _two_member_setup(monkeypatch)
    at = edit_progress(as_member(site, "Anna"), {0: {"Status": "in Arbeit", "Notiz": "Annas"}})
    # Switching to Ben must not leak Anna's unsaved edits onto Ben's row.
    at.selectbox(key="me").set_value("Ben").run()
    assert not at.exception
    assert (progress_editor(at).iloc[0]["ID"], progress_editor(at).iloc[0]["Notiz"]) == ("B", "")

    button(at, "Fortschritt speichern").click()
    at = at.run()
    saved = tracking.load().progress
    assert (saved["A"].note, saved["B"].note) == ("", "")

    # Returning to Anna still restores her own unsaved draft.
    at.selectbox(key="me").set_value("Anna").run()
    assert progress_editor(at).iloc[0]["Notiz"] == "Annas"


def test_team_view_asks_for_a_name_instead_of_picking_the_first_member(site):
    at = site.radio(key="role").set_value("Team").run()
    assert not at.exception
    assert at.selectbox(key="me").value is None
    assert at.selectbox(key="me").proto.placeholder == "Name wählen"
    assert at.header[0].value == "Mein Bereich"
    assert any("Wähle links unter „Ich bin“ deinen Namen." in i.value for i in at.info)
    assert not [b for b in at.button if b.label == "Speichern"]


def test_planung_reloads_team_file_on_each_run_while_keeping_overrides(site, monkeypatch, tmp_path):
    _real_team(monkeypatch, [TEAM[0].model_copy(update={"hours_per_week": 20})])
    at = site.switch_page(PLANUNG).run()
    assert list(at.session_state["team_df"]["Stunden/Woche"]) == [20]

    # Another browser session updates team.json: Planung picks it up on the next run.
    ben = workbench.Member(name="Ben", skills={"SQL": 3}, hours_per_week=15)
    workbench.save_team([TEAM[0].model_copy(update={"hours_per_week": 30}), ben])
    at = at.run()
    assert list(at.session_state["team_df"]["Name"]) == ["Anna", "Ben"]
    assert list(at.session_state["team_df"]["Stunden/Woche"]) == [30, 15]

    # Opening a logged run keeps its own team until the lead loads the live team again.
    clara = workbench.Member(name="Clara", skills={"Python": 3}, hours_per_week=12)
    log = tmp_path / "run-20261109-120000.json"
    record = {
        "project": PROJECT.model_dump(mode="json"),
        "team": [clara.model_dump(mode="json")],
        "plan": plan_input(member="Clara"),
        "rounds": [],
    }
    log.write_text(json.dumps(record), encoding="utf-8")
    monkeypatch.setattr(workbench, "saved_runs", lambda: [log])
    at = at.run()
    button(at, "Lauf öffnen").click()
    at = at.run()
    assert list(at.session_state["team_df"]["Name"]) == ["Clara"]
    assert list(at.run().session_state["team_df"]["Name"]) == ["Clara"]

    button(at, "Aktuelles Team laden").click()
    assert list(at.run().session_state["team_df"]["Name"]) == ["Anna", "Ben"]


def test_absences_saved_on_mein_bereich_reach_forecast_and_rest_replanning(site, monkeypatch):
    _real_team(monkeypatch, adopt_plan=PLAN, project=FUTURE)
    at = as_member(site, "Anna")
    next(t for t in at.text_input if t.label == "Abwesend").input("06.01.2099–07.01.2099")
    button(at, "Speichern").click()
    at = at.run()
    assert not at.exception and not at.error

    at = as_lead(at).switch_page("views/kontrolle.py").run()
    assert {m.label: m.value for m in at.metric}["Voraussichtliches Ende"] == "09.01.2099"
    button(at, "Rest mit dem Agenten umplanen").click()
    at.run()
    at = at.switch_page(PLANUNG).run()
    assert not at.exception and not at.error
    assert list(at.session_state["team_df"]["Abwesend"]) == ["06.01.2099–07.01.2099"]
    assert {m.label: m.value for m in at.metric}["Planende"] == "09.01.2099"


def test_unsaved_progress_survives_switching_ansicht_and_other_members_saves(site, monkeypatch):
    _two_member_setup(monkeypatch)
    at = edit_progress(as_member(site, "Anna"), {0: {"Status": "in Arbeit", "Notiz": "Annas"}})
    # Switching Ansicht (Startseite <-> Mein Bereich both have url_path == "") keeps the draft.
    at = as_lead(at).radio(key="role").set_value("Team").run()
    assert not at.exception and at.selectbox(key="me").value == "Anna"
    assert progress_editor(at).iloc[0]["Notiz"] == "Annas"

    # Ben saves his own task meanwhile: Anna's draft is neither dropped nor blocked.
    ben_done = [{"ID": "B", "Status": "fertig", "Ist (h)": 16, "Notiz": "Bens"}]
    tracking.save(tracking.apply_rows(tracking.load(), ben_done))
    button(at, "Fortschritt speichern").click()
    at = at.run()
    assert not at.exception and not at.error
    assert not [w.value for w in at.warning if "inzwischen geändert" in w.value]
    stored = tracking.load().progress
    assert (stored["A"].status, stored["A"].note) == ("in Arbeit", "Annas")
    assert (stored["B"].status, stored["B"].note) == ("fertig", "Bens")


def test_a_member_can_leave_the_team_and_their_open_tasks_stay_updatable(site, monkeypatch):
    _two_member_setup(monkeypatch)
    at = as_member(site, "Ben")
    assert button(at, "Team verlassen").disabled
    at.checkbox(key="leave_team_sure_Ben").check().run()
    assert not button(at, "Team verlassen").disabled
    button(at, "Team verlassen").click()
    at = at.run()
    assert not at.exception and not at.error
    assert [m.name for m in REAL_LOAD_TEAM()] == ["Anna"]
    assert at.selectbox(key="me").value is None and notices(at) == ["Ben hat das Team verlassen."]

    # Ben still owns task B in the adopted plan: selectable to finish/update that task.
    at.selectbox(key="me").set_value("Ben").run()
    assert not at.exception and not at.error
    assert any("nicht mehr im Team" in i.value for i in at.info)
    assert not [b for b in at.button if b.label == "Speichern"]
    at = edit_progress(at, {0: {"Status": "fertig", "Ist (h)": 14, "Notiz": "übergeben"}})
    button(at, "Fortschritt speichern").click()
    at = at.run()
    assert not at.exception and not at.error
    saved = tracking.load().progress["B"]
    assert (saved.status, saved.note) == ("fertig", "übergeben")


def test_team_view_and_member_survive_a_fresh_session_with_query_params(site, monkeypatch):
    _real_team(monkeypatch)
    at = as_member(site, "Anna")
    assert (at.query_params.get("ansicht"), at.query_params.get("ich")) == ("Team", "Anna")

    # Simulate F5: a brand-new session starts with the URL's query parameters.
    fresh = AppTest.from_file(str(SITE), default_timeout=30)
    fresh.query_params["ansicht"], fresh.query_params["ich"] = "Team", "Anna"
    fresh.run()
    assert not fresh.exception
    assert (fresh.radio(key="role").value, fresh.selectbox(key="me").value) == ("Team", "Anna")
    assert fresh.header[0].value == "Mein Bereich · Anna"

    fresh = as_lead(fresh)
    assert "ansicht" not in fresh.query_params and "ich" not in fresh.query_params

    # Unknown member in URL does not crash and asks to pick a name.
    stale = AppTest.from_file(str(SITE), default_timeout=30)
    stale.query_params["ansicht"], stale.query_params["ich"] = "Team", "Unbekannt"
    stale.run()
    assert not stale.exception and stale.radio(key="role").value == "Team"
    assert stale.selectbox(key="me").value is None


def test_mein_bereich_accepts_decimal_hours_and_omits_row_number_in_errors(site, monkeypatch):
    _real_team(monkeypatch)
    at = as_member(site, "Anna")
    next(t for t in at.text_input if t.label == "Fähigkeiten mit Stufe 1–5").input("Python super")
    button(at, "Speichern").click()
    at = at.run()
    assert any("Python super" in e.value for e in at.error)
    assert not any("Zeile 1" in e.value for e in at.error)

    next(t for t in at.text_input if t.label == "Fähigkeiten mit Stufe 1–5").input("Python 4")
    hours_input = next(n for n in at.number_input if n.label == "Stunden pro Woche")
    assert hours_input.proto.step == 0.5
    hours_input.set_value(12.5)
    button(at, "Speichern").click()
    at = at.run()
    assert not at.exception and not at.error
    assert [m.hours_per_week for m in REAL_LOAD_TEAM()] == [12.5]


def test_mein_bereich_disables_save_button_on_conflict(site):
    tracking.adopt(PROJECT, TEAM, PLAN)
    at = edit_progress(as_member(site, "Anna"), {0: {"Notiz": "Entwurf"}})
    tracking.save(tracking.apply_rows(tracking.load(), [{"ID": "A", "Notiz": "anderer Tab"}]))
    at = at.run()
    assert not at.exception
    assert any("inzwischen geändert" in w.value for w in at.warning)
    assert button(at, "Fortschritt speichern").disabled
