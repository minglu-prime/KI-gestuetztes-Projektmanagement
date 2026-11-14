import csv
import io
import json
from datetime import date

import pytest
from test_tools import PROJECT, TEAM, plan_input

from pm_agent.models import Member, Plan
from pm_agent.planning import check_plan
from pm_agent.workbench import (
    InputError,
    append_run,
    explain_task,
    gantt,
    load_run,
    load_team,
    plan_rows,
    round_summary,
    rows_to_plan,
    rows_to_team,
    save_team,
    saved_runs,
    team_rows,
    to_csv,
    to_markdown,
)

PLAN = Plan.model_validate(plan_input())


def test_team_table_round_trip_and_skill_formats():
    rows = [
        {"Name": "Anna", "Skills": "Python 4, SQL:3", "Stunden/Woche": 20, "Notiz": None},
        {"Name": None, "Skills": None, "Stunden/Woche": None, "Notiz": None},  # empty editor row
    ]
    team = rows_to_team(rows)
    assert team == [Member(name="Anna", skills={"Python": 4, "SQL": 3}, hours_per_week=20)]
    assert rows_to_team(team_rows(team)) == team


def test_unreadable_team_rows_name_the_row_and_the_problem():
    rows = [
        {"Name": "Anna", "Skills": "Python sehr gut", "Stunden/Woche": 20},
        {"Name": "Ben", "Skills": "", "Stunden/Woche": 0},
    ]
    with pytest.raises(InputError) as err:
        rows_to_team(rows)
    message = str(err.value)
    assert "Zeile 1 (Anna): Skill 'Python sehr gut' nicht lesbar" in message
    assert "Zeile 2 (Ben): hours_per_week" in message


def test_plan_table_round_trip_keeps_descriptions_and_risks():
    original = Plan.model_validate(
        {
            **plan_input(),
            "tasks": [{**plan_input()["tasks"][0], "description": "Tabellen"}]
            + plan_input()["tasks"][1:],
        }
    )
    rebuilt = rows_to_plan(plan_rows(original), original, original.risks)
    assert rebuilt == original


def test_an_edit_in_the_table_reaches_the_check():
    rows = plan_rows(PLAN)
    rows[0]["Stunden"] = 400  # far beyond Anna's capacity until the deadline
    edited = rows_to_plan(rows, PLAN, PLAN.risks)
    assert any("überlastet" in w for w in check_plan(edited, TEAM, PROJECT).warnings)


def test_a_row_without_person_stays_unassigned_and_the_check_says_so():
    rows = plan_rows(PLAN)
    rows[1]["Person"] = ""
    result = check_plan(rows_to_plan(rows, PLAN, []), TEAM, PROJECT)
    assert result.errors == ["Task 'B' ist niemandem zugewiesen"]


def test_an_invalid_estimate_is_an_input_error():
    rows = plan_rows(PLAN)
    rows[0]["Stunden"] = -3
    with pytest.raises(InputError, match="Zeile 1 \\(A\\): estimate_hours"):
        rows_to_plan(rows, PLAN, [])


def test_team_file_round_trip_missing_file_and_damaged_file(tmp_path):
    path = tmp_path / "data" / "team.json"
    assert load_team(path) == []
    save_team(TEAM, path)
    assert load_team(path) == TEAM
    path.write_text("{kaputt", encoding="utf-8")
    with pytest.raises(InputError, match="team.json ist beschädigt"):
        load_team(path)


def test_only_runs_with_plan_project_and_team_can_be_reopened(tmp_path):
    record = {
        "outcome": "plan",
        "project": PROJECT.model_dump(mode="json"),
        "team": [m.model_dump(mode="json") for m in TEAM],
        "plan": PLAN.model_dump(mode="json"),
        "rounds": [],
    }
    (tmp_path / "run-20261111-090000.json").write_text(json.dumps(record), encoding="utf-8")
    (tmp_path / "run-20261111-080000.json").write_text(
        json.dumps({**record, "plan": None, "outcome": "error"}), encoding="utf-8"
    )
    (tmp_path / "run-20261110-080000.json").write_text(  # logged before project/team were kept
        json.dumps({"outcome": "plan", "plan": record["plan"]}), encoding="utf-8"
    )

    (path,) = saved_runs(tmp_path)
    project, team, plan, _ = load_run(path)
    assert (project, team, plan) == (PROJECT, TEAM, PLAN)


def test_runs_csv_gets_one_header_and_one_line_per_export(tmp_path):
    path = tmp_path / "logs" / "runs.csv"
    append_run({"quelle": "agent", "runden": 3}, path)
    append_run({"quelle": "protokoll", "runden": 0}, path)
    assert list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8")))) == [
        {"quelle": "agent", "runden": "3"},
        {"quelle": "protokoll", "runden": "0"},
    ]


def test_round_summary_counts_check_messages_and_names_rejections():
    report = check_plan(PLAN, TEAM, PROJECT).model_dump_json(include={"errors", "warnings"})
    checked = {"tool_results": [{"tool": "check_plan", "is_error": False, "content": report}]}
    rejected = {
        "tool_results": [
            {
                "tool": "submit_plan",
                "is_error": True,
                "content": "Plan abgelehnt. Behebe diese Fehler:\n- X",
            }
        ]
    }
    accepted = {
        "tool_results": [{"tool": "submit_plan", "is_error": False, "content": "Plan angenommen."}]
    }

    assert round_summary(1, checked) == (
        "Runde 1 · check_plan: 0 Fehler, 1 Warnungen",
        ["Task 'A' braucht 'SQL', Anna hat diese Fähigkeit nicht angegeben"],
    )
    assert round_summary(2, rejected) == (
        "Runde 2 · submit_plan: abgelehnt",
        ["Plan abgelehnt. Behebe diese Fehler:\n- X"],
    )
    assert round_summary(3, accepted) == ("Runde 3 · submit_plan: Plan angenommen.", [])
    assert round_summary(4, {"text": "", "stop_reason": "end_turn"})[0] == (
        "Runde 4 · beendet (end_turn)"
    )


def test_export_contains_dates_reasons_and_warnings():
    result = check_plan(PLAN, TEAM, PROJECT)
    markdown = to_markdown(PROJECT, PLAN, result)
    assert (
        "| A | Datenmodell | Anna | 8 | 09.11.2026 | 09.11.2026 | kennt die Raumdaten |" in markdown
    )
    assert "**Kritischer Pfad:** A → B" in markdown
    assert "- Task 'A' braucht 'SQL', Anna hat diese Fähigkeit nicht angegeben" in markdown
    assert "- Die Hochschule liefert die Raumdaten zu spät" in markdown

    rows = list(csv.reader(io.StringIO(to_csv(PLAN, result)), delimiter=";"))
    assert rows[0][-3:] == ["Start", "Ende", "Begründung"]
    assert rows[2][:3] == ["B", "API", "Anna"] and rows[2][-3:-1] == ["10.11.2026", "11.11.2026"]
    assert result.end_date == date(2026, 11, 11)


def test_a_task_that_ends_on_the_deadline_does_not_cross_the_deadline_line():
    # The plan ends on Wed 11.11. With that day as the deadline the plan is on time (not
    # reported as late), so no bar may reach beyond the line.
    on_the_day = PROJECT.model_copy(update={"deadline": date(2026, 11, 11)})
    result = check_plan(PLAN, TEAM, on_the_day)
    assert result.end_date == on_the_day.deadline
    assert not any("nach der Deadline" in w for w in result.warnings)

    bars, line = gantt(PLAN, result, on_the_day.deadline)

    assert [(b["Aufgabe"], b["Zeitraum"]) for b in bars] == [
        ("A · Datenmodell", "09.11. – 09.11."),
        ("B · API", "10.11. – 11.11."),
    ]
    assert max(b["Ende"] for b in bars) <= line


def test_a_task_that_ends_after_the_deadline_crosses_the_line():
    result = check_plan(PLAN, TEAM, PROJECT.model_copy(update={"deadline": date(2026, 11, 10)}))
    bars, line = gantt(PLAN, result, date(2026, 11, 10))
    assert max(b["Ende"] for b in bars) > line


def test_absences_are_read_from_the_team_table_and_written_back_the_same_way():
    rows = [
        {
            "Name": "Anna",
            "Skills": "",
            "Stunden/Woche": 20,
            "Abwesend": "01.12.2026–05.12.2026, 23.12.2026, 4.1.2027 - 8.1.2027, "
            "01.02.2027 bis 02.02.2027",
        }
    ]
    (anna,) = rows_to_team(rows)
    assert [(a.first, a.last) for a in anna.absences] == [
        (date(2026, 12, 1), date(2026, 12, 5)),
        (date(2026, 12, 23), date(2026, 12, 23)),
        (date(2027, 1, 4), date(2027, 1, 8)),
        (date(2027, 2, 1), date(2027, 2, 2)),
    ]
    (row,) = team_rows([anna])
    assert row["Abwesend"] == (
        "01.12.2026–05.12.2026, 23.12.2026, 04.01.2027–08.01.2027, 01.02.2027–02.02.2027"
    )
    assert rows_to_team([row]) == [anna]


def test_an_unreadable_absence_names_the_row_and_shows_the_expected_form():
    rows = [{"Name": "Anna", "Skills": "", "Stunden/Woche": 20, "Abwesend": "nächste Woche"}]
    with pytest.raises(InputError) as err:
        rows_to_team(rows)
    assert str(err.value) == (
        "Zeile 1 (Anna): Abwesenheit 'nächste Woche' nicht lesbar, erwartet zum Beispiel "
        "'01.12.2026–05.12.2026' oder '23.12.2026'"
    )
    rows[0]["Abwesend"] = "31.02.2027"
    with pytest.raises(InputError, match="Abwesenheit '31.02.2027' nicht lesbar"):
        rows_to_team(rows)
    rows[0]["Abwesend"] = "05.12.2026–01.12.2026"
    with pytest.raises(InputError, match="Ende der Abwesenheit liegt vor ihrem Beginn"):
        rows_to_team(rows)


BEN = Member(name="Ben", skills={"SQL": 3}, hours_per_week=20)
CLARA = Member(name="Clara", skills={"sql": 4, "Python": 2}, hours_per_week=10)


def test_a_task_is_explained_with_its_reason_skills_neighbours_and_slack():
    team = [*TEAM, BEN, CLARA]
    result = check_plan(PLAN, team, PROJECT)
    view = explain_task(PLAN, team, result, "A")

    assert (view["title"], view["member"], view["hours"]) == ("Datenmodell", "Anna", 8)
    assert view["reason"] == "kennt die Raumdaten"
    assert (view["start"], view["end"]) == (date(2026, 11, 9), date(2026, 11, 9))
    assert view["skills"] == [("SQL", None)]  # Anna has not named SQL
    assert view["depends_on"] == [] and view["needed_by"] == [("B", "API")]
    assert view["critical"] is True and view["slack"] == 0
    # Who else could do it: best fit first. Skill names match without regard to case.
    assert view["alternatives"] == [
        {"member": "Clara", "skills": {"SQL": 4}, "utilization": 0},
        {"member": "Ben", "skills": {"SQL": 3}, "utilization": 0},
    ]


def test_a_task_without_required_skills_lists_the_least_loaded_people_first():
    busy_ben = Plan.model_validate(
        {
            **plan_input(),
            "tasks": plan_input()["tasks"] + [{"id": "C", "title": "Doku", "estimate_hours": 10}],
            "assignments": plan_input()["assignments"]
            + [{"task_id": "C", "member": "Ben", "reason": "hat Zeit"}],
        }
    )
    team = [*TEAM, BEN, CLARA]
    view = explain_task(busy_ben, team, check_plan(busy_ben, team, PROJECT), "B")
    assert view["skills"] == []
    assert view["depends_on"] == [("A", "Datenmodell")]
    assert [a["member"] for a in view["alternatives"]] == ["Clara", "Ben"]
    assert view["alternatives"][1]["utilization"] == pytest.approx(10 / 120)
