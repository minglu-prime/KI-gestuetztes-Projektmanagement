import json
from datetime import date

import pytest
from test_tools import PROJECT, TEAM, plan_input

from pm_agent.models import ControlReport, Member, Plan, StatusSummary
from pm_agent.planning import check_plan
from pm_agent.tracking import (
    Progress,
    adopt,
    agent_runs,
    apply_rows,
    control_document,
    earned_value,
    evaluate,
    forecast,
    forecast_bars,
    forecast_text,
    has_progress,
    hours_text,
    load,
    next_step,
    planned_curve,
    progress_rows,
    reassignment_effect,
    rest_plan,
    rest_project,
    save,
    status_report,
    week_ahead,
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
        "remaining_hours": None,
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


def test_the_forecast_has_dates_for_every_unfinished_task(tracking):
    outlook = forecast(tracking, date(2026, 11, 10))  # Tue: A is overdue, nothing is done
    assert [(s.task_id, s.member, s.start, s.end) for s in outlook.schedule] == [
        ("A", "Anna", date(2026, 11, 10), date(2026, 11, 10)),
        ("B", "Anna", date(2026, 11, 11), date(2026, 11, 12)),
    ]
    done = forecast(progressed(tracking, A="fertig", B="fertig"), date(2026, 11, 12))
    assert done.schedule == []


def test_the_forecast_reads_as_one_sentence(tracking):
    def said(today, **status):
        project = progressed(tracking, **status) if status else tracking
        return forecast_text(forecast(project, today), PROJECT.deadline)

    assert said(date(2026, 11, 10), A="fertig") == (
        "Voraussichtliches Ende 11.11.2026, wie geplant; bis zur Deadline (18.12.2026) bleiben "
        "27 Arbeitstage Puffer"
    )
    assert said(date(2026, 11, 10)) == (
        "Voraussichtliches Ende 12.11.2026, 1 Arbeitstag später als geplant; bis zur Deadline "
        "(18.12.2026) bleiben 26 Arbeitstage Puffer"
    )
    assert said(date(2026, 12, 16)) == (
        "Voraussichtliches Ende 18.12.2026, 27 Arbeitstage später als geplant; bis zur Deadline "
        "(18.12.2026) bleibt kein Puffer"
    )
    assert said(date(2026, 12, 21)) == (
        "Voraussichtliches Ende 23.12.2026, 30 Arbeitstage später als geplant; die Deadline "
        "(18.12.2026) wird um 3 Arbeitstage verpasst"
    )
    assert said(date(2026, 11, 12), A="fertig", B="fertig") == "Alle Aufgaben sind fertig."


def test_the_status_report_carries_the_forecast(tracking):
    updated = apply_rows(tracking, ROWS)  # A finished, B started with 4 of 16 h
    report = status_report(updated, evaluate(updated, today=date(2026, 11, 12)))
    assert (
        "**Prognose:** Voraussichtliches Ende 13.11.2026, 2 Arbeitstage später als geplant; bis "
        "zur Deadline (18.12.2026) bleiben 25 Arbeitstage Puffer" in report
    )
    assert "$" not in report


def test_plan_and_forecast_are_two_bars_per_unfinished_task(tracking):
    started = progressed(tracking, A="fertig")
    today = date(2026, 11, 11)  # Wed: B should have started on Tuesday
    bars = forecast_bars(evaluate(started, today), forecast(started, today))
    # A bar ends at the start of the day after its last day, like in the Gantt chart.
    assert bars == [
        {
            "Aufgabe": "B · API",
            "Art": "Plan",
            "Start": date(2026, 11, 10),
            "Ende": date(2026, 11, 12),
            "Zeitraum": "10.11. – 11.11.",
        },
        {
            "Aufgabe": "B · API",
            "Art": "Prognose",
            "Start": date(2026, 11, 11),
            "Ende": date(2026, 11, 13),
            "Zeitraum": "11.11. – 12.11.",
        },
    ]


def test_a_remaining_estimate_replaces_plan_minus_actual_in_the_forecast(tracking):
    # Wed 11.11.: B has 4 of its 16 h booked, but 20 h are still to do: Wed, Thu, half of Fri.
    rows = [
        {"ID": "A", "Status": "fertig", "Ist (h)": 8},
        {"ID": "B", "Status": "in Arbeit", "Ist (h)": 4, "Rest (h)": 20},
    ]
    updated = apply_rows(tracking, rows)
    assert updated.progress["B"].remaining_hours == 20
    assert forecast(updated, date(2026, 11, 11)).end == date(2026, 11, 13)
    # An open task can have one too: A is expected to take 16 h instead of 8 h.
    bigger = apply_rows(tracking, [{"ID": "A", "Status": "offen", "Rest (h)": 16}])
    assert forecast(bigger, date(2026, 11, 9)).end == date(2026, 11, 12)


def test_the_remaining_estimate_is_shown_in_the_progress_table_and_kept(tracking, tmp_path):
    updated = apply_rows(
        tracking, [{"ID": "B", "Status": "in Arbeit", "Ist (h)": 4, "Rest (h)": 20}]
    )
    save(updated, tmp_path / "projekt.json")
    assert load(tmp_path / "projekt.json") == updated
    assert [(r["ID"], r["Rest (h)"]) for r in progress_rows(updated)] == [("A", None), ("B", 20)]
    assert apply_rows(tracking, progress_rows(updated)) == updated


def test_a_finished_task_has_nothing_left_and_an_empty_cell_means_unknown(tracking):
    rows = [
        {"ID": "A", "Status": "fertig", "Ist (h)": 8, "Rest (h)": 5},
        {"ID": "B", "Status": "in Arbeit", "Ist (h)": 4, "Rest (h)": None},
    ]
    updated = apply_rows(tracking, rows)
    assert updated.progress["A"].remaining_hours is None
    assert updated.progress["B"].remaining_hours is None


@pytest.mark.parametrize(
    ("row", "message"),
    [
        ({"ID": "A", "Status": "offen", "Rest (h)": -1}, r"Zeile 1 \(A\): Rest-Stunden"),
        ({"ID": "A", "Status": "offen", "Rest (h)": "wenig"}, r"Zeile 1 \(A\): Rest-Stunden"),
        (
            {"ID": "A", "Status": "in Arbeit", "Rest (h)": 0},
            r"Zeile 1 \(A\): Rest 0 h, aber Status 'in Arbeit'. Setze den Status auf fertig",
        ),
    ],
)
def test_an_unreadable_remaining_estimate_names_the_row_and_the_problem(tracking, row, message):
    with pytest.raises(InputError, match=message):
        apply_rows(tracking, [row])


def test_progress_saved_before_remaining_estimates_existed_still_loads():
    assert (
        Progress.model_validate({"status": "in Arbeit", "actual_hours": 3}).remaining_hours is None
    )


@pytest.fixture
def two_people(tmp_path):
    """Anna has two independent tasks of two days each; Ben (SQL, full time) has none."""
    ben = Member(name="Ben", skills={"SQL": 3}, hours_per_week=40)
    plan = Plan.model_validate(
        {
            "tasks": [
                {
                    "id": "X",
                    "title": "Backend",
                    "estimate_hours": 16,
                    "required_skills": ["Python"],
                },
                {"id": "Y", "title": "Datenbank", "estimate_hours": 16, "required_skills": ["SQL"]},
            ],
            "assignments": [
                {"task_id": "X", "member": "Anna", "reason": "kennt Python"},
                {"task_id": "Y", "member": "Anna", "reason": "hat Zeit"},
            ],
        }
    )
    return adopt(PROJECT, [*TEAM, ben], plan, path=tmp_path / "projekt.json")


def test_the_forecast_can_be_computed_with_tasks_given_to_someone_else(two_people):
    monday = date(2026, 11, 9)
    assert forecast(two_people, monday).end == date(2026, 11, 12)  # Anna alone: four days
    shared = forecast(two_people, monday, reassign={"Y": "Ben"})
    assert shared.end == date(2026, 11, 10)
    assert [(s.task_id, s.member) for s in shared.schedule] == [("X", "Anna"), ("Y", "Ben")]
    assert shared.planned_end == date(2026, 11, 12)  # the plan itself is not touched


def test_the_effect_of_a_reassignment_is_a_sentence_with_numbers(two_people):
    monday = date(2026, 11, 9)
    assert reassignment_effect(two_people, monday, ["Y"], "Ben") == (
        "Voraussichtliches Ende 10.11.2026 statt 12.11.2026 (2 Arbeitstage früher)"
    )
    # Ben has not named Python: the sentence says so.
    assert reassignment_effect(two_people, monday, ["X"], "Ben") == (
        "Voraussichtliches Ende 10.11.2026 statt 12.11.2026 (2 Arbeitstage früher). "
        "Ben hat Python nicht angegeben (X)"
    )
    # Giving both to Ben only moves the queue to him.
    assert reassignment_effect(two_people, monday, ["X", "Y"], "Ben") == (
        "Das voraussichtliche Ende bleibt der 12.11.2026. Ben hat Python nicht angegeben (X)"
    )
    assert reassignment_effect(two_people, monday, ["Y"], "Zoe") == (
        "Nicht prüfbar: Zoe ist nicht im Team"
    )


def test_a_finished_task_is_left_out_of_a_reassignment(two_people):
    done = apply_rows(two_people, [{"ID": "Y", "Status": "fertig", "Ist (h)": 16}])
    assert reassignment_effect(done, date(2026, 11, 9), ["Y"], "Ben") == (
        "Das voraussichtliche Ende bleibt der 10.11.2026"
    )


def test_the_next_step_follows_from_the_state_of_the_project(tracking):
    def advice(today, **status):
        project = progressed(tracking, **status) if status else tracking
        return next_step(project, today)

    # Before anything is recorded, and nothing is late yet.
    assert advice(date(2026, 11, 9)) == (
        "Noch kein Fortschritt erfasst. Trage Status und Ist-Stunden auf der Seite "
        "Durchführung ein.",
        "durchfuehrung",
    )
    assert advice(date(2026, 11, 10), A="fertig") == (
        "Das Projekt liegt im Plan. Halte den Fortschritt auf der Seite Durchführung aktuell.",
        "durchfuehrung",
    )
    assert advice(date(2026, 11, 10)) == (
        "1 Aufgabe ist im Verzug. Die Seite Kontrolle zeigt, was daran hängt und wohin das "
        "Ende rückt.",
        "kontrolle",
    )
    assert advice(date(2026, 11, 12)) == (
        "2 Aufgaben sind im Verzug. Die Seite Kontrolle zeigt, was daran hängt und wohin das "
        "Ende rückt.",
        "kontrolle",
    )
    assert advice(date(2026, 12, 21)) == (
        "Nach heutigem Stand wird die Deadline verpasst. Die Seite Kontrolle zeigt, welche "
        "Aufgaben das Ende verschieben.",
        "kontrolle",
    )
    assert advice(date(2026, 11, 12), A="fertig", B="fertig") == (
        "Alle Aufgaben sind fertig. Der Statusbericht auf der Seite Durchführung hält den "
        "Abschluss fest.",
        "durchfuehrung",
    )


def test_the_rest_of_a_project_is_a_project_from_today_with_what_is_left(tracking):
    # Thu 12.11.: A is finished, B has 4 of its 16 h booked.
    project, plan = rest_project(apply_rows(tracking, ROWS), date(2026, 11, 12))

    assert (project.idea, project.start_date, project.deadline) == (
        PROJECT.idea,
        date(2026, 11, 12),
        PROJECT.deadline,
    )
    (task,) = plan.tasks
    assert (task.id, task.title, task.estimate_hours) == ("B", "API", 12)
    assert task.depends_on == []  # A is done: nothing to wait for
    assert [(a.task_id, a.member, a.reason) for a in plan.assignments] == [
        ("B", "Anna", "kennt Python")
    ]
    assert plan.risks == PLAN.risks


def test_the_rest_starts_no_earlier_than_the_project(tracking):
    project, plan = rest_project(tracking, date(2026, 11, 2))  # a week before the start
    assert project.start_date == PROJECT.start_date
    assert [t.id for t in plan.tasks] == ["A", "B"] and plan.tasks[1].depends_on == ["A"]


def test_there_is_no_rest_of_a_finished_project_or_after_the_deadline(tracking):
    done = progressed(tracking, A="fertig", B="fertig")
    with pytest.raises(InputError, match="Alle Aufgaben sind fertig"):
        rest_project(done, date(2026, 11, 12))
    with pytest.raises(InputError, match=r"Die Deadline \(18.12.2026\) liegt in der Vergangenheit"):
        rest_project(tracking, date(2026, 12, 21))


def test_a_rest_that_does_not_fit_the_calendar_is_a_problem_not_a_crash(tracking):
    # A typo-sized remaining estimate: 20 million hours end after the year 9999.
    absurd = apply_rows(tracking, [{"ID": "B", "Status": "in Arbeit", "Rest (h)": 20_000_000}])
    today = date(2026, 11, 10)
    outlook = forecast(absurd, today)

    assert outlook.problem == (
        "Task 'B' würde erst nach dem 31.12.9999 enden, so weit reicht der Kalender nicht"
    )
    assert (outlook.end, outlook.schedule) == (None, [])
    assert forecast_text(outlook, PROJECT.deadline) == f"Nicht berechenbar: {outlook.problem}"
    assert forecast_bars(evaluate(absurd, today), outlook) == []
    advice, page = next_step(absurd, today)
    assert advice.startswith("Die Prognose lässt sich nicht berechnen") and page == "durchfuehrung"
    # The status report and the facts for the agents are still written.
    assert "**Prognose:** Nicht berechenbar" in status_report(absurd, evaluate(absurd, today))


def test_a_reassignment_that_cannot_be_scheduled_is_not_checkable(two_people):
    gone = Member(
        name="Cem",
        hours_per_week=40,
        absences=[{"first": date(2026, 11, 1), "last": date.max}],
    )
    with_cem = two_people.model_copy(update={"team": [*two_people.team, gone]})
    monday = date(2026, 11, 9)
    assert reassignment_effect(with_cem, monday, ["Y"], "Cem") == (
        "Nicht prüfbar: Task 'Y' würde erst nach dem 31.12.9999 enden, so weit reicht der "
        "Kalender nicht"
    )
    # Names outside the team are not scheduled either.
    assert forecast(two_people, monday, reassign={"Y": "Zoe"}).problem == (
        "Task 'Y' ist 'Zoe' zugewiesen, diese Person ist nicht im Team"
    )


def test_the_forecast_keeps_the_order_of_the_plan_when_a_finished_task_drops_out(tmp_path):
    # Anna: T1, then T2 (after T1) and T3. Ben: T4 after T3. The plan puts T3 before T2.
    ben = Member(name="Ben", hours_per_week=40)
    plan = Plan.model_validate(
        {
            "tasks": [
                {"id": "T1", "title": "a", "estimate_hours": 8},
                {"id": "T2", "title": "b", "estimate_hours": 16, "depends_on": ["T1"]},
                {"id": "T3", "title": "c", "estimate_hours": 8},
                {"id": "T4", "title": "d", "estimate_hours": 24, "depends_on": ["T3"]},
            ],
            "assignments": [
                {"task_id": tid, "member": member, "reason": "r"}
                for tid, member in [("T1", "Anna"), ("T2", "Anna"), ("T3", "Anna"), ("T4", "Ben")]
            ],
        }
    )
    team = [*TEAM, ben]
    planned = {s.task_id: (s.start, s.end) for s in check_plan(plan, team, PROJECT).schedule}
    assert planned["T3"][0] < planned["T2"][0]  # the case this test is about
    adopted = adopt(PROJECT, team, plan, path=tmp_path / "projekt.json")
    on_plan = apply_rows(adopted, [{"ID": "T1", "Status": "fertig", "Ist (h)": 8}])

    outlook = forecast(on_plan, date(2026, 11, 10))  # Tuesday: T1 was done on Monday

    assert outlook.shift == 0
    assert {s.task_id: (s.start, s.end) for s in outlook.schedule} == {
        tid: dates for tid, dates in planned.items() if tid != "T1"
    }


def test_a_started_task_shorter_than_an_hour_is_not_counted_as_an_hour(tmp_path):
    short = Plan.model_validate(
        {
            "tasks": [{"id": "A", "title": "Mail", "estimate_hours": 0.5}],
            "assignments": [{"task_id": "A", "member": "Anna", "reason": "r"}],
        }
    )
    adopted = adopt(PROJECT, TEAM, short, path=tmp_path / "projekt.json")
    started = apply_rows(adopted, [{"ID": "A", "Status": "in Arbeit", "Ist (h)": 0}])
    assert rest_plan(started).tasks[0].estimate_hours == 0.5
    overrun = apply_rows(adopted, [{"ID": "A", "Status": "in Arbeit", "Ist (h)": 2}])
    assert rest_plan(overrun).tasks[0].estimate_hours == 0.5


def test_the_control_document_is_filled_from_plan_progress_and_forecast(tracking):
    updated = apply_rows(tracking, ROWS)  # A finished with 10 h, B started with 4 of 16 h
    text = control_document(updated, evaluate(updated, today=date(2026, 11, 12)))

    assert "**Projekt:** Raumbuchung für Lerngruppen" in text
    assert "**Stand:** 12.11.2026" in text
    assert (
        "**Prognose:** Voraussichtliches Ende 13.11.2026, 2 Arbeitstage später als geplant" in text
    )
    assert "- Fortschritt: 33 %" in text
    assert "- Ist-Stunden bisher: 14 h" in text
    assert "- Abweichung der fertigen Aufgaben: +2 h" in text
    assert "- Kosten: kein Stundensatz gesetzt" in text
    assert "- B · API (Anna), geplant bis 11.11.2026, Status: in Arbeit; hält auf: nichts" in text
    assert "| Anna | 24 | 14 | 8 |" in text
    assert "Noch nicht erstellt. Der Kontroll-Agent" in text
    assert "$" not in text  # every placeholder is filled


def test_the_control_document_takes_the_hourly_rate_and_the_agents_report(two_people):
    monday = date(2026, 11, 16)  # a week after the start: X and Y are both overdue
    report = ControlReport(
        assessment="kritisch",
        findings=[{"task_ids": ["X", "Y"], "observation": "Nichts wurde begonnen."}],
        measures=[
            {"task_ids": ["X"], "action": "Anna beginnt X.", "effect": "X wird fertig."},
            {
                "task_ids": ["Y"],
                "action": "Ben übernimmt Y.",
                "effect": "Zwei Tage gewonnen.",
                "reassign_to": "Ben",
            },
        ],
    )
    text = control_document(two_people, evaluate(two_people, monday), report=report, rate=50)

    assert "- Plankosten gesamt: 1.600,00 €" in text  # 32 h at 50 €
    assert "- Ist-Kosten bisher: 0,00 €" in text
    assert "**Bewertung:** kritisch" in text
    assert "- **X, Y:** Nichts wurde begonnen." in text
    assert (
        "| X | Anna beginnt X. | X wird fertig. | Keine Umverteilung: nicht nachrechenbar |" in text
    )
    assert (
        "| Y | Ben übernimmt Y. | Zwei Tage gewonnen. | Voraussichtliches Ende 17.11.2026 "
        "statt 19.11.2026 (2 Arbeitstage früher) |" in text
    )
    assert "*Vorschlag des Kontroll-Agenten (Claude), von der Projektleitung zu prüfen.*" in text
    assert "$" not in text


def test_the_progress_table_says_when_each_task_is_expected_to_end(tracking):
    # Tue 10.11.: A was planned for Monday and is still open.
    rows = progress_rows(tracking, today=date(2026, 11, 10))
    assert [(r["ID"], r["Geplantes Ende"], r["Prognose Ende"]) for r in rows] == [
        ("A", "09.11.2026", "10.11.2026"),
        ("B", "11.11.2026", "12.11.2026"),
    ]
    done = progress_rows(progressed(tracking, A="fertig"), today=date(2026, 11, 10))
    assert [r["Prognose Ende"] for r in done] == ["fertig", "11.11.2026"]
    # No forecast, no dates: the reason is on the Kontrolle page.
    absurd = apply_rows(tracking, [{"ID": "B", "Status": "in Arbeit", "Rest (h)": 20_000_000}])
    assert [r["Prognose Ende"] for r in progress_rows(absurd, today=date(2026, 11, 10))] == [
        "nicht berechenbar",
        "nicht berechenbar",
    ]
    # The new column is read-only: saving the table as shown changes nothing.
    assert apply_rows(tracking, rows) == tracking


def test_a_finished_task_reads_finished_even_when_the_rest_cannot_be_forecast(tracking):
    absurd = apply_rows(
        tracking,
        [
            {"ID": "A", "Status": "fertig", "Ist (h)": 8},
            {"ID": "B", "Status": "in Arbeit", "Rest (h)": 20_000_000},
        ],
    )
    assert [r["Prognose Ende"] for r in progress_rows(absurd, today=date(2026, 11, 10))] == [
        "fertig",
        "nicht berechenbar",
    ]


def test_the_control_document_keeps_its_shape_whatever_the_report_says(two_people):
    report = ControlReport(
        assessment="kritisch",
        findings=[{"task_ids": ["X"], "observation": "Zeile 1\n\n| a | b |\n# Titel"}],
        measures=[
            {"task_ids": ["X"], "action": "Erst klären,\r\ndann bauen", "effect": "Ruhe | Zeit"},
            {
                "task_ids": ["Z9"],  # not in the plan
                "action": "Ben übernimmt.",
                "effect": "Schneller.",
                "reassign_to": "Ben",
            },
        ],
    )
    monday = date(2026, 11, 16)
    text = control_document(two_people, evaluate(two_people, monday), report=report)

    assert "- **X:** Zeile 1 \\| a \\| b \\| # Titel" in text
    assert (
        "| X | Erst klären, dann bauen | Ruhe \\| Zeit | Keine Umverteilung: nicht nachrechenbar |"
        in text
    )
    assert (
        "| Z9 | Ben übernimmt. | Schneller. | Nicht prüfbar: Aufgabe Z9 ist nicht im Plan |" in text
    )


def test_earned_value_compares_what_is_done_with_what_the_plan_wanted_done(tracking):
    # Tue 10.11.: the plan wanted A (8 h) done and B (16 h, two days) half done.
    updated = apply_rows(tracking, ROWS)  # A finished with 10 h, B started with 4 h
    value = earned_value(evaluate(updated, today=date(2026, 11, 10)))

    assert (value.planned, value.earned, value.actual) == (16, 8, 14)
    assert (hours_text(41.64), hours_text(8.0)) == ("41,6", "8")
    assert value.schedule_index == 0.5  # half of what was planned is done
    assert value.cost_index == pytest.approx(8 / 14)  # 14 h booked for 8 h of finished work


def test_earned_value_has_no_index_without_a_basis(tracking):
    # Fri 06.11., before the first planned day: nothing was planned yet, nothing is booked.
    early = earned_value(evaluate(tracking, today=date(2026, 11, 6)))
    assert (early.planned, early.earned, early.actual) == (0, 0, 0)
    assert early.schedule_index is None
    assert early.cost_index is None
    # After the plan's last day the planned value stays at the whole plan.
    assert earned_value(evaluate(tracking, today=date(2026, 12, 1))).planned == 24


def test_the_planned_curve_has_one_point_per_workday_of_the_plan(tracking):
    assert planned_curve(evaluate(tracking, today=date(2026, 11, 10))) == [
        {"Tag": date(2026, 11, 9), "Stunden": 8},
        {"Tag": date(2026, 11, 10), "Stunden": 16},
        {"Tag": date(2026, 11, 11), "Stunden": 24},
    ]


def test_the_control_document_names_the_earned_value(tracking):
    updated = apply_rows(tracking, ROWS)
    text = control_document(updated, evaluate(updated, today=date(2026, 11, 10)))
    assert "- Planwert bis heute: 16 h" in text
    assert "- Fertigstellungswert: 8 h" in text
    assert "- Termin-Kennzahl (SPI): 0,50" in text
    assert "- Aufwands-Kennzahl (CPI): 0,57" in text

    before = control_document(tracking, evaluate(tracking, today=date(2026, 11, 6)))
    assert "- Termin-Kennzahl (SPI): nicht berechenbar, der Plan hat noch nicht begonnen" in before
    assert "- Aufwands-Kennzahl (CPI): nicht berechenbar, keine Ist-Stunden erfasst" in before


def test_the_week_ahead_lists_what_the_forecast_starts_in_the_next_workdays(tracking):
    # Tue 10.11., nothing done: the forecast puts A on Tuesday and B on Wed and Thu.
    tuesday = date(2026, 11, 10)
    assert week_ahead(tracking, tuesday) == [
        {
            "Person": "Anna",
            "ID": "A",
            "Aufgabe": "Datenmodell",
            "Beginn": "10.11.2026",
            "Ende": "10.11.2026",
            "Status": "offen",
        },
        {
            "Person": "Anna",
            "ID": "B",
            "Aufgabe": "API",
            "Beginn": "11.11.2026",
            "Ende": "12.11.2026",
            "Status": "offen",
        },
    ]
    # Only today: B starts tomorrow.
    assert [row["ID"] for row in week_ahead(tracking, tuesday, days=1)] == ["A"]
    # Nothing is left of a finished project, and nothing can be said without a forecast.
    assert week_ahead(progressed(tracking, A="fertig", B="fertig"), tuesday) == []
    absurd = apply_rows(tracking, [{"ID": "B", "Status": "in Arbeit", "Rest (h)": 20_000_000}])
    assert week_ahead(absurd, tuesday) == []
