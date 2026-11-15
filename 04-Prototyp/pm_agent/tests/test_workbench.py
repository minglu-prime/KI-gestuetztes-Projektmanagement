import csv
import io
import json
from datetime import date

import pytest
from test_tools import PROJECT, TEAM, plan_input

from pm_agent import workbench
from pm_agent.models import Member, Plan
from pm_agent.planning import check_plan
from pm_agent.workbench import (
    InputError,
    append_run,
    bar_end,
    explain_task,
    free_days,
    free_days_text,
    gantt,
    load_run,
    load_team,
    plan_rows,
    round_summary,
    rows_to_plan,
    rows_to_team,
    save_team,
    saved_runs,
    suggested_wishes,
    table_plan,
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


def test_runs_csv_keeps_every_value_under_its_column_when_the_columns_change(tmp_path):
    # A later version of the site records one thing more, or names the columns in another
    # order. The lines written before must not end up under the wrong heading.
    path = tmp_path / "logs" / "runs.csv"
    append_run({"quelle": "agent", "runden": 3}, path)
    append_run({"runden": 0, "format": "csv", "quelle": "protokoll"}, path)
    assert list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8")))) == [
        {"quelle": "agent", "runden": "3", "format": ""},
        {"quelle": "protokoll", "runden": "0", "format": "csv"},
    ]


def test_runs_csv_loses_no_line_when_an_old_line_is_longer_than_the_heading(tmp_path):
    # What an earlier version left behind once a column was added: a line with a cell more
    # than the heading. Bringing the new column must keep every line, and the surplus cell
    # is the value of that column.
    path = tmp_path / "runs.csv"
    path.write_text("quelle,runden\nagent,3\nagent,5,csv\nagent,7\n", encoding="utf-8")
    append_run({"quelle": "agent", "runden": 1, "format": "md"}, path)
    assert list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8")))) == [
        {"quelle": "agent", "runden": "3", "format": ""},
        {"quelle": "agent", "runden": "5", "format": "csv"},
        {"quelle": "agent", "runden": "7", "format": ""},
        {"quelle": "agent", "runden": "1", "format": "md"},
    ]
    assert not list(tmp_path.glob("*.tmp"))  # the rewrite went through a file of its own


def test_runs_csv_is_appended_to_and_left_alone_otherwise(tmp_path):
    # A file a spreadsheet saved: a byte order mark, Windows encoding, no line end at the
    # end, a line with a cell too many. None of that is the business of an export: the new
    # line goes below, and every byte before it stays.
    path = tmp_path / "runs.csv"
    before = "\ufeffquelle,runden\r\n".encode() + "geändert,3,x\r\nagent,5".encode("cp1252")
    path.write_bytes(before)
    append_run({"runden": 1, "quelle": "agent"}, path)
    assert path.read_bytes() == before + b"\r\nagent,1\r\n"


def test_runs_csv_is_found_where_the_tests_point_it(tmp_path, monkeypatch):
    # The page calls append_run without a path. Bound at import, the default would be the
    # real logs/runs.csv whatever a test sets.
    monkeypatch.setattr(workbench, "RUNS_CSV", tmp_path / "runs.csv")
    append_run({"quelle": "agent"})
    assert (tmp_path / "runs.csv").read_bytes() == b"quelle\r\nagent\r\n"


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
    with pytest.raises(
        InputError, match="Abwesenheit '05.12.2026–01.12.2026': Das Ende liegt vor dem Beginn"
    ):
        rows_to_team(rows)
    with pytest.raises(InputError, match="^'05.12.2026–01.12.2026': Das Ende liegt vor dem"):
        free_days("05.12.2026–01.12.2026")


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


def test_the_bars_of_the_gantt_chart_carry_slack_and_the_critical_path():
    ben = Member(name="Ben", skills={"SQL": 3}, hours_per_week=40)
    data = plan_input()
    data["tasks"].append({"id": "C", "title": "Doku", "estimate_hours": 8})
    data["assignments"].append({"task_id": "C", "member": "Ben", "reason": "hat Zeit"})
    plan = Plan.model_validate(data)
    team = [*TEAM, ben]
    bars, _ = gantt(plan, check_plan(plan, team, PROJECT), PROJECT.deadline)
    # Anna needs Mon-Wed for A and B. Ben's C takes one day and could slip two.
    assert [(b["Aufgabe"], b["Kritisch"], b["Puffer"]) for b in bars] == [
        ("A · Datenmodell", True, 0),
        ("B · API", True, 0),
        ("C · Doku", False, 2),
    ]


def test_a_deadline_on_the_last_day_of_the_calendar_can_still_be_drawn():
    # A day after 31.12.9999 does not exist. The charts drew the line there and crashed.
    assert bar_end(date(2026, 11, 11)) == date(2026, 11, 12)
    assert bar_end(date.max) == date.max
    bars, line = gantt(PLAN, check_plan(PLAN, TEAM, PROJECT), date.max)
    assert line == date.max and len(bars) == 2


def test_wishes_are_suggested_from_what_the_check_found():
    team = [*TEAM, BEN]
    suggestions = suggested_wishes(PLAN, team, check_plan(PLAN, team, PROJECT), PROJECT)
    # Anna does A without SQL, Ben has it. And always: what if the longest critical task grows.
    assert suggestions == [
        "Gib A (Datenmodell) an Ben: Ben hat SQL angegeben.",
        "Was, wenn B (API) doppelt so lange dauert?",
    ]


def test_a_late_plan_and_an_overloaded_person_come_first():
    tight = PROJECT.model_copy(update={"deadline": date(2026, 11, 10)})  # the plan needs 3 days
    team = [*TEAM, BEN]
    suggestions = suggested_wishes(PLAN, team, check_plan(PLAN, team, tight), tight)
    assert suggestions[:3] == [
        "Der Plan soll spätestens am 10.11.2026 enden.",
        "Entlaste Anna: Bis zur Deadline ist mehr zugewiesen als verfügbar.",
        "Gib A (Datenmodell) an Ben: Ben hat SQL angegeben.",
    ]
    assert len(suggestions) <= 4


def test_a_plan_that_ends_on_the_deadline_gets_a_wish_for_buffer():
    on_the_day = PROJECT.model_copy(update={"deadline": date(2026, 11, 11)})
    suggestions = suggested_wishes(PLAN, TEAM, check_plan(PLAN, TEAM, on_the_day), on_the_day)
    assert suggestions[0] == "Schaffe vor der Deadline mindestens zwei Arbeitstage Puffer."


def test_an_uneven_load_suggests_moving_work_and_a_broken_plan_suggests_nothing():
    idle = Member(name="Dora", skills={"Python": 3}, hours_per_week=40)
    tight = PROJECT.model_copy(update={"deadline": date(2026, 11, 13)})  # one week
    result = check_plan(PLAN, [*TEAM, idle], tight)  # Anna 24 of 40 h, Dora nothing
    assert "Verteile Arbeit von Anna auf Dora um." in suggested_wishes(
        PLAN, [*TEAM, idle], result, tight
    )
    broken = Plan.model_validate(plan_input(member="Zoe"))
    assert suggested_wishes(broken, TEAM, check_plan(broken, TEAM, PROJECT), PROJECT) == []


def test_the_table_gives_a_plan_back_in_its_own_form():
    # Claude may list the assignments in another order than the tasks. The table has one row
    # per task, so they come back in task order: the same plan, written differently.
    data = plan_input()
    data["assignments"].reverse()
    shuffled = Plan.model_validate(data)
    assert rows_to_plan(plan_rows(shuffled), shuffled, shuffled.risks) != shuffled
    assert table_plan(shuffled) == PLAN
    assert table_plan(PLAN) == PLAN


def test_a_plan_the_table_cannot_give_back_is_its_own_table_form():
    # Pydantic keeps a title made of a control character, the table reads it as empty.
    data = plan_input()
    data["tasks"][0]["title"] = "\x1c"
    odd = Plan.model_validate(data)
    with pytest.raises(InputError):
        rows_to_plan(plan_rows(odd), odd, odd.risks)
    assert table_plan(odd) == odd


def test_free_days_are_typed_like_absences_and_read_back():
    days = free_days("24.12.2026–01.01.2027, 06.01.2027")
    assert [(d.first, d.last) for d in days] == [
        (date(2026, 12, 24), date(2027, 1, 1)),
        (date(2027, 1, 6), date(2027, 1, 6)),
    ]
    assert free_days_text(days) == "24.12.2026–01.01.2027, 06.01.2027"
    assert free_days("") == []
    with pytest.raises(InputError, match="'Weihnachten' nicht lesbar"):
        free_days("Weihnachten")
