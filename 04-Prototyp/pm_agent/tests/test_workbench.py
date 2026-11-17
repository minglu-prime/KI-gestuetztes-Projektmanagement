import csv
import io
import json
import os
import threading
from datetime import date, datetime
from pathlib import Path

import pytest
from test_tools import PROJECT, TEAM, plan_input

from pm_agent import workbench
from pm_agent.models import Member, Plan, Requirement
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
    put_aside,
    read_runs,
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


def test_runs_csv_takes_a_line_under_its_heading_and_in_its_order(tmp_path):
    path = tmp_path / "runs.csv"
    append_run({"quelle": "agent", "runden": 3, "format": "md"}, path)
    append_run({"runden": 0, "quelle": "protokoll"}, path)  # another order, a column less
    assert list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8")))) == [
        {"quelle": "agent", "runden": "3", "format": "md"},
        {"quelle": "protokoll", "runden": "0", "format": ""},
    ]
    assert list(tmp_path.glob("runs-bis-*.csv")) == []


@pytest.mark.parametrize(
    "old",
    [
        b"quelle,runden\r\nagent,3\r\nagent,5,csv\r\n",  # the row brings a new column
        b"\r\nquelle,runden,format\r\nagent,3,md\r\n",  # an empty first line
        b"quelle;runden;format\r\nagent;3;md\r\n",  # saved by a German spreadsheet
        b"quelle,runden,format\r\nagent,3,md,zu viel\r\n",  # a line with a cell too many
        b'quelle,runden,format\r\nagent,3,"md\r\n',  # a quote that is never closed
        b'"quelle,runden\r\n' + b"x,agent\r\n" * 20000,  # the same, larger than a cell may be
        "quelle,runden,format\r\ngeändert,3,md\r\n".encode("cp1252"),  # not UTF-8
    ],
)
def test_runs_csv_with_other_columns_is_put_aside_as_it_is(tmp_path, old):
    # Nothing in such a file is read, moved or rewritten: under which heading its values
    # belong is not for an export to decide. It gets another name, byte for byte, and a new
    # file begins.
    path = tmp_path / "runs.csv"
    path.write_bytes(old)
    append_run({"quelle": "agent", "runden": 1, "format": "csv"}, path)
    (aside,) = tmp_path.glob("runs-bis-*.csv")
    assert aside.read_bytes() == old
    assert path.read_bytes() == b"quelle,runden,format\r\nagent,1,csv\r\n"


def test_runs_csv_whose_columns_fit_keeps_every_byte(tmp_path):
    # A byte order mark, other line ends, no line end after the last line: the new line
    # goes below, on a line of its own.
    path = tmp_path / "runs.csv"
    before = b"\xef\xbb\xbfquelle,runden\nagent,5"
    path.write_bytes(before)
    append_run({"runden": 1, "quelle": "agent"}, path)
    assert path.read_bytes() == before + b"\r\nagent,1\r\n"
    assert list(tmp_path.glob("runs-bis-*.csv")) == []


def test_bytes_that_only_look_like_a_byte_order_mark_are_content(tmp_path):
    # EF BB BB is a letter (U+FEFB), not the mark EF BB BF.
    path = tmp_path / "runs.csv"
    path.write_bytes(b"\xef\xbb\xbb\r\n")
    append_run({"quelle": "agent"}, path)
    (aside,) = put_aside(path)
    assert (tmp_path / aside).read_bytes() == b"\xef\xbb\xbb\r\n"


@pytest.mark.parametrize("empty", [b"", b"\xef\xbb\xbf", b"\r\n\r\n", b"\xef\xbb\xbf\n \n"])
def test_runs_csv_without_any_content_is_begun_anew(tmp_path, empty):
    # Nothing to keep, so nothing to put aside.
    path = tmp_path / "runs.csv"
    path.write_bytes(empty)
    append_run({"quelle": "agent", "runden": 1}, path)
    assert path.read_bytes() == b"quelle,runden\r\nagent,1\r\n"
    assert put_aside(path) == []


def test_runs_csv_is_never_put_aside_over_another_file(tmp_path, monkeypatch):
    # Three times in the same second: every old file keeps a name of its own, and
    # put_aside names them oldest first. Files somebody else put there do not count.
    class Noon(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 11, 15, 12, 0, 0)

    monkeypatch.setattr(workbench, "datetime", Noon)
    path = tmp_path / "runs.csv"
    (tmp_path / "runs-bis-notizen.csv").write_bytes(b"meins")
    (tmp_path / "runs-bis-20261115-120000-9.csv").mkdir()
    # A file that already has the name the first one would get, as another server of the
    # same second would leave it: it is not written over.
    (tmp_path / "runs-bis-20261115-120000.csv").write_bytes(b"von nebenan")
    for number in range(3):
        path.write_bytes(b"alt%d\r\n1\r\n" % number)
        append_run({"quelle": "agent"}, path)
    assert put_aside(path) == [
        "runs-bis-20261115-120000.csv",
        "runs-bis-20261115-120000-2.csv",
        "runs-bis-20261115-120000-3.csv",
        "runs-bis-20261115-120000-4.csv",
    ]
    assert [(tmp_path / name).read_bytes() for name in put_aside(path)] == [
        b"von nebenan",
        b"alt0\r\n1\r\n",
        b"alt1\r\n1\r\n",
        b"alt2\r\n1\r\n",
    ]


def test_putting_aside_moves_the_file_that_is_there(tmp_path, monkeypatch):
    # Another server on the same folder appends a line after this one has read the file.
    # Put aside as a copy of what was read, that line would be in no file at all.
    path = tmp_path / "runs.csv"
    path.write_bytes(b"quelle,runden\r\nagent,1\r\n")
    heading = workbench._record_heading

    def read_then_the_other_server_writes(content):
        with path.open("ab") as file:
            file.write(b"nebenan,2\r\n")
        return heading(content)

    monkeypatch.setattr(workbench, "_record_heading", read_then_the_other_server_writes)
    append_run({"quelle": "agent", "runden": 3, "format": "csv"}, path)
    (aside,) = put_aside(path)
    assert (tmp_path / aside).read_bytes() == b"quelle,runden\r\nagent,1\r\nnebenan,2\r\n"


@pytest.mark.parametrize(
    "move",
    [
        pytest.param(
            workbench._rename,
            marks=pytest.mark.skipif(os.name != "nt", reason="refuses only on Windows"),
        ),
        workbench._link_and_unlink,
    ],
)
def test_both_ways_to_move_a_file_refuse_a_name_that_exists(tmp_path, move):
    # Windows and the other systems each have one move that does not write over a file.
    # On Windows both run: its file system has hard links too.
    source, free, taken = tmp_path / "runs.csv", tmp_path / "frei.csv", tmp_path / "belegt.csv"
    source.write_bytes(b"alt")
    taken.write_bytes(b"von nebenan")
    with pytest.raises(FileExistsError):
        move(source, taken)
    assert (source.read_bytes(), taken.read_bytes()) == (b"alt", b"von nebenan")
    move(source, free)
    assert not source.exists()
    assert free.read_bytes() == b"alt"


def test_no_list_of_files_put_aside_without_the_folder(tmp_path):
    # A fresh clone has no logs folder until the first run or export.
    assert put_aside(tmp_path / "logs" / "runs.csv") == []
    assert read_runs(tmp_path / "logs" / "runs.csv") == []


def test_the_record_is_read_with_the_check_it_is_written_with(tmp_path):
    path = tmp_path / "runs.csv"
    assert read_runs(path) == []
    path.write_bytes(b"\xef\xbb\xbf\r\n")  # nothing in it
    assert read_runs(path) == []
    append_run({"quelle": "Agent, auf Wunsch geändert", "runden": 3}, path)
    append_run({"quelle": "agent", "runden": None}, path)
    assert read_runs(path) == [
        {"quelle": "Agent, auf Wunsch geändert", "runden": "3"},
        {"quelle": "agent", "runden": ""},
    ]
    # A surplus cell that a table program would read as "no value" and leave out.
    path.write_bytes(b"quelle,runden\r\nagent,5,NA\r\nagent,3,None\r\n")
    with pytest.raises(InputError, match="kein sauberes Protokoll"):
        read_runs(path)


def test_runs_csv_takes_every_line_of_exports_at_the_same_time(tmp_path):
    # Every browser session has a thread of its own. Appending is "go to the end, write":
    # two at once could write over each other, and the page said nothing.
    path = tmp_path / "runs.csv"

    def export(session):
        for number in range(150):
            append_run({"quelle": f"sitzung-{session}", "runden": number}, path)

    threads = [threading.Thread(target=export, args=(session,)) for session in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    lines = list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8"))))
    assert sorted((line["quelle"], int(line["runden"])) for line in lines) == sorted(
        (f"sitzung-{session}", number) for session in range(8) for number in range(150)
    )


def test_a_line_that_cannot_be_written_leaves_the_file_as_it_was(tmp_path):
    # A lone surrogate cannot be encoded (a file name on Windows can hold one). Nothing is
    # written then, not even the heading of a new file.
    path = tmp_path / "runs.csv"
    with pytest.raises(UnicodeEncodeError):
        append_run({"quelle": "Protokoll run-\udc80.json"}, path)
    assert not path.exists()
    path.write_bytes(b"quelle\r\nagent\r\n")
    with pytest.raises(UnicodeEncodeError):
        append_run({"quelle": "Protokoll run-\udc80.json"}, path)
    assert path.read_bytes() == b"quelle\r\nagent\r\n"
    # Also a file that would have to be put aside first: it stays where it is.
    with pytest.raises(UnicodeEncodeError):
        append_run({"quelle": "Protokoll run-\udc80.json", "neu": 1}, path)
    assert path.read_bytes() == b"quelle\r\nagent\r\n"
    assert put_aside(path) == []


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


def tricky_plan(title, member="Anna", hours=2.5):
    data = plan_input(member=member)
    data["tasks"][0].update(title=title, estimate_hours=hours)
    return Plan.model_validate(data)


def test_the_csv_opens_in_german_excel_as_written():
    # Excel reads UTF-8 without a byte order mark as cp1252 ("BegrÃ¼ndung"), and a German
    # Excel reads "2.5" as a date, not as hours.
    plan = tricky_plan("Datenmodell", hours=2.5)
    text = to_csv(plan, check_plan(plan, TEAM, PROJECT))
    assert text.startswith("﻿")
    rows = list(csv.reader(io.StringIO(text.removeprefix("﻿")), delimiter=";"))
    assert rows[1][:4] == ["A", "Datenmodell", "Anna", "2,5"]


@pytest.mark.parametrize("title", ['=HYPERLINK("http://x")', "+1", "-2+3", "@SUMME(A1)"])
def test_no_cell_of_the_csv_runs_as_a_formula(title):
    # Titles come from Claude and from the editable table: Excel must show them, not run them.
    plan = tricky_plan(title)
    text = to_csv(plan, check_plan(plan, TEAM, PROJECT)).removeprefix("﻿")
    rows = list(csv.reader(io.StringIO(text), delimiter=";"))
    assert rows[1][1] == "'" + title


def test_markdown_keeps_every_cell_and_line_in_its_place():
    plan = tricky_plan("Daten")
    idea = PROJECT.model_copy(update={"idea": "Raumbuchung\nfür Lerngruppen"})
    data = plan.model_dump()
    data["risks"] = ["Raumdaten\nfehlen"]
    data["tasks"][0]["id"] = "A|1"
    data["tasks"][1]["depends_on"] = ["A|1"]
    data["assignments"][0]["task_id"] = "A|1"
    plan = Plan.model_validate(data)
    markdown = to_markdown(idea, plan, check_plan(plan, TEAM, idea))
    assert "**Projekt:** Raumbuchung für Lerngruppen  " in markdown
    assert "| A\\|1 | Daten | Anna |" in markdown
    assert "- Raumdaten fehlen" in markdown


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


@pytest.mark.parametrize(
    "old",
    [b"quelle,quelle,runden\r\nagent,protokoll,3\r\n", b"quelle,,\r\nagent,1,2\r\n"],
)
def test_a_heading_with_a_name_twice_or_without_one_is_no_record(tmp_path, old):
    # Two columns of one name: read by name, one value would hide the other.
    path = tmp_path / "runs.csv"
    path.write_bytes(old)
    with pytest.raises(InputError, match="kein sauberes Protokoll"):
        read_runs(path)
    append_run({"quelle": "agent"}, path)
    (aside,) = put_aside(path)
    assert (tmp_path / aside).read_bytes() == old
    assert read_runs(path) == [{"quelle": "agent"}]


def test_a_link_that_cannot_be_finished_is_taken_back(tmp_path, monkeypatch):
    # The other systems' way to move: link, then remove the old name. If the old name
    # cannot be removed, the new one must not stay, or the next export would put the same
    # file aside a second time.
    source, target = tmp_path / "runs.csv", tmp_path / "runs-bis-x.csv"
    source.write_bytes(b"alt")
    unlink = Path.unlink

    def held(self, *args, **kwargs):
        if self == source:
            raise PermissionError(13, "in use")
        unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", held)
    with pytest.raises(PermissionError):
        workbench._link_and_unlink(source, target)
    assert [file.name for file in tmp_path.iterdir()] == ["runs.csv"]


def traced_plan():
    data = plan_input()
    data["tasks"][0]["requirement_ids"] = ["R1", "R2"]
    return Plan.model_validate(data)


def test_plan_table_round_trip_keeps_requirement_ids():
    plan = traced_plan()
    rows = plan_rows(plan)
    assert rows[0]["Anforderungen"] == "R1, R2" and rows[1]["Anforderungen"] == ""
    back = rows_to_plan(rows, plan, plan.risks)
    assert [t.requirement_ids for t in back.tasks] == [["R1", "R2"], []]
    assert table_plan(plan) == plan


def test_the_csv_has_the_requirements_before_the_dates():
    plan = traced_plan()
    rows = list(
        csv.reader(io.StringIO(to_csv(plan, check_plan(plan, TEAM, PROJECT))), delimiter=";")
    )
    assert rows[0][-4:] == ["Anforderungen", "Start", "Ende", "Begründung"]
    assert rows[1][-4] == "R1, R2"


def test_the_exported_plan_lists_the_tasks_of_each_requirement():
    needs = [
        Requirement(
            id=rid,
            title=title,
            story="Als Nutzerin will ich das.",
            priority="Muss",
            criteria=["geht"],
        )
        for rid, title in [("R1", "Raum | sehen"), ("R2", "Buchen"), ("R3", "Export")]
    ]
    plan = traced_plan()  # A serves R1 and R2
    markdown = to_markdown(PROJECT, plan, check_plan(plan, TEAM, PROJECT), needs)
    assert "## Anforderungen" in markdown
    assert r"- R1 · Raum \| sehen (Muss): A" in markdown
    assert "- R3 · Export (Muss): keine" in markdown
    # Without approved requirements the export is as before.
    assert "## Anforderungen" not in to_markdown(PROJECT, plan, check_plan(plan, TEAM, PROJECT))


def test_the_plan_table_keeps_the_demos_and_the_markdown_lists_them():
    from test_tools import PROJECT, TEAM, plan_input

    from pm_agent.models import Plan
    from pm_agent.planning import check_plan
    from pm_agent.workbench import plan_rows, rows_to_plan, table_plan, to_markdown

    plan = Plan.model_validate(
        {**plan_input(), "demos": [{"week": 1, "title": "API zeigen", "task_ids": ["A", "B"]}]}
    )
    assert rows_to_plan(plan_rows(plan), plan, plan.risks).demos == plan.demos
    assert table_plan(plan) == plan
    text = to_markdown(PROJECT, plan, check_plan(plan, TEAM, PROJECT))
    assert "## Demos je Woche\n\n- Woche 1 (bis 13.11.2026): API zeigen (A, B)" in text


def test_demo_rows_say_whether_each_demo_is_ready_in_its_week():
    from test_tools import PROJECT, TEAM, plan_input

    from pm_agent.models import Plan
    from pm_agent.planning import check_plan
    from pm_agent.workbench import demo_rows

    data = plan_input()
    data["tasks"][1]["estimate_hours"] = 40  # B ends Monday 16.11.
    plan = Plan.model_validate(
        {
            **data,
            "demos": [
                {"week": 2, "title": "API zeigen", "task_ids": ["B"]},
                {"week": 1, "title": "Modell zeigen", "task_ids": ["A", "B"]},
            ],
        }
    )
    assert demo_rows(plan, check_plan(plan, TEAM, PROJECT), PROJECT) == [
        {
            "Woche": 1,
            "Bis": "13.11.2026",
            "Demo": "Modell zeigen",
            "Aufgaben": "A, B",
            "Rechtzeitig fertig": "nein: B endet am 16.11.2026",
        },
        {
            "Woche": 2,
            "Bis": "20.11.2026",
            "Demo": "API zeigen",
            "Aufgaben": "B",
            "Rechtzeitig fertig": "ja",
        },
    ]


def test_a_task_removed_in_the_table_leaves_the_demos():
    from test_tools import plan_input

    from pm_agent.models import Plan
    from pm_agent.workbench import plan_rows, rows_to_plan

    plan = Plan.model_validate(
        {
            **plan_input(),
            "demos": [
                {"week": 1, "title": "beides", "task_ids": ["A", "B"]},
                {"week": 2, "title": "nur B", "task_ids": ["B"]},
            ],
        }
    )
    rows = [row for row in plan_rows(plan) if row["ID"] != "B"]
    rows[0]["Abhängig von"] = ""
    demos = rows_to_plan(rows, plan, plan.risks).demos
    assert [(d.week, d.task_ids) for d in demos] == [(1, ["A"])]


def test_demo_rows_of_a_plan_with_errors_are_not_checked():
    from test_tools import PROJECT, TEAM, plan_input

    from pm_agent.models import Plan
    from pm_agent.planning import check_plan
    from pm_agent.workbench import demo_rows

    plan = Plan.model_validate(
        {**plan_input(), "demos": [{"week": 1, "title": "x", "task_ids": ["A", "Z"]}]}
    )
    result = check_plan(plan, TEAM, PROJECT)
    assert result.errors
    assert demo_rows(plan, result, PROJECT)[0]["Rechtzeitig fertig"] == "nicht geprüft"
