import json
from datetime import date

import pytest
from test_tools import PROJECT, TEAM, plan_input

from pm_agent.models import Plan, StatusSummary
from pm_agent.tracking import (
    adopt,
    agent_runs,
    apply_rows,
    evaluate,
    forecast,
    has_progress,
    load,
    progress_rows,
    save,
    status_report,
    work_packages,
)
from pm_agent.workbench import InputError

# Anna has 8 h per workday: A (8 h) is planned for Mon 09.11., B (16 h) for 10.–11.11.
PLAN = Plan.model_validate(plan_input())
ROWS = [
    {"ID": "A", "Status": "fertig", "Ist (h)": 10, "Notiz": "Schema zweimal geändert"},
    {"ID": "B", "Status": "in Arbeit", "Ist (h)": 4, "Notiz": None},
]


@pytest.fixture
def tracking(tmp_path):
    return adopt(PROJECT, TEAM, PLAN, path=tmp_path / "projekt.json")


def test_an_adopted_plan_is_saved_as_the_baseline_without_progress(tracking, tmp_path):
    assert load(tmp_path / "projekt.json") == tracking
    assert (tracking.project, tracking.team, tracking.plan) == (PROJECT, TEAM, PLAN)
    assert not has_progress(tracking)
    assert [(r["ID"], r["Status"], r["Ist (h)"]) for r in progress_rows(tracking)] == [
        ("A", "offen", 0),
        ("B", "offen", 0),
    ]


def test_no_adopted_project_is_none_and_a_damaged_file_is_an_error(tmp_path):
    path = tmp_path / "projekt.json"
    assert load(path) is None
    path.write_text('{"plan": 1}', encoding="utf-8")
    with pytest.raises(InputError, match="projekt.json ist beschädigt"):
        load(path)


def test_a_plan_with_errors_cannot_be_adopted(tmp_path):
    broken = Plan.model_validate(plan_input(member="Zoe"))  # Zoe is not in the team
    with pytest.raises(InputError, match="Zoe"):
        adopt(PROJECT, TEAM, broken, path=tmp_path / "projekt.json")
    assert not (tmp_path / "projekt.json").exists()


def test_recorded_progress_is_kept_and_saved(tracking, tmp_path):
    updated = apply_rows(tracking, ROWS)
    save(updated, tmp_path / "projekt.json")

    assert load(tmp_path / "projekt.json") == updated
    assert has_progress(updated)
    assert updated.progress["A"].model_dump() == {
        "status": "fertig",
        "actual_hours": 10,
        "note": "Schema zweimal geändert",
    }
    assert updated.progress["B"].note == ""


@pytest.mark.parametrize(
    ("row", "message"),
    [
        ({"ID": "Z", "Status": "offen", "Ist (h)": 0}, r"Zeile 1 \(Z\): Aufgabe nicht im Plan"),
        ({"ID": "A", "Status": "halb", "Ist (h)": 0}, r"Zeile 1 \(A\): Status 'halb' unbekannt"),
        ({"ID": "A", "Status": "offen", "Ist (h)": -1}, r"Zeile 1 \(A\): Ist-Stunden"),
        ({"ID": "A", "Status": "offen", "Ist (h)": "viel"}, r"Zeile 1 \(A\): Ist-Stunden"),
    ],
)
def test_unreadable_progress_rows_name_the_row_and_the_problem(tracking, row, message):
    with pytest.raises(InputError, match=message):
        apply_rows(tracking, [row])


def test_an_empty_hours_cell_counts_as_zero(tracking):
    updated = apply_rows(tracking, [{"ID": "A", "Status": "in Arbeit", "Ist (h)": None}])
    assert updated.progress["A"].actual_hours == 0


def test_evaluation_compares_plan_and_actual_and_finds_overdue_tasks(tracking):
    result = evaluate(apply_rows(tracking, ROWS), today=date(2026, 11, 12))

    assert (result.planned_hours, result.actual_hours) == (24, 14)
    assert result.progress == pytest.approx(8 / 24)  # only A is finished
    assert result.finished_deviation == 2  # A took 10 h instead of 8 h
    assert [t.id for t in result.overdue] == ["B"]  # planned until 11.11., not finished
    assert result.tasks[1].planned_end == date(2026, 11, 11)
    assert result.by_member == [
        {"Person": "Anna", "Plan (h)": 24, "Ist (h)": 14, "Fertig (Plan-h)": 8}
    ]


def test_a_task_is_not_overdue_on_its_planned_end_day(tracking):
    assert evaluate(tracking, today=date(2026, 11, 11)).overdue[0].id == "A"
    assert [t.id for t in evaluate(tracking, today=date(2026, 11, 9)).overdue] == []


def test_the_status_report_is_filled_from_plan_and_progress(tracking):
    updated = apply_rows(tracking, ROWS)
    report = status_report(updated, evaluate(updated, today=date(2026, 11, 12)))

    assert "**Projekt:** Raumbuchung für Lerngruppen" in report
    assert "**Stand:** 12.11.2026" in report
    assert "- Fortschritt: 33 %" in report
    assert "- Aufgaben: 1 fertig, 1 in Arbeit, 0 offen" in report
    assert "- Abweichung der fertigen Aufgaben: +2 h" in report
    assert "- B · API (Anna), geplant bis 11.11.2026" in report
    assert "| A | Datenmodell | Anna | fertig | 8 | 10 | Schema zweimal geändert |" in report
    assert "- Die Hochschule liefert die Raumdaten zu spät" in report
    assert "$" not in report  # every placeholder is filled


def test_a_status_report_without_overdue_tasks_says_so(tracking):
    report = status_report(tracking, evaluate(tracking, today=date(2026, 11, 9)))
    assert "Keine Aufgabe im Verzug." in report
    assert "Noch nicht erstellt. Der Durchführungs-Agent" in report


def test_the_agents_summary_goes_into_the_status_report_marked_as_a_proposal(tracking):
    summary = StatusSummary(
        summary="A ist fertig, B ist im Verzug.",
        next_steps=[{"task_id": "B", "action": "Anna schließt die API bis Freitag ab."}],
    )
    report = status_report(tracking, evaluate(tracking, today=date(2026, 11, 12)), summary)

    assert "A ist fertig, B ist im Verzug.\n\n- **B:** Anna schließt die API" in report
    assert "*Vorschlag des Durchführungs-Agenten (Claude)" in report
    assert "Noch nicht erstellt" not in report


def test_work_packages_describe_every_task(tracking):
    text = work_packages(tracking)

    assert "## A · Datenmodell" in text
    assert "| Verantwortlich | Anna |" in text
    assert "| Zeitraum | 10.11.2026 bis 11.11.2026 |" in text
    assert "| Abhängig von | A |" in text
    assert "| Benötigte Skills | SQL |" in text
    assert "**Begründung der Zuweisung:** kennt die Raumdaten" in text
    assert "$" not in text


def test_agent_runs_list_time_rounds_and_tokens_of_every_agent(tmp_path):
    usage = {"input_tokens": 1200, "output_tokens": 300, "cache_read_input_tokens": 500}
    (tmp_path / "run-20261111-124944.json").write_text(
        json.dumps(
            {
                "started": "2026-11-11T12:49:44+01:00",
                "seconds": 184.2,
                "outcome": "plan",
                "rounds": [{"usage": usage}, {"usage": usage}],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "run-20261111-124330.json").write_text(
        json.dumps({"started": "2026-11-11T12:43:30+01:00", "seconds": 0.4, "outcome": "error"}),
        encoding="utf-8",
    )
    (tmp_path / "kontrolle-20261112-090000.json").write_text(
        json.dumps({"seconds": 20.5, "outcome": "kontrollbericht", "rounds": [{"usage": usage}]}),
        encoding="utf-8",
    )

    assert agent_runs(tmp_path) == [
        {
            "Lauf": "kontrolle-20261112-090000.json",
            "Agent": "Kontrolle",
            "Ergebnis": "Kontrollbericht",
            "Dauer (s)": 20.5,
            "Runden": 1,
            "Eingabe-Token": 1700,
            "Ausgabe-Token": 300,
        },
        {
            "Lauf": "run-20261111-124944.json",
            "Agent": "Planung",
            "Ergebnis": "Plan",
            "Dauer (s)": 184.2,
            "Runden": 2,
            "Eingabe-Token": 3400,
            "Ausgabe-Token": 600,
        },
        {
            "Lauf": "run-20261111-124330.json",
            "Agent": "Planung",
            "Ergebnis": "Fehler",
            "Dauer (s)": 0.4,
            "Runden": 0,
            "Eingabe-Token": 0,
            "Ausgabe-Token": 0,
        },
    ]


def progressed(tracking, **status):
    """The project with the given status per task, e.g. A="fertig" or B=("in Arbeit", 4)."""
    rows = []
    for task_id, state in status.items():
        name, hours = state if isinstance(state, tuple) else (state, 0)
        rows.append({"ID": task_id, "Status": name, "Ist (h)": hours})
    return apply_rows(tracking, rows)


def test_on_schedule_the_forecast_is_the_plan(tracking):
    # Tue 10.11.: A is finished as planned, B starts today.
    outlook = forecast(progressed(tracking, A="fertig"), date(2026, 11, 10))
    assert (outlook.planned_end, outlook.end, outlook.shift) == (
        date(2026, 11, 11),
        date(2026, 11, 11),
        0,
    )
    assert outlook.blocked == {}


def test_an_overdue_task_moves_the_end_and_names_what_waits_for_it(tracking):
    # Tue 10.11.: A should have been finished on Monday and is still open.
    outlook = forecast(tracking, date(2026, 11, 10))
    assert (outlook.end, outlook.shift) == (date(2026, 11, 12), 1)  # A today, B Wed and Thu
    assert outlook.blocked == {"A": ["B"]}
    assert outlook.deadline_gap == -26  # still 26 workdays before the deadline on 18.12.


def test_past_the_deadline_the_forecast_says_by_how_much(tracking):
    # Mon 21.12., nothing done. The deadline was Fri 18.12.
    outlook = forecast(tracking, date(2026, 12, 21))
    assert outlook.end == date(2026, 12, 23)
    assert outlook.deadline_gap == 3


def test_a_started_task_counts_with_what_is_left_of_its_estimate(tracking):
    # Wed 11.11.: B (16 h) has 4 h booked, 12 h are left: today and half of Thursday.
    started = progressed(tracking, A="fertig", B=("in Arbeit", 4))
    assert forecast(started, date(2026, 11, 11)).end == date(2026, 11, 12)
    # More hours booked than estimated and still not finished: it stays in the schedule.
    over = progressed(tracking, A="fertig", B=("in Arbeit", 20))
    assert forecast(over, date(2026, 11, 11)).end == date(2026, 11, 11)


def test_a_finished_project_has_no_forecast(tracking):
    outlook = forecast(progressed(tracking, A="fertig", B="fertig"), date(2026, 11, 12))
    assert outlook.end is None and outlook.shift == 0 and outlook.blocked == {}
