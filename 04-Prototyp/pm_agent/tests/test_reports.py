"""What the reports, the advice and the checks of the agents say: German numbers, Markdown that
keeps its shape, and no claim the numbers do not back."""

import json
from datetime import date

import pytest
from test_tools import PROJECT, TEAM, plan_input

from pm_agent.followup import check_report
from pm_agent.models import ControlReport, Member, Plan
from pm_agent.tracking import (
    Forecast,
    adopt,
    agent_runs,
    apply_rows,
    control_document,
    evaluate,
    next_step,
    rest_plan,
    status_report,
    work_packages,
)

# Anna, 8 h a workday. A (8 h) on Mon 09.11., B (16 h, after A) on 10.–11.11.
PLAN = Plan.model_validate(plan_input())
MONDAY = date(2026, 11, 9)


@pytest.fixture
def path(tmp_path):
    return tmp_path / "projekt.json"


def plan_of(*tasks, member="Anna"):
    """A plan from (ID, title, hours), one after the other."""
    return Plan.model_validate(
        {
            "tasks": [
                {"id": i, "title": title, "estimate_hours": hours} for i, title, hours in tasks
            ],
            "assignments": [{"task_id": i, "member": member, "reason": "r"} for i, _, _ in tasks],
        }
    )


def test_the_overview_of_runs_survives_a_log_it_cannot_read(tmp_path):
    # A log cut off when the program was killed while writing it.
    (tmp_path / "durchfuehrung-20261116-101010.json").write_bytes(b"")
    (tmp_path / "run-20261116-090000.json").write_text(
        json.dumps({"outcome": "plan", "seconds": 12.5, "rounds": [{"usage": {}}]}),
        encoding="utf-8",
    )
    damaged, good = agent_runs(tmp_path)
    assert damaged["Lauf"] == "durchfuehrung-20261116-101010.json"
    assert damaged["Ergebnis"].startswith("Protokoll unlesbar:")
    assert (good["Lauf"], good["Ergebnis"], good["Runden"]) == (
        "run-20261116-090000.json",
        "Plan",
        1,
    )


def test_the_advice_does_not_call_a_late_project_on_plan(path):
    # Monday: A is begun and needs 24 h instead of 8. Nothing is overdue yet and the deadline
    # holds, but the end moves two workdays.
    tracking = apply_rows(
        adopt(PROJECT, TEAM, PLAN, path=path),
        [{"ID": "A", "Status": "in Arbeit", "Ist (h)": 0, "Rest (h)": 24}],
    )
    advice, page = next_step(tracking, MONDAY)
    assert "liegt im Plan" not in advice
    assert "2 Arbeitstage später" in advice and page == "kontrolle"


def test_booked_hours_of_an_open_task_count_in_the_forecast(path):
    # Hours booked, status left at "offen": 6 of A's 8 h are done.
    tracking = apply_rows(
        adopt(PROJECT, TEAM, PLAN, path=path), [{"ID": "A", "Status": "offen", "Ist (h)": 6}]
    )
    assert {t.id: t.estimate_hours for t in rest_plan(tracking).tasks} == {"A": 2, "B": 16}


def test_reports_write_hours_the_german_way_and_without_float_noise(path):
    plan = plan_of(("A", "Datenmodell", 0.7), ("B", "API", 0.1))
    tracking = apply_rows(
        adopt(PROJECT, TEAM, plan, path=path),
        [
            {"ID": "A", "Status": "fertig", "Ist (h)": 0.6},
            {"ID": "B", "Status": "fertig", "Ist (h)": 0.2},
        ],
    )
    result = evaluate(tracking, MONDAY)
    for report in (status_report(tracking, result), control_document(tracking, result)):
        assert "Planstunden gesamt: 0,8 h" in report
        assert "Abweichung der fertigen Aufgaben: +0 h" in report
    assert "| A | Datenmodell | Anna | fertig | 0,7 | 0,6 |" in status_report(tracking, result)
    assert "| Aufwand | 0,7 h |" in work_packages(tracking)


def test_reports_keep_their_tables_and_lists_whatever_the_names_hold(path):
    team = [Member(name="Anna | Bo", skills={"Python": 4}, hours_per_week=40)]
    plan = plan_of(("A", "Datenmodell", 8), ("B", "API|\nTests", 16), member="Anna | Bo")
    data = plan.model_dump()
    data["risks"] = ["Raumdaten\nfehlen"]
    tracking = adopt(PROJECT, team, Plan.model_validate(data), path=path)
    result = evaluate(tracking, date(2026, 11, 20))  # both tasks overdue
    report = status_report(tracking, result)
    assert "| B | API\\| Tests | Anna \\| Bo | offen |" in report
    assert "- B · API\\| Tests (Anna \\| Bo), geplant bis" in report
    assert "- Raumdaten fehlen" in report
    packages = work_packages(tracking)
    assert "## B · API\\| Tests" in packages
    assert "| Verantwortlich | Anna \\| Bo |" in packages


def report_with(measure, assessment="gefährdet"):
    return ControlReport(
        assessment=assessment,
        findings=[{"observation": "Stand geprüft."}],
        measures=[measure] if measure else [],
    )


def test_a_task_cannot_be_given_to_the_person_who_has_it(path):
    tracking = adopt(PROJECT, TEAM, PLAN, path=path)
    report = report_with(
        {"task_ids": ["B"], "action": "Umverteilen", "effect": "schneller", "reassign_to": "Anna"}
    )
    assert check_report(report, evaluate(tracking, MONDAY), TEAM) == [
        "Gegenmaßnahme gibt 'B' an Anna, die die Aufgabe schon hat"
    ]


def test_work_dropped_from_an_earlier_plan_is_called_closed_not_finished(path):
    # A finished, B begun; the next plan has only C. B's booked part is history, not finished.
    first = apply_rows(
        adopt(PROJECT, TEAM, PLAN, path=path),
        [
            {"ID": "A", "Status": "fertig", "Ist (h)": 8},
            {"ID": "B", "Status": "in Arbeit", "Ist (h)": 4},
        ],
    )
    later = adopt(PROJECT, TEAM, plan_of(("C", "Tests", 6)), path=path, keep=first)
    measure = {"task_ids": ["A", "B"], "action": "Neu", "effect": "x", "reassign_to": "Anna"}
    assert check_report(report_with(measure), evaluate(later, MONDAY), TEAM) == [
        "Gegenmaßnahme will die fertige Aufgabe 'A' neu vergeben",
        "Gegenmaßnahme will die abgeschlossene Aufgabe 'B' neu vergeben",
    ]


def test_on_plan_is_no_assessment_for_a_forecast_past_the_deadline(path):
    tracking = adopt(PROJECT, TEAM, PLAN, path=path)
    late = Forecast(
        planned_end=date(2026, 11, 11),
        end=date(2026, 12, 21),
        shift=28,
        deadline_gap=1,
        blocked={},
        schedule=[],
    )
    errors = check_report(report_with(None, "im Plan"), evaluate(tracking, MONDAY), TEAM, late)
    assert errors == [
        "Die Prognose endet nach der Deadline, die Bewertung kann nicht 'im Plan' sein"
    ]
